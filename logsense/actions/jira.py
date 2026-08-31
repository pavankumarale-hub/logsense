"""Jira-compatible payload builder.

Outputs a Jira Cloud REST API v3 payload that can be POSTed to
POST /rest/api/3/issue — useful for environments where Jira is the
canonical tracker rather than GitHub.

Always dry-run in this implementation; a real Jira POST is left as an
exercise (requires Atlassian OAuth or API token configuration).
"""

import uuid

from logsense.rca.models import RCAResult
from logsense.triage.models import Cluster
from .models import IncidentDraft

def _para(text: str) -> dict:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


_PRIORITY_MAP = {
    "CRITICAL": "Highest",
    "ERROR": "High",
    "WARN": "Medium",
    "INFO": "Low",
    "DEBUG": "Lowest",
}


class JiraPayloadBuilder:
    def __init__(self, project_key: str = "OPS") -> None:
        self._project_key = project_key

    def build(self, rca: RCAResult, cluster: Cluster) -> IncidentDraft:
        priority = _PRIORITY_MAP.get(cluster.max_severity, "Medium")

        description_content = [
            _para(f"Summary: {rca.summary}"),
            _para(f"Root Cause Hypothesis: {rca.root_cause_hypothesis}"),
            _para(f"Suggested Action: {rca.suggested_action}"),
            _para(
                f"Cluster template: {cluster.template} | "
                f"Occurrences: {cluster.count} | "
                f"Risk score: {cluster.risk_score:.3f} | "
                f"Confidence: {rca.confidence} ({rca.confidence_score:.0%})"
            ),
        ]

        payload = {
            "fields": {
                "project": {"key": self._project_key},
                "summary": f"[LogSense] {rca.title}",
                "issuetype": {"name": "Bug"},
                "priority": {"name": priority},
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": description_content,
                },
                "labels": ["logsense", "auto-rca"],
                "components": [{"name": rca.affected_service}],
            }
        }

        return IncidentDraft(
            id=str(uuid.uuid4()),
            rca_id=rca.id,
            platform="jira",
            payload=payload,
            status="draft",
        )
