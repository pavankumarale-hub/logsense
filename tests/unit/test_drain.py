"""Unit tests for the Drain log clustering algorithm."""

import pytest
from datetime import datetime, timezone

from logsense.triage.drain import DrainParser
from logsense.ingestion.models import LogEntry


pytestmark = pytest.mark.unit


def _make_entry(message: str, service: str = "svc") -> LogEntry:
    return LogEntry(
        id="test-id",
        timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        level="ERROR",
        service=service,
        message=message,
        raw_line=message,
        source="test",
        ingested_at=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
    )


class TestTemplateExtraction:
    def test_identical_messages_produce_one_group(self):
        parser = DrainParser()
        e1 = _make_entry("Connection refused to database")
        e2 = _make_entry("Connection refused to database")
        g1 = parser.add_entry(e1)
        g2 = parser.add_entry(e2)
        assert g1.id == g2.id

    def test_numeric_variables_become_wildcard(self):
        parser = DrainParser()
        e1 = _make_entry("Connection timeout after 30000ms")
        e2 = _make_entry("Connection timeout after 29998ms")
        g1 = parser.add_entry(e1)
        g2 = parser.add_entry(e2)
        assert g1.id == g2.id
        assert "<*>" in g1.template

    def test_uuid_variables_become_wildcard(self):
        parser = DrainParser()
        e1 = _make_entry("Session a1b2c3d4-e5f6-7890-abcd-ef1234567890 expired")
        e2 = _make_entry("Session b2c3d4e5-f6a7-8901-bcde-fa2345678901 expired")
        g1 = parser.add_entry(e1)
        g2 = parser.add_entry(e2)
        assert g1.id == g2.id

    def test_distinct_error_types_produce_different_groups(self):
        parser = DrainParser()
        e1 = _make_entry("Database connection timeout after 30000ms")
        e2 = _make_entry("JWT validation failed for user 12345")
        g1 = parser.add_entry(e1)
        g2 = parser.add_entry(e2)
        assert g1.id != g2.id

    def test_groups_property_returns_all_groups(self):
        parser = DrainParser()
        for msg in [
            "DB timeout after 30000ms",
            "DB timeout after 30001ms",
            "NPE in service Foo",
            "NPE in service Bar",
        ]:
            parser.add_entry(_make_entry(msg))
        assert len(parser.groups) == 2

    def test_template_is_stable_after_merging(self):
        parser = DrainParser()
        e1 = _make_entry("Error processing order 111 for customer alice")
        e2 = _make_entry("Error processing order 222 for customer bob")
        parser.add_entry(e1)
        g2 = parser.add_entry(e2)
        assert "Error processing order" in g2.template
        assert "<*>" in g2.template

    def test_ip_addresses_become_wildcard(self):
        parser = DrainParser()
        e1 = _make_entry("Connection from 192.168.1.100 rejected")
        e2 = _make_entry("Connection from 10.0.0.50 rejected")
        g1 = parser.add_entry(e1)
        g2 = parser.add_entry(e2)
        assert g1.id == g2.id

    def test_different_token_count_produces_different_group(self):
        parser = DrainParser()
        e1 = _make_entry("short error")
        e2 = _make_entry("this is a completely different and much longer error message")
        g1 = parser.add_entry(e1)
        g2 = parser.add_entry(e2)
        assert g1.id != g2.id

    def test_custom_sim_threshold(self):
        # With very high threshold, even slightly different messages stay separate
        strict_parser = DrainParser(sim_threshold=0.99)
        e1 = _make_entry("Error reading file config.yaml at line 42")
        e2 = _make_entry("Error reading file settings.yaml at line 99")
        g1 = strict_parser.add_entry(e1)
        g2 = strict_parser.add_entry(e2)
        # After preprocessing (numbers → <*>), tokens still differ at "config.yaml" vs "settings.yaml"
        # so they should stay in separate groups with strict threshold
        assert g1.id != g2.id
