"""POST /api/v1/rca — RCA generation and incident drafting endpoints."""

import json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from logsense.storage.db import get_db
from logsense.storage.repository import LogRepository
from logsense.triage.models import Cluster
from logsense.rca.generator import RCAGenerator
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

    import datetime as _dt
    cluster = Cluster(
        id=cluster_row["id"],
        template=cluster_row["template"],
        template_tokens=json.loads(cluster_row["template_tokens"]),
        first_seen=_dt.datetime.fromisoformat(cluster_row["first_seen"]),
        last_seen=_dt.datetime.fromisoformat(cluster_row["last_seen"]),
        count=cluster_row["count"],
        max_severity=cluster_row["max_severity"],
        affected_services=set(json.loads(cluster_row["affected_services"])),
        risk_score=cluster_row["risk_score"] or 0.0,
    )

    generator = RCAGenerator()
    rca = generator.generate(cluster, log_samples)
    await repo.insert_rca_result(rca)

    return {"source": "generated", "rca": rca.to_dict()}


class DraftRequest(BaseModel):
    cluster_id: str
    platform: str = "github"
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

    import datetime as _dt
    from logsense.rca.models import RCAResult

    rca = RCAResult(
        id=rca_row["id"],
        cluster_id=rca_row["cluster_id"],
        title=rca_row["title"],
        summary=rca_row["summary"],
        root_cause_hypothesis=rca_row["root_cause_hypothesis"],
        confidence=rca_row["confidence"],  # type: ignore[arg-type]
        confidence_score=rca_row["confidence_score"],
        suggested_action=rca_row["suggested_action"],
        affected_service=rca_row["affected_service"],
        model_used=rca_row["model_used"],
        generated_at=_dt.datetime.fromisoformat(rca_row["generated_at"]),
    )
    cluster = Cluster(
        id=cluster_row["id"],
        template=cluster_row["template"],
        template_tokens=json.loads(cluster_row["template_tokens"]),
        first_seen=_dt.datetime.fromisoformat(cluster_row["first_seen"]),
        last_seen=_dt.datetime.fromisoformat(cluster_row["last_seen"]),
        count=cluster_row["count"],
        max_severity=cluster_row["max_severity"],
        affected_services=set(json.loads(cluster_row["affected_services"])),
        risk_score=cluster_row["risk_score"] or 0.0,
    )

    if req.platform == "jira":
        draft = JiraPayloadBuilder().build(rca, cluster)
    else:
        draft = GitHubIssueDrafter(dry_run=req.dry_run).draft(rca, cluster)

    await repo.insert_incident_draft(draft)
    return {"status": draft.status, "platform": req.platform, "draft": draft.to_dict()}
