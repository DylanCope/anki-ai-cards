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
# anki-ai-cards-backend.internal) is IPv6-only, so the backend must accept
# IPv6. Fly's public proxy/health-checker reaches the app over IPv4, so it
# must accept IPv4 too. Plain `uvicorn app.main:app --host ::` looks
# dual-stack but isn't: uvicorn's CLI path with no pre-bound socket calls
# asyncio's `loop.create_server(host=, port=)`, which unconditionally forces
# IPV6_V6ONLY=1 on the socket it creates (see `app/run_server.py`'s
# docstring for the full root-cause trace) -- that's what made the public
# health check fail while 6PN worked fine. `run_server.py` pre-binds the
# socket via `Config.bind_socket()` (no V6ONLY override, genuine dual-stack)
# and hands it to `Server.run(sockets=...)` instead.
CMD ["python", "-m", "app.run_server"]
