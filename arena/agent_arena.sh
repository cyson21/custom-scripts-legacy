#!/usr/bin/env bash
set -euo pipefail

# --- Global Configurations ---
CLI_REPO=""
BASE_REPO="${BASE_REPO:-}"
BASE_BRANCH="${BASE_BRANCH:-develop}"
ARENA_UI_MODE="${ARENA_UI_MODE:-auto}"
AUTO_OPEN_REVIEW_UI="${AUTO_OPEN_REVIEW_UI:-1}"
AUTO_OPEN_ASSIMILATION_UI="${AUTO_OPEN_ASSIMILATION_UI:-1}"
INTERACTIVE_WINNER_PICK="${INTERACTIVE_WINNER_PICK:-1}"
AUTO_COMMIT="${AUTO_COMMIT:-1}"
AUTO_UPDATE_GITIGNORE="${AUTO_UPDATE_GITIGNORE:-0}"
ARENA_COLLECT_PARALLEL="${ARENA_COLLECT_PARALLEL:-1}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
REVIEW_PROMPT_TEMPLATE_REL="${REVIEW_PROMPT_TEMPLATE_REL:-templates/PROMPT_TEMPLATES.md}"
AGENTS="${AGENTS:-codex,claude}"
INTEGRATED_REVIEWER="${INTEGRATED_REVIEWER:-}"

RUN_ID=""
RUN_DIR=""
TASK_FILE=""

# --- Script Directory Resolution ---
SOURCE=${BASH_SOURCE[0]}
while [ -L "$SOURCE" ]; do
  DIR=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )
  SOURCE=$(readlink "$SOURCE")
  [[ $SOURCE != /* ]] && SOURCE=$DIR/$SOURCE
done
SCRIPT_DIR=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )

LIB_DIR="$SCRIPT_DIR/lib"
LIBEXEC_DIR="$SCRIPT_DIR/libexec"
TEMPLATE_DIR="$SCRIPT_DIR/templates"
AGENT_CONF_DIR="${ARENA_AGENT_CONF_DIR:-$SCRIPT_DIR/conf}"
AGENT_CONF_EXTRA_DIR="${ARENA_AGENT_CONF_EXTRA_DIR:-$SCRIPT_DIR/agents.d}"
declare -a AGENT_CATALOG=()

# --- Load Library Modules ---
# shellcheck disable=SC1091
source "$LIB_DIR/core.sh"
source "$LIB_DIR/agent.sh"
source "$LIB_DIR/run.sh"
source "$LIB_DIR/ui.sh"
source "$LIB_DIR/report.sh"
source "$LIB_DIR/cmd.sh"
source "$LIB_DIR/tui.sh"

# --- Main Entry Point ---
main() {
  load_agent_configs
  init_agent_runtime_settings
  if [[ -z "${AGENTS:-}" ]]; then
    AGENTS="${AGENT_CATALOG[0]}"
  fi

  if [[ $# -eq 0 ]]; then
    BASE_REPO="$(resolve_base_repo)"
    run_tui_mode
    exit 0
  fi

  local -a filtered_args=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --repo)
        [[ $# -ge 2 ]] || die "--repo에는 경로 인자가 필요합니다"
        CLI_REPO="$(abs_path "$2")"
        shift 2
        ;;
      *)
        filtered_args+=("$1")
        shift
        ;;
    esac
  done

  set -- "${filtered_args[@]}"
  local cmd="${1:-}"
  if [[ -z "$cmd" ]]; then
    BASE_REPO="$(resolve_base_repo)"
    run_tui_mode
    exit 0
  fi
  shift || true

  case "$cmd" in
    -h|--help|help) usage; exit 0 ;;
  esac

  if [[ "$cmd" = "init" || -n "$CLI_REPO" ]]; then
    BASE_REPO="$(resolve_base_repo)"
  elif [[ -z "$BASE_REPO" ]]; then
    BASE_REPO="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  fi

  case "$cmd" in
    start) cmd_start "$@" ;;
    init) cmd_init "$@" ;;
    launch) cmd_launch "$@" ;;
    collect) cmd_collect "$@" ;;
    review) cmd_review "$@" ;;
    review-only) cmd_review_only "$@" ;;
    review-pack) cmd_review_pack "$@" ;;
    handoff) cmd_handoff "$@" ;;
    finish) cmd_finish "$@" ;;
    cleanup) cmd_cleanup "$@" ;;
    cleanup-old) cmd_cleanup_old "$@" ;;
    status) cmd_status "$@" ;;
    *) die "알 수 없는 명령어입니다: $cmd" ;;
  esac
}

main "$@"
