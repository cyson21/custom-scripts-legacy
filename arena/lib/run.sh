#!/usr/bin/env bash

# --- Repository Management ---
resolve_base_repo() {
  # Priority: --repo (CLI_REPO) > BASE_REPO env > git auto-detect.
  local candidate
  candidate="${CLI_REPO:-${BASE_REPO:-$(git rev-parse --show-toplevel 2>/dev/null || true)}}"
  [[ -n "$candidate" ]] || die "BASE_REPO를 확인할 수 없습니다. --repo <abs-path>를 지정하거나 git 저장소 내부에서 실행하세요."

  local top
  top="$(git -C "$candidate" rev-parse --show-toplevel 2>/dev/null)" || die "git 저장소가 아닙니다: $candidate"
  printf '%s\n' "$top"
}

ensure_clean_repo() {
  local dirty
  dirty="$(git -C "$BASE_REPO" status --porcelain=v1)"
  [[ -z "$dirty" ]] || die "기준 저장소가 dirty 상태입니다. 먼저 워킹 트리를 정리하세요: $BASE_REPO"
}

ensure_required_commands() {
  local required=(git)
  local agent cmd token
  agents_csv_to_array "$AGENTS"
  for agent in "${AGENT_ARRAY[@]}"; do
    token="$(agent_first_cmd_token "$agent")"
    [[ -n "$token" ]] || die "에이전트 명령어가 비어 있습니다: $agent"
    required+=("$token")
  done

  for cmd in "${required[@]}"; do
    has_cmd "$cmd" || die "필수 명령어를 찾을 수 없습니다: $cmd"
  done

  if [[ "$ARENA_UI_MODE" = "iterm2" ]]; then
    has_cmd osascript || die "ARENA_UI_MODE=iterm2 에는 osascript가 필요합니다"
    can_use_iterm2 || die "ARENA_UI_MODE=iterm2 이지만 iTerm2를 사용할 수 없습니다"
  fi
}

# --- Meta & Context ---
upsert_meta_var() {
  local key="$1" value="$2" file="$3"
  local escaped
  escaped="$(printf "%s" "$value" | sed "s/'/'''/g")"
  if grep -q "^${key}=" "$file"; then
    sed -i.bak "s|^${key}=.*$|${key}='${escaped}'|" "$file"
  else
    printf "%s='%s'\n" "$key" "$escaped" >> "$file"
  fi
  rm -f "${file}.bak"
}

load_meta() {
  [[ -n "$RUN_ID" ]] || die "RUN_ID는 필수입니다"
  local global_meta="$HOME/.arena/runs/${RUN_ID}.env"
  local meta=""

  if [[ -n "$CLI_REPO" ]]; then
    BASE_REPO="$(git -C "$CLI_REPO" rev-parse --show-toplevel 2>/dev/null)" || die "git 저장소가 아닙니다: $CLI_REPO"
    RUN_DIR="$BASE_REPO/.arena/runs/$RUN_ID"
    meta="$RUN_DIR/meta.env"
    [[ -f "$meta" ]] || die "런 메타데이터를 찾을 수 없습니다: $meta"
  else
    # 1) Try current BASE_REPO / current git repo first.
    if [[ -z "$BASE_REPO" ]]; then
      BASE_REPO="$(git rev-parse --show-toplevel 2>/dev/null || true)"
    fi
    if [[ -n "$BASE_REPO" ]]; then
      RUN_DIR="$BASE_REPO/.arena/runs/$RUN_ID"
      meta="$RUN_DIR/meta.env"
    fi

    # 2) If not found, fallback to global run index and retry.
    if [[ -z "$meta" || ! -f "$meta" ]]; then
      if [[ -f "$global_meta" ]]; then
        local owner
        owner="$(stat -f '%Su' "$global_meta" 2>/dev/null || stat -c '%U' "$global_meta" 2>/dev/null)"
        [[ "$owner" = "$(id -un)" ]] || die "전역 인덱스 파일 소유자가 현재 사용자와 다릅니다: $global_meta"
        # shellcheck disable=SC1090
        source "$global_meta"
        [[ -n "${BASE_REPO:-}" ]] || die "전역 인덱스에 BASE_REPO가 없습니다: $global_meta"
        RUN_DIR="$BASE_REPO/.arena/runs/$RUN_ID"
        meta="$RUN_DIR/meta.env"
      fi
    fi

    [[ -n "$meta" && -f "$meta" ]] || die "런 메타데이터를 찾을 수 없습니다: ${RUN_DIR:-<unknown>}/meta.env"
  fi

  # shellcheck disable=SC1090
  source "$meta"

  if [[ -n "$CLI_REPO" ]]; then
    BASE_REPO="$(git -C "$CLI_REPO" rev-parse --show-toplevel 2>/dev/null)" || die "git 저장소가 아닙니다: $CLI_REPO"
  fi

  BASE_REPO="${BASE_REPO:?}"
  BASE_BRANCH="${BASE_BRANCH:?}"
  TASK_FILE="${TASK_FILE:?}"
  AGENTS="$(normalize_agents_csv "${AGENTS:-}")"
  INTEGRATED_REVIEWER="${INTEGRATED_REVIEWER:-}"
  REVIEW_PROMPT_TEMPLATE_REL="${REVIEW_PROMPT_TEMPLATE_REL:-model_review/templates/PROMPT_TEMPLATES.md}"
  ARENA_COLLECT_PARALLEL="${ARENA_COLLECT_PARALLEL:-1}"
  init_agent_runtime_settings
  apply_agent_runtime_defaults

  validate_mode ARENA_UI_MODE "$ARENA_UI_MODE"
  validate_bool AUTO_OPEN_REVIEW_UI "$AUTO_OPEN_REVIEW_UI"
  validate_bool AUTO_OPEN_ASSIMILATION_UI "$AUTO_OPEN_ASSIMILATION_UI"
  validate_bool INTERACTIVE_WINNER_PICK "$INTERACTIVE_WINNER_PICK"
  validate_bool AUTO_COMMIT "$AUTO_COMMIT"
  validate_bool AUTO_UPDATE_GITIGNORE "$AUTO_UPDATE_GITIGNORE"
  validate_bool ARENA_COLLECT_PARALLEL "$ARENA_COLLECT_PARALLEL"
  validate_retention_days RETENTION_DAYS "${RETENTION_DAYS:-7}"

  local agent wt br
  agents_csv_to_array "$AGENTS"
  for agent in "${AGENT_ARRAY[@]}"; do
    validate_prompt_mode "${agent}_PROMPT_MODE" "$(agent_prompt_mode "$agent")"
    wt="$(agent_worktree "$agent")"
    br="$(agent_branch "$agent")"
    [[ -n "$wt" ]] || die "런 메타데이터에 ${agent} worktree가 없습니다"
    [[ -n "$br" ]] || die "런 메타데이터에 ${agent} branch가 없습니다"
  done
}

latest_repo_run_id() {
  local base="${BASE_REPO:-}"
  [[ -n "$base" && -d "$base/.arena/runs" ]] || return 1
  local latest
  latest="$(ls -1td "$base/.arena/runs/"*/ 2>/dev/null | head -n 1 || true)"
  [[ -n "$latest" ]] || return 1
  basename "$latest"
}

resolve_run_dir_quiet() {
  [[ -n "${RUN_ID:-}" ]] || return 1

  if [[ -n "${BASE_REPO:-}" && -d "$BASE_REPO/.arena/runs/$RUN_ID" ]]; then
    printf '%s\n' "$BASE_REPO/.arena/runs/$RUN_ID"
    return 0
  fi

  local global_meta="$HOME/.arena/runs/${RUN_ID}.env"
  [[ -f "$global_meta" ]] || return 1

  local owner_repo=""
  owner_repo="$(grep -m1 '^BASE_REPO=' "$global_meta" | cut -d= -f2- | tr -d "'" || true)"
  [[ -n "$owner_repo" && -d "$owner_repo/.arena/runs/$RUN_ID" ]] || return 1
  printf '%s\n' "$owner_repo/.arena/runs/$RUN_ID"
}

sync_run_context() {
  local run_dir=""
  run_dir="$(resolve_run_dir_quiet || true)"
  [[ -n "$run_dir" ]] || return 1

  RUN_DIR="$run_dir"
  local meta="$RUN_DIR/meta.env"
  [[ -f "$meta" ]] || return 1

  BASE_REPO="$(grep -m1 '^BASE_REPO=' "$meta" | cut -d= -f2- | tr -d "'" || true)"
  BASE_BRANCH="$(grep -m1 '^BASE_BRANCH=' "$meta" | cut -d= -f2- | tr -d "'" || true)"
  AGENTS="$(grep -m1 '^AGENTS=' "$meta" | cut -d= -f2- | tr -d "'" || true)"
  INTEGRATED_REVIEWER="$(grep -m1 '^INTEGRATED_REVIEWER=' "$meta" | cut -d= -f2- | tr -d "'" || true)"
  
  # user를 제외하고 화면에 보여줄 AI 에이전트 목록 재정의
  local display_agents=()
  local -a tmp_arr=()
  IFS=',' read -r -a tmp_arr <<< "$AGENTS" || true
  for a in "${tmp_arr[@]-}"; do
    [[ "$a" != "user" ]] && display_agents+=("$a")
  done
  DISPLAY_AGENTS="$(IFS=','; echo "${display_agents[*]}")"

  return 0
}

can_use_iterm2() {
  has_cmd osascript || return 1
  osascript -e 'tell application "iTerm2" to version' >/dev/null 2>&1
}
