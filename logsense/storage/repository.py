"""Data access layer — all SQL lives here, nowhere else."""

import json
from datetime import datetime, timezone

from logsense.ingestion.models import LogEntry
from logsense.triage.models import Cluster
from logsense.rca.models import RCAResult
from logsense.actions.models import IncidentDraft
from .db import Database


class LogRepository:
    def __init__(self, db: Database):
        self._db = db

    # ------------------------------------------------------------------ #
    #  Log entries                                                         #
    # ------------------------------------------------------------------ #

    async def insert_log_entries(self, entries: list[LogEntry]) -> int:
        if not entries:
            return 0
        async with self._db.connection() as conn:
            await conn.executemany(
                """INSERT OR IGNORE INTO log_entries
                   (id, timestamp, level, service, message, stack_trace,
                    trace_id, correlation_id, raw_line, source, ingested_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        e.id,
                        e.timestamp.isoformat(),
                        e.level,
                        e.service,
                        e.message,
                        e.stack_trace,
                        e.trace_id,
                        e.correlation_id,
                        e.raw_line,
                        e.source,
                        e.ingested_at.isoformat(),
                    )
                    for e in entries
                ],
            )
            await conn.commit()
        return len(entries)

    async def get_log_entries(
        self,
        limit: int = 100,
        offset: int = 0,
        level: str | None = None,
        service: str | None = None,
    ) -> list[dict]:
        clauses = []
        params: list = []
        if level:
            clauses.append("level = ?")
            params.append(level.upper())
        if service:
            clauses.append("service = ?")
            params.append(service.lower())
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM log_entries {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        async with self._db.connection() as conn:
            async with conn.execute(sql, params) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    #  Clusters                                                            #
    # ------------------------------------------------------------------ #

    async def upsert_cluster(self, cluster: "Cluster") -> None:
        async with self._db.connection() as conn:
            await conn.execute(
                """INSERT INTO clusters
                   (id, template, template_tokens, first_seen, last_seen,
                    count, max_severity, affected_services, risk_score, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(template) DO UPDATE SET
                     last_seen        = excluded.last_seen,
                     count            = excluded.count,
                     max_severity     = excluded.max_severity,
                     affected_services= excluded.affected_services,
                     risk_score       = excluded.risk_score,
                     updated_at       = excluded.updated_at""",
                (
                    cluster.id,
                    cluster.template,
                    json.dumps(cluster.template_tokens),
                    cluster.first_seen.isoformat(),
                    cluster.last_seen.isoformat(),
                    cluster.count,
                    cluster.max_severity,
                    json.dumps(sorted(cluster.affected_services)),
                    cluster.risk_score,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await conn.commit()

    async def add_cluster_members(self, cluster_id: str, entry_ids: list[str]) -> None:
        if not entry_ids:
            return
        async with self._db.connection() as conn:
            await conn.executemany(
                "INSERT OR IGNORE INTO cluster_members (cluster_id, log_entry_id) VALUES (?,?)",
                [(cluster_id, eid) for eid in entry_ids],
            )
            await conn.commit()

    async def get_clusters(
        self, limit: int = 50, min_risk_score: float = 0.0
    ) -> list[dict]:
        async with self._db.connection() as conn:
            async with conn.execute(
                """SELECT * FROM clusters
                   WHERE risk_score >= ?
                   ORDER BY risk_score DESC
                   LIMIT ?""",
                (min_risk_score, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_cluster_by_id(self, cluster_id: str) -> dict | None:
        async with self._db.connection() as conn:
            async with conn.execute(
                "SELECT * FROM clusters WHERE id = ?", (cluster_id,)
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None

    async def get_cluster_log_samples(
        self, cluster_id: str, limit: int = 5
    ) -> list[dict]:
        async with self._db.connection() as conn:
            async with conn.execute(
                """SELECT le.* FROM log_entries le
                   JOIN cluster_members cm ON cm.log_entry_id = le.id
                   WHERE cm.cluster_id = ?
                   ORDER BY le.timestamp DESC
                   LIMIT ?""",
                (cluster_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    #  RCA results                                                         #
    # ------------------------------------------------------------------ #

    async def insert_rca_result(self, result: "RCAResult") -> None:
        async with self._db.connection() as conn:
            await conn.execute(
                """INSERT OR REPLACE INTO rca_results
                   (id, cluster_id, title, summary, root_cause_hypothesis,
                    confidence, confidence_score, suggested_action,
                    affected_service, model_used, generated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    result.id,
                    result.cluster_id,
                    result.title,
                    result.summary,
                    result.root_cause_hypothesis,
                    result.confidence,
                    result.confidence_score,
                    result.suggested_action,
                    result.affected_service,
                    result.model_used,
                    result.generated_at.isoformat(),
                ),
            )
            await conn.commit()

    async def get_rca_for_cluster(self, cluster_id: str) -> dict | None:
        async with self._db.connection() as conn:
            async with conn.execute(
                """SELECT * FROM rca_results
                   WHERE cluster_id = ?
                   ORDER BY generated_at DESC
                   LIMIT 1""",
                (cluster_id,),
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------ #
    #  Incident drafts                                                     #
    # ------------------------------------------------------------------ #

    async def insert_incident_draft(self, draft: "IncidentDraft") -> None:
        async with self._db.connection() as conn:
            await conn.execute(
                """INSERT OR REPLACE INTO incident_drafts
                   (id, rca_id, platform, payload, status, external_url, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    draft.id,
                    draft.rca_id,
                    draft.platform,
                    json.dumps(draft.payload),
                    draft.status,
                    draft.external_url,
                    draft.created_at.isoformat(),
                ),
            )
            await conn.commit()
