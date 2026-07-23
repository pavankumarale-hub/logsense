# ADR 0001 — Log Clustering Approach: Drain vs. Embedding-Based

**Status:** Accepted
**Date:** 2024-01-15
**Deciders:** Project author

---

## Context

LogSense needs to group similar log lines into clusters before feeding them to
an LLM for root cause analysis. The two mainstream approaches in 2024 are:

1. **Template extraction** (Drain, Spell, AEL): Treat log messages as
   token sequences; extract a stable template by replacing variable tokens
   with wildcards.
2. **Embedding-based clustering** (k-means / HDBSCAN over sentence embeddings):
   Encode each log message as a dense vector, then cluster in embedding space.

---

## Decision

We use **Drain (template extraction)** for v1.

---

## Rationale

### Drain advantages

| Property | Drain | Embeddings |
|---|---|---|
| Latency per log | O(depth × max_children) ≈ μs | O(n × d) embedding call ≈ 5–50ms |
| External dependency | None | Embedding model (OpenAI/local) |
| Determinism | Yes — same input always same cluster | No — depends on random init |
| Interpretability | Template is a human-readable string | Cluster label requires manual naming |
| Works offline | Yes | Requires embedding API or local GPU |
| Memory | O(nodes × vocab) — bounded | O(n × d) — grows linearly |

### Why not embeddings for v1?

Embedding-based clustering is genuinely superior for **semantically equivalent
but syntactically different** errors, e.g.:

- `"Cannot connect to postgres"` and `"Failed to reach database"` would land in
  separate Drain templates but the same embedding cluster.

However, for a portfolio project and for v1 production deployments:

1. **Zero cold-start friction.** Drain requires no API key, no model download,
   no GPU. The pipeline works out of the box with `pip install logsense`.
2. **In production, most error patterns ARE syntactically similar.** Java stack
   traces, database timeout messages, and HTTP error logs repeat the same
   structural wording; template extraction captures these reliably.
3. **Cost and latency.** In a high-throughput log environment (10k+ lines/min),
   embedding every line is impractical without significant infrastructure.
   Drain processes lines at ~500k/sec on a single core.

### What we lose

- Semantic grouping of paraphrase-variant errors.
- Ability to cluster across different log formats that describe the same root
  cause (e.g. a Java NPE and an upstream Nginx 502 caused by the same bug).

### Mitigation

The LLM RCA step partially compensates: when we surface a Drain cluster to
the model, it can recognize that two separately-clustered patterns stem from
the same root cause and say so in its hypothesis.

---

## Future consideration

A v2 upgrade path: run Drain first for cheap initial grouping, then optionally
merge clusters using embedding similarity as a second pass, gated behind a
`ENABLE_SEMANTIC_MERGE=true` flag. This keeps the fast path cheap and the
semantic path opt-in.

---

## Storage corollary

SQLite was chosen over Postgres for the same philosophy: zero external
dependency, `docker compose up` just works, and the pipeline itself is the
story, not the infrastructure. A production deployment would use Postgres
with an async driver and connection pooling.
