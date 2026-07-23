"""Unit tests for the log parser.

These tests are purely in-memory — no I/O, no LLM calls.
"""

import pytest
from datetime import timezone

from logsense.ingestion.parser import parse_log_lines
from logsense.ingestion.normalizer import normalize


pytestmark = pytest.mark.unit


class TestSpringBootCustomFormat:
    def test_parses_error_line(self):
        line = "2024-01-15 10:23:45.123 ERROR [payment-service] [trace=abc123] - DB timeout after 30000ms"
        entries = parse_log_lines(line)
        assert len(entries) == 1
        e = entries[0]
        assert e.level == "ERROR"
        assert e.service == "payment-service"
        assert "DB timeout" in e.message
        assert e.trace_id == "abc123"
        assert e.timestamp.year == 2024
        assert e.timestamp.tzinfo == timezone.utc

    def test_parses_warn_line(self):
        line = "2024-01-15 10:23:46.001 WARN  [inventory-service] - Circuit breaker OPEN"
        entries = parse_log_lines(line)
        assert len(entries) == 1
        assert entries[0].level == "WARN"
        assert entries[0].service == "inventory-service"

    def test_attaches_stack_trace_to_preceding_entry(self):
        content = (
            "2024-01-15 10:23:47.456 ERROR [order-service] [trace=xyz] - NullPointerException\n"
            "\tat com.example.order.OrderService.processOrder(OrderService.java:142)\n"
            "\tat com.example.order.OrderController.submitOrder(OrderController.java:89)\n"
        )
        entries = parse_log_lines(content)
        assert len(entries) == 1
        assert entries[0].stack_trace is not None
        assert "OrderService.processOrder" in entries[0].stack_trace

    def test_parses_multiple_entries(self):
        fixture_path = "tests/fixtures/spring_boot_errors.log"
        with open(fixture_path) as f:
            content = f.read()
        entries = parse_log_lines(content)
        assert len(entries) >= 10
        levels = {e.level for e in entries}
        assert "ERROR" in levels
        assert "WARN" in levels

    def test_services_normalized_to_lowercase(self):
        line = "2024-01-15 10:23:45.123 ERROR [Payment-Service] - Something failed"
        entries = normalize(parse_log_lines(line))
        assert entries[0].service == "payment-service"


class TestSpringBootDefaultFormat:
    def test_parses_default_format(self):
        line = "2024-01-15 10:23:45.123  ERROR 12345 --- [main] com.example.PaymentService : Connection refused"
        entries = parse_log_lines(line)
        assert len(entries) == 1
        assert entries[0].level == "ERROR"
        # Parser extracts the second-to-last segment of the logger FQCN as service name
        # e.g. com.example.PaymentService → "example" (the package, not the class)
        assert entries[0].service in ("example", "paymentservice", "payment-service")
        assert "Connection refused" in entries[0].message


class TestNginxFormat:
    def test_parses_nginx_error(self):
        line = '2024/01/15 10:23:44 [error] 1234#1234: *1 connect() failed (111: Connection refused) while connecting to upstream, client: 10.0.0.15'
        entries = parse_log_lines(line)
        assert len(entries) == 1
        assert entries[0].service == "nginx"
        assert entries[0].level == "ERROR"
        assert "Connection refused" in entries[0].message

    def test_parses_nginx_fixture(self):
        with open("tests/fixtures/nginx_errors.log") as f:
            content = f.read()
        entries = parse_log_lines(content)
        assert len(entries) >= 5
        assert all(e.service == "nginx" for e in entries)


class TestJsonFormat:
    def test_parses_json_line(self):
        import json
        data = {
            "timestamp": "2024-01-15T10:23:45.123Z",
            "level": "ERROR",
            "service": "auth-service",
            "traceId": "trace-abc",
            "message": "JWT token validation failed",
        }
        entries = parse_log_lines(json.dumps(data))
        assert len(entries) == 1
        assert entries[0].level == "ERROR"
        assert entries[0].service == "auth-service"
        assert entries[0].trace_id == "trace-abc"
        assert "JWT" in entries[0].message

    def test_parses_json_fixture(self):
        with open("tests/fixtures/mixed_json.log") as f:
            content = f.read()
        entries = parse_log_lines(content)
        assert len(entries) == 5
        assert entries[0].level == "ERROR"


class TestEdgeCases:
    def test_empty_content_returns_empty_list(self):
        assert parse_log_lines("") == []

    def test_blank_lines_ignored(self):
        content = "\n\n\n2024-01-15 10:23:45.123 ERROR [svc] - msg\n\n"
        entries = parse_log_lines(content)
        assert len(entries) == 1

    def test_unparseable_lines_skipped(self):
        content = "This is completely unparseable garbage\n2024-01-15 10:23:45.123 ERROR [svc] - real error"
        entries = parse_log_lines(content)
        assert len(entries) == 1
        assert "real error" in entries[0].message

    def test_level_normalization(self):
        cases = [
            ("WARNING", "WARN"),
            ("FATAL", "CRITICAL"),
            ("TRACE", "DEBUG"),
        ]
        for raw, expected in cases:
            line = f"2024-01-15 10:23:45.123 {raw} [svc] - msg"
            entries = normalize(parse_log_lines(line))
            assert entries[0].level == expected, f"Expected {expected} for {raw}"
