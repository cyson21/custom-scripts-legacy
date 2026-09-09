#!/usr/bin/env bash

# --- Input Helpers ---
arena_prompt_input() {
  local prompt="$1" default="${2:-}"
  if has_cmd gum; then
    gum input --prompt "$prompt" --value "$default"
  else
    read -r -p "$prompt" value
    if [[ -z "$value" ]]; then
      printf '%s\n' "$default"
    else
      printf '%s\n' "$value"
    fi
  fi
}

arena_pick_one() {
  local prompt="$1"
  shift
  local -a options=("$@")
  [[ "${#options[@]}" -gt 0 ]] || die "선택 가능한 옵션이 없습니다: $prompt"

  if has_cmd fzf; then
    printf '%s\n' "${options[@]}" | fzf --prompt="$prompt > " --height=40% --reverse
    return
  fi

  if has_cmd gum; then
    gum choose --header "$prompt" "${options[@]}"
    return
  fi

  local idx=1 opt
  for opt in "${options[@]}"; do
    echo "[$idx] $opt"
    idx=$((idx + 1))
  done
  read -r -p "$prompt 번호 선택: " n
  [[ "$n" =~ ^[0-9]+$ ]] || die "잘못된 선택입니다: $n"
  (( n >= 1 && n <= ${#options[@]} )) || die "잘못된 선택입니다: $n"
  printf '%s\n' "${options[$((n - 1))]}"
}

# --- Specific Pickers ---
arena_pick_agents_gui() {
  local -a options=("${AGENT_CATALOG[@]}")
  local selected=""
  if has_cmd fzf; then
    selected="$(printf '%s\n' "${options[@]}" | fzf --multi --prompt='에이전트 선택(1~3) > ' --height=50% --reverse || true)"
    [[ -n "$selected" ]] || die "에이전트를 하나 이상 선택해야 합니다"
    selected="$(printf '%s\n' "$selected" | paste -sd',' -)"
    normalize_agents_csv "$selected"
    return
  fi

  local input
  input="$(arena_prompt_input "에이전트 입력($(IFS=,; echo "${AGENT_CATALOG[*]}") 중 1~3개, 쉼표구분): " "$AGENTS")"
  normalize_agents_csv "$input"
}

arena_pick_branch_gui() {
  local -a branches=()
  local b
  while IFS= read -r b; do
    [[ -n "$b" ]] && branches+=("$b")
  done < <(git -C "$BASE_REPO" for-each-ref --format='%(refname:short)' refs/heads | sort)
  [[ "${#branches[@]}" -gt 0 ]] || die "선택 가능한 로컬 브랜치가 없습니다"

  local picked
  picked="$(arena_pick_one "기준 브랜치 선택" "${branches[@]}" "__직접입력__")"
  if [[ "$picked" = "__직접입력__" ]]; then
    picked="$(arena_prompt_input '기준 브랜치 입력: ' "$BASE_BRANCH")"
  fi
  printf '%s\n' "$picked"
}

arena_pick_task_file_gui() {
  local path
  path="$(arena_prompt_input '태스크 파일 경로 입력: ' "$TASK_FILE")"
  path="$(abs_path "$path")"
  [[ -f "$path" ]] || die "작업 파일을 찾을 수 없습니다: $path"
  printf '%s\n' "$path"
}

arena_pick_integrated_reviewer() {
  agents_csv_to_array "$AGENTS"
  arena_pick_one "최종 통합 리뷰 모델 선택" "${AGENT_ARRAY[@]}"
}

arena_pick_winner() {
  local -a choices=()
  local agent patch_file
  agents_csv_to_array "$AGENTS"
  for agent in "${AGENT_ARRAY[@]}"; do
    patch_file="$RUN_DIR/diff/${agent}_vs_base.patch"
    choices+=("$(printf '%s\t%s' "$agent" "$patch_file")")
  done

  if has_cmd fzf; then
    local preview_cmd
    if has_cmd bat; then
      preview_cmd='bat --color=always --style=plain {2}'
    else
      preview_cmd='sed -n "1,220p" {2}'
    fi

    local selected
    selected="$(printf '%s\n' "${choices[@]}" | 
      fzf --prompt='승자 선택 > ' --height=40% --reverse --delimiter=$'\t' --with-nth=1 
          --preview="$preview_cmd")"
    [[ -n "$selected" ]] || die "승자가 선택되지 않았습니다"
    printf '%s\n' "${selected%%$'\t'*}"
  else
    warn "fzf를 찾을 수 없어 번호 선택 메뉴로 전환합니다."
    local idx=1 choice
    for choice in "${choices[@]}"; do
      echo "[$idx] ${choice%%$'\t'*}"
      idx=$((idx + 1))
    done
    read -r -p "승자 번호를 선택하세요: " n
    [[ "$n" =~ ^[0-9]+$ ]] || die "잘못된 선택입니다: $n"
    (( n >= 1 && n <= ${#choices[@]} )) || die "잘못된 선택입니다: $n"
    choice="${choices[$((n - 1))]}"
    printf '%s\n' "${choice%%$'\t'*}"
  fi
}

arena_pick_run_id() {
  local index_dir="$HOME/.arena/runs"
  if [[ ! -d "$index_dir" ]]; then
    warn "런 인덱스 디렉터리를 찾을 수 없습니다: $index_dir"
    return 1
  fi

  local -a files=()
  local f
  while IFS= read -r f; do
    [[ -n "$f" ]] && files+=("$f")
  done < <(ls -1t "$index_dir"/*.env 2>/dev/null || true)

  local -a candidates=()
  local -a all_candidates=()
  local run_id repo branch init_time

  candidates+=("$(printf '%s\t%s\t%s\t%s\t%s' "__ADHOC__" "[현재 저장소]" "[현재 브랜치]" "[새 리뷰 세션 시작]" "")")
  all_candidates+=("$(printf '%s\t%s\t%s\t%s\t%s' "__ADHOC__" "[현재 저장소]" "[현재 브랜치]" "[새 리뷰 세션 시작]" "")")

  for f in "${files[@]}"; do
    run_id="$(basename "$f" .env)"
    repo="$(grep -m1 '^BASE_REPO=' "$f" | cut -d= -f2- | tr -d "'" || true)"
    branch="$(grep -m1 '^BASE_BRANCH=' "$f" | cut -d= -f2- | tr -d "'" || true)"
    init_time="$(grep -m1 '^INIT_TIME=' "$f" | cut -d= -f2- | tr -d "'" || true)"

    all_candidates+=("$(printf '%s\t%s\t%s\t%s\t%s' "$run_id" "$repo" "$branch" "$init_time" "$f")")

    if [[ -n "${BASE_REPO:-}" && -n "$repo" && "$repo" != "$BASE_REPO" ]]; then
      continue
    fi

    candidates+=("$(printf '%s\t%s\t%s\t%s\t%s' "$run_id" "$repo" "$branch" "$init_time" "$f")")
  done

  if [[ "${#candidates[@]}" -eq 1 ]]; then
    if [[ "${#all_candidates[@]}" -gt 1 ]]; then
      warn "BASE_REPO 필터와 일치하는 run이 없어 전체 run으로 전환합니다: ${BASE_REPO:-<none>}"
      candidates=("${all_candidates[@]}")
    fi
  fi

  if has_cmd fzf; then
    local selected
    selected="$(printf '%s\n' "${candidates[@]}" | 
      fzf --prompt='Select run_id > ' --height=50% --reverse --delimiter=$'\t' --with-nth=1,2,3,4 \
          --preview='if [[ "{1}" == "__ADHOC__" ]]; then echo "선택 시 현재 브랜치의 즉석(Adhoc) 리뷰 세션을 생성합니다."; else sed -n "1,120p" "{5}"; fi')"
    [[ -n "$selected" ]] || die "RUN_ID가 선택되지 않았습니다"
    printf '%s\n' "${selected%%$'\t'*}"
  else
    warn "fzf를 찾을 수 없어 번호 선택 메뉴로 전환합니다."
    local i=1 line
    for line in "${candidates[@]}"; do
      IFS=$'\t' read -r run_id repo branch init_time _ <<< "$line"
      if [[ "$run_id" == "__ADHOC__" ]]; then
        echo "[$i] [새로 시작] 현재 브랜치 즉석 리뷰 생성"
      else
        echo "[$i] $run_id | $repo | $branch | $init_time"
      fi
      i=$((i + 1))
    done
    read -r -p "RUN 번호를 선택하세요: " n
    [[ "$n" =~ ^[0-9]+$ ]] || die "잘못된 선택입니다: $n"
    (( n >= 1 && n <= ${#candidates[@]} )) || die "잘못된 선택입니다: $n"
    line="${candidates[$((n - 1))]}"
    printf '%s\n' "${line%%$'\t'*}"
  fi
}

# --- UI Mode & Dispatcher ---
arena_detect_ui_mode() {
  case "$ARENA_UI_MODE" in
    iterm2)
      can_use_iterm2 || die "ARENA_UI_MODE=iterm2 이지만 iTerm2를 사용할 수 없습니다"
      printf 'iterm2\n'
      ;;
    tmux)
      has_cmd tmux || die "ARENA_UI_MODE=tmux 이지만 tmux를 사용할 수 없습니다"
      printf 'tmux\n'
      ;;
    none)
      printf 'none\n'
      ;;
    auto)
      if can_use_iterm2; then
        printf 'iterm2\n'
      elif has_cmd tmux; then
        printf 'tmux\n'
      else
        printf 'none\n'
      fi
      ;;
    *) die "잘못된 ARENA_UI_MODE 값입니다: $ARENA_UI_MODE" ;;
  esac
}

arena_wait_confirm() {
  local msg="$1"
  if has_cmd gum; then
    gum confirm "$msg"
  else
    read -r -p "$msg [Enter] " _
  fi
}

iterm2_open_tab() {
  local cmd="$1"
  local escaped
  escaped="${cmd//\\/\\\\}"
  escaped="${escaped//\"/\\\"}"

  osascript <<EOF
tell application "iTerm2"
  activate
  if (count of windows) = 0 then
    create window with default profile
  end if
  tell current window
    create tab with default profile
    tell current session
      write text "$escaped"
    end tell
  end tell
end tell
EOF
}

tmux_open_window() {
  local session="$1" name="$2" cmd="$3"
  if tmux has-session -t "$session" 2>/dev/null; then
    tmux new-window -t "$session" -n "$name" "$cmd"
  else
    tmux new-session -d -s "$session" -n "$name" "$cmd"
  fi
}

build_bash_cmd_for_path() {
  local path="$1"
  printf 'bash %q' "$path"
}

# --- Shared UI Dispatcher (DRY Refactoring) ---
_dispatch_ui_tabs() {
  local ui_mode="$1"
  local -a script_paths=("${@:2}")
  [[ "${#script_paths[@]}" -gt 0 ]] || return 0

  case "$ui_mode" in
    iterm2)
      for path in "${script_paths[@]}"; do
        iterm2_open_tab "$(build_bash_cmd_for_path "$path")"
      done
      ;;
    tmux)
      local session="arena-${RUN_ID}"
      for path in "${script_paths[@]}"; do
        local name
        name="$(basename "$path" .sh)"
        tmux_open_window "$session" "$name" "$(build_bash_cmd_for_path "$path")"
      done
      log "tmux 세션에 창을 열었습니다: $session"
      ;;
    none)
      log "수동 실행 명령어:"
      for path in "${script_paths[@]}"; do
        printf "  bash '%s'\n" "$path"
      done
      ;;
    *) die "알 수 없는 UI 모드입니다: $ui_mode" ;;
  esac
}

open_review_ui() {
  local ui_mode="$1"
  local -a review_wrappers=()
  local wrapper
  while IFS= read -r wrapper; do
    [[ -n "$wrapper" ]] && review_wrappers+=("$wrapper")
  done < <(find "$RUN_DIR/scripts" -maxdepth 1 -type f -name 'review_*.sh' | sort)
  [[ "${#review_wrappers[@]}" -gt 0 ]] || die "리뷰 wrapper를 찾지 못했습니다: $RUN_DIR/scripts"

  _dispatch_ui_tabs "$ui_mode" "${review_wrappers[@]}"
}

open_assimilation_ui() {
  local ui_mode="$1" winner="$2"
  local wrapper="$RUN_DIR/scripts/assimilate_${winner}.sh"
  [[ -f "$wrapper" ]] || die "assimilation wrapper를 찾을 수 없습니다: $wrapper"

  _dispatch_ui_tabs "$ui_mode" "$wrapper"
}

open_integrated_review_ui() {
  local ui_mode="$1" reviewer="$2"
  local wrapper="$RUN_DIR/scripts/integrated_review_by_${reviewer}.sh"
  [[ -f "$wrapper" ]] || die "integrated review wrapper를 찾을 수 없습니다: $wrapper"

  _dispatch_ui_tabs "$ui_mode" "$wrapper"
}
