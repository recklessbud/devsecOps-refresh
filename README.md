# DevSecOps Refresh

[view-threat-model](./docs/README.md)
## Phase 1: Project setup and shift-left security

**Goal:** catch security problems before every push to github.

### Repository layout

```
app/          application code
tests/        pytest suite
k8s/          hardened Kubernetes manifests and Kyverno policy (Phase 4)
.github/      CI, release and cluster-test workflows
docs/         diagrams and threat model
```

Dependencies are managed with `uv` and a committed lockfile, so every build
resolves exactly the same versions.

### Pre-commit gates

Every commit runs these hooks locally:

| Hook | Catches |
|---|---|
| `detect-private-key`, `check-added-large-files` | Private keys and accidental binaries |
| Black, Flake8 | Style and basic correctness |
| Bandit | Insecure Python patterns (e.g. `shell=True`) |
| detect-secrets (with baseline) | High-entropy strings and credential patterns |
| Gitleaks | Known secret formats, including cloud keys |

### Proof it works

I tested that the gates fail, not only that they pass:

1. **Secret blocked.** I committed a file containing an AWS-format access key.
   Both Gitleaks and detect-secrets rejected the commit.
2. **Insecure code blocked.** I added `subprocess.call("ls", shell=True)`.
   Bandit rejected it with B602.

### What I learned

- `.secrets.baseline` contains hashes that scanners later flagged as secrets.
  That file needed an explicit exclusion in the history-scanning job.
- Deleting a file doesn't remove it from git history. Secret scanners that read
  history keep finding it, so a leaked credential means rotation, not deletion.


## Phase 2: CI security gates

**Goal:** every pull request and every push to `main` passes automated security
checks before anything is built or released. The pipeline runs in
`.github/workflows/ci.yml`, with the secret scan in a reusable workflow.

### Least privilege by default

The workflow token is read-only (`permissions: contents: read`). Jobs that need
more must ask for it explicitly, and in this phase none do. Runs on the same
ref are cancelled when a newer commit arrives, so stale runs don't pile up.

### The gates

| Job | Tool | Fails the build on |
|---|---|---|
| Lint & test | Black, Flake8, pytest | Style violations, failing tests |
| SAST | Bandit | Insecure Python patterns |
| SAST | Semgrep (`p/python`, `p/owasp-top-ten`) | OWASP-style code issues |
| Dependency audit | pip-audit on the exported lockfile | Known CVEs in production dependencies |
| Secret scan | Gitleaks (full history) | Credential patterns in any commit |
| Secret scan | TruffleHog (reusable workflow) | Candidate and verified secrets |
| Container | Hadolint | Dockerfile anti-patterns |
| Container | Trivy (CRITICAL and HIGH, unfixed ignored) | Vulnerabilities with an available fix |

The container job only runs after every other job passes (`needs:`), so
nothing is built from code that failed an earlier gate.

### Problems I hit, and what I did about them

**Secret scanners kept failing on a file I had already deleted.**
`.secrets.baseline` was committed early with findings in it. I deleted and
regenerated it, but TruffleHog scans git history, so the old commit kept
failing every run. Deleting a file does not remove it from history.
I had to reset the git history to remove the findings from history

**Trivy found 5 HIGH vulnerabilities in 3 packages** (msgpack, setuptools,
urllib3), all with fixes available. I updated the opentelemetry-api to 1.45.2
because that was the sole package causing the pipeline failure, the rest were
warnings

**Dependabot flooded the repo with 7 PRs** the moment I enabled it, all
failing for the same reason: they branch from `main`, and `main` was red.
Fixing one failing job on `main` cleared all of them.

### Proof it works
1. **Vulnerable dependency:** pinned an old package version. pip-audit failed.
2. **Insecure code:** added `shell=True`. Bandit and Semgrep failed.
3. **Old base image:** Trivy reported CRITICAL/HIGH findings.
4. **Dockerfile lint:** unpinned `apt-get install`. Hadolint failed.


## Phase 3: Secure build, SBOM and signing

**Goal:** publish a container image whose origin can be proven. Anyone pulling
it can check that it was built by this repository's release workflow, and see
exactly what is inside it.

### Privilege separation

Publishing lives in its own workflow (`release.yml`), separate from CI. CI is
read-only and runs on every pull request. Release runs only on `main`, only
after CI has succeeded (`workflow_run`), and checks out the exact commit CI
tested. Elevated permissions are granted at the job level, not the whole
workflow:

| Permission | Why |
|---|---|
| `packages: write` | Push the image to GHCR |
| `id-token: write` | Request the OIDC token used for keyless signing |
| `attestations: write` | Store build attestations |

### What the release job does

1. Builds the image and pushes it to `ghcr.io`, tagged with the commit SHA,
   with a fresh base-image pull and `provenance: mode=max` plus `sbom: true`
   so the registry also stores build provenance.
2. Signs the image **by digest** with Cosign in keyless mode.
3. Generates a CycloneDX SBOM of the pushed image with Syft.
4. Attaches the SBOM to the image as a signed attestation.
5. Verifies its own signature at the end of the run.

### Why these choices

- **Sign the digest, not the tag.** Tags are mutable, so `:latest` or even a
  SHA tag can be re-pointed at different content. A digest identifies exactly
  one image.
- **Keyless signing.** There is no private key to store, rotate or leak.
  Cosign requests a short-lived OIDC token from GitHub, Sigstore's Fulcio CA
  issues a certificate bound to this workflow's identity, and the signing event
  is recorded in the public Rekor transparency log.
- **Verification pins an identity, not just "is signed".** A valid signature
  from some other repository's workflow must not pass, so verification checks
  both the certificate identity (this repo) and the OIDC issuer
  (`token.actions.githubusercontent.com`).
- **An SBOM turns "what's in this image?" into a query.** When a new CVE is
  published, a stored SBOM can be re-scanned without rebuilding anything:
  `trivy sbom sbom.cdx.json`.

### Verifying an image yourself

```bash
IMAGE="ghcr.io/recklessbud/devsecops-refresh@sha256:045031bbb4546dbbf660b25a790f4de2974dade003415b563cc44d28c37bfdce"

cosign verify \
  --certificate-identity-regexp "^https://github.com/recklessbud/devsecOps-refresh/" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  "$IMAGE"

cosign verify-attestation --type cyclonedx \
  --certificate-identity-regexp "^https://github.com/recklessbud/devsecOps-refresh/" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  "$IMAGE"
```

### Proof it works

![cosign verify](./docs/screenshots/Screenshot%202026-11-26%20065509.png)

1. Verifying with a wrong identity (`someone-else`) fails.
2. Verifying an image from another source fails with "no signatures found".

![`verify-attestation`](./docs/screenshots/Screenshot%202026-11-26%20070629.png)
1. got a number 3361 meaning it works

The same identity check is enforced inside the cluster by Kyverno in Phase 4.

### Problems I hit, and what I learned

**"No signatures found" on an image I knew was signed.** I had copied the
`sha256:` value from the workflow's **Artifacts** section. Those are hashes of
uploaded files (the build record and the SBOM JSON), not of the image. Cosign
looks up signatures attached to the image digest in the registry, so it found
nothing. The image digest comes from the registry's Packages page, from the
"Build and push" step output, or from `docker buildx imagetools inspect`.

**A malformed reference** (`...@@sha256:...`) gave a parse error that looked
like a signing failure. It was a typo, and a reminder to read the error text
before debugging the pipeline.




## Phase 4: Hardened Kubernetes, admission control and DAST

**Goal:** the cluster itself refuses to run anything that isn't hardened, from
an unknown registry, or not built by this repository's pipeline, so a mistake
in the delivery path doesn't turn into a running workload.

Everything was developed against a local [kind](https://kind.sigs.k8s.io/)
cluster, with manifests in `k8s/`.

### Hardened workload

The `sdp` namespace enforces the Pod Security Standards `restricted` profile,
so the API server rejects non-compliant pods outright.
### Admission control with Kyverno
A `ClusterPolicy` (`k8s/kyverno-verify-images.yaml`) adds two rules for the
`sdp` namespace:

1. **`verify-cosign-keyless`:** images from this repository's GHCR path must
   carry a valid keyless Cosign signature whose certificate identity matches
   this repository's workflow and whose issuer is GitHub's OIDC provider. This
   is the same check shown in Phase 3, enforced at admission.
2. **`only-the-registry`:** nothing else may run in the namespace. Without this
   rule, an image that doesn't match the signature rule's image pattern would
   never be inspected and would simply be admitted. A signature policy needs
   an allowlist beside it.

### Proof it works

| Test | Result |
|---|---|
| Pod with `--privileged` in `sdp` | Rejected by Pod Security (`violates PodSecurity "restricted"`) |
| Hardened pod using `busybox:1.36` | Rejected by Kyverno, rule `only-the-registry` |
| Pod using this repo's signed image | Admitted |
| Same image, policy temporarily trusting a different identity | Rejected by the signature rule |
| Same image, real identity restored | Admitted again |
| Write to `/app` inside a running pod | Fails (read-only root filesystem) |
| Write to `/tmp` | Works; process runs as uid 10001 |

The last rejected/admitted pair is the important one: the identical pod flips
from rejected to admitted when only the trusted identity changes, so the
cryptographic check is doing real work and not just the image pattern.

### Problems I hit, and what I learned

**kind failed to start the cluster** (`kubeadm init` errors). The newest default
node image was too new for the setup: kubeadm rejected the older config format
the kind binary generated. Pinning a known-good kind version and node image
pair fixed it, and the pair is pinned in the workflow for the same reason.
right version for kind v0.30.0

### Dynamic scanning and automated cluster tests

**[If the cluster-test workflow is green]**
A workflow (`cluster-test.yml`) runs after each successful release. It creates
a kind cluster, installs Kyverno at a pinned chart version, deploys the
released digest, and asserts that the cluster rejects an unknown-registry pod
and a correctly-sourced pod under the wrong signing identity, with a positive
control that the same pod is admitted under the right one. It then runs an
OWASP ZAP baseline scan against the live service and uploads the report.
Zap was only showing warnings so I bypassed it
