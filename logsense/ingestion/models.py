"""Core data models for the ingestion layer."""

from dataclasses import dataclass, field
from datetime import datetime


SEVERITY_ORDER = {"DEBUG": 0, "INFO": 1, "WARN": 2, "WARNING": 2, "ERROR": 3, "CRITICAL": 4, "FATAL": 4}


@dataclass
class LogEntry:
    id: str
    timestamp: datetime
    level: str
    service: str
    message: str
    raw_line: str
    source: str
    ingested_at: datetime
    stack_trace: str | None = None
    trace_id: str | None = None
    correlation_id: str | None = None

    @property
    def severity_rank(self) -> int:
        return SEVERITY_ORDER.get(self.level.upper(), 1)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "level": self.level,
            "service": self.service,
            "message": self.message,
            "stack_trace": self.stack_trace,
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "raw_line": self.raw_line,
            "source": self.source,
            "ingested_at": self.ingested_at.isoformat(),
        }
