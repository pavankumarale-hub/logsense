"""Drain log template extraction.

Drain (He et al. 2017, "Drain: An Online Log Parsing Approach with Fixed Depth
Tree") extracts stable templates from streaming log messages in O(n) time per
message, with no pre-training or embedding calls required.

Algorithm summary
-----------------
1. Preprocess: replace common variable tokens (numbers, IPs, UUIDs, paths)
   with the wildcard ``<*>``.
2. Length node: route by token count to a sub-tree.
3. Prefix node: walk using the first (depth-1) tokens, inserting ``<*>``
   children as wildcards.
4. Leaf: compare against existing LogGroups using token-similarity; merge or
   create as appropriate.

Why Drain over embedding-based clustering for v1?
- O(1) memory per token (tree nodes), not O(n * embedding_dim)
- Zero external API calls — works offline, no latency penalty
- Deterministic: same logs always produce the same clusters
- Interpretable: templates are human-readable strings
See docs/adr/0001-clustering-approach.md for the full tradeoff analysis.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logsense.ingestion.models import LogEntry

# ---------------------------------------------------------------------------
# Preprocessing regexes — applied left-to-right before tokenisation
# ---------------------------------------------------------------------------
_PREPROCESS_RULES: list[tuple[re.Pattern, str]] = [
    # IPv4 addresses
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<*>"),
    # UUIDs
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<*>"),
    # Hex strings (error codes, hashes)
    (re.compile(r"\b0x[0-9a-fA-F]{4,}\b"), "<*>"),
    # Timestamps / durations inside messages (e.g. "after 30000ms", "2024-01-15T10:23:45Z")
    (re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?"), "<*>"),
    (re.compile(r"\b\d+ms\b"), "<*>ms"),
    # File paths
    (re.compile(r"(?:/[\w.\-]+){2,}"), "<*>"),
    # Standalone numbers (line numbers, PIDs, counts, ports)
    (re.compile(r"\b\d+\b"), "<*>"),
]

_WILDCARD = "<*>"


def _preprocess(message: str) -> str:
    for pattern, replacement in _PREPROCESS_RULES:
        message = pattern.sub(replacement, message)
    return message


def _tokenize(message: str) -> list[str]:
    return message.split()


def _seq_similarity(tokens_a: list[str], tokens_b: list[str]) -> float:
    """Weighted similarity between two token sequences.

    Literal-vs-literal match   → 1.0 credit (strong agreement)
    Wildcard-vs-wildcard match → 0.5 credit (structural agreement only)
    Any mismatch               → 0.0 credit

    Half-credit for wildcard pairs preserves clustering of all-variable
    messages (e.g. pure IP/number log lines that preprocess entirely to
    '<*>' tokens) while preventing high-wildcard-density messages with
    different literal tokens from falsely merging at the default threshold.
    """
    if len(tokens_a) != len(tokens_b) or not tokens_a:
        return 0.0
    score = sum(
        (1.0 if a == b and a != _WILDCARD else 0.5 if a == b else 0.0)
        for a, b in zip(tokens_a, tokens_b)
    )
    return score / len(tokens_a)


def _merge_templates(a: list[str], b: list[str]) -> list[str]:
    """Return a merged template: keep tokens that match, wildcard the rest."""
    return [ta if ta == tb else _WILDCARD for ta, tb in zip(a, b)]


# ---------------------------------------------------------------------------
# Tree nodes
# ---------------------------------------------------------------------------

@dataclass
class LogGroup:
    """A single cluster represented by its template tokens."""
    id: str
    template_tokens: list[str]

    @property
    def template(self) -> str:
        return " ".join(self.template_tokens)


@dataclass
class PrefixNode:
    children: dict[str, "PrefixNode"] = field(default_factory=dict)
    log_groups: list[LogGroup] = field(default_factory=list)


class DrainParser:
    """Online log parser implementing the Drain algorithm."""

    def __init__(
        self,
        depth: int = 4,
        sim_threshold: float = 0.5,
        max_children: int = 100,
    ) -> None:
        if depth < 2:
            raise ValueError("depth must be >= 2")
        self._depth = depth
        self._sim_threshold = sim_threshold
        self._max_children = max_children
        self._root = PrefixNode()
        # Map template string -> LogGroup (for O(1) lookup)
        self._template_index: dict[str, LogGroup] = {}

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def add_entry(self, entry: "LogEntry") -> LogGroup:
        """Process one log entry and return its LogGroup."""
        preprocessed = _preprocess(entry.message)
        tokens = _tokenize(preprocessed)
        return self._route(tokens)

    @property
    def groups(self) -> list[LogGroup]:
        return list(self._template_index.values())

    # ------------------------------------------------------------------ #
    #  Internal tree walk                                                  #
    # ------------------------------------------------------------------ #

    def _route(self, tokens: list[str]) -> LogGroup:
        # Level 1: token count bucket
        count_key = str(len(tokens))
        count_node = self._root.children.setdefault(count_key, PrefixNode())

        # Levels 2..depth-1: prefix walk
        node = count_node
        for tok in tokens[: self._depth - 1]:
            key = tok
            if key not in node.children:
                if len(node.children) >= self._max_children:
                    key = _WILDCARD
                if key not in node.children:
                    node.children[key] = PrefixNode()
            node = node.children[key]

        # Leaf: match or create
        return self._match_or_create(node, tokens)

    def _match_or_create(self, leaf: PrefixNode, tokens: list[str]) -> LogGroup:
        best_group: LogGroup | None = None
        best_sim = -1.0

        for group in leaf.log_groups:
            if len(group.template_tokens) != len(tokens):
                continue
            sim = _seq_similarity(group.template_tokens, tokens)
            if sim > best_sim:
                best_sim = sim
                best_group = group

        if best_group is not None and best_sim >= self._sim_threshold:
            merged = _merge_templates(best_group.template_tokens, tokens)
            old_key = best_group.template
            best_group.template_tokens = merged
            # Re-index under new template key
            if old_key in self._template_index:
                del self._template_index[old_key]
            self._template_index[best_group.template] = best_group
            return best_group

        new_group = LogGroup(id=str(uuid.uuid4()), template_tokens=list(tokens))
        leaf.log_groups.append(new_group)
        self._template_index[new_group.template] = new_group
        return new_group
