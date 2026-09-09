#!/usr/bin/env bash

# --- Internal Agent Helpers ---
agent_upper() {
  printf '%s\n' "$1" | tr '[:lower:]' '[:upper:]'
}

agent_runtime_var() {
  local agent="$1" field="$2"
  local up
  up="$(agent_upper "$agent")"
  printf 'ARENA_AGENT_%s_%s\n' "$up" "$field"
}

agent_default_var() {
  local agent="$1" field="$2"
  local up
  up="$(agent_upper "$agent")"
  printf 'ARENA_AGENT_DEF_%s_%s\n' "$up" "$field"
}

legacy_env_name() {
  local agent="$1" field="$2"
  local up
  up="$(agent_upper "$agent")"
  case "$field" in
    CMD) printf '%s\n' "${up}_CMD" ;;
    PROMPT_MODE) printf '%s\n' "${up}_PROMPT_MODE" ;;
    PROMPT_FLAG) printf '%s\n' "${up}_PROMPT_FLAG" ;;
    WORKTREE_ROOT) printf '%s\n' "${up}_WORKTREE_ROOT" ;;
    WORKTREE) printf '%s\n' "${up}_WORKTREE" ;;
    BRANCH) printf '%s\n' "${up}_BRANCH" ;;
    TEST_CMD) printf '%s\n' "TEST_CMD_${up}" ;;
    *) return 1 ;;
  esac
}

# --- Commonized Property Accessors ---
_get_agent_prop() {
  local agent="$1" prop="$2"
  is_supported_agent "$agent" || die "알 수 없는 에이전트입니다: $agent"
  dynamic_var_get "$(agent_runtime_var "$agent" "$prop")"
}

_set_agent_prop() {
  local agent="$1" prop="$2" value="$3"
  is_supported_agent "$agent" || die "알 수 없는 에이전트입니다: $agent"
  dynamic_var_set "$(agent_runtime_var "$agent" "$prop")" "$value"
}

# Public getters (consolidated)
agent_cmd()         { _get_agent_prop "$1" "CMD"; }
agent_prompt_mode() { _get_agent_prop "$1" "PROMPT_MODE"; }
agent_prompt_flag() { _get_agent_prop "$1" "PROMPT_FLAG"; }
agent_worktree_root() { _get_agent_prop "$1" "WORKTREE_ROOT"; }
agent_worktree()    { _get_agent_prop "$1" "WORKTREE"; }
agent_branch()      { _get_agent_prop "$1" "BRANCH"; }
agent_test_cmd()    { _get_agent_prop "$1" "TEST_CMD"; }

# Public setters (consolidated)
set_agent_worktree_root() { _set_agent_prop "$1" "WORKTREE_ROOT" "$2"; }
set_agent_worktree()      { _set_agent_prop "$1" "WORKTREE" "$2"; }
set_agent_branch()        { _set_agent_prop "$1" "BRANCH" "$2"; }

agent_setting() {
  dynamic_var_get "$(agent_runtime_var "$1" "$2")"
}

set_agent_setting() {
  dynamic_var_set "$(agent_runtime_var "$1" "$2")" "$3"
}

# --- Catalog & Config ---
register_agent_config() {
  local agent="$1"
  local up
  up="$(agent_upper "$agent")"
  if is_supported_agent "$agent"; then
    return 0
  fi
  AGENT_CATALOG+=("$agent")
  dynamic_var_set "ARENA_AGENT_DEF_${up}_CMD" "${ARENA_AGENT_CMD_DEFAULT:-$agent}"
  dynamic_var_set "ARENA_AGENT_DEF_${up}_PROMPT_MODE" "${ARENA_AGENT_PROMPT_MODE_DEFAULT:-stdin}"
  dynamic_var_set "ARENA_AGENT_DEF_${up}_PROMPT_FLAG" "${ARENA_AGENT_PROMPT_FLAG_DEFAULT:---p}"
  dynamic_var_set "ARENA_AGENT_DEF_${up}_WORKTREE_ROOT" "${ARENA_AGENT_WORKTREE_ROOT_DEFAULT:-}"
  dynamic_var_set "ARENA_AGENT_DEF_${up}_TEST_CMD" "${ARENA_AGENT_TEST_CMD_DEFAULT:-}"
}

load_agent_configs() {
  AGENT_CATALOG=()
  [[ -d "$AGENT_CONF_DIR" ]] || die "에이전트 설정 디렉터리를 찾을 수 없습니다: $AGENT_CONF_DIR"

  local -a files=()
  local file
  while IFS= read -r file; do
    [[ -n "$file" ]] && files+=("$file")
  done < <(find "$AGENT_CONF_DIR" -maxdepth 1 -type f -name 'agent_*.sh' | sort)
  if [[ -d "$AGENT_CONF_EXTRA_DIR" ]]; then
    while IFS= read -r file; do
      [[ -n "$file" ]] && files+=("$file")
    done < <(find "$AGENT_CONF_EXTRA_DIR" -maxdepth 1 -type f -name '*.conf' | sort)
  fi

  for file in "${files[@]}"; do
    unset ARENA_AGENT_NAME ARENA_AGENT_CMD_DEFAULT ARENA_AGENT_PROMPT_MODE_DEFAULT
    unset ARENA_AGENT_PROMPT_FLAG_DEFAULT ARENA_AGENT_WORKTREE_ROOT_DEFAULT ARENA_AGENT_TEST_CMD_DEFAULT
    # shellcheck disable=SC1090
    source "$file"
    [[ -n "${ARENA_AGENT_NAME:-}" ]] || die "ARENA_AGENT_NAME이 비어 있습니다: $file"
    register_agent_config "$ARENA_AGENT_NAME"
  done

  [[ "${#AGENT_CATALOG[@]}" -gt 0 ]] || die "에이전트 설정 파일이 없습니다: $AGENT_CONF_DIR/agent_*.sh 또는 $AGENT_CONF_EXTRA_DIR/*.conf"
}

init_agent_runtime_settings() {
  local agent up field runtime_var legacy_var def_var resolved
  for agent in "${AGENT_CATALOG[@]}"; do
    up="$(agent_upper "$agent")"
    for field in CMD PROMPT_MODE PROMPT_FLAG WORKTREE_ROOT WORKTREE BRANCH TEST_CMD; do
      runtime_var="$(agent_runtime_var "$agent" "$field")"
      legacy_var="$(legacy_env_name "$agent" "$field" || true)"
      def_var="$(agent_default_var "$agent" "$field")"
      resolved="$(dynamic_var_get "$runtime_var")"
      [[ -z "$resolved" && -n "$legacy_var" ]] && resolved="$(dynamic_var_get "$legacy_var")"
      [[ -z "$resolved" ]] && resolved="$(dynamic_var_get "$def_var")"
      dynamic_var_set "$runtime_var" "$resolved"
    done
  done
}

apply_agent_runtime_defaults() {
  local agent root
  for agent in "${AGENT_CATALOG[@]}"; do
    root="$(agent_setting "$agent" WORKTREE_ROOT)"
    if [[ -z "$root" ]]; then
      if [[ "$agent" = "codex" ]]; then
        root="${CODEX_HOME:-$HOME/.codex}/worktrees"
      else
        [[ -n "$BASE_REPO" ]] || continue
        root="$BASE_REPO/.${agent}/worktrees"
      fi
      set_agent_setting "$agent" WORKTREE_ROOT "$root"
    fi
  done
}

is_supported_agent() {
  local -a catalog=("${AGENT_CATALOG[@]-}")
  local a
  [[ "$1" == "user" ]] && return 0 # 'user' is always supported for manual/adhoc tasks
  for a in "${catalog[@]}"; do
    [[ "$a" = "$1" ]] && return 0
  done
  return 1
}

# --- CSV & Array Helpers ---
normalize_agents_csv() {
  local raw="$1"
  local -a out=()
  local item
  local -a items=()
  IFS=',' read -r -a items <<< "$raw" || true
  for item in "${items[@]-}"; do
    item="$(trim_spaces "$item")"
    item="$(printf '%s' "$item" | tr '[:upper:]' '[:lower:]')"
    [[ -n "$item" ]] || continue
    is_supported_agent "$item" || die "지원하지 않는 에이전트입니다: $item (지원: $(IFS=,; echo "${AGENT_CATALOG[*]}"))"
    if [[ " ${out[*]-} " != *" ${item} "* ]]; then
      out+=("$item")
    fi
  done
  [[ "${#out[@]}" -ge 1 && "${#out[@]}" -le 4 ]] || die "에이전트는 1~4개를 선택해야 합니다 (입력값: $raw)"
  (IFS=','; printf '%s\n' "${out[*]}")
}

agents_csv_to_array() {
  local csv="$1"
  local item
  AGENT_ARRAY=()
  local -a __tmp_agents=()
  IFS=',' read -r -a __tmp_agents <<< "$csv" || true
  for item in "${__tmp_agents[@]-}"; do
    [[ -n "$item" ]] && AGENT_ARRAY+=("$item")
  done
}

agent_in_csv() {
  local agent="$1" csv="$2"
  local a
  agents_csv_to_array "$csv"
  for a in "${AGENT_ARRAY[@]}"; do
    [[ "$a" = "$agent" ]] && return 0
  done
  return 1
}

agent_first_cmd_token() {
  local cmd
  cmd="$(agent_cmd "$1")"
  set -- $cmd
  printf '%s\n' "${1:-}"
}
