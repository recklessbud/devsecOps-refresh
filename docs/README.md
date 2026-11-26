# Threat Model

| Threat | Control | Where enforced | Evidence |
|---|---|---|---|
| Secret committed to the repo | detect-secrets, Gitleaks, TruffleHog | Pre-commit and CI | Blocked test commit |
| Vulnerable dependency or base image | pip-audit, Trivy | CI | [failing run screenshot] |
| Insecure code pattern | Bandit, Semgrep | Pre-commit and CI | `shell=True` test |
| Tampered or untrusted image | Cosign keyless signing, identity pinned | Release, then Kyverno at admission | Wrong-identity pod rejected |
| Image from an unknown registry | Kyverno `only-the-registry` | Cluster admission | Denial message |
| Privileged or root workload | Pod Security `restricted` | Cluster admission | Rejected privileged pod |
| Container compromise impact | Non-root, read-only FS, no capabilities, seccomp | Pod spec | `touch /app/x` fails |
| Lateral movement | NetworkPolicy (default deny) | Cluster |
