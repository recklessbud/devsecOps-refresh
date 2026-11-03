# syntax=docker/dockerfile:1

# ---- builder: resolve and install deps ----
FROM python:3.13-slim-bookworm AS builder

# Pin uv to the version you have locally (`uv --version`)
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv



ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Same path as the runtime stage so venv shebangs stay valid
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ---- runtime: only what's needed to run ----
FROM python:3.13-slim-bookworm AS runtime

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app \
    --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY app ./app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip uninstall -y setuptools pip wheel 2>/dev/null || true

USER 10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
