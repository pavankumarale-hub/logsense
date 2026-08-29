"""POST /api/v1/ingest — Log ingestion endpoint."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from logsense.ingestion import parse_log_lines, normalize
from logsense.storage.db import get_db
from logsense.storage.repository import LogRepository
from logsense.triage.cluster import ClusterEngine

router = APIRouter()


class IngestRequest(BaseModel):
    content: str
    source: str = "api"


class IngestResponse(BaseModel):
    entries_parsed: int
    clusters_updated: int
    message: str


@router.post("", response_model=IngestResponse)
async def ingest_logs(req: IngestRequest) -> IngestResponse:
    """Parse raw log content and store entries + clusters."""
    entries = normalize(parse_log_lines(req.content, source=req.source))

    if not entries:
        raise HTTPException(status_code=422, detail="No parseable log lines found.")

    db = get_db()
    repo = LogRepository(db)
    await repo.insert_log_entries(entries)

    engine = ClusterEngine()
    clusters = engine.process(entries)
    for cluster in clusters:
        await repo.upsert_cluster(cluster)

    return IngestResponse(
        entries_parsed=len(entries),
        clusters_updated=len(clusters),
        message=f"Ingested {len(entries)} entries, updated {len(clusters)} clusters.",
    )
