"""Data models for the triage layer."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Cluster:
    id: str
    template: str
    template_tokens: list[str]
    first_seen: datetime
    last_seen: datetime
    count: int
    max_severity: str
    affected_services: set[str]
    entry_ids: list[str] = field(default_factory=list)
    risk_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "template": self.template,
            "template_tokens": self.template_tokens,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "count": self.count,
            "max_severity": self.max_severity,
            "affected_services": sorted(self.affected_services),
            "risk_score": round(self.risk_score, 4),
        }
