"""SQLite connection management and schema bootstrap.

Design rationale (vs. Postgres): SQLite is sufficient for a demo/portfolio
context where the primary goal is showing the pipeline, not horizontal scale.
It requires zero external infrastructure — `docker compose up` just works.
A real production deployment would swap in Postgres; the repository layer
abstracts the difference. See docs/adr/0001-clustering-approach.md for the
storage tradeoff discussion.
"""

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from logsense.config import get_settings

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS log_entries (
    id              TEXT PRIMARY KEY,
    timestamp       TEXT NOT NULL,
    level           TEXT NOT NULL,
    service         TEXT NOT NULL,
    message         TEXT NOT NULL,
    stack_trace     TEXT,
    trace_id        TEXT,
    correlation_id  TEXT,
    raw_line        TEXT NOT NULL,
    source          TEXT NOT NULL,
    ingested_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_log_entries_timestamp ON log_entries(timestamp);
CREATE INDEX IF NOT EXISTS idx_log_entries_level     ON log_entries(level);
CREATE INDEX IF NOT EXISTS idx_log_entries_service   ON log_entries(service);

CREATE TABLE IF NOT EXISTS clusters (
    id                  TEXT PRIMARY KEY,
    template            TEXT NOT NULL UNIQUE,
    template_tokens     TEXT NOT NULL,   -- JSON array
    first_seen          TEXT NOT NULL,
    last_seen           TEXT NOT NULL,
    count               INTEGER NOT NULL DEFAULT 0,
    max_severity        TEXT NOT NULL,
    affected_services   TEXT NOT NULL,   -- JSON array
    risk_score          REAL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clusters_risk_score ON clusters(risk_score DESC);

CREATE TABLE IF NOT EXISTS cluster_members (
    cluster_id      TEXT NOT NULL REFERENCES clusters(id),
    log_entry_id    TEXT NOT NULL REFERENCES log_entries(id),
    PRIMARY KEY (cluster_id, log_entry_id)
);

CREATE TABLE IF NOT EXISTS rca_results (
    id                      TEXT PRIMARY KEY,
    cluster_id              TEXT NOT NULL REFERENCES clusters(id),
    title                   TEXT NOT NULL,
    summary                 TEXT NOT NULL,
    root_cause_hypothesis   TEXT NOT NULL,
    confidence              TEXT NOT NULL,  -- low | medium | high
    confidence_score        REAL NOT NULL,
    suggested_action        TEXT NOT NULL,
    affected_service        TEXT NOT NULL,
    model_used              TEXT NOT NULL,
    generated_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS incident_drafts (
    id                  TEXT PRIMARY KEY,
    rca_id              TEXT NOT NULL REFERENCES rca_results(id),
    platform            TEXT NOT NULL,  -- github | jira
    payload             TEXT NOT NULL,  -- JSON
    status              TEXT NOT NULL DEFAULT 'draft',
    external_url        TEXT,
    created_at          TEXT NOT NULL
);
"""


class Database:
    def __init__(self, db_path: str):
        self._path = db_path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self._path) as conn:
            await conn.executescript(_DDL)
            await conn.commit()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self._path) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys=ON")
            yield conn


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database(get_settings().db_path)
    return _db
