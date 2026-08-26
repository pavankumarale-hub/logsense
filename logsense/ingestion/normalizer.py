"""Post-parse normalization pass.

After parsing, entries may have inconsistent level names or ambiguous service
names extracted from different formats. This module applies a final
normalization to guarantee a stable schema regardless of source format.
"""

from .models import LogEntry, SEVERITY_ORDER

_LEVEL_ALIASES: dict[str, str] = {
    "TRACE": "DEBUG",
    "FATAL": "CRITICAL",
    "WARNING": "WARN",
    "SEVERE": "ERROR",
}

_VALID_LEVELS: frozenset[str] = frozenset({"DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"})


def normalize(entries: list[LogEntry]) -> list[LogEntry]:
    """Apply normalization rules in-place and return the same list."""
    for entry in entries:
        entry.level = _normalize_level(entry.level)
        entry.service = _normalize_service(entry.service)
        entry.message = entry.message.strip()
    return entries


def _normalize_level(level: str) -> str:
    upper = level.upper().strip()
    mapped = _LEVEL_ALIASES.get(upper, upper)
    return mapped if mapped in _VALID_LEVELS else "INFO"


def _normalize_service(service: str) -> str:
    s = service.strip().lower()
    s = s.replace("_", "-")
    if not s:
        return "unknown"
    return s
