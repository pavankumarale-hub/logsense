"""Multi-format log parser.

Supports:
  - Spring Boot default and custom structured formats
  - Nginx error logs
  - Generic JSON log lines
  - RFC 3164 / syslog-style lines

Each format is tried in order; the first match wins.
"""

import json
import re
import uuid
from datetime import datetime, timezone
from .models import LogEntry

# ---------------------------------------------------------------------------
# Pre-compiled patterns
# ---------------------------------------------------------------------------

# Spring Boot default: "2024-01-15 10:23:45.123  ERROR 12345 --- [main] com.example.Service : Message"
_SB_DEFAULT = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2}[.,]\d{3})\s+"
    r"(?P<level>TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\s+"
    r"(?P<pid>\d+)\s+---\s+\[(?P<thread>[^\]]+)\]\s+"
    r"(?P<logger>\S+)\s*:\s*(?P<message>.+)"
)

# Spring Boot / custom structured: "2024-01-15 10:23:45.123 ERROR [service-name] [trace=abc] - Message"
_SB_CUSTOM = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2}[.,]\d{3,6})\s+"
    r"(?P<level>TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\s+"
    r"\[(?P<service>[^\]]+)\]"
    r"(?:\s+\[(?P<trace_ctx>[^\]]*)\])?"
    r"\s*[-–]\s*(?P<message>.+)"
)

# Nginx error: "2024/01/15 10:23:45 [error] 1234#5678: *9 message, client: 1.2.3.4, server: ..."
_NGINX_ERROR = re.compile(
    r"(?P<date>\d{4}/\d{2}/\d{2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})\s+"
    r"\[(?P<level>\w+)\]\s+"
    r"(?P<pid>\d+)#(?P<tid>\d+):\s+"
    r"(?:\*(?P<cid>\d+)\s+)?(?P<message>.+)"
)

# Syslog: "Jan 15 10:23:45 hostname service[pid]: message"
_SYSLOG = re.compile(
    r"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(?P<day>\d{1,2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+"
    r"(?P<service>\w[\w.-]*)(?:\[(?P<pid>\d+)\])?:\s+"
    r"(?P<message>.+)"
)

# Common log keywords that suggest severity when level is absent
_LEVEL_HINTS = re.compile(
    r"\b(ERROR|FATAL|CRITICAL|WARN(?:ING)?|INFO|DEBUG)\b", re.IGNORECASE
)

_TRACE_CTX = re.compile(r"(?:trace|traceId|trace_id|X-Trace-ID)[=:\s]+([a-f0-9\-]+)", re.IGNORECASE)
_CORR_CTX = re.compile(r"(?:correlation|correlationId|corr)[=:\s]+([a-f0-9\-]+)", re.IGNORECASE)

_MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

_LEVEL_MAP: dict[str, str] = {"WARNING": "WARN", "FATAL": "CRITICAL"}


def _parse_datetime(date_str: str, time_str: str) -> datetime:
    combined = f"{date_str} {time_str}".replace("/", "-").replace(",", ".")
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(combined, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _normalize_level(raw: str) -> str:
    upper = raw.upper()
    return _LEVEL_MAP.get(upper, upper)


def _extract_trace_info(text: str) -> tuple[str | None, str | None]:
    tm = _TRACE_CTX.search(text)
    cm = _CORR_CTX.search(text)
    return (tm.group(1) if tm else None, cm.group(1) if cm else None)


def _try_json(line: str, source: str, now: datetime) -> LogEntry | None:
    if not line.startswith("{"):
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None

    ts_raw = data.get("timestamp") or data.get("time") or data.get("@timestamp")
    try:
        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")) if ts_raw else now
    except ValueError:
        ts = now

    level = _normalize_level(str(data.get("level") or data.get("severity") or "INFO"))
    service = str(data.get("service") or data.get("logger") or data.get("app") or "unknown")
    message = str(data.get("message") or data.get("msg") or "")
    trace_id = str(data.get("traceId") or data.get("trace_id") or data.get("trace") or "") or None
    corr_id = str(data.get("correlationId") or data.get("correlation_id") or "") or None

    return LogEntry(
        id=str(uuid.uuid4()),
        timestamp=ts,
        level=level,
        service=service,
        message=message,
        stack_trace=data.get("stack_trace") or data.get("exception"),
        trace_id=trace_id,
        correlation_id=corr_id,
        raw_line=line,
        source=source,
        ingested_at=now,
    )


def _try_spring_boot_default(line: str, source: str, now: datetime) -> LogEntry | None:
    m = _SB_DEFAULT.match(line)
    if not m:
        return None
    ts = _parse_datetime(m.group("date"), m.group("time"))
    logger = m.group("logger")
    service = logger.split(".")[-2] if "." in logger else logger
    message = m.group("message")
    trace_id, corr_id = _extract_trace_info(message)
    return LogEntry(
        id=str(uuid.uuid4()),
        timestamp=ts,
        level=_normalize_level(m.group("level")),
        service=service,
        message=message,
        raw_line=line,
        source=source,
        ingested_at=now,
        trace_id=trace_id,
        correlation_id=corr_id,
    )


def _try_spring_boot_custom(line: str, source: str, now: datetime) -> LogEntry | None:
    m = _SB_CUSTOM.match(line)
    if not m:
        return None
    ts = _parse_datetime(m.group("date"), m.group("time"))
    message = m.group("message")
    trace_ctx = m.group("trace_ctx") or ""
    trace_id, corr_id = _extract_trace_info(f"{trace_ctx} {message}")
    return LogEntry(
        id=str(uuid.uuid4()),
        timestamp=ts,
        level=_normalize_level(m.group("level")),
        service=m.group("service").strip(),
        message=message,
        raw_line=line,
        source=source,
        ingested_at=now,
        trace_id=trace_id,
        correlation_id=corr_id,
    )


def _try_nginx_error(line: str, source: str, now: datetime) -> LogEntry | None:
    m = _NGINX_ERROR.match(line)
    if not m:
        return None
    ts = _parse_datetime(m.group("date"), m.group("time"))
    return LogEntry(
        id=str(uuid.uuid4()),
        timestamp=ts,
        level=_normalize_level(m.group("level")),
        service="nginx",
        message=m.group("message"),
        raw_line=line,
        source=source,
        ingested_at=now,
    )


def _try_syslog(line: str, source: str, now: datetime) -> LogEntry | None:
    m = _SYSLOG.match(line)
    if not m:
        return None
    month_num = _MONTH_MAP.get(m.group("month"), 1)
    day = int(m.group("day"))
    date_str = f"{now.year}-{month_num:02d}-{day:02d}"
    ts = _parse_datetime(date_str, m.group("time"))
    message = m.group("message")
    level_hint = _LEVEL_HINTS.search(message)
    level = _normalize_level(level_hint.group(1)) if level_hint else "INFO"
    return LogEntry(
        id=str(uuid.uuid4()),
        timestamp=ts,
        level=level,
        service=m.group("service"),
        message=message,
        raw_line=line,
        source=source,
        ingested_at=now,
    )


_PARSERS = [
    _try_json,
    _try_spring_boot_default,
    _try_spring_boot_custom,
    _try_nginx_error,
    _try_syslog,
]


def _is_stack_trace_continuation(line: str) -> bool:
    stripped = line.lstrip()
    return (
        stripped.startswith("at ")
        or stripped.startswith("Caused by:")
        or stripped.startswith("...\t")
    )


def parse_log_lines(content: str, source: str = "manual") -> list[LogEntry]:
    """Parse a multi-line log string into a list of LogEntry objects.

    Stack traces that follow a parsed entry are attached to that entry rather
    than emitted as separate entries.
    """
    now = datetime.now(timezone.utc)
    lines = content.splitlines()
    entries: list[LogEntry] = []
    stack_buf: list[str] = []
    pending: LogEntry | None = None

    def _flush():
        nonlocal pending
        if pending is not None:
            if stack_buf:
                pending.stack_trace = "\n".join(stack_buf)
            entries.append(pending)
            pending = None
            stack_buf.clear()

    for line in lines:
        if not line.strip():
            continue

        if _is_stack_trace_continuation(line) and pending is not None:
            stack_buf.append(line)
            continue

        _flush()

        entry: LogEntry | None = None
        for parser in _PARSERS:
            entry = parser(line, source, now)
            if entry:
                break

        if entry:
            pending = entry
        # Lines that don't match any parser are silently skipped (noise/blank separators)

    _flush()
    return entries
