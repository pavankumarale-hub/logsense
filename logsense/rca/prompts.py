"""Prompt templates for LLM-driven RCA.

Design notes (see docs/adr/0002-llm-prompt-design-and-confidence-scoring.md):
- System prompt is kept short and declarative to avoid confusion with the
  user-turn context.
- We ask for JSON directly (not wrapped in ```json fences) and rely on the
  model's native structured-output capability to enforce the schema.
- Confidence scoring is calibrated by giving the model explicit rubric
  anchors rather than letting it self-anchor arbitrarily.
"""

SYSTEM_PROMPT = """\
You are an expert Site Reliability Engineer performing root cause analysis on \
production application logs. Your job is to reason about error patterns, \
hypothesize the most likely root cause, and suggest a concrete next action.

Respond with a single JSON object — no prose, no markdown fences — matching \
this exact schema:

{
  "title":                   "<80-char incident title>",
  "summary":                 "2-3 sentence description of what is happening",
  "root_cause_hypothesis":   "Detailed hypothesis: what is failing, why, and \
what triggered it",
  "confidence":              "low|medium|high",
  "confidence_score":        <float 0.0-1.0>,
  "suggested_action":        "Specific, actionable next step (query X, restart \
Y, check Z metric)",
  "affected_service":        "Primary service name"
}

Confidence rubric:
  high   (0.70–1.00): Clear, repeating pattern with an obvious and specific cause.
  medium (0.40–0.69): Pattern is visible but the cause requires further investigation.
  low    (0.00–0.39): Ambiguous — multiple possible causes, insufficient data.
"""

USER_TEMPLATE = """\
Analyze this error cluster detected in our production logs.

**Template (extracted pattern):** {template}
**Occurrence count:** {count}
**Time window:** {first_seen} → {last_seen}
**Affected services:** {services}
**Highest severity level:** {severity}

**Representative log samples (up to 5):**
{log_samples}

Perform root cause analysis and respond with the JSON schema from your instructions.
"""


def build_user_prompt(
    template: str,
    count: int,
    first_seen: str,
    last_seen: str,
    services: list[str],
    severity: str,
    log_samples: list[str],
) -> str:
    samples_text = "\n".join(f"  [{i+1}] {s}" for i, s in enumerate(log_samples[:5]))
    return USER_TEMPLATE.format(
        template=template,
        count=count,
        first_seen=first_seen,
        last_seen=last_seen,
        services=", ".join(sorted(services)),
        severity=severity,
        log_samples=samples_text,
    )
