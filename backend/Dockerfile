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
# ECONNREFUSED. "::" is meant to be dual-stack (bindv6only=0 at the OS
# level), but the deployed backend currently refuses IPv4 loopback
# (127.0.0.1) while accepting IPv6 loopback (::1) -- root cause NOT yet
# found; see PROGRESS.md's "Backend external reachability" entry for the
# full investigation (what's confirmed, what's ruled out, what to try next)
# before changing this again. --loop asyncio (added during that
# investigation, to rule out uvloop forcing IPV6_V6ONLY) made no observable
# difference -- kept because it's harmless, not because it's a fix.
CMD ["uvicorn", "app.main:app", "--host", "::", "--port", "8000", "--loop", "asyncio"]
