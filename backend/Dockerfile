# Runtime image for the FastAPI backend, built and deployed via
# `backend/fly.toml`. Uses `uv` to install the locked dependency set from
# pyproject.toml/uv.lock (no dev dependencies — pytest/respx aren't needed at
# runtime).
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY scripts ./scripts

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# Fly's private 6PN network (used by the frontend to reach this app at
# anki-ai-cards-backend.internal) is IPv6-only. Binding to 0.0.0.0 (IPv4
# wildcard) leaves nothing listening on the IPv6 side, so 6PN connections get
# ECONNREFUSED even though the public proxy's IPv4 health checks pass fine.
# "::" is dual-stack by default on Linux, so it keeps accepting both.
CMD ["uvicorn", "app.main:app", "--host", "::", "--port", "8000"]
