# LogSense — Low-Level Design: Triage & RCA Pipeline

**Version:** 1.1
**Status:** Active
**Last updated:** 2026-07-23

---

## 1. Problem Statement

Application logs are the highest-density signal source for diagnosing production
incidents, but they are unstructured, high-volume, and require expert pattern
recognition to interpret under pressure. On-call engineers spend 30–60 minutes
per incident correlating log patterns across services before they can form a
root cause hypothesis.

This LLD describes the triage and RCA pipeline that reduces that time to
< 30 seconds by: (1) grouping redundant error messages into canonical templates,
(2) scoring clusters by operational urgency, and (3) generating a plain-language
root cause hypothesis with a concrete next action.

---

## 2. Scope

This document covers the core pipeline: `ingestion → clustering → scoring → RCA`.

The action layer (GitHub issue drafting) and MCP/REST interfaces are described
in `docs/architecture.md`. The ADRs document major tradeoff decisions.

Out of scope: log shipping infrastructure, authentication/authz, multi-tenant
isolation.

---

## 3. Design Constraints

| Constraint | Value |
|---|---|
| Throughput target | 10k log lines/sec on a single core (offline batch) |
| RCA latency | < 5s per cluster (LLM call dominates) |
| LLM cost | Minimize calls — one call per cluster, result cached |
| Infrastructure | Zero managed services required in dev (SQLite, no Redis) |
| Determinism | Same log file must always produce the same clusters |
| Portability | LLM model is runtime-configurable via env var |

---

## 4. System Components

### 4.1 Ingestion Layer (`logsense/ingestion/`)

**Responsibility:** Accept raw log content in multiple formats and emit a
normalized `LogEntry` stream.

**Supported formats (tried in order):**
1. JSON (any line starting with `{`)
2. Spring Boot default (`YYYY-MM-DD HH:MM:SS.mmm LEVEL PID --- [thread] logger : msg`)
3. Spring Boot custom (`YYYY-MM-DD HH:MM:SS.mmm LEVEL [service] [trace=id] - msg`)
4. Nginx error (`YYYY/MM/DD HH:MM:SS [level] pid#tid: msg`)
5. Syslog RFC 3164 (`Mon DD HH:MM:SS host service[pid]: msg`)

**Stack trace handling:** Continuation lines (starting with `\tat`, `Caused by:`,
`\t...`) are appended to the preceding entry's `stack_trace` field rather than
emitted as separate entries. This prevents one Java exception from inflating
cluster counts.

**Normalization pass:**
- `level` → canonical set (`DEBUG`, `INFO`, `WARN`, `ERROR`, `CRITICAL`)
- `service` → lowercase, hyphens instead of underscores
- `message` → `.strip()`

**Output schema:**
```python
@dataclass
class LogEntry:
    id: str            # UUID4
    timestamp: datetime  # always UTC
    level: str
    service: str
    message: str
    stack_trace: str | None
    trace_id: str | None
    correlation_id: str | None
    raw_line: str
    source: str
    ingested_at: datetime
```

### 4.2 Drain Clustering (`logsense/triage/drain.py`)

**Algorithm:** Drain (He et al., 2017) with the following parameterisation:

| Parameter | Default | Effect |
|---|---|---|
| `depth` | 4 | Height of prefix tree; higher = more precise routing |
| `sim_threshold` | 0.5 | Minimum token-similarity to merge into existing group |
| `max_children` | 100 | Cap on prefix node branching factor |

**Processing steps per log entry:**

```
1. Preprocess message: apply regex rules to replace variable tokens with <*>
   Rules (applied left-to-right):
   - IPv4 addresses       → <*>
   - UUIDs (8-4-4-4-12)   → <*>
   - Hex strings 0x...    → <*>
   - ISO timestamps       → <*>
   - Numbers followed by "ms" → <*>ms  (preserve "ms" unit for readability)
   - Unix-style file paths → <*>
   - Standalone integers   → <*>

2. Tokenize: split preprocessed message on whitespace

3. Route to length node: root.children[str(len(tokens))]

4. Walk prefix path: tokens[0..depth-2], inserting wildcard children
   when a token is unseen and the node is at max_children capacity

5. At leaf: compute seq_similarity(existing_group.tokens, new_tokens)
   seq_similarity = (literal matches × 1.0 + wildcard-vs-wildcard matches × 0.5) / total_tokens
   Wildcard positions count as half a match: this allows all-variable messages
   (e.g. pure IP/number lines that preprocess entirely to <*>) to cluster together,
   while preventing high-wildcard messages with different literal tokens from
   falsely merging at the default threshold.

6a. If best_similarity >= sim_threshold:
      Merge: template[i] = token if match else <*>
      Update template index

6b. Else:
      Create new LogGroup with tokens as initial template
```

**Complexity:** O(depth × max_children) per entry ≈ O(1) amortized.

### 4.3 Cluster Manager (`logsense/triage/cluster.py`)

The `ClusterEngine` wraps `DrainParser` and maintains `Cluster` objects
(business-level view) mapped to `LogGroup` objects (Drain's internal view).

When Drain merges two templates (widening `token → <*>`), the `LogGroup.id`
remains stable but `template_tokens` changes. The engine detects this and
updates the cluster's template in-place, keeping SQLite state consistent.

### 4.4 Risk Scorer (`logsense/triage/scorer.py`)

```
risk_score = (frequency_score × 0.40)
           + (recency_score   × 0.30)
           + (severity_score  × 0.30)
```

**Frequency score:** `log1p(count) / log1p(1000)`, capped at 1.0.
Log scale prevents a 10k-entry connection storm from completely dominating
a 5-entry OOM that would cause a node failure.

**Recency score:** `exp(-0.693 × age_hours / 1.0)`.
Half-life = 1 hour. A cluster that fired 1 hour ago has recency_score = 0.5.
A cluster from yesterday approaches 0.

**Severity score:**
```
DEBUG    → 0.0
INFO     → 0.1
WARN     → 0.4
ERROR    → 0.8
CRITICAL → 1.0
```

**Weight rationale:** Frequency is given the highest weight because the most
useful signal in log triage is *rate*. Recency is second — stale patterns
should not dominate the triage view. Severity breaks ties and surfaces
high-severity low-frequency events (OOM, data corruption) over noisy WARNs.

### 4.5 RCA Generator (`logsense/rca/generator.py`)

**Input:** A `Cluster` object + up to 5 representative log samples.

**Prompt strategy (see ADR 0002 for rationale):**
- System prompt: schema definition + confidence rubric
- User turn: cluster metadata + log samples

**Output parsing:**
1. Strip markdown fences if present
2. `json.loads()` the response
3. Clamp `confidence_score` to [0, 1]
4. Derive `confidence` label from score if model omits it

**Caching:** Before making an LLM call, the pipeline checks whether
an RCA already exists for the cluster in SQLite. Cache is invalidated
by `force=True` flag (REST) or not in MCP (cost-conscious default).

### 4.6 Storage Schema

See `logsense/storage/db.py` for the DDL. Key relationships:

```
log_entries ──< cluster_members >── clusters ──< rca_results ──< incident_drafts
```

`clusters.template` has a UNIQUE constraint to support upsert-on-conflict
when the same template reappears across ingestion batches.

---

## 5. Data Flow

```
Raw log content (string)
        │
        ▼
  parse_log_lines()          # ingestion/parser.py — multi-format
        │
        ▼
  normalize()                # ingestion/normalizer.py — canonical levels/services
        │
        ▼
  ClusterEngine.process()    # triage/cluster.py
    ├── DrainParser.add_entry()   # triage/drain.py — template extraction
    └── score_cluster()           # triage/scorer.py — batch-local risk score (initial)
        │
        ▼
  LogRepository.upsert_cluster()  # storage/repository.py
    # Accumulates count, preserves max_severity and affected_services across batches,
    # then recomputes risk_score from the cumulative DB values (not the batch-local
    # score) so frequency reflects total cluster history, not just the current batch.
        │
        ▼  (on demand)
  RCAGenerator.generate()    # rca/generator.py — LLM call
        │
        ▼
  RCAResult                  # rca/models.py
        │
        ▼  (on demand)
  GitHubIssueDrafter.draft() # actions/github.py — incident report
  JiraPayloadBuilder.build() # actions/jira.py
```

---

## 6. Failure Modes and Mitigations

| Failure | Impact | Mitigation |
|---|---|---|
| Anthropic API down | RCA unavailable | Cache previous RCA; surface error clearly |
| Malformed LLM JSON | RCA generation fails | `_parse_response` strips fences (handles trailing prose after closing fence), raises `ValueError` with raw text |
| Drain template explosion | Too many clusters | `max_children` cap per node; `sim_threshold` merge |
| SQLite lock contention | Slow concurrent writes | WAL mode enabled; async driver (aiosqlite) |
| Log format not recognized | Entry skipped | Logged silently; `parse_log_lines` returns subset |
| Stack trace inflates counts | Overcounting errors | Continuation lines attach to preceding entry |

---

## 7. Rollout / Operational Notes

**First deploy:**
1. Set `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `LOGSENSE_DRY_RUN=true`
2. `docker compose up`
3. Ingest sample logs, verify clusters appear at `/api/v1/triage/clusters`
4. Run RCA on top cluster, review output
5. When satisfied, set `LOGSENSE_DRY_RUN=false` to enable real issue creation

**Drain parameter tuning:**
- If clusters are too granular (too many similar but slightly different
  templates), lower `sim_threshold` (e.g. 0.4) or reduce `depth`.
- If unrelated errors merge into one cluster, raise `sim_threshold` (e.g. 0.65).

**Production scaling path:**
- Replace SQLite with Postgres + `asyncpg`
- Add a message queue (Kafka / SQS) in front of the ingestion layer
- Deploy `ClusterEngine` as a stateless worker reading from the queue
- Keep RCA generation as an on-demand API call (not streaming)
