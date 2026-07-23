"""Unit tests for the risk scoring logic."""

import math
import pytest
from datetime import datetime, timedelta, timezone

from logsense.triage.models import Cluster
from logsense.triage.scorer import score_cluster


pytestmark = pytest.mark.unit


def _make_cluster(
    count: int = 10,
    severity: str = "ERROR",
    age_minutes: float = 0.0,
) -> Cluster:
    now = datetime.now(timezone.utc)
    last_seen = now - timedelta(minutes=age_minutes)
    return Cluster(
        id="test-cluster",
        template="Database connection timeout after <*>ms",
        template_tokens=["Database", "connection", "timeout", "after", "<*>ms"],
        first_seen=last_seen - timedelta(minutes=5),
        last_seen=last_seen,
        count=count,
        max_severity=severity,
        affected_services={"payment-service"},
    )


class TestScoreRange:
    def test_score_is_in_unit_interval(self):
        for count in [1, 10, 100, 1000]:
            for severity in ["DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"]:
                cluster = _make_cluster(count=count, severity=severity)
                score = score_cluster(cluster, datetime.now(timezone.utc))
                assert 0.0 <= score <= 1.0, f"score={score} out of range for {count},{severity}"

    def test_score_is_float(self):
        cluster = _make_cluster()
        score = score_cluster(cluster, datetime.now(timezone.utc))
        assert isinstance(score, float)


class TestSeverityImpact:
    def test_critical_scores_higher_than_error(self):
        now = datetime.now(timezone.utc)
        crit = _make_cluster(severity="CRITICAL")
        err = _make_cluster(severity="ERROR")
        assert score_cluster(crit, now) > score_cluster(err, now)

    def test_error_scores_higher_than_warn(self):
        now = datetime.now(timezone.utc)
        err = _make_cluster(severity="ERROR")
        warn = _make_cluster(severity="WARN")
        assert score_cluster(err, now) > score_cluster(warn, now)

    def test_debug_scores_lowest(self):
        now = datetime.now(timezone.utc)
        debug = _make_cluster(severity="DEBUG")
        info = _make_cluster(severity="INFO")
        assert score_cluster(debug, now) < score_cluster(info, now)


class TestFrequencyImpact:
    def test_higher_count_scores_higher(self):
        now = datetime.now(timezone.utc)
        rare = _make_cluster(count=1)
        frequent = _make_cluster(count=100)
        assert score_cluster(frequent, now) > score_cluster(rare, now)

    def test_frequency_is_log_scaled(self):
        now = datetime.now(timezone.utc)
        # A 1000x increase in count should NOT produce a 1000x increase in score
        small = _make_cluster(count=1)
        large = _make_cluster(count=1000)
        score_small = score_cluster(small, now)
        score_large = score_cluster(large, now)
        ratio = score_large / score_small if score_small > 0 else float("inf")
        assert ratio < 10, f"Score ratio {ratio:.1f} too large — frequency should be log-scaled"


class TestRecencyImpact:
    def test_recent_cluster_scores_higher_than_old(self):
        now = datetime.now(timezone.utc)
        recent = _make_cluster(age_minutes=1)
        old = _make_cluster(age_minutes=120)
        assert score_cluster(recent, now) > score_cluster(old, now)

    def test_very_old_cluster_recency_approaches_zero(self):
        now = datetime.now(timezone.utc)
        ancient = _make_cluster(age_minutes=60 * 24 * 7)  # 1 week old
        score = score_cluster(ancient, now)
        # Recency component (0.3 weight) should be nearly 0; total should be low
        assert score < 0.5  # only frequency + severity contribute meaningfully


class TestEdgeCases:
    def test_single_occurrence_critical(self):
        now = datetime.now(timezone.utc)
        cluster = _make_cluster(count=1, severity="CRITICAL")
        score = score_cluster(cluster, now)
        assert score > 0.0

    def test_zero_count_does_not_crash(self):
        now = datetime.now(timezone.utc)
        cluster = _make_cluster(count=0)
        score = score_cluster(cluster, now)
        assert score >= 0.0
