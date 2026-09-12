"""Data models for the actions layer."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class IncidentDraft:
    id: str
    rca_id: str
    platform: str  # "github" | "jira"
    payload: dict[str, Any]
    status: str = "draft"  # "draft" | "submitted"
    external_url: str | None = None
    created_at: datetime = field(default_factory=_now_utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rca_id": self.rca_id,
            "platform": self.platform,
            "payload": self.payload,
            "status": self.status,
            "external_url": self.external_url,
            "created_at": self.created_at.isoformat(),
        }
