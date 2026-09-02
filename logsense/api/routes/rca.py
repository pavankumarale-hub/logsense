"""POST /api/v1/rca — RCA generation and incident drafting endpoints."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from logsense.storage.db import get_db
from logsense.storage.repository import LogRepository
from logsense.triage.models import Cluster
from logsense.rca.generator import RCAGenerator
from logsense.rca.models import RCAResult
from logsense.actions.github import GitHubIssueDrafter
from logsense.actions.jira import JiraPayloadBuilder

router = APIRouter()


@router.post("/cluster/{cluster_id}")
async def generate_rca(cluster_id: str, force: bool = Query(default=False)):
    """Run LLM RCA for a cluster. Returns cached result unless force=true."""
    db = get_db()
    repo = LogRepository(db)

    if not force:
        cached = await repo.get_rca_for_cluster(cluster_id)
        if cached:
            return {"source": "cache", "rca": cached}

    cluster_row = await repo.get_cluster_by_id(cluster_id)
    if not cluster_row:
        raise HTTPException(status_code=404, detail="Cluster not found")

    samples = await repo.get_cluster_log_samples(cluster_id, limit=5)
    log_samples = [s["message"] for s in samples]

    cluster = Cluster.from_row(cluster_row)

    generator = RCAGenerator()
    rca = generator.generate(cluster, log_samples)
    await repo.insert_rca_result(rca)

    return {"source": "generated", "rca": rca.to_dict()}


class DraftRequest(BaseModel):
    cluster_id: str
    platform: Literal["github", "jira"] = "github"
    dry_run: bool = True


@router.post("/draft")
async def draft_incident(req: DraftRequest):
    """Draft a GitHub issue or Jira payload from a cluster's RCA."""
    db = get_db()
    repo = LogRepository(db)

    rca_row = await repo.get_rca_for_cluster(req.cluster_id)
    if not rca_row:
        raise HTTPException(
            status_code=404,
            detail="No RCA found. Call POST /rca/cluster/{id} first.",
        )

    cluster_row = await repo.get_cluster_by_id(req.cluster_id)
    if not cluster_row:
        raise HTTPException(status_code=404, detail="Cluster not found")

    rca = RCAResult.from_row(rca_row)
    cluster = Cluster.from_row(cluster_row)

    if req.platform == "jira":
        draft = JiraPayloadBuilder().build(rca, cluster)
    else:
        draft = GitHubIssueDrafter(dry_run=req.dry_run).draft(rca, cluster)

    await repo.insert_incident_draft(draft)
    return {"status": draft.status, "platform": req.platform, "draft": draft.to_dict()}
