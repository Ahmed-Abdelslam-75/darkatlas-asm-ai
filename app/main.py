"""FastAPI application entrypoint.

Creates the tables on startup (simple and reliable for this self-contained
slice — see the README for why we use create_all over Alembic here) and mounts
the asset and analysis routers. OpenAPI/Swagger is served at /docs for free.
"""

from fastapi import FastAPI

from .db import Base, engine
from .models import Asset, Relationship  # noqa: F401 - ensure models are registered
from .routers import analyze, assets

app = FastAPI(
    title="DarkAtlas Asset Management — AI Layer",
    version="1.0.0",
    description=(
        "A self-contained slice of the DarkAtlas ASM Asset Management module: "
        "import & deduplicate assets, track their lifecycle and relationships, "
        "and analyze them with a LangChain-powered layer (NL query, risk scoring, "
        "enrichment, reporting)."
    ),
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


app.include_router(assets.router)
app.include_router(analyze.router)
