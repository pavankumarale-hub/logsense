# Connecting LogSense to Claude Desktop / Claude Code

LogSense exposes its core pipeline as an MCP (Model Context Protocol) server.
Once configured, Claude can ingest logs, run triage, generate RCA, and draft
incident reports directly from a conversation — no copy-paste, no manual API
calls.

---

## Prerequisites

1. Python 3.11+ installed
2. LogSense installed: `pip install -e .` (from the repo root)
3. `.env` file created: `cp .env.example .env` and fill in `ANTHROPIC_API_KEY`

---

## Claude Desktop

Edit (or create) `~/.claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "logsense": {
      "command": "python",
      "args": ["-m", "logsense.mcp_server.server"],
      "cwd": "/path/to/logsense",
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-your-key-here",
        "ANTHROPIC_MODEL": "claude-sonnet-4-6",
        "LOGSENSE_DB_PATH": "/path/to/logsense.db",
        "LOGSENSE_DRY_RUN": "true"
      }
    }
  }
}
```

Replace `/path/to/logsense` with the absolute path to the repo root.

Restart Claude Desktop. You should see `logsense` in the tools list.

---

## Claude Code (CLI)

Add to your project's `.claude/settings.json` or to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "logsense": {
      "command": "python",
      "args": ["-m", "logsense.mcp_server.server"],
      "cwd": "/path/to/logsense",
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-your-key-here",
        "LOGSENSE_DB_PATH": "/tmp/logsense.db"
      }
    }
  }
}
```

Or launch the server manually in a separate terminal and point Claude Code at it:

```bash
cd /path/to/logsense
source .venv/bin/activate
python -m logsense.mcp_server.server
```

---

## Verifying the connection

Once configured, ask Claude:

> "List the available LogSense tools"

Claude should respond with the four tools: `ingest_logs`, `get_clusters`,
`get_rca_for_cluster`, `draft_incident_report`.

---

## Example conversation

```
User: Here are my logs from the last 10 minutes. Can you identify what's broken?

[pastes log content]

Claude: (calls ingest_logs with the log content)
        (calls get_clusters to see the risk-ranked summary)

        I found 3 clusters. The highest-risk one (score: 0.82) is:
        "Database connection timeout after <*>ms" — appeared 8 times in 2 minutes,
        all from payment-service.

        Want me to run root cause analysis on this?

User: Yes please.

Claude: (calls get_rca_for_cluster)

        Root Cause Hypothesis (high confidence, 88%):
        The HikariCP connection pool in payment-service is exhausted. Most likely
        a slow query is holding connections without releasing them. The consistent
        30-second timeout is the HikariCP wait timeout.

        Suggested action: Run SHOW PROCESSLIST and check HikariCP metrics at
        /actuator/metrics/hikaricp.connections.active.

        Want me to draft a GitHub issue?

User: Yes, draft it.

Claude: (calls draft_incident_report — dry_run=true by default)

        Here's the draft issue: [title, body, labels shown]

        To actually create it, I'd need LOGSENSE_DRY_RUN=false in my config
        and GITHUB_TOKEN / GITHUB_REPO set.
```

---

## Available Tools

### `ingest_logs`
Parse and store log content.
- `content` (string, required): raw log text
- `source` (string, optional): label for the source, e.g. "production-k8s"

### `get_clusters`
Return clusters ranked by risk score.
- `limit` (int, default 20)
- `min_risk_score` (float, default 0.0)

### `get_rca_for_cluster`
Run LLM root cause analysis for a cluster. Caches results — subsequent calls
return the cached RCA without a new LLM call.
- `cluster_id` (string, required): ID from `get_clusters` output

### `draft_incident_report`
Draft a GitHub issue or Jira payload from a cluster's RCA.
- `cluster_id` (string, required)
- `platform` (string, default "github"): "github" or "jira"
- `dry_run` (bool, default true): if true, return the payload without posting

---

## Troubleshooting

**"No module named logsense"** — Make sure LogSense is installed in the same
Python environment the MCP server command uses. Run `which python` to check.

**"ANTHROPIC_API_KEY not set"** — The `env` block in the MCP config must
include the key, or it must be set in the shell environment before launching
Claude Desktop.

**Clusters don't appear after ingesting** — Check that the `LOGSENSE_DB_PATH`
is writable. The first `ingest_logs` call also initializes the schema.
