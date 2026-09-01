"""Cluster engine: wraps Drain and maps groups to Cluster objects."""

import uuid
from datetime import datetime, timezone

from logsense.config import get_settings
from logsense.ingestion.models import LogEntry, SEVERITY_ORDER
from .drain import DrainParser
from .models import Cluster
from .scorer import score_cluster


class ClusterEngine:
    """Stateful engine that accumulates log entries into clusters.

    Designed to be called once per ingestion batch.  For incremental ingestion
    across multiple batches the engine should be reconstructed from the
    persisted cluster state (see ClusterEngine.from_stored_clusters).
    """

    def __init__(self, drain: DrainParser | None = None) -> None:
        cfg = get_settings()
        self._drain = drain or DrainParser(
            depth=cfg.drain_depth,
            sim_threshold=cfg.drain_sim_threshold,
            max_children=cfg.drain_max_children,
        )
        # cluster_id -> Cluster
        self._clusters: dict[str, Cluster] = {}
        # Drain LogGroup.id -> application Cluster.id
        self._group_to_cluster: dict[str, str] = {}

    def process(self, entries: list[LogEntry]) -> list[Cluster]:
        """Ingest entries, update clusters, return updated cluster list."""
        for entry in entries:
            group = self._drain.add_entry(entry)
            cluster_id = self._group_to_cluster.get(group.id)

            if cluster_id and cluster_id in self._clusters:
                cluster = self._clusters[cluster_id]
                # Template may have widened — update it
                cluster.template = group.template
                cluster.template_tokens = list(group.template_tokens)
                cluster.count += 1
                cluster.last_seen = max(cluster.last_seen, entry.timestamp)
                cluster.first_seen = min(cluster.first_seen, entry.timestamp)
                if SEVERITY_ORDER.get(entry.level, 0) > SEVERITY_ORDER.get(cluster.max_severity, 0):
                    cluster.max_severity = entry.level
                cluster.affected_services.add(entry.service)
                cluster.entry_ids.append(entry.id)
            else:
                cluster = Cluster(
                    id=str(uuid.uuid4()),
                    template=group.template,
                    template_tokens=list(group.template_tokens),
                    first_seen=entry.timestamp,
                    last_seen=entry.timestamp,
                    count=1,
                    max_severity=entry.level,
                    affected_services={entry.service},
                    entry_ids=[entry.id],
                )
                self._clusters[cluster.id] = cluster
                self._group_to_cluster[group.id] = cluster.id

        now = datetime.now(timezone.utc)
        for cluster in self._clusters.values():
            cluster.risk_score = score_cluster(cluster, now)

        return list(self._clusters.values())

    @property
    def clusters(self) -> list[Cluster]:
        return list(self._clusters.values())
