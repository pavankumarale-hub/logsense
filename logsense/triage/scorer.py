"""Risk scoring for log clusters.

Score components
----------------
1. Frequency (40%): log-scaled count, capped at 1.0 at 1000 occurrences.
   Rationale: frequency matters but a million-entry storm shouldn't dwarf a
   10-entry silent data corruption.

2. Recency (30%): exponential decay with a 1-hour half-life.
   Rationale: a cluster that fired 5 minutes ago is more actionable than one
   that fired last night, even if counts are identical.

3. Severity (30%): linear mapping from log level.
   Rationale: an ERROR cluster with 3 hits outranks a WARN cluster with 300.

Final score is in [0.0, 1.0].  Clusters are ranked descending.
"""

import math
from datetime import datetime

from .models import Cluster

_SEVERITY_SCORE: dict[str, float] = {
    "DEBUG": 0.0,
    "INFO": 0.1,
    "WARN": 0.4,
    "ERROR": 0.8,
    "CRITICAL": 1.0,
}

_FREQ_CAP = 1000.0      # log(1000) → frequency_score = 1.0
_HALF_LIFE_HOURS = 1.0  # recency half-life
_LN2 = math.log(2)     # ln(2) for exponential half-life decay


def score_cluster(cluster: "Cluster", now: datetime) -> float:
    freq_score = min(math.log1p(cluster.count) / math.log1p(_FREQ_CAP), 1.0)

    age_hours = max((now - cluster.last_seen).total_seconds() / 3600, 0.0)
    recency_score = math.exp(-_LN2 * age_hours / _HALF_LIFE_HOURS)

    sev_score = _SEVERITY_SCORE.get(cluster.max_severity, 0.5)

    return (freq_score * 0.4) + (recency_score * 0.3) + (sev_score * 0.3)
