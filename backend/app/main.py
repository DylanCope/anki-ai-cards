from fastapi import FastAPI

app = FastAPI(title="anki-ai-cards")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
