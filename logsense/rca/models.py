"""Data models for RCA results."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

ConfidenceLevel = Literal["low", "medium", "high"]


@dataclass
class RCAResult:
    id: str
    cluster_id: str
    title: str
    summary: str
    root_cause_hypothesis: str
    confidence: ConfidenceLevel
    confidence_score: float
    suggested_action: str
    affected_service: str
    model_used: str
    generated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "RCAResult":
        return cls(
            id=row["id"],
            cluster_id=row["cluster_id"],
            title=row["title"],
            summary=row["summary"],
            root_cause_hypothesis=row["root_cause_hypothesis"],
            confidence=cast(ConfidenceLevel, row["confidence"]),
            confidence_score=row["confidence_score"],
            suggested_action=row["suggested_action"],
            affected_service=row["affected_service"],
            model_used=row["model_used"],
            generated_at=datetime.fromisoformat(row["generated_at"]),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "cluster_id": self.cluster_id,
            "title": self.title,
            "summary": self.summary,
            "root_cause_hypothesis": self.root_cause_hypothesis,
            "confidence": self.confidence,
            "confidence_score": round(self.confidence_score, 3),
            "suggested_action": self.suggested_action,
            "affected_service": self.affected_service,
            "model_used": self.model_used,
            "generated_at": self.generated_at.isoformat(),
        }
