#!/usr/bin/env bash
# LogSense end-to-end demo
# Usage: bash scripts/demo.sh
# Requires: ANTHROPIC_API_KEY set in environment or .env

set -euo pipefail

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
CYAN="\033[0;36m"
RESET="\033[0m"

step() { echo -e "\n${BOLD}${CYAN}▶ $1${RESET}"; }
ok()   { echo -e "${GREEN}✓ $1${RESET}"; }
info() { echo -e "${YELLOW}  $1${RESET}"; }

echo -e "${BOLD}╔═══════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║       LogSense — End-to-End Demo          ║${RESET}"
echo -e "${BOLD}╚═══════════════════════════════════════════╝${RESET}"

if [ ! -f ".env" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: ANTHROPIC_API_KEY not set. Copy .env.example to .env and fill it in."
  exit 1
fi

# Activate venv if present
if [ -d ".venv" ]; then source .venv/bin/activate; fi

# Clean state
step "1/5  Resetting demo database"
rm -f demo.db
export LOGSENSE_DB_PATH=demo.db
ok "Clean database ready"

step "2/5  Ingesting Spring Boot error logs"
logsense ingest tests/fixtures/spring_boot_errors.log --source spring-boot-demo
ok "Spring Boot logs ingested"

step "3/5  Ingesting Nginx error logs"
logsense ingest tests/fixtures/nginx_errors.log --source nginx-demo
ok "Nginx logs ingested"

step "4/5  Triaging clusters (ranked by risk score)"
echo ""
logsense triage --limit 10

step "5/5  Running LLM root cause analysis on top cluster"
TOP_CLUSTER=$(logsense triage --limit 1 2>/dev/null | awk '{print $NF}')
echo ""
info "Top cluster ID: ${TOP_CLUSTER}"
echo ""
logsense rca "$TOP_CLUSTER"

echo ""
step "BONUS  Drafting GitHub incident report (dry run)"
logsense draft "$TOP_CLUSTER" --platform github
info "Dry run: no issue was created. Pass --no-dry-run to actually post."

echo ""
echo -e "${BOLD}${GREEN}✓ Demo complete!${RESET}"
echo -e "  REST API: ${CYAN}make serve${RESET}"
echo -e "  MCP server: ${CYAN}make mcp${RESET}"
echo -e "  Full docs: ${CYAN}docs/architecture.md${RESET}"

# Clean up demo db
rm -f demo.db
