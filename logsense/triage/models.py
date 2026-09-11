"""Data models for the triage layer."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


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

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Cluster":
        return cls(
            id=row["id"],
            template=row["template"],
            template_tokens=json.loads(row["template_tokens"]),
            first_seen=datetime.fromisoformat(row["first_seen"]),
            last_seen=datetime.fromisoformat(row["last_seen"]),
            count=row["count"],
            max_severity=row["max_severity"],
            affected_services=set(json.loads(row["affected_services"])),
            risk_score=row["risk_score"] or 0.0,
        )

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
