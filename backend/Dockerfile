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

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
