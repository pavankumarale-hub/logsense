"""LLM RCA generation via the Anthropic API.

The generator is intentionally thin: it assembles the prompt, calls the API,
parses the JSON response, and maps it to an RCAResult.  Business logic lives
in the prompts module; retry/error-handling lives here.
"""

import json
import uuid
from datetime import datetime, timezone

import anthropic

from logsense.config import get_settings
from logsense.triage.models import Cluster
from .models import RCAResult
from .prompts import SYSTEM_PROMPT, build_user_prompt


class RCAGenerator:
    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        cfg = get_settings()
        self._client = client or anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        self._model = cfg.anthropic_model
        self._max_tokens = cfg.anthropic_max_tokens

    def generate(
        self,
        cluster: Cluster,
        log_samples: list[str],
    ) -> RCAResult:
        """Call the LLM and return a structured RCAResult.

        Raises:
            anthropic.APIError: on network or API failures
            ValueError: if the model returns malformed JSON
        """
        user_prompt = build_user_prompt(
            template=cluster.template,
            count=cluster.count,
            first_seen=cluster.first_seen.isoformat(),
            last_seen=cluster.last_seen.isoformat(),
            services=list(cluster.affected_services),
            severity=cluster.max_severity,
            log_samples=log_samples,
        )

        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        if not response.content:
            raise ValueError("LLM returned an empty content list — no text to parse")
        first_block = response.content[0]
        if not hasattr(first_block, "text"):
            raise ValueError(
                f"LLM returned a non-text content block: {type(first_block).__name__}"
            )
        raw_text = first_block.text.strip()
        return self._parse_response(raw_text, cluster.id)

    def _parse_response(self, raw_text: str, cluster_id: str) -> RCAResult:
        # Strip accidental markdown fences the model may add.
        # Remove the opening fence line, then find the last ``` line and
        # truncate there (including any trailing prose the model appended after
        # the closing fence).  Searching from the end ensures inner ``` blocks
        # inside JSON string values (e.g. suggested_action shell snippets) are
        # preserved.
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            lines = lines[1:]  # opening fence always present (checked above)
            close_idx = next(
                (i for i in range(len(lines) - 1, -1, -1) if lines[i].startswith("```")),
                None,
            )
            if close_idx is not None:
                lines = lines[:close_idx]
            raw_text = "\n".join(lines).strip()

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM returned non-JSON response: {raw_text[:200]}") from exc

        confidence_score = float(data.get("confidence_score", 0.5))
        confidence_score = max(0.0, min(1.0, confidence_score))

        raw_confidence = str(data.get("confidence", "medium")).lower()
        if raw_confidence not in ("low", "medium", "high"):
            if confidence_score >= 0.7:
                raw_confidence = "high"
            elif confidence_score >= 0.4:
                raw_confidence = "medium"
            else:
                raw_confidence = "low"

        return RCAResult(
            id=str(uuid.uuid4()),
            cluster_id=cluster_id,
            title=str(data.get("title", "Untitled Incident"))[:80],
            summary=str(data.get("summary", "")),
            root_cause_hypothesis=str(data.get("root_cause_hypothesis", "")),
            confidence=raw_confidence,  # type: ignore[arg-type]
            confidence_score=confidence_score,
            suggested_action=str(data.get("suggested_action", "")),
            affected_service=str(data.get("affected_service", "unknown")),
            model_used=self._model,
            generated_at=datetime.now(timezone.utc),
        )
