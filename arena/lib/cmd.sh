#!/usr/bin/env bash

# --- Command Helpers ---
collect_one_agent() {
  local agent="$1"
  local worktree branch test_cmd

  worktree="$(agent_worktree "$agent")"
  branch="$(agent_branch "$agent")"
  test_cmd="$(agent_test_cmd "$agent")"

  [[ -d "$worktree" ]] || die "워크트리를 찾을 수 없습니다: $worktree"
  git -C "$worktree" rev-parse --verify HEAD >/dev/null

  local dirty="0"
  if ! git -C "$worktree" diff --quiet || ! git -C "$worktree" diff --cached --quiet || [[ -n "$(git -C "$worktree" ls-files --others --exclude-standard)" ]]; then
    dirty="1"
  fi

  if [[ "$dirty" = "1" ]]; then
    if [[ "$AUTO_COMMIT" = "1" ]]; then
      log "[$agent] dirty 변경사항을 감지하여 자동 커밋을 생성합니다"
      git -C "$worktree" add -A
      if ! git -C "$worktree" diff --cached --quiet; then
        git -C "$worktree" commit -m "chore(arena): auto-commit for $RUN_ID ($agent)"
      fi
    else
      die "[$agent] dirty 변경사항이 있지만 AUTO_COMMIT=0 입니다"
    fi
  fi

  local base_sha source_sha tree_sha snapshot_sha ref
  base_sha="$(git -C "$BASE_REPO" rev-parse "$BASE_BRANCH")"
  source_sha="$(git -C "$worktree" rev-parse HEAD)"
  tree_sha="$(git -C "$worktree" rev-parse HEAD^{tree})"

  local commit_msg
  commit_msg=$(cat <<EOF
arena snapshot ${RUN_ID}/${agent}
source:${source_sha}
base:${base_sha}
branch:${branch}
created:$(current_ts)
EOF
)
  snapshot_sha="$(printf '%s' "$commit_msg" | git -C "$BASE_REPO" commit-tree "$tree_sha" -p "$base_sha")"

  ref="refs/arena/snapshots/$RUN_ID/$agent"
  git -C "$BASE_REPO" update-ref "$ref" "$snapshot_sha"

  printf '%s\n' "$snapshot_sha" >"$RUN_DIR/commits/${agent}.sha"
  printf '%s\n' "$source_sha" >"$RUN_DIR/commits/${agent}.source.sha"

  git -C "$BASE_REPO" diff --binary "$base_sha" "$snapshot_sha" >"$RUN_DIR/diff/${agent}_vs_base.patch"
  git -C "$BASE_REPO" diff --shortstat "$base_sha" "$snapshot_sha" >"$RUN_DIR/summary/${agent}_shortstat.txt" || true
  git -C "$worktree" log --oneline "$BASE_BRANCH..HEAD" >"$RUN_DIR/summary/${agent}_branch_commits.txt" || true

  if [[ -n "$test_cmd" ]]; then
    local rc
    set +e
    (cd "$worktree" && bash -lc "$test_cmd") >"$RUN_DIR/tests/${agent}.log" 2>&1
    rc=$?
    set -e
    printf '%s\n' "$rc" >"$RUN_DIR/tests/${agent}.exit_code"
  else
    printf 'SKIPPED\n' >"$RUN_DIR/tests/${agent}.exit_code"
  fi

  log "[$agent] 스냅샷 생성 완료: $snapshot_sha"
}

arena_run_prompt_file() {
  local agent="$1" file="$2"
  local prompt
  prompt="$(cat "$file")"
  local cmd flag
  local -a cmd_parts
  cmd="$(agent_cmd "$agent")"
  flag="$(agent_prompt_flag "$agent")"
  read -r -a cmd_parts <<< "$cmd"
  if [[ "$flag" = "__POSITIONAL__" ]]; then
    "${cmd_parts[@]}" "$prompt"
  else
    "${cmd_parts[@]}" "$flag" "$prompt"
  fi
}

ensure_run_layout() {
  mkdir -p "$RUN_DIR"/{diff,summary,prompts,scripts,commits,logs,handoff,tests,status}
  mkdir -p "$RUN_DIR"/reviews/{base,cross,integrated}
}

write_wrapper() {
  local path="$1" agent="$2" worktree="$3" prompt_file="$4" output_file="$5"
  local cmd flag
  cmd="$(agent_cmd "$agent")"
  flag="$(agent_prompt_flag "$agent")"
  
  # Make sure status directory exists
  mkdir -p "$RUN_DIR/status"
  
  local status_file="$RUN_DIR/status/${agent}_review.done"
  # If an output file is provided, we redirect the AI output to it.
  local redirect=""
  if [[ -n "$output_file" ]]; then
    redirect="> $(printf '%q' "$output_file")"
  fi

  cat >"$path" <<EOF
#!/usr/bin/env bash
set -euo pipefail

# Start marker
rm -f $(printf '%q' "$status_file")
touch $(printf '%q' "$RUN_DIR/status/${agent}_review.running")

cd $(printf '%q' "$worktree")
prompt="\$(cat $(printf '%q' "$prompt_file"))"
cmd=$(printf '%q' "$cmd")
flag=$(printf '%q' "$flag")
read -r -a cmd_parts <<< "\$cmd"

echo "[arena] $agent 리뷰 중... 완료되면 창을 닫거나 무시하셔도 됩니다."

if [[ "\$flag" = "__POSITIONAL__" ]]; then
  eval "\"\${cmd_parts[@]}\" \"\$prompt\" $redirect"
else
  eval "\"\${cmd_parts[@]}\" \"\$flag\" \"\$prompt\" $redirect"
fi

# End marker
rm -f $(printf '%q' "$RUN_DIR/status/${agent}_review.running")
touch $(printf '%q' "$status_file")
echo "[arena] $agent 리뷰 완료."
sleep 2
EOF

  chmod +x "$path"
}

generate_wrapper_scripts() {
  local reviewer target
  agents_csv_to_array "$AGENTS"

  for reviewer in "${AGENT_ARRAY[@]}"; do
    [[ "$reviewer" == "user" ]] && continue
    for target in "${AGENT_ARRAY[@]}"; do
      [[ "$reviewer" = "$target" ]] && continue
      
      # Base review
      if [[ "$reviewer" == "$target" && -f "$RUN_DIR/prompts/base_review_${reviewer}.md" ]]; then
          write_wrapper \
            "$RUN_DIR/scripts/review_base_${reviewer}.sh" \
            "$reviewer" \
            "$(agent_worktree "$reviewer")" \
            "$RUN_DIR/prompts/base_review_${reviewer}.md" \
            "$RUN_DIR/reviews/base/${reviewer}_review.md"
      fi

      # Cross review
      if [[ -f "$RUN_DIR/prompts/review_${reviewer}_on_${target}.md" ]]; then
          write_wrapper \
            "$RUN_DIR/scripts/review_${reviewer}_on_${target}.sh" \
            "$reviewer" \
            "$(agent_worktree "$reviewer")" \
            "$RUN_DIR/prompts/review_${reviewer}_on_${target}.md" \
            "$RUN_DIR/reviews/cross/${reviewer}_on_${target}.md"
      fi
    done

    write_wrapper \
      "$RUN_DIR/scripts/assimilate_${reviewer}.sh" \
      "$reviewer" \
      "$(agent_worktree "$reviewer")" \
      "$RUN_DIR/prompts/assimilate_if_${reviewer}_wins.md" \
      ""

    if [[ -f "$RUN_DIR/prompts/integrated_review_by_${reviewer}.md" ]]; then
      write_wrapper \
        "$RUN_DIR/scripts/integrated_review_by_${reviewer}.sh" \
        "$reviewer" \
        "$(agent_worktree "$reviewer")" \
        "$RUN_DIR/prompts/integrated_review_by_${reviewer}.md" \
        "$RUN_DIR/summary/integrated_review.md"
    fi
  done
}

# --- Adhoc Review Initialization ---
cmd_adhoc_init() {
  log "현재 브랜치로부터 즉석(Adhoc) 리뷰 세션을 생성합니다."
  
  local current_branch; current_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
  [[ -n "$current_branch" ]] || die "git 저장소 내부가 아닙니다."
  
  # 1. 정보 수집 (GUI)
  local base_br; base_br="$(arena_pick_branch_gui)"
  
  # AI 모델 여러 개 선택 안내
  log "베이스 리뷰 및 교차 리뷰를 수행할 AI 모델을 선택하세요. (Tab키/스페이스바 다중선택 가능)"
  local ai_agents; ai_agents="$(arena_pick_agents_gui)"
  
  # 통합 리뷰 모델 선택 안내
  agents_csv_to_array "$ai_agents"
  log "위에서 선택한 모델(${ai_agents})들의 리뷰 결과를 종합할 [최종 통합 리뷰 모델]을 선택하세요."
  local integrated_reviewer; integrated_reviewer="$(arena_pick_one "최종 통합 리뷰 모델 선택" "${AGENT_ARRAY[@]}")"
  
  # 'user' 에이전트를 포함하여 AGENTS 구성
  local final_agents="user,${ai_agents}"
  AGENTS="$(normalize_agents_csv "$final_agents")"
  
  RUN_ID="adhoc-$(date '+%Y%m%d-%H%M%S')"
  RUN_DIR="$BASE_REPO/.arena/runs/$RUN_ID"
  BASE_BRANCH="$base_br"
  TASK_FILE="${TASK_FILE:-$RUN_DIR/prompts/adhoc_task.md}"
  
  mkdir -p "$RUN_DIR/prompts"
  echo "Adhoc review for branch: $current_branch" > "$TASK_FILE"
  
  ensure_run_layout
  
  # 2. 에이전트 설정 (현재 디렉토리를 user의 워크트리로 활용)
  init_agent_runtime_settings
  
  # user 에이전트 강제 설정 및 PROMPT_MODE 오류 방지
  set_agent_branch "user" "$current_branch"
  set_agent_worktree "user" "$BASE_REPO"
  _set_agent_prop "user" "PROMPT_MODE" "stdin"
  
  # AI 에이전트들은 빈 워크트리/브랜치로 설정 (리뷰 전용이므로 실제 코드는 생성 안 함)
  agents_csv_to_array "$ai_agents"
  for agent in "${AGENT_ARRAY[@]}"; do
    set_agent_branch "$agent" "$current_branch" # 리뷰를 위해 타겟 브랜치를 일단 동일하게 설정
    set_agent_worktree "$agent" "$BASE_REPO"    # 실제 launch를 안 하므로 경로만 맞춰둠
  done
  
  # 3. 메타데이터 저장
  cat >"$RUN_DIR/meta.env" <<EOF
RUN_ID='${RUN_ID}'
RUN_DIR='${RUN_DIR}'
BASE_REPO='${BASE_REPO}'
BASE_BRANCH='${BASE_BRANCH}'
TASK_FILE='${TASK_FILE}'
AGENTS='${AGENTS}'
INTEGRATED_REVIEWER='${integrated_reviewer}'
ARENA_UI_MODE='${ARENA_UI_MODE}'
AUTO_OPEN_REVIEW_UI='${AUTO_OPEN_REVIEW_UI}'
AUTO_OPEN_ASSIMILATION_UI='${AUTO_OPEN_ASSIMILATION_UI}'
INTERACTIVE_WINNER_PICK='${INTERACTIVE_WINNER_PICK}'
AUTO_COMMIT='${AUTO_COMMIT}'
AUTO_UPDATE_GITIGNORE='${AUTO_UPDATE_GITIGNORE}'
ARENA_COLLECT_PARALLEL='${ARENA_COLLECT_PARALLEL}'
RETENTION_DAYS='${RETENTION_DAYS}'
REVIEW_PROMPT_TEMPLATE_REL='${REVIEW_PROMPT_TEMPLATE_REL}'
INIT_TIME='$(current_ts)'
EOF

  # Ensure the environment variable in the active shell is also updated
  INTEGRATED_REVIEWER="${integrated_reviewer}"

  # 에이전트 상세 정보 추가
  agents_csv_to_array "$AGENTS"
  for agent in "${AGENT_ARRAY[@]}"; do
    local up; up="$(agent_upper "$agent")"
    upsert_meta_var "ARENA_AGENT_${up}_WORKTREE" "$(agent_worktree "$agent")" "$RUN_DIR/meta.env"
    upsert_meta_var "ARENA_AGENT_${up}_BRANCH" "$(agent_branch "$agent")" "$RUN_DIR/meta.env"
    
    # Adhoc user property injection to avoid load_meta crashes
    if [[ "$agent" == "user" ]]; then
      upsert_meta_var "ARENA_AGENT_USER_PROMPT_MODE" "stdin" "$RUN_DIR/meta.env"
    fi
  done

  cp "$RUN_DIR/meta.env" "$HOME/.arena/runs/${RUN_ID}.env"
  
  log "즉석 리뷰 세션이 생성되었습니다. RUN_ID: $RUN_ID"
  
  # 4. 즉시 수집 (현재 코드를 스냅샷으로 저장)
  cmd_collect --run-id "$RUN_ID" --agent "user"
  # AI 에이전트들은 비교 대상이 없으므로 빈 패치 생성용으로 더미 수집
  for agent in "${AGENT_ARRAY[@]}"; do
    [[ "$agent" == "user" ]] && continue
    # AI 에이전트는 base와 동일한 상태로 간주하여 diff가 없게 만듦
    # (실제로는 collect가 베이스와 현재 워크트리를 비교하므로, 
    # AI 리뷰어의 워크트리=BASE_REPO이면 diff가 0이 됨)
  done
}

# --- Command Implementations ---
cmd_init() {
  local override_base="" override_run_id="" override_agents=""
  local init_cleanup_armed="0"
  local -a init_created_branches=()
  local -a init_created_worktrees=()

  cleanup_init_failure() {
    local rc=$?
    trap - ERR
    [[ "$init_cleanup_armed" = "1" ]] || return "$rc"

    set +e
    warn "init 중 오류가 발생해 생성 리소스 정리를 시도합니다 (exit=$rc)"
    local wt br
    for wt in "${init_created_worktrees[@]}"; do
      [[ -d "$wt" ]] || continue
      git -C "$BASE_REPO" worktree remove --force "$wt" >/dev/null 2>&1 || true
    done
    for br in "${init_created_branches[@]}"; do
      git -C "$BASE_REPO" show-ref --verify --quiet "refs/heads/$br" && git -C "$BASE_REPO" branch -D "$br" >/dev/null 2>&1 || true
    done
    [[ -n "${RUN_DIR:-}" && -d "$RUN_DIR" ]] && rm -rf "$RUN_DIR"
    [[ -n "${RUN_ID:-}" ]] && rm -f "$HOME/.arena/runs/${RUN_ID}.env"
    exit "$rc"
  }

  trap cleanup_init_failure ERR

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --task-file) TASK_FILE="$2"; shift 2 ;;
      --base) override_base="$2"; shift 2 ;;
      --agents) override_agents="$2"; shift 2 ;;
      --run-id) override_run_id="$2"; shift 2 ;;
      --update-gitignore) AUTO_UPDATE_GITIGNORE="1"; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "알 수 없는 init 옵션입니다: $1" ;;
    esac
  done

  if [[ -n "$override_agents" ]]; then AGENTS="$(normalize_agents_csv "$override_agents")"; fi
  if [[ -n "$override_base" ]]; then BASE_BRANCH="$override_base"; fi

  if [[ -z "$TASK_FILE" ]]; then
    TASK_FILE="$(arena_pick_task_file_gui)"
  else
    TASK_FILE="$(abs_path "$TASK_FILE")"
    [[ -f "$TASK_FILE" ]] || die "작업 파일을 찾을 수 없습니다: $TASK_FILE"
  fi

  if [[ -z "$override_base" ]]; then BASE_BRANCH="$(arena_pick_branch_gui)"; fi
  if [[ -z "$override_agents" ]]; then AGENTS="$(arena_pick_agents_gui)"; fi
  AGENTS="$(normalize_agents_csv "$AGENTS")"

  validate_mode ARENA_UI_MODE "$ARENA_UI_MODE"
  validate_bool AUTO_OPEN_REVIEW_UI "$AUTO_OPEN_REVIEW_UI"
  validate_bool AUTO_OPEN_ASSIMILATION_UI "$AUTO_OPEN_ASSIMILATION_UI"
  validate_bool INTERACTIVE_WINNER_PICK "$INTERACTIVE_WINNER_PICK"
  validate_bool AUTO_COMMIT "$AUTO_COMMIT"
  validate_bool AUTO_UPDATE_GITIGNORE "$AUTO_UPDATE_GITIGNORE"
  validate_bool ARENA_COLLECT_PARALLEL "$ARENA_COLLECT_PARALLEL"
  validate_retention_days RETENTION_DAYS "$RETENTION_DAYS"
  init_agent_runtime_settings

  local agent root
  agents_csv_to_array "$AGENTS"
  for agent in "${AGENT_ARRAY[@]}"; do
    validate_prompt_mode "${agent}_PROMPT_MODE" "$(agent_prompt_mode "$agent")"
  done

  ensure_required_commands
  ensure_clean_repo
  git -C "$BASE_REPO" show-ref --verify --quiet "refs/heads/$BASE_BRANCH" || die "기준 브랜치를 찾을 수 없습니다: $BASE_BRANCH"

  RUN_ID="${override_run_id:-$(date '+%Y%m%d-%H%M%S')}"
  RUN_DIR="$BASE_REPO/.arena/runs/$RUN_ID"
  init_cleanup_armed="1"
  apply_agent_runtime_defaults
  INTEGRATED_REVIEWER=""

  for agent in "${AGENT_ARRAY[@]}"; do
    root="$(agent_worktree_root "$agent")"
    [[ -n "$root" ]] || die "worktree root가 비어 있습니다: $agent"
    set_agent_branch "$agent" "feature/arena-${agent}-${RUN_ID}"
    set_agent_worktree "$agent" "$root/arena-${agent}-${RUN_ID}"
    [[ ! -d "$(agent_worktree "$agent")" ]] || die "워크트리 경로가 이미 존재합니다: $(agent_worktree "$agent")"
  done

  mkdir -p "$RUN_DIR"
  for agent in "${AGENT_ARRAY[@]}"; do mkdir -p "$(agent_worktree_root "$agent")"; done
  ensure_run_layout

  for agent in "${AGENT_ARRAY[@]}"; do
    git -C "$BASE_REPO" worktree add -b "$(agent_branch "$agent")" "$(agent_worktree "$agent")" "$BASE_BRANCH"
    init_created_branches+=("$(agent_branch "$agent")")
    init_created_worktrees+=("$(agent_worktree "$agent")")
  done

  if [[ "$AUTO_UPDATE_GITIGNORE" = "1" ]]; then
    local gitignore_file="$BASE_REPO/.gitignore"
    if [[ -f "$gitignore_file" ]] && ! grep -qxF '.arena/' "$gitignore_file"; then
      printf '\n.arena/\n' >> "$gitignore_file"
      log ".gitignore에 .arena/ 항목을 추가했습니다"
    fi
  fi

  cat >"$RUN_DIR/meta.env" <<EOF
RUN_ID='${RUN_ID}'
RUN_DIR='${RUN_DIR}'
BASE_REPO='${BASE_REPO}'
BASE_BRANCH='${BASE_BRANCH}'
TASK_FILE='${TASK_FILE}'
AGENTS='${AGENTS}'
INTEGRATED_REVIEWER='${INTEGRATED_REVIEWER}'
ARENA_UI_MODE='${ARENA_UI_MODE}'
AUTO_OPEN_REVIEW_UI='${AUTO_OPEN_REVIEW_UI}'
AUTO_OPEN_ASSIMILATION_UI='${AUTO_OPEN_ASSIMILATION_UI}'
INTERACTIVE_WINNER_PICK='${INTERACTIVE_WINNER_PICK}'
AUTO_COMMIT='${AUTO_COMMIT}'
AUTO_UPDATE_GITIGNORE='${AUTO_UPDATE_GITIGNORE}'
ARENA_COLLECT_PARALLEL='${ARENA_COLLECT_PARALLEL}'
RETENTION_DAYS='${RETENTION_DAYS}'
REVIEW_PROMPT_TEMPLATE_REL='${REVIEW_PROMPT_TEMPLATE_REL}'
INIT_TIME='$(current_ts)'
EOF

  for agent in "${AGENT_ARRAY[@]}"; do
    local up legacy_var
    up="$(agent_upper "$agent")"
    upsert_meta_var "ARENA_AGENT_${up}_CMD" "$(agent_cmd "$agent")" "$RUN_DIR/meta.env"
    upsert_meta_var "ARENA_AGENT_${up}_PROMPT_MODE" "$(agent_prompt_mode "$agent")" "$RUN_DIR/meta.env"
    upsert_meta_var "ARENA_AGENT_${up}_PROMPT_FLAG" "$(agent_prompt_flag "$agent")" "$RUN_DIR/meta.env"
    upsert_meta_var "ARENA_AGENT_${up}_WORKTREE_ROOT" "$(agent_worktree_root "$agent")" "$RUN_DIR/meta.env"
    upsert_meta_var "ARENA_AGENT_${up}_WORKTREE" "$(agent_worktree "$agent")" "$RUN_DIR/meta.env"
    upsert_meta_var "ARENA_AGENT_${up}_BRANCH" "$(agent_branch "$agent")" "$RUN_DIR/meta.env"
    upsert_meta_var "ARENA_AGENT_${up}_TEST_CMD" "$(agent_test_cmd "$agent")" "$RUN_DIR/meta.env"

    for field in CMD PROMPT_MODE PROMPT_FLAG WORKTREE_ROOT WORKTREE BRANCH TEST_CMD; do
      legacy_var="$(legacy_env_name "$agent" "$field" || true)"
      [[ -n "$legacy_var" ]] && upsert_meta_var "$legacy_var" "$(agent_setting "$agent" "$field")" "$RUN_DIR/meta.env"
    done
  done

  local global_index_dir="$HOME/.arena/runs"
  mkdir -p "$global_index_dir"
  cp "$RUN_DIR/meta.env" "$global_index_dir/${RUN_ID}.env"
  log "전역 인덱스를 저장했습니다: $global_index_dir/${RUN_ID}.env"

  init_cleanup_armed="0"
  trap - ERR
  log "Arena 초기화 완료. RUN_ID: $RUN_ID"
}

cmd_start() { cmd_init "$@"; cmd_launch --run-id "$RUN_ID"; }

cmd_launch() {
  while [[ $# -gt 0 ]]; do
    case "$1" in --run-id) RUN_ID="$2"; shift 2 ;; *) die "알 수 없는 launch 옵션입니다: $1" ;; esac
  done
  if [[ -z "$RUN_ID" ]]; then RUN_ID="$(arena_pick_run_id)"; log "RUN 선택 완료: $RUN_ID"; fi
  load_meta
  local ui_mode; ui_mode="$(arena_detect_ui_mode)"

  local -a launch_cmds=()
  local agent cmd flag wt rendered
  agents_csv_to_array "$AGENTS"
  for agent in "${AGENT_ARRAY[@]}"; do
    cmd="$(agent_cmd "$agent")"; flag="$(agent_prompt_flag "$agent")"; wt="$(agent_worktree "$agent")"
    if [[ "$flag" = "__POSITIONAL__" ]]; then
      rendered="cd $(printf '%q' "$wt") && $cmd \"\$(cat $(printf '%q' "$TASK_FILE"))\""
    else
      rendered="cd $(printf '%q' "$wt") && $cmd $flag \"\$(cat $(printf '%q' "$TASK_FILE"))\""
    fi
    launch_cmds+=("$(printf '%s\t%s' "$agent" "$rendered")")
  done

  case "$ui_mode" in
    iterm2) for line in "${launch_cmds[@]}"; do iterm2_open_tab "${line#*$'	'}"; done ;;
    tmux)
      local session="arena-${RUN_ID}"
      for line in "${launch_cmds[@]}"; do
        agent="${line%%$'	'*}"; tmux_open_window "$session" "$agent" "${line#*$'	'}"
      done
      ;;
    none)
      log "Manual launch commands:"
      for line in "${launch_cmds[@]}"; do printf '  %s\n' "${line#*$'	'}"; done
      ;;
    *) die "알 수 없는 UI 모드입니다: $ui_mode" ;;
  esac
  log "launch 완료 (ui_mode=$ui_mode)"
}

cmd_collect() {
  local target_agent=""
  while [[ $# -gt 0 ]]; do
    case "$1" in --run-id) RUN_ID="$2"; shift 2 ;; --agent) target_agent="$2"; shift 2 ;; *) die "알 수 없는 collect 옵션입니다: $1" ;; esac
  done
  if [[ -z "$RUN_ID" ]]; then RUN_ID="$(arena_pick_run_id)"; log "RUN 선택 완료: $RUN_ID"; fi
  load_meta; ensure_run_layout

  if [[ -n "$target_agent" ]]; then
    agent_in_csv "$target_agent" "$AGENTS" || die "이 run에 없는 에이전트입니다: $target_agent (AGENTS=$AGENTS)"
    collect_one_agent "$target_agent"
  else
    local agent
    agents_csv_to_array "$AGENTS"
    if [[ "$ARENA_COLLECT_PARALLEL" = "1" && "${#AGENT_ARRAY[@]}" -gt 1 ]]; then
      local -a pids=() pid_agents=()
      local pid i rc failed="0"
      for agent in "${AGENT_ARRAY[@]}"; do (collect_one_agent "$agent") & pids+=("$!"); pid_agents+=("$agent"); done
      for i in "${!pids[@]}"; do
        pid="${pids[$i]}"
        if ! wait "$pid"; then rc=$?; warn "[${pid_agents[$i]}] collect 실패 (exit=$rc)"; failed="1"; fi
      done
      [[ "$failed" = "0" ]] || die "하나 이상의 에이전트 collect가 실패했습니다"
    else
      for agent in "${AGENT_ARRAY[@]}"; do collect_one_agent "$agent"; done
    fi
  fi
  log "collect 완료"
}

cmd_review_pack() {
  local override_integrated_reviewer=""
  while [[ $# -gt 0 ]]; do
    case "$1" in --run-id) RUN_ID="$2"; shift 2 ;; --integrated-reviewer) override_integrated_reviewer="$2"; shift 2 ;; *) die "알 수 없는 review-pack 옵션입니다: $1" ;; esac
  done
  if [[ -z "$RUN_ID" ]]; then RUN_ID="$(arena_pick_run_id)"; log "RUN 선택 완료: $RUN_ID"; fi
  load_meta; ensure_run_layout

  local agent reviewer target
  agents_csv_to_array "$AGENTS"
  for agent in "${AGENT_ARRAY[@]}"; do [[ -f "$RUN_DIR/diff/${agent}_vs_base.patch" ]] || collect_one_agent "$agent"; done

  cat >"$RUN_DIR/summary/comparison.md" <<EOF
# Arena 비교 결과 ($RUN_ID)
- 기준 저장소: $BASE_REPO
- 기준 브랜치: $BASE_BRANCH
- 에이전트: $AGENTS
- 생성 시각: $(current_ts)
## 스냅샷 커밋
$(for agent in "${AGENT_ARRAY[@]}"; do printf -- "- %s 스냅샷: %s\n" "$agent" "$(cat "$RUN_DIR/commits/${agent}.sha")"; done)
## 요약 통계
$(for agent in "${AGENT_ARRAY[@]}"; do printf -- "- %s: %s\n" "$agent" "$(cat "$RUN_DIR/summary/${agent}_shortstat.txt" 2>/dev/null || echo "N/A")"; done)
EOF

  local review_prompt_template_file
  if [[ -f "$TEMPLATE_DIR/$(basename "$REVIEW_PROMPT_TEMPLATE_REL")" ]]; then
    review_prompt_template_file="$TEMPLATE_DIR/$(basename "$REVIEW_PROMPT_TEMPLATE_REL")"
  else
    review_prompt_template_file="$BASE_REPO/$REVIEW_PROMPT_TEMPLATE_REL"
  fi

  local rel_reviews_dir; rel_reviews_dir="$(python3 -c "import os; print(os.path.relpath('$RUN_DIR/reviews', '$BASE_REPO'))" 2>/dev/null || echo ".arena/runs/$RUN_ID/reviews")"

  local base_review_template_block="" cross_review_template_block="" integrated_review_template_block=""
  if [[ -f "$review_prompt_template_file" ]]; then
    base_review_template_block="$(extract_markdown_section_by_heading "$review_prompt_template_file" "1) 베이스 리뷰 (완전자동)" || true)"
    cross_review_template_block="$(extract_markdown_section_by_heading "$review_prompt_template_file" "2) 교차 리뷰 (완전자동)" || true)"
    integrated_review_template_block="$(extract_markdown_section_by_heading "$review_prompt_template_file" "3) 통합 리뷰 (완전자동)" || true)"
    base_review_template_block="${base_review_template_block//\{REVIEWS_DIR\}/$rel_reviews_dir}"
    cross_review_template_block="${cross_review_template_block//\{REVIEWS_DIR\}/$rel_reviews_dir}"
    integrated_review_template_block="${integrated_review_template_block//\{REVIEWS_DIR\}/$rel_reviews_dir}"
  fi

  for agent in "${AGENT_ARRAY[@]}"; do
    cat >"$RUN_DIR/prompts/base_review_${agent}.md" <<EOF
You are ${agent} reviewing your own implementation for run $RUN_ID.
Use these artifacts:
- $RUN_DIR/diff/${agent}_vs_base.patch
$(if [[ -n "$base_review_template_block" ]]; then printf -- "[기준 브랜치 리뷰 프롬프트 지침]\n- 아래 블록을 반드시 준수하세요.\n\n%s" "$base_review_template_block"
else printf -- "Return findings by severity and include concrete file-level references."; fi)
EOF
  done

  for reviewer in "${AGENT_ARRAY[@]}"; do
    for target in "${AGENT_ARRAY[@]}"; do
      [[ "$reviewer" = "$target" ]] && continue
      cat >"$RUN_DIR/prompts/review_${reviewer}_on_${target}.md" <<EOF
You are ${reviewer} reviewing ${target}'s implementation.
Use these artifacts:
- $RUN_DIR/diff/${target}_vs_base.patch
- $RUN_DIR/summary/comparison.md
- $RUN_DIR/reviews/base/${target}_*review.md
$(if [[ -n "$cross_review_template_block" ]]; then printf -- "[기준 브랜치 리뷰 프롬프트 지침]\n- 아래 블록을 반드시 준수하세요.\n\n%s" "$cross_review_template_block"
else printf -- "Return findings by severity and include concrete file-level references."; fi)
EOF
    done
  done

  if [[ -n "$override_integrated_reviewer" ]]; then INTEGRATED_REVIEWER="$override_integrated_reviewer"; fi
  if [[ -z "$INTEGRATED_REVIEWER" ]]; then INTEGRATED_REVIEWER="$(arena_pick_integrated_reviewer)"; fi
  agent_in_csv "$INTEGRATED_REVIEWER" "$AGENTS" || die "통합 리뷰 모델이 현재 에이전트 목록에 없습니다: $INTEGRATED_REVIEWER"

  cat >"$RUN_DIR/prompts/integrated_review_by_${INTEGRATED_REVIEWER}.md" <<EOF
You are ${INTEGRATED_REVIEWER}, responsible for final integrated review for run $RUN_ID.
Input artifacts:
- $RUN_DIR/summary/comparison.md
- $RUN_DIR/reviews/base/*.md
- $RUN_DIR/reviews/cross/*.md
- $RUN_DIR/diff/*_vs_base.patch
$(if [[ -n "$integrated_review_template_block" ]]; then printf -- "[기준 브랜치 리뷰 프롬프트 지침]\n- 아래 블록을 반드시 준수하세요.\n\n%s" "$integrated_review_template_block"
else printf -- "Task:\n1) Consolidate cross-review findings.\n2) Produce integrated verdict.\n3) Write to: $RUN_DIR/summary/integrated_review.md"; fi)
EOF

  generate_wrapper_scripts
  upsert_meta_var "INTEGRATED_REVIEWER" "$INTEGRATED_REVIEWER" "$RUN_DIR/meta.env"
  upsert_meta_var "INTEGRATED_REVIEWER" "$INTEGRATED_REVIEWER" "$HOME/.arena/runs/${RUN_ID}.env"

  if [[ "$AUTO_OPEN_REVIEW_UI" = "1" ]]; then
    local ui_mode; ui_mode="$(arena_detect_ui_mode)"
    open_review_ui "$ui_mode"
    arena_wait_confirm "크로스 리뷰가 완료되었나요? (${AGENTS})"
    open_integrated_review_ui "$ui_mode" "$INTEGRATED_REVIEWER"
    arena_wait_confirm "통합 리뷰가 완료되었나요? (리뷰어: $INTEGRATED_REVIEWER)"
  fi
  log "프롬프트 파일 생성 완료: $RUN_DIR/prompts"
}

cmd_review() {
  local ir=""; while [[ $# -gt 0 ]]; do case "$1" in --run-id) RUN_ID="$2"; shift 2 ;; --integrated-reviewer) ir="$2"; shift 2 ;; *) die "알 수 없는 review 옵션입니다: $1" ;; esac; done
  if [[ -z "$RUN_ID" ]]; then RUN_ID="$(arena_pick_run_id)"; log "RUN 선택 완료: $RUN_ID"; fi
  cmd_collect --run-id "$RUN_ID"
  cmd_review_pack --run-id "$RUN_ID" ${ir:+--integrated-reviewer "$ir"}
}

cmd_review_only() {
  local ir=""; while [[ $# -gt 0 ]]; do case "$1" in --run-id) RUN_ID="$2"; shift 2 ;; --integrated-reviewer) ir="$2"; shift 2 ;; *) die "알 수 없는 review-only 옵션입니다: $1" ;; esac; done
  if [[ -z "$RUN_ID" ]]; then RUN_ID="$(arena_pick_run_id)"; log "RUN 선택 완료: $RUN_ID"; fi
  cmd_review_pack --run-id "$RUN_ID" ${ir:+--integrated-reviewer "$ir"}
}

cmd_handoff() {
  local winner="" commit_mode="0"
  while [[ $# -gt 0 ]]; do
    case "$1" in --run-id) RUN_ID="$2"; shift 2 ;; --winner) winner="$2"; shift 2 ;; --commit) commit_mode="1"; shift ;; *) die "알 수 없는 handoff 옵션입니다: $1" ;; esac
  done
  if [[ -z "$RUN_ID" ]]; then RUN_ID="$(arena_pick_run_id)"; log "RUN 선택 완료: $RUN_ID"; fi
  load_meta; ensure_run_layout
  if [[ -z "$winner" && "$INTERACTIVE_WINNER_PICK" = "1" ]]; then winner="$(arena_pick_winner)"; log "승자 선택 완료: $winner"; fi
  [[ -n "$winner" ]] || die "승자 지정이 필요합니다 (--winner <agent>)"
  agent_in_csv "$winner" "$AGENTS" || die "잘못된 승자 값입니다: $winner (AGENTS=$AGENTS)"

  if [[ "$AUTO_OPEN_ASSIMILATION_UI" = "1" ]]; then
    local ui_mode; ui_mode="$(arena_detect_ui_mode)"; open_assimilation_ui "$ui_mode" "$winner"
    arena_wait_confirm "assimilation이 완료되었나요?"
  fi

  collect_one_agent "$winner"
  local snapshot_sha; snapshot_sha="$(cat "$RUN_DIR/commits/${winner}.sha")"
  
  # Adhoc 모드에서 승자가 'user'인 경우, 이미 원본 저장소에 코드가 있으므로 Handoff(cherry-pick)를 생략합니다.
  if [[ "$RUN_ID" == adhoc-* && "$winner" == "user" ]]; then
    log "즉석(Adhoc) 리뷰이므로 내 코드(user)를 내 브랜치에 덮어쓰는 Handoff 과정을 생략합니다."
    cat >"$RUN_DIR/handoff/result.md" <<EOF
# Handoff 결과 ($RUN_ID)
- Winner: $winner
- 브랜치: $BASE_BRANCH
상태: 즉석 리뷰(자체 코드 유지)
EOF
    return 0
  fi

  ensure_clean_repo
  local current_branch; current_branch="$(git -C "$BASE_REPO" rev-parse --abbrev-ref HEAD)"
  [[ "$current_branch" != "$BASE_BRANCH" ]] && git -C "$BASE_REPO" checkout "$BASE_BRANCH"

  local cp_log="$RUN_DIR/handoff/apply.log" rc
  set +e
  if [[ "$commit_mode" = "1" ]]; then git -C "$BASE_REPO" cherry-pick -x "$snapshot_sha" >"$cp_log" 2>&1
  else git -C "$BASE_REPO" cherry-pick -n "$snapshot_sha" >"$cp_log" 2>&1; fi
  rc=$?; set -e
  if [[ "$rc" -ne 0 ]]; then die "변경 반영(cherry-pick)에 실패했습니다. $RUN_DIR/handoff/conflict.txt 를 확인하세요."; fi

  if [[ "$commit_mode" = "1" ]]; then
    local new_commit; new_commit="$(git -C "$BASE_REPO" rev-parse HEAD)"
    cat >"$RUN_DIR/handoff/result.md" <<EOF
# Handoff 결과 ($RUN_ID)
- Winner: $winner
- 반영 커밋: $new_commit
- 브랜치: $BASE_BRANCH
EOF
    log "handoff 완료: $BASE_BRANCH 브랜치에 커밋 생성 ($new_commit)"
  else
    cat >"$RUN_DIR/handoff/result.md" <<EOF
# Handoff 결과 ($RUN_ID)
- Winner: $winner
- 브랜치: $BASE_BRANCH
상태: 로컬 반영 완료(미커밋)
EOF
    log "handoff 완료: 로컬에 변경사항만 반영했습니다"
  fi
}

cmd_finish() {
  local winner="" keep_index="0" force="0" no_cleanup="0" commit_mode="0"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --run-id) RUN_ID="$2"; shift 2 ;; --winner) winner="$2"; shift 2 ;; --keep-index) keep_index="1"; shift ;;
      --force) force="1"; shift ;; --no-cleanup) no_cleanup="1"; shift ;; --commit) commit_mode="1"; shift ;;
      *) if is_supported_agent "$1"; then [[ -z "$winner" ]] || die "승자 중복"; winner="$1"; shift; else die "알 수 없는 옵션: $1"; fi ;;
    esac
  done
  if [[ -z "$RUN_ID" ]]; then RUN_ID="$(arena_pick_run_id)"; log "RUN 선택 완료: $RUN_ID"; fi
  cmd_collect --run-id "$RUN_ID"
  [[ ! -f "$RUN_DIR/summary/comparison.md" || -z "${INTEGRATED_REVIEWER:-}" ]] && cmd_review_pack --run-id "$RUN_ID"
  
  if [[ -z "$winner" ]]; then 
    if [[ "$RUN_ID" == adhoc-* ]]; then
      # Adhoc 모드에서는 사용자의 코드가 기준이므로 승자를 'user'로 자동 지정
      winner="user"
      log "즉석 리뷰 세션: 승자를 'user'로 자동 지정합니다."
    else
      winner="$(arena_pick_winner)"
      log "승자 선택 완료: $winner"
    fi
  fi
  
  local -a handoff_args=(--run-id "$RUN_ID" --winner "$winner"); [[ "$commit_mode" = "1" ]] && handoff_args+=(--commit)
  cmd_handoff "${handoff_args[@]}"

  local report_file; report_file="$(generate_integrated_report)"; log "통합 리포트: $report_file"
  if [[ "$no_cleanup" = "0" ]]; then
    local -a cleanup_args=(--run-id "$RUN_ID"); [[ "$keep_index" = "1" ]] && cleanup_args+=(--keep-index); [[ "$force" = "1" ]] && cleanup_args+=(--force)
    cmd_cleanup "${cleanup_args[@]}"
  fi
}

cmd_cleanup() {
  local force="0" keep_index="0" delete_history="0"; while [[ $# -gt 0 ]]; do case "$1" in --run-id) RUN_ID="$2"; shift 2 ;; --force) force="1"; shift ;; --keep-index) keep_index="1"; shift ;; --delete-history) delete_history="1"; shift ;; *) die "알 수 없는 cleanup 옵션: $1" ;; esac; done
  if [[ -z "$RUN_ID" ]]; then RUN_ID="$(arena_pick_run_id)"; log "RUN 선택 완료: $RUN_ID"; fi
  load_meta
  local agent wt br; agents_csv_to_array "$AGENTS"
  
  for agent in "${AGENT_ARRAY[@]}"; do
    wt="$(agent_worktree "$agent")"
    [[ "$wt" == "$BASE_REPO" ]] && continue # Adhoc user 방어
    [[ -d "$wt" ]] && [[ -n "$(git -C "$wt" status --porcelain)" ]] && [[ "$force" != "1" ]] && die "dirty 워크트리: $wt"
  done
  
  for agent in "${AGENT_ARRAY[@]}"; do 
    wt="$(agent_worktree "$agent")"
    [[ "$wt" == "$BASE_REPO" ]] && continue # 절대 BASE_REPO 워크트리는 지우지 않음
    [[ -d "$wt" ]] && git -C "$BASE_REPO" worktree remove ${force:+"--force"} "$wt"
  done
  
  for agent in "${AGENT_ARRAY[@]}"; do 
    br="$(agent_branch "$agent")"
    # 현재 체크아웃된 브랜치(주로 user의 작업 브랜치)는 삭제하지 않음
    local current_br; current_br="$(git -C "$BASE_REPO" rev-parse --abbrev-ref HEAD 2>/dev/null)"
    if [[ "$br" != "$current_br" ]]; then
      git -C "$BASE_REPO" branch -D "$br" >/dev/null 2>&1 || true
    fi
  done
  
  while IFS= read -r ref; do [[ -n "$ref" ]] && git -C "$BASE_REPO" update-ref -d "$ref"; done < <(git -C "$BASE_REPO" for-each-ref --format='%(refname)' "refs/arena/snapshots/$RUN_ID/")

  if [[ -f "$HOME/.arena/runs/${RUN_ID}.env" && "$keep_index" != "1" ]]; then rm "$HOME/.arena/runs/${RUN_ID}.env"; log "전역 인덱스 삭제"; fi
  
  if [[ "$delete_history" = "1" ]]; then
    rm -rf "$RUN_DIR"
    log "기록(RUN_DIR) 영구 삭제 완료: $RUN_DIR"
  else
    cat >"$RUN_DIR/cleanup/result.md" <<EOF
# Cleanup 결과 ($RUN_ID)
- 시간: $(current_ts)
EOF
    log "cleanup 완료: $RUN_ID"
  fi
}

cmd_cleanup_old() {
  local rd="$RETENTION_DAYS" apply="0" ro="0" go="0"
  while [[ $# -gt 0 ]]; do
    case "$1" in --retention-days) rd="$2"; shift 2 ;; --apply) apply="1"; shift ;; --repo-only) ro="1"; shift ;; --global-only) go="1"; shift ;; *) die "알 수 없는 옵션: $1" ;; esac
  done
  validate_retention_days RETENTION_DAYS "$rd"
  local rrd=""; if [[ "$go" != "1" ]]; then if [[ -n "${BASE_REPO:-}" ]]; then rrd="$BASE_REPO/.arena/runs"; elif [[ "$ro" = "1" ]]; then die "--repo-only는 BASE_REPO 필요"; fi; fi

  local -a s_repo=() s_glob=() o_glob=()
  if [[ -n "$rrd" && -d "$rrd" ]]; then while IFS= read -r p; do [[ -n "$p" ]] && s_repo+=("$p"); done < <(find "$rrd" -mindepth 1 -maxdepth 1 -type d -mtime +"$rd" | sort); fi
  if [[ "$ro" != "1" && -d "$HOME/.arena/runs" ]]; then
    while IFS= read -r f; do [[ -n "$f" ]] && s_glob+=("$f"); done < <(find "$HOME/.arena/runs" -mindepth 1 -maxdepth 1 -type f -name '*.env' -mtime +"$rd" | sort)
    while IFS= read -r f; do
      [[ -n "$f" ]] || continue
      local rid="$(basename "$f" .env)" orp="$(grep -m1 '^BASE_REPO=' "$f" | cut -d= -f2- | tr -d "'" || true)"
      [[ -z "$orp" || ! -d "$orp/.arena/runs/$rid" ]] && o_glob+=("$f")
    done < <(find "$HOME/.arena/runs" -mindepth 1 -maxdepth 1 -type f -name '*.env' | sort)
  fi

  log "cleanup-old 스캔 결과 ($rd 일 경과, 모드=$([[ "$apply" = "1" ]] && echo APPLY || echo DRY-RUN))"
  if [[ "$apply" != "1" ]]; then log "--apply 미지정으로 삭제 미수행"; return 0; fi
  for p in "${s_repo[@]}"; do rm -rf "$p"; log "삭제: $p"; f="$HOME/.arena/runs/$(basename "$p").env"; [[ -f "$f" ]] && rm "$f"; done
  for f in "${s_glob[@]}"; do [[ -f "$f" ]] && rm "$f"; done
  for f in "${o_glob[@]}"; do [[ -f "$f" ]] && rm "$f"; done
}

cmd_status() {
  local summary="0"; while [[ $# -gt 0 ]]; do case "$1" in --run-id) RUN_ID="$2"; shift 2 ;; --summary) summary="1"; shift ;; *) die "알 수 없는 status 옵션: $1" ;; esac; done
  if [[ -z "$RUN_ID" ]]; then
    RUN_ID="$(latest_repo_run_id || true)"; [[ -z "$RUN_ID" ]] && RUN_ID="$(ls -1t "$HOME/.arena/runs/"*.env 2>/dev/null | head -n 1 | xargs basename -s .env || true)"
    [[ -n "$RUN_ID" ]] && log "최신 RUN_ID 사용: $RUN_ID" || { echo "실행 이력 없음"; return 0; }
  fi
  load_meta
  local winner="$(grep -m1 '^- Winner:' "$RUN_DIR/handoff/result.md" | sed 's/^- Winner:[[:space:]]*//' 2>/dev/null || echo "(미선택)")"
  local cleanup="미실행"; [[ -f "$RUN_DIR/cleanup/result.md" ]] && cleanup="완료"

  cat <<EOF
RUN_ID: $RUN_ID
기준 저장소: $BASE_REPO
기준 브랜치: $BASE_BRANCH
에이전트: $AGENTS
승자: $winner | 정리 상태: $cleanup
EOF

  local agent; agents_csv_to_array "$AGENTS"
  for agent in "${AGENT_ARRAY[@]}"; do
    local wt="$(agent_worktree "$agent")" br="$(agent_branch "$agent")" prog="초기화됨"
    [[ -f "$RUN_DIR/commits/${agent}.sha" ]] && prog="수집 완료"
    [[ -f "$RUN_DIR/prompts/review_${agent}_on_*.md" ]] && prog="리뷰 준비 완료"
    [[ -f "$RUN_DIR/handoff/result.md" ]] && prog="handoff 완료"
    [[ ! -d "$wt" && ! -f "$RUN_DIR/cleanup/result.md" ]] && prog="정리 완료"
    echo -e "\n[$agent]\n  워크트리: $wt ($([[ -d "$wt" ]] && echo 활성 || echo 삭제))\n  브랜치: $br\n  상태: $prog"
  done
  echo -e "\n통합 리포트: $(generate_integrated_report)"
}

cmd_open_review_ui() {
  while [[ $# -gt 0 ]]; do case "$1" in --run-id) RUN_ID="$2"; shift 2 ;; *) die "알 수 없는 옵션: $1" ;; esac; done
  [[ -n "$RUN_ID" ]] || die "RUN_ID 필수"
  load_meta; ensure_run_layout; generate_wrapper_scripts
  local ui_mode; ui_mode="$(arena_detect_ui_mode)"
  
  # 크로스 리뷰 시작
  open_review_ui "$ui_mode"
  
  # 프로세스 모니터링 (gum spin)
  log "AI 에이전트들이 리뷰를 진행 중입니다. (새 창을 닫지 마세요)"
  local expected_files=()
  local wrapper
  while IFS= read -r wrapper; do
    [[ -n "$wrapper" ]] || continue
    local agent_name; agent_name="$(basename "$wrapper" | sed 's/review_//' | sed 's/_on_.*//' | sed 's/.sh//')"
    expected_files+=("$RUN_DIR/status/${agent_name}_review.done")
  done < <(find "$RUN_DIR/scripts" -maxdepth 1 -type f -name 'review_*.sh' | sort)

  if has_cmd gum; then
    # Create a temporary script for gum spin to run
    local wait_script="$RUN_DIR/status/wait_cross_review.sh"
    cat > "$wait_script" <<EOF
#!/usr/bin/env bash
expected=(${expected_files[@]})
while true; do
  all_done=1
  for f in "\${expected[@]}"; do
    if [[ ! -f "\$f" ]]; then
      all_done=0
      break
    fi
  done
  if [[ "\$all_done" -eq 1 ]]; then break; fi
  sleep 1
done
EOF
    chmod +x "$wait_script"
    gum spin --spinner dot --title "크로스 리뷰 완료 대기 중..." -- bash "$wait_script"
  else
    log "크로스 리뷰가 완료될 때까지 대기합니다..."
    local wait_script="$RUN_DIR/status/wait_cross_review.sh"
    bash "$wait_script"
  fi
  log "모든 크로스 리뷰가 완료되었습니다."

  [[ -n "${INTEGRATED_REVIEWER:-}" ]] || die "INTEGRATED_REVIEWER 미설정"
  
  # 통합 리뷰 시작
  open_integrated_review_ui "$ui_mode" "$INTEGRATED_REVIEWER"
  
  local expected_integrated="$RUN_DIR/status/${INTEGRATED_REVIEWER}_review.done"
  if has_cmd gum; then
    local wait_integrated="$RUN_DIR/status/wait_integrated.sh"
    cat > "$wait_integrated" <<EOF
#!/usr/bin/env bash
while [[ ! -f "$expected_integrated" ]]; do sleep 1; done
EOF
    chmod +x "$wait_integrated"
    gum spin --spinner line --title "통합 리뷰(${INTEGRATED_REVIEWER}) 작성 대기 중..." -- bash "$wait_integrated"
  else
    log "통합 리뷰 완료를 대기합니다..."
    while [[ ! -f "$expected_integrated" ]]; do sleep 1; done
  fi
  log "통합 리뷰가 완료되었습니다."
}

cmd_check_integrated_review() {
  while [[ $# -gt 0 ]]; do case "$1" in --run-id) RUN_ID="$2"; shift 2 ;; *) die "알 수 없는 옵션: $1" ;; esac; done
  [[ -n "$RUN_ID" ]] || die "RUN_ID 필수"; load_meta
  local f="$RUN_DIR/summary/integrated_review.md"
  if [[ -f "$f" ]]; then echo "통합 리뷰 내용:"; sed -n '1,120p' "$f"; else warn "리뷰 파일 없음: $f"; fi
}

cmd_apply_feedback() {
  while [[ $# -gt 0 ]]; do case "$1" in --run-id) RUN_ID="$2"; shift 2 ;; *) die "알 수 없는 옵션: $1" ;; esac; done
  [[ -n "$RUN_ID" ]] || die "RUN_ID 필수"; load_meta
  
  [[ -n "${INTEGRATED_REVIEWER:-}" ]] || die "통합 리뷰 모델(INTEGRATED_REVIEWER)이 설정되지 않았습니다."
  
  local review_file="$RUN_DIR/summary/integrated_review.md"
  [[ -f "$review_file" ]] || die "통합 리뷰 파일이 없습니다: $review_file"
  
  local diff_file="$RUN_DIR/diff/user_vs_base.patch"
  [[ -f "$diff_file" ]] || diff_file="$(ls -1 "$RUN_DIR/diff/"*_vs_base.patch | head -n 1)"
  
  log "AI($INTEGRATED_REVIEWER)를 활용하여 리뷰 피드백을 기반으로 수정된 패치를 생성합니다..."
  
  local prompt_file="$RUN_DIR/prompts/apply_feedback.md"
  cat > "$prompt_file" <<EOF
You are an expert developer.
Review the following "Integrated Code Review" and the original "Diff".
Your task is to generate a new standard unified diff (.patch format) that applies the suggested changes from the review onto the original code.
Provide ONLY the raw diff text. Do not use markdown code blocks like \`\`\`diff.

# Original Diff:
$(cat "$diff_file" | head -n 500)

# Review Feedback to Apply:
$(cat "$review_file")
EOF

  local cmd flag
  cmd="$(agent_cmd "$INTEGRATED_REVIEWER")"
  flag="$(agent_prompt_flag "$INTEGRATED_REVIEWER")"
  
  local generated_patch="$RUN_DIR/summary/applied_feedback.patch"
  local -a cmd_parts
  read -r -a cmd_parts <<< "$cmd"
  
  set +e
  if [[ "$flag" = "__POSITIONAL__" ]]; then
    "${cmd_parts[@]}" "$(cat "$prompt_file")" > "$generated_patch"
  else
    "${cmd_parts[@]}" "$flag" "$(cat "$prompt_file")" > "$generated_patch"
  fi
  set -e
  
  # Remove markdown wrappers if present
  sed -i.bak '/^```/d' "$generated_patch"
  rm -f "$generated_patch.bak"
  
  if [[ -s "$generated_patch" ]]; then
    log "생성된 패치를 적용 시도합니다..."
    if git -C "$BASE_REPO" apply --allow-empty "$generated_patch" >/dev/null 2>&1; then
      log "피드백이 성공적으로 자동 적용(Apply) 되었습니다. (git status를 확인하세요)"
    else
      warn "자동 적용에 실패했습니다. 패치 파일($generated_patch)을 확인하고 수동으로 반영하세요."
    fi
  else
    die "AI가 패치 생성에 실패했습니다."
  fi
}

cmd_amend_commit() {
  while [[ $# -gt 0 ]]; do case "$1" in --run-id) RUN_ID="$2"; shift 2 ;; *) die "알 수 없는 옵션: $1" ;; esac; done
  [[ -n "$RUN_ID" ]] || die "RUN_ID 필수"; load_meta
  
  [[ -n "${INTEGRATED_REVIEWER:-}" ]] || die "통합 리뷰 모델(INTEGRATED_REVIEWER)이 설정되지 않았습니다."
  
  local current_branch; current_branch="$(git -C "$BASE_REPO" rev-parse --abbrev-ref HEAD)"
  
  # --- History Cleanup (Squash auto-commits) ---
  log "현재 브랜치($current_branch)의 임시 커밋들을 탐색하여 하나의 커밋으로 Squash 합니다..."
  
  # Find all commits from BASE_BRANCH to HEAD
  local -a auto_commits=()
  while IFS= read -r sha; do
    [[ -n "$sha" ]] && auto_commits+=("$sha")
  done < <(git -C "$BASE_REPO" log --format="%H" --grep="chore(arena): auto-commit" "$BASE_BRANCH..HEAD")
  
  if [[ "${#auto_commits[@]}" -gt 1 ]]; then
    log "${#auto_commits[@]}개의 임시 커밋이 발견되어 병합(Squash)을 진행합니다."
    # Soft reset to the parent of the oldest auto-commit, which is effectively BASE_BRANCH if we only made auto-commits
    # A safer way: soft reset to BASE_BRANCH, then commit with the generic message.
    git -C "$BASE_REPO" reset --soft "$BASE_BRANCH"
    git -C "$BASE_REPO" commit -m "chore(arena): squashed auto-commits" > /dev/null
    log "임시 커밋 병합 완료."
  elif [[ "${#auto_commits[@]}" -eq 0 ]]; then
    log "병합할 임시 커밋이 발견되지 않았습니다. 현재 HEAD를 기준으로 진행합니다."
  else
    log "임시 커밋이 1개이므로 Squash 없이 바로 진행합니다."
  fi
  # ---------------------------------------------
  
  log "AI($INTEGRATED_REVIEWER)를 활용하여 커밋 메시지를 생성합니다..."
  
  # 직전 커밋(HEAD)의 변경사항을 가져옴 (auto-commit 내용)
  local diff_file="$RUN_DIR/summary/commit_diff.patch"
  git -C "$BASE_REPO" diff HEAD~1..HEAD > "$diff_file"
  
  local prompt_file="$RUN_DIR/prompts/generate_commit_msg.md"
  cat > "$prompt_file" <<EOF
You are an expert software engineer.
Generate a professional Git commit message based on the following code diff.
Follow the Conventional Commits format (e.g., feat:, fix:, chore:, refactor:, etc.).
Provide ONLY the commit message text. Do not include any explanations, markdown code blocks, or preamble.

Diff:
$(cat "$diff_file")
EOF

  local cmd flag
  cmd="$(agent_cmd "$INTEGRATED_REVIEWER")"
  flag="$(agent_prompt_flag "$INTEGRATED_REVIEWER")"
  
  local generated_msg
  local -a cmd_parts
  read -r -a cmd_parts <<< "$cmd"
  
  set +e
  if [[ "$flag" = "__POSITIONAL__" ]]; then
    generated_msg="$("${cmd_parts[@]}" "$(cat "$prompt_file")")"
  else
    generated_msg="$("${cmd_parts[@]}" "$flag" "$(cat "$prompt_file")")"
  fi
  set -e
  
  # Remove markdown code blocks if the AI accidentally included them
  generated_msg="$(echo "$generated_msg" | sed 's/^```.*//g' | sed 's/```$//g' | awk 'NF {print} ')"
  
  if [[ -z "$generated_msg" ]]; then
    die "AI가 커밋 메시지 생성에 실패했습니다."
  fi
  
  echo "================================="
  echo -e "$generated_msg"
  echo "================================="
  
  if gum confirm "위 내용으로 커밋을 Amend 하시겠습니까?"; then
    git -C "$BASE_REPO" commit --amend -m "$generated_msg"
    log "커밋이 성공적으로 Amend 되었습니다."
    
    if gum confirm "원격 저장소에 강제 푸시(Force Push) 하시겠습니까?"; then
      git -C "$BASE_REPO" push origin "$current_branch" --force
      log "강제 푸시가 완료되었습니다."
    fi
  else
    log "커밋 Amend가 취소되었습니다."
  fi
}
