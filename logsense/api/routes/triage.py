"""GET /api/v1/triage — Cluster triage endpoints."""

from fastapi import APIRouter, Query

from logsense.storage.db import get_db
from logsense.storage.repository import LogRepository

router = APIRouter()


@router.get("/clusters")
async def list_clusters(
    limit: int = Query(default=20, le=200),
    min_risk_score: float = Query(default=0.0, ge=0.0, le=1.0),
):
    """Return clusters ranked by risk score."""
    db = get_db()
    repo = LogRepository(db)
    clusters = await repo.get_clusters(limit=limit, min_risk_score=min_risk_score)
    return {"clusters": clusters, "total": len(clusters)}


@router.get("/clusters/{cluster_id}")
async def get_cluster(cluster_id: str):
    """Return a single cluster by ID, with recent log samples."""
    db = get_db()
    repo = LogRepository(db)
    cluster = await repo.get_cluster_by_id(cluster_id)
    if not cluster:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Cluster not found")
    samples = await repo.get_cluster_log_samples(cluster_id, limit=5)
    return {"cluster": cluster, "samples": samples}
