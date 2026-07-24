#!/usr/bin/env bash
# LogSense end-to-end demo
# Usage: bash scripts/demo.sh
# Requires: ANTHROPIC_API_KEY set in environment or .env

set -euo pipefail

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
CYAN="\033[0;36m"
RED="\033[0;31m"
RESET="\033[0m"

step()  { echo -e "\n${BOLD}${CYAN}▶ $1${RESET}"; }
ok()    { echo -e "${GREEN}✓ $1${RESET}"; }
info()  { echo -e "${YELLOW}  $1${RESET}"; }
warn()  { echo -e "${YELLOW}⚠ $1${RESET}"; }
sep()   { echo -e "${BOLD}────────────────────────────────────────────────${RESET}"; }

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║       LogSense — End-to-End Demo             ║${RESET}"
echo -e "${BOLD}║  Ingest → Cluster → Score → LLM RCA → Draft ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${RESET}"
echo ""

# ── API key check ──────────────────────────────────────────────────────────
if [ -f ".env" ]; then
  # shellcheck disable=SC1091
  set -a && source .env && set +a
fi

HAS_API_KEY=true
if [ -z "${ANTHROPIC_API_KEY:-}" ] || [ "${ANTHROPIC_API_KEY}" = "sk-ant-your-key-here" ]; then
  warn "ANTHROPIC_API_KEY not set — steps 5 and 6 (LLM RCA + draft) will be skipped."
  warn "Edit .env and set a real ANTHROPIC_API_KEY to run the full demo."
  HAS_API_KEY=false
fi

# ── Activate venv if present ───────────────────────────────────────────────
if [ -d ".venv" ]; then source .venv/bin/activate; fi

# ── Clean state ────────────────────────────────────────────────────────────
step "1/6  Resetting demo database"
rm -f demo.db
export LOGSENSE_DB_PATH=demo.db
ok "Clean database ready (demo.db)"

# ── Ingest Spring Boot logs ────────────────────────────────────────────────
step "2/6  Ingesting Spring Boot error logs"
logsense ingest tests/fixtures/spring_boot_errors.log --source spring-boot-demo
ok "Spring Boot logs ingested"

# ── Ingest Nginx logs ─────────────────────────────────────────────────────
step "3/6  Ingesting Nginx error logs"
logsense ingest tests/fixtures/nginx_errors.log --source nginx-demo
ok "Nginx logs ingested"

# ── Triage clusters ───────────────────────────────────────────────────────
step "4/6  Triage — clusters ranked by risk score"
sep
logsense triage --limit 10
sep

# ── LLM RCA ───────────────────────────────────────────────────────────────
if [ "$HAS_API_KEY" = "false" ]; then
  warn "Skipping LLM steps (no ANTHROPIC_API_KEY). Set the key and re-run for the full demo."
  echo ""
  echo -e "${BOLD}${GREEN}✓ Pipeline demo complete (ingestion + clustering).${RESET}"
  echo -e "  To run the full demo including LLM RCA:"
  echo -e "  ${CYAN}cp .env.example .env${RESET}  # add your ANTHROPIC_API_KEY"
  echo -e "  ${CYAN}make demo${RESET}"
  rm -f demo.db
  exit 0
fi

step "5/6  LLM root cause analysis on top cluster"
TOP_CLUSTER=$(logsense triage --limit 1 2>/dev/null | awk '{print $NF}')
info "Top cluster ID: ${TOP_CLUSTER}"
echo ""
logsense rca "$TOP_CLUSTER"

# ── Draft incident report ─────────────────────────────────────────────────
step "6/6  Drafting GitHub incident report (dry run)"
logsense draft "$TOP_CLUSTER" --platform github
info "Dry run — no issue was created. Pass --no-dry-run to actually post."

# ── Summary ───────────────────────────────────────────────────────────────
echo ""
sep
echo -e "${BOLD}${GREEN}✓ Full end-to-end demo complete.${RESET}"
echo ""
echo -e "  What just ran:"
echo -e "  ${CYAN}logsense ingest${RESET}   → parsed multi-format logs, extracted templates, scored clusters"
echo -e "  ${CYAN}logsense triage${RESET}   → ranked clusters by risk (frequency × recency × severity)"
echo -e "  ${CYAN}logsense rca${RESET}      → LLM root cause analysis with calibrated confidence"
echo -e "  ${CYAN}logsense draft${RESET}    → structured GitHub incident report payload"
echo ""
echo -e "  Next:"
echo -e "  ${CYAN}make serve${RESET}   — REST API on http://localhost:8000/docs"
echo -e "  ${CYAN}make mcp${RESET}     — MCP server (connect from Claude Desktop / Claude Code)"
echo -e "  Full docs: ${CYAN}docs/architecture.md${RESET}"
sep
echo ""

# Clean up demo db
rm -f demo.db
