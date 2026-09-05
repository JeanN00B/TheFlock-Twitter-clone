"""theFlock-twitter API (hexagonal, flat app/ — see backend/AGENTS.md)."""

from fastapi import FastAPI

app = FastAPI(title="theFlock-twitter API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
