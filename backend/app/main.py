from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router

app = FastAPI(title="anki-ai-cards")
app.include_router(auth_router)
app.include_router(chat_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
