"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from logsense.storage.db import get_db
from logsense.api.routes import ingest, triage, rca as rca_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = get_db()
    await db.initialize()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="LogSense API",
        description=(
            "AI-powered log analysis: ingest, cluster, root-cause, and report. "
            "Also available as an MCP server — see /docs for tool equivalents."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(ingest.router, prefix="/api/v1/ingest", tags=["Ingestion"])
    app.include_router(triage.router, prefix="/api/v1/triage", tags=["Triage"])
    app.include_router(rca_router.router, prefix="/api/v1/rca", tags=["RCA"])

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "logsense"}

    return app


app = create_app()
