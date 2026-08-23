"""CLI entrypoint for LogSense."""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import click

from logsense.config import get_settings
from logsense.ingestion import parse_log_lines, normalize
from logsense.storage.db import get_db
from logsense.storage.repository import LogRepository
from logsense.triage.cluster import ClusterEngine
from logsense.rca.generator import RCAGenerator
from logsense.rca.models import RCAResult
from logsense.triage.models import Cluster
from logsense.actions.github import GitHubIssueDrafter
from logsense.actions.jira import JiraPayloadBuilder


@click.group()
def cli():
    """LogSense — AI-powered log analysis and incident management."""


@cli.command()
@click.argument("log_file", type=click.Path(exists=True))
@click.option("--source", default=None, help="Label for the log source")
def ingest(log_file: str, source: str | None):
    """Parse and store logs from a file."""
    path = Path(log_file)
    content = path.read_text()
    src = source or path.name

    entries = normalize(parse_log_lines(content, source=src))
    if not entries:
        click.echo("No parseable log lines found.", err=True)
        sys.exit(1)

    async def _run():
        db = get_db()
        await db.initialize()
        repo = LogRepository(db)
        await repo.insert_log_entries(entries)

        engine = ClusterEngine()
        clusters = engine.process(entries)
        for c in clusters:
            await repo.upsert_cluster(c)

        click.echo(f"Ingested {len(entries)} entries → {len(clusters)} clusters")

    asyncio.run(_run())


@cli.command()
@click.option("--limit", default=20, show_default=True)
@click.option("--min-risk", default=0.0, show_default=True)
def triage(limit: int, min_risk: float):
    """Show clusters ranked by risk score."""

    async def _run():
        db = get_db()
        await db.initialize()
        repo = LogRepository(db)
        clusters = await repo.get_clusters(limit=limit, min_risk_score=min_risk)
        if not clusters:
            click.echo("No clusters found. Run `logsense ingest` first.")
            return
        for c in clusters:
            click.echo(
                f"[{c['risk_score']:.3f}] {c['max_severity']:8s} "
                f"x{c['count']:4d}  {c['template'][:80]}  {c['id']}"
            )

    asyncio.run(_run())


@cli.command()
@click.argument("cluster_id")
def rca(cluster_id: str):
    """Run LLM root cause analysis for a cluster ID."""

    async def _run():
        db = get_db()
        await db.initialize()
        repo = LogRepository(db)

        cached = await repo.get_rca_for_cluster(cluster_id)
        if cached:
            click.echo("[cached]\n" + json.dumps(cached, indent=2))
            return

        cluster_row = await repo.get_cluster_by_id(cluster_id)
        if not cluster_row:
            click.echo(f"Cluster {cluster_id} not found.", err=True)
            sys.exit(1)

        samples = await repo.get_cluster_log_samples(cluster_id, limit=5)
        log_samples = [s["message"] for s in samples]

        cluster = Cluster(
            id=cluster_row["id"],
            template=cluster_row["template"],
            template_tokens=json.loads(cluster_row["template_tokens"]),
            first_seen=datetime.fromisoformat(cluster_row["first_seen"]),
            last_seen=datetime.fromisoformat(cluster_row["last_seen"]),
            count=cluster_row["count"],
            max_severity=cluster_row["max_severity"],
            affected_services=set(json.loads(cluster_row["affected_services"])),
            risk_score=cluster_row["risk_score"] or 0.0,
        )

        generator = RCAGenerator()
        result = generator.generate(cluster, log_samples)
        await repo.insert_rca_result(result)
        click.echo(json.dumps(result.to_dict(), indent=2))

    asyncio.run(_run())


@cli.command()
@click.argument("cluster_id")
@click.option("--platform", default="github", type=click.Choice(["github", "jira"]))
@click.option("--no-dry-run", is_flag=True, default=False, help="Actually create the issue")
def draft(cluster_id: str, platform: str, no_dry_run: bool):
    """Draft an incident report for a cluster."""

    async def _run():
        db = get_db()
        await db.initialize()
        repo = LogRepository(db)

        rca_row = await repo.get_rca_for_cluster(cluster_id)
        if not rca_row:
            click.echo("No RCA found. Run `logsense rca <cluster_id>` first.", err=True)
            sys.exit(1)

        cluster_row = await repo.get_cluster_by_id(cluster_id)
        if not cluster_row:
            click.echo(f"Cluster {cluster_id} not found.", err=True)
            sys.exit(1)

        rca_obj = RCAResult(
            id=rca_row["id"], cluster_id=rca_row["cluster_id"],
            title=rca_row["title"], summary=rca_row["summary"],
            root_cause_hypothesis=rca_row["root_cause_hypothesis"],
            confidence=rca_row["confidence"],  # type: ignore[arg-type]
            confidence_score=rca_row["confidence_score"],
            suggested_action=rca_row["suggested_action"],
            affected_service=rca_row["affected_service"],
            model_used=rca_row["model_used"],
            generated_at=datetime.fromisoformat(rca_row["generated_at"]),
        )
        cluster_obj = Cluster(
            id=cluster_row["id"], template=cluster_row["template"],
            template_tokens=json.loads(cluster_row["template_tokens"]),
            first_seen=datetime.fromisoformat(cluster_row["first_seen"]),
            last_seen=datetime.fromisoformat(cluster_row["last_seen"]),
            count=cluster_row["count"], max_severity=cluster_row["max_severity"],
            affected_services=set(json.loads(cluster_row["affected_services"])),
            risk_score=cluster_row["risk_score"] or 0.0,
        )

        dry_run = not no_dry_run
        if platform == "jira":
            d = JiraPayloadBuilder().build(rca_obj, cluster_obj)
        else:
            d = GitHubIssueDrafter(dry_run=dry_run).draft(rca_obj, cluster_obj)

        await repo.insert_incident_draft(d)
        click.echo(json.dumps(d.to_dict(), indent=2))

    asyncio.run(_run())


@cli.command()
def serve():
    """Start the FastAPI REST server."""
    import uvicorn
    cfg = get_settings()
    uvicorn.run(
        "logsense.api.app:app",
        host=cfg.api_host,
        port=cfg.api_port,
        reload=False,
        log_level=cfg.log_level.lower(),
    )
