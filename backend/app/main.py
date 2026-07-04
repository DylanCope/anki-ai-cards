from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.models import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Creates any missing tables (idempotent — CREATE TABLE IF NOT EXISTS
    # semantics via SQLModel's create_all, safe to run on every startup).
    # Tests never caught the absence of this: every test module calls
    # init_db() directly in its own fixture setup, so the real deployed app
    # was the first place this ever ran against a genuinely fresh database.
    init_db()
    yield


app = FastAPI(title="anki-ai-cards", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(chat_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
