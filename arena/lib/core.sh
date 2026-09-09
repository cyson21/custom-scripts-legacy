#!/usr/bin/env bash

# --- Logging & Utils ---
log() { printf '[arena] %s\n' "$*"; }
warn() { printf '[arena][warn] %s\n' "$*" >&2; }
die() { printf '[arena][error] %s\n' "$*" >&2; exit 1; }

has_cmd() { command -v "$1" >/dev/null 2>&1; }

abs_path() {
  local p="$1"
  if [[ "$p" = /* ]]; then
    printf '%s\n' "$p"
  else
    printf '%s/%s\n' "$(cd "$(dirname "$p")" && pwd)" "$(basename "$p")"
  fi
}

current_ts() { date '+%Y-%m-%d %H:%M:%S'; }

html_escape_stream() {
  sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

trim_spaces() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s\n' "$s"
}

# --- Dynamic Variables ---
dynamic_var_get() {
  local name="$1"
  eval "printf '%s\n' \"\${$name:-}\""
}

dynamic_var_set() {
  local name="$1" value="$2"
  printf -v "$name" '%s' "$value"
}

# --- Validation ---
validate_bool() {
  local name="$1" value="$2"
  [[ "$value" = "0" || "$value" = "1" ]] || die "$name 값은 0 또는 1이어야 합니다 (입력값: $value)"
}

validate_mode() {
  local name="$1" value="$2"
  case "$value" in
    auto|iterm2|tmux|none) ;;
    *) die "$name 값은 auto|iterm2|tmux|none 중 하나여야 합니다 (입력값: $value)" ;;
  esac
}

validate_prompt_mode() {
  local name="$1" value="$2"
  case "$value" in
    stdin|file) ;;
    *) die "$name 값은 stdin|file 중 하나여야 합니다 (입력값: $value)" ;;
  esac
}

validate_retention_days() {
  local name="$1" value="$2"
  [[ "$value" =~ ^[0-9]+$ ]] || die "$name 값은 0 이상의 정수여야 합니다 (입력값: $value)"
}

extract_markdown_section_by_heading() {
  local file="$1" heading="$2"
  [[ -f "$file" ]] || return 1

  awk -v target="## $heading" '
    $0 == target { capture=1; next }
    capture && /^## / { exit }
    capture { print }
  ' "$file"
}

usage() {
  cat <<'USAGE'
사용법:
  scripts/arena/agent_arena.sh [--repo <abs-path>]
  scripts/arena/agent_arena.sh [--repo <abs-path>] <command> [options]

명령어:
  start       [--task-file <path>] [--base <branch>] [--agents <csv>] [--run-id <id>] [--update-gitignore]
  init        [--task-file <path>] [--base <branch>] [--agents <csv>] [--run-id <id>] [--update-gitignore]
  launch      [--run-id <id>]
  collect     [--run-id <id>] [--agent <name>]
  review      [--run-id <id>] [--integrated-reviewer <name>]
  review-only [--run-id <id>] [--integrated-reviewer <name>]
  review-pack [--run-id <id>] [--integrated-reviewer <name>]
  handoff     [--run-id <id>] [--winner <name>] [--commit]
  finish      [--run-id <id>] [--winner <name>] [<name>] [--commit] [--keep-index] [--force] [--no-cleanup]
  cleanup     [--run-id <id>] [--force] [--keep-index]
  cleanup-old [--retention-days <n>] [--apply] [--repo-only] [--global-only]
  status      [--run-id <id>] [--summary]

전역 옵션:
  --repo <abs-path>   대상 저장소 강제 지정 (--run-id와 함께 쓰면 fallback 없음)

무인자 실행:
  gum 기반 TUI 진입 (시작 모드 선택: 전체 루프 / 리뷰 전용)
USAGE
}
