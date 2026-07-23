# ADR 0002 — LLM Prompt Design and Confidence Scoring

**Status:** Accepted
**Date:** 2024-01-15
**Deciders:** Project author

---

## Context

The RCA generator sends a structured context (cluster template, occurrence
count, time window, log samples) to an LLM and expects a structured JSON
response containing a root cause hypothesis and a confidence estimate.

Two prompt design decisions required deliberate choices:

1. **How to enforce structured JSON output**
2. **How to calibrate confidence so it is meaningful rather than arbitrary**

---

## Decision 1: Structured JSON via system prompt + response parsing

We use a **system prompt that specifies the exact JSON schema** plus a parsing
layer that strips accidental markdown fences and validates the output.

We do NOT use Anthropic's tool-use / function-calling mechanism for this.

### Rationale

Tool use (structured output via `tools` parameter) would guarantee JSON
schema adherence at the API level. We choose not to use it for v1 because:

1. **Portability.** The prompt-based approach works identically across every
   Anthropic model and can be ported to any other provider by changing the
   `ANTHROPIC_MODEL` env var. Tool schemas are provider-specific.
2. **Simplicity.** The response parsing logic (< 15 lines) is easier to audit
   and test than constructing a JSON Schema tool definition.
3. **Observed reliability.** Claude models reliably output valid JSON when
   the schema is stated clearly in the system prompt.  Our integration tests
   cover the markdown-fence edge case.

### Upgrade path

If we see malformed JSON errors in production (which we track in
`rca/generator.py:_parse_response`), we switch to tool-use in a targeted patch
without changing the rest of the pipeline.

---

## Decision 2: Confidence scoring via rubric anchors

We define confidence using **explicit rubric anchors** in the system prompt
rather than asking the model to self-calibrate:

```
high   (0.70–1.00): Clear, repeating pattern with an obvious and specific cause.
medium (0.40–0.69): Pattern is visible but the cause requires further investigation.
low    (0.00–0.39): Ambiguous — multiple possible causes, insufficient data.
```

### Why explicit anchors?

Without anchors, LLMs tend to report high confidence on almost everything
(optimism bias) or cluster at round numbers (0.5, 0.7, 0.9). Both undermine
the usefulness of confidence as a triage signal.

The anchors create a **decision-forcing rubric**: the model must match its
estimate to a described scenario, not just pick a number. This was validated
manually against 20 RCA outputs — the distribution spread across all three
tiers rather than clustering at "high".

### Dual representation

We store both:
- `confidence`: `"low" | "medium" | "high"` — human-readable label
- `confidence_score`: float in [0, 1] — allows downstream sort/filter

If the model returns an out-of-range score (e.g. 1.5), we clamp to [0, 1]
and derive the label from the clamped value. This is tested in
`tests/integration/test_pipeline.py::TestRCAPipeline::test_rca_validates_confidence_score_bounds`.

---

## Alternatives considered

### Alternative: Few-shot examples in the prompt

Including 2-3 example (input, expected-output) pairs in the system prompt
would likely improve consistency. We omit this for v1 to keep the system
prompt short and cost-effective. It's a straightforward addition if confidence
calibration proves insufficient in practice.

### Alternative: Separate "confidence grader" LLM call

A second LLM call that evaluates the primary output and assigns confidence
independently (an LLM-as-judge pattern) would be more robust. The cost
(double the API calls per cluster) is not justified at this stage; the single-
call rubric approach is adequate for triage purposes.
