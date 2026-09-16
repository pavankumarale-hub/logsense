"""LogSense MCP Server.

Exposes four tools that mirror the core pipeline:

  ingest_logs          → parse and store log content
  get_clusters         → retrieve triage summary with risk scores
  get_rca_for_cluster  → run LLM root cause analysis for a cluster
  draft_incident_report → build a GitHub / Jira issue payload

Run via:
  python -m logsense.mcp_server.server
  # or: logsense-mcp   (if installed via pip)

Claude Desktop config (~/.claude_desktop_config.json):
  {
    "mcpServers": {
      "logsense": {
        "command": "python",
        "args": ["-m", "logsense.mcp_server.server"],
        "cwd": "/path/to/logsense",
        "env": {
          "ANTHROPIC_API_KEY": "sk-ant-...",
          "LOGSENSE_DB_PATH": "/path/to/logsense.db"
        }
      }
    }
  }

See docs/mcp-connection-guide.md for full setup instructions.
"""

import json
from typing import Literal

from mcp.server.fastmcp import FastMCP

from logsense.ingestion import parse_log_lines, normalize
from logsense.storage.db import get_db
from logsense.storage.repository import LogRepository
from logsense.triage.cluster import ClusterEngine
from logsense.rca.generator import RCAGenerator
from logsense.rca.models import RCAResult
from logsense.triage.models import Cluster
from logsense.actions.github import GitHubIssueDrafter
from logsense.actions.jira import JiraPayloadBuilder

mcp = FastMCP(
    "logsense",
    instructions=(
        "AI-powered log analysis agent: ingest logs, cluster errors, "
        "run LLM root cause analysis, and draft incident reports."
    ),
)


# ---------------------------------------------------------------------------
#  Tool: ingest_logs
# ---------------------------------------------------------------------------

@mcp.tool()
async def ingest_logs(content: str, source: str = "mcp-client") -> str:
    """Parse and store log content. Returns a summary of what was ingested.

    Args:
        content: Raw log text (multi-line, mixed formats supported).
        source:  Optional label for the log source (default: "mcp-client").
    """
    db = get_db()
    await db.initialize()
    repo = LogRepository(db)

    entries = normalize(parse_log_lines(content, source=source))

    if not entries:
        return json.dumps({"status": "ok", "entries_parsed": 0, "message": "No parseable log lines found."})

    count = await repo.insert_log_entries(entries)

    # Run clustering immediately so clusters are available for triage
    engine = ClusterEngine()
    clusters = engine.process(entries)

    for cluster in clusters:
        await repo.upsert_cluster(cluster)

    return json.dumps({
        "status": "ok",
        "entries_parsed": count,
        "clusters_updated": len(clusters),
        "message": f"Ingested {count} log entries across {len(clusters)} clusters.",
    })


# ---------------------------------------------------------------------------
#  Tool: get_clusters
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_clusters(
    limit: int = 20,
    min_risk_score: float = 0.0,
) -> str:
    """Return triage summary: clusters ranked by risk score.

    Args:
        limit:          Maximum number of clusters to return (default 20).
        min_risk_score: Only return clusters with risk_score >= this value.
    """
    db = get_db()
    await db.initialize()
    repo = LogRepository(db)

    clusters = await repo.get_clusters(limit=limit, min_risk_score=min_risk_score)
    return json.dumps({"clusters": clusters, "total": len(clusters)})


# ---------------------------------------------------------------------------
#  Tool: get_rca_for_cluster
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_rca_for_cluster(cluster_id: str) -> str:
    """Run LLM-powered root cause analysis for a specific cluster.

    If a cached RCA already exists for this cluster, it is returned directly
    without making a new LLM call.

    Args:
        cluster_id: The cluster ID from get_clusters output.
    """
    db = get_db()
    await db.initialize()
    repo = LogRepository(db)

    # Return cached result if available
    cached = await repo.get_rca_for_cluster(cluster_id)
    if cached:
        return json.dumps({"source": "cache", "rca": cached})

    cluster_row = await repo.get_cluster_by_id(cluster_id)
    if not cluster_row:
        return json.dumps({"error": f"Cluster {cluster_id} not found."})

    samples = await repo.get_cluster_log_samples(cluster_id, limit=5)
    log_samples = [s["message"] for s in samples]

    cluster = Cluster.from_row(cluster_row)

    generator = RCAGenerator()
    rca = generator.generate(cluster, log_samples)

    await repo.insert_rca_result(rca)

    return json.dumps({"source": "generated", "rca": rca.to_dict()})


# ---------------------------------------------------------------------------
#  Tool: draft_incident_report
# ---------------------------------------------------------------------------

@mcp.tool()
async def draft_incident_report(
    cluster_id: str,
    platform: Literal["github", "jira"] = "github",
    dry_run: bool = True,
) -> str:
    """Draft (or create) a GitHub issue or Jira ticket from an RCA result.

    An RCA must exist for the cluster — call get_rca_for_cluster first.

    Args:
        cluster_id: Cluster to draft for.
        platform:   "github" or "jira" (default: "github").
        dry_run:    If True (default), return the payload without creating the issue.
    """
    db = get_db()
    await db.initialize()
    repo = LogRepository(db)

    rca_row = await repo.get_rca_for_cluster(cluster_id)
    if not rca_row:
        return json.dumps({
            "error": "No RCA found for this cluster. Call get_rca_for_cluster first."
        })

    cluster_row = await repo.get_cluster_by_id(cluster_id)
    if not cluster_row:
        return json.dumps({"error": f"Cluster {cluster_id} not found."})

    rca = RCAResult.from_row(rca_row)
    cluster = Cluster.from_row(cluster_row)

    if platform == "jira":
        draft = JiraPayloadBuilder().build(rca, cluster)
    else:
        draft = GitHubIssueDrafter(dry_run=dry_run).draft(rca, cluster)

    await repo.insert_incident_draft(draft)

    return json.dumps({
        "status": draft.status,
        "platform": platform,
        "dry_run": dry_run,
        "draft": draft.to_dict(),
    })


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
