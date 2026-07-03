from fastapi import FastAPI

from app.api.auth import router as auth_router

app = FastAPI(title="anki-ai-cards")
app.include_router(auth_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
