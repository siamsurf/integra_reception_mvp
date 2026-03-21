from fastapi import FastAPI

import app.db.models  # noqa: F401  # Ensure all ORM models are registered.
from app.db.session import Base, engine
from app.web.router import router as web_router

app = FastAPI(title="INTEGRA Reception Hub + Quote Precheck", version="0.1.0")


@app.on_event("startup")
def on_startup() -> None:
    """Create tables for MVP if they do not exist."""
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(web_router)
