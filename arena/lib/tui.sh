#!/usr/bin/env bash

# --- TUI Helpers ---
LAST_ACTION_NAME=""
LAST_ACTION_ERROR=""

has_active_run_context() {
  if [[ -n "${RUN_ID:-}" ]] && sync_run_context >/dev/null 2>&1; then
    return 0
  fi

  local latest=""
  latest="$(latest_repo_run_id || true)"
  if [[ -n "$latest" ]]; then
    RUN_ID="$latest"
    sync_run_context >/dev/null 2>&1 || true
    return 0
  fi

  latest="$(ls -1t "$HOME/.arena/runs/"*.env 2>/dev/null | head -n 1 | xargs basename -s .env || true)"
  if [[ -n "$latest" ]]; then
    RUN_ID="$latest"
    sync_run_context >/dev/null 2>&1 || true
    return 0
  fi

  return 1
}

detect_tui_workflow_mode() {
  local run_dir=""
  run_dir="$(resolve_run_dir_quiet || true)"
  [[ -n "$run_dir" ]] || { printf '%s\n' "full"; return 0; }

  if [[ "${AGENTS:-}" == user,* || "${AGENTS:-}" == *",user,"* || "${AGENTS:-}" == *,user || "${AGENTS:-}" == "user" ]]; then
    printf '%s\n' "review"
  elif [[ "${RUN_ID:-}" == adhoc-* ]]; then
    printf '%s\n' "review"
  else
    printf '%s\n' "full"
  fi
}

workflow_status_code() {
  local mode="${1:-full}"
  local run_dir=""
  run_dir="$(resolve_run_dir_quiet || true)"

  if [[ -z "$run_dir" || ! -f "$run_dir/meta.env" ]]; then
    printf '%s\n' "new"
    return 0
  fi

  if [[ -f "$run_dir/cleanup/result.md" ]]; then
    printf '%s\n' "cleaned"
    return 0
  fi
  if [[ -f "$run_dir/handoff/result.md" ]]; then
    printf '%s\n' "handoff_done"
    return 0
  fi

  if [[ "$mode" = "review" ]]; then
    if [[ -f "$run_dir/summary/integrated_review.md" ]]; then
      printf '%s\n' "integrated_ready"
      return 0
    fi
    if find "$run_dir/reviews" -type f 2>/dev/null | grep -q .; then
      printf '%s\n' "reviews_ready"
      return 0
    fi
    if find "$run_dir/prompts" -type f 2>/dev/null | grep -q .; then
      printf '%s\n' "review_pack_ready"
      return 0
    fi
    printf '%s\n' "new"
    return 0
  fi

  if [[ -f "$run_dir/summary/comparison.md" ]]; then
    printf '%s\n' "review_ready"
    return 0
  fi
  if compgen -G "$run_dir/commits/*.sha" >/dev/null 2>&1; then
    printf '%s\n' "collect_ready"
    return 0
  fi
  if [[ -f "$run_dir/meta.env" ]]; then
    printf '%s\n' "init_done"
    return 0
  fi
  printf '%s\n' "new"
}

workflow_next_action() {
  local mode="${1:-full}"
  local state
  state="$(workflow_status_code "$mode")"
  case "$mode:$state" in
    full:new) printf '%s\n' "Init/Start" ;;
    full:init_done) printf '%s\n' "Launch 또는 Collect" ;;
    full:collect_ready) printf '%s\n' "Review" ;;
    full:review_ready) printf '%s\n' "Finish" ;;
    full:handoff_done) printf '%s\n' "Cleanup" ;;
    full:cleaned) printf '%s\n' "새 RUN 시작" ;;
    review:new) printf '%s\n' "Review-Pack" ;;
    review:review_pack_ready) printf '%s\n' "Open Review UI" ;;
    review:reviews_ready) printf '%s\n' "Integrated Review 확인" ;;
    review:integrated_ready) printf '%s\n' "Finish 또는 Apply Feedback" ;;
    review:handoff_done) printf '%s\n' "Cleanup" ;;
    review:cleaned) printf '%s\n' "다른 RUN 선택" ;;
    *) printf '%s\n' "Status" ;;
  esac
}

show_recovery_actions() {
  local failed_action="$1"
  local mode="${2:-full}"
  local suggestion1="Status 확인"
  local suggestion2="돌아가기"
  local suggestion3="RUN 변경"

  case "$mode:$failed_action" in
    full:Launch)
      suggestion1="Init/Start"
      suggestion2="Status 확인"
      ;;
    full:Review)
      suggestion1="Collect"
      suggestion2="Status 확인"
      ;;
    full:Finish)
      suggestion1="Review"
      suggestion2="Status 확인"
      ;;
    full:Cleanup)
      suggestion1="Status 확인"
      suggestion2="돌아가기"
      ;;
    review:Review-Pack)
      suggestion1="Status 확인"
      suggestion2="RUN 변경"
      ;;
    review:Open\ Review\ UI)
      suggestion1="Review-Pack"
      suggestion2="Status 확인"
      ;;
    review:Integrated\ Review\ 확인)
      suggestion1="Open Review UI"
      suggestion2="Status 확인"
      ;;
    review:Finish)
      suggestion1="Integrated Review 확인"
      suggestion2="Status 확인"
      ;;
  esac

  local picked
  picked="$(gum choose "$suggestion1" "$suggestion2" "$suggestion3")"
  printf '%s\n' "$picked"
}

show_loop_footer() {
  local mode="${1:-full}"
  local run_dir winner cleanup_state agents reviewer next_action state
  run_dir="$(resolve_run_dir_quiet || true)"
  winner="(미선택)"
  cleanup_state="미실행"
  agents="${DISPLAY_AGENTS:-${AGENTS:-"(알 수 없음)"}}"
  reviewer="${INTEGRATED_REVIEWER:-"(미선택)"}"
  state="$(workflow_status_code "$mode")"
  next_action="$(workflow_next_action "$mode")"
  
  # --- Live Dashboard (Git Status) ---
  local git_status=""
  if [[ -n "$BASE_REPO" && -d "$BASE_REPO/.git" ]]; then
    local dirty_count; dirty_count="$(git -C "$BASE_REPO" status --porcelain | wc -l | tr -d ' ')"
    local current_branch; current_branch="$(git -C "$BASE_REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")"
    if [[ "$dirty_count" -gt 0 ]]; then
      git_status="변경됨 ($dirty_count files) on $current_branch"
    else
      git_status="Clean on $current_branch"
    fi
  else
    git_status="알 수 없음"
  fi

  if [[ -n "$run_dir" ]]; then
    if [[ -f "$run_dir/meta.env" ]]; then
      # sync_run_context sets DISPLAY_AGENTS and INTEGRATED_REVIEWER
      # but let's grab them as fallback if empty
      [[ -z "$DISPLAY_AGENTS" ]] && agents="$(grep -m1 '^AGENTS=' "$run_dir/meta.env" | cut -d= -f2- | tr -d "'" | sed 's/user,//g' | sed 's/,user//g' || true)"
      [[ -z "$INTEGRATED_REVIEWER" ]] && reviewer="$(grep -m1 '^INTEGRATED_REVIEWER=' "$run_dir/meta.env" | cut -d= -f2- | tr -d "'" || true)"
      [[ -n "$reviewer" ]] || reviewer="(미선택)"
    fi
    if [[ -f "$run_dir/handoff/result.md" ]]; then
      winner="$(grep -m1 '^- Winner:' "$run_dir/handoff/result.md" | sed 's/^- Winner:[[:space:]]*//' || true)"
      [[ -n "$winner" ]] || winner="(알 수 없음)"
    fi
    [[ -f "$run_dir/cleanup/result.md" ]] && cleanup_state="완료"
  fi

  echo
  echo "----------------------------------------"
  echo "RUN_ID: ${RUN_ID:-"(미선택)"}"
  echo "에이전트: ${agents:-"(알 수 없음)"}"
  echo "통합 리뷰어: ${reviewer:-"(미선택)"}"
  echo "승자: $winner | 정리 상태: $cleanup_state"
  echo "현재 저장소 상태: $git_status"
  echo "현재 단계: $state"
  echo "권장 다음 단계: $next_action"
  if [[ -n "$LAST_ACTION_ERROR" ]]; then
    echo "최근 실패: ${LAST_ACTION_NAME:-unknown} -> $LAST_ACTION_ERROR"
  fi
  echo "----------------------------------------"
}

pick_run_id_safe() {
  local picked rc
  set +e
  picked="$(arena_pick_run_id)"
  rc=$?
  set -e
  if [[ "$rc" -ne 0 || -z "$picked" ]]; then
    warn "RUN 선택에 실패했습니다"
    return 1
  fi
  
  if [[ "$picked" == "__ADHOC__" ]]; then
    run_action_safe cmd_adhoc_init
    sync_run_context || true
    return 0
  fi

  RUN_ID="$picked"
  sync_run_context || true
}

run_action_safe() {
  LAST_ACTION_NAME="$1"
  LAST_ACTION_ERROR=""
  set +e
  local output
  output="$("$@" 2>&1)"
  local rc=$?
  set -e
  if [[ "$rc" -ne 0 ]]; then
    LAST_ACTION_ERROR="$(printf '%s' "$output" | tail -n 1)"
    [[ -n "$LAST_ACTION_ERROR" ]] || LAST_ACTION_ERROR="실행 실패 (exit=$rc)"
    warn "$LAST_ACTION_ERROR"
  elif [[ -n "$output" ]]; then
    printf '%s\n' "$output"
  fi
  return "$rc"
}

show_entry_mode_menu() {
  has_cmd gum || die "TUI 실행에는 'gum'이 필요합니다. (brew install gum)"
  local -a options=()
  if has_active_run_context; then
    sync_run_context || true
    local detected_mode
    detected_mode="$(detect_tui_workflow_mode)"
    options+=("이어서 진행 (${RUN_ID} / $(workflow_next_action "$detected_mode"))")
  fi
  options+=("전체 루프 (AI 코딩 + 리뷰)" "리뷰 전용 (현재 코드 리뷰받기)" "히스토리 관리 (기록 삭제)")
  gum choose "${options[@]}"
}

run_history_management_loop() {
  has_cmd gum || die "TUI 실행에는 'gum'이 필요합니다. (brew install gum)"
  while true; do
    clear
    echo "========================================"
    echo "       Arena 히스토리 관리 메뉴"
    echo "========================================"
    
    local choice
    choice="$(gum choose "특정 기록 삭제 (수동 선택)" "오래된 기록 일괄 삭제 (기본 7일)" "메인 메뉴로 돌아가기")"
    
    case "$choice" in
      "특정 기록 삭제 (수동 선택)")
        local picked rc
        set +e
        picked="$(arena_pick_run_id)"
        rc=$?
        set -e
        if [[ "$rc" -eq 0 && -n "$picked" && "$picked" != "__ADHOC__" ]]; then
          if gum confirm "정말로 [$picked] 기록을 영구 삭제하시겠습니까?"; then
            run_action_safe cmd_cleanup --run-id "$picked" --force --delete-history
            gum input --prompt "삭제가 완료되었습니다. 아무 키나 누르세요..." --placeholder "Enter to continue" >/dev/null || true
          fi
        fi
        ;;
      "오래된 기록 일괄 삭제 (기본 7일)")
        local days
        days="$(gum input --prompt "며칠 이상 경과된 기록을 삭제할까요? (기본값: 7): " --value "7")"
        if [[ "$days" =~ ^[0-9]+$ ]]; then
          if gum confirm "${days}일 이상된 모든 기록을 영구 삭제하시겠습니까?"; then
            run_action_safe cmd_cleanup_old --retention-days "$days" --apply
            gum input --prompt "일괄 삭제가 완료되었습니다. 아무 키나 누르세요..." --placeholder "Enter to continue" >/dev/null || true
          fi
        else
          warn "숫자만 입력 가능합니다."
          sleep 1
        fi
        ;;
      "메인 메뉴로 돌아가기") return 10 ;;
    esac
  done
}

run_full_workflow_loop() {
  has_cmd gum || die "TUI 실행에는 'gum'이 필요합니다. (brew install gum)"
  while true; do
    sync_run_context || true
    show_loop_footer "full"
    local choice
    local state launch_label collect_label review_label finish_label cleanup_label
    state="$(workflow_status_code "full")"
    launch_label="Launch"
    collect_label="Collect"
    review_label="Review"
    finish_label="Finish"
    cleanup_label="Cleanup"
    [[ "$state" = "new" ]] && launch_label="[잠김] Launch (먼저 Init/Start)"
    [[ "$state" = "new" ]] && collect_label="[잠김] Collect (먼저 Init/Start)"
    [[ "$state" = "new" || "$state" = "init_done" ]] && review_label="[잠김] Review (먼저 Collect)"
    [[ "$state" = "new" || "$state" = "init_done" || "$state" = "collect_ready" ]] && finish_label="[잠김] Finish (먼저 Review)"
    [[ "$state" = "new" ]] && cleanup_label="[잠김] Cleanup (대상 RUN 없음)"
    choice="$(gum choose "Init/Start" "$launch_label" "$collect_label" "$review_label" "$finish_label" "$cleanup_label" "Status" "모드 전환" "종료")"

    case "$choice" in
      "Init/Start")
        if run_action_safe cmd_start; then
          # cmd_start sets RUN_ID, now it persists because we removed subshell
          sync_run_context || true
        else
          local recovery
          recovery="$(show_recovery_actions "Init/Start" "full")"
          [[ "$recovery" = "Status 확인" ]] && run_action_safe cmd_status --summary || true
        fi
        ;;
      "[잠김] Launch (먼저 Init/Start)")
        warn "Launch는 Init/Start 후에 사용할 수 있습니다."
        ;;
      "Launch")
        if [[ -z "$RUN_ID" ]]; then pick_run_id_safe || continue; fi
        if ! run_action_safe cmd_launch --run-id "$RUN_ID"; then
          local recovery
          recovery="$(show_recovery_actions "Launch" "full")"
          case "$recovery" in
            "Init/Start") run_action_safe cmd_start ;;
            "Status 확인") run_action_safe cmd_status --run-id "$RUN_ID" --summary || true ;;
            "RUN 변경") pick_run_id_safe || true ;;
          esac
        fi
        ;;
      "[잠김] Collect (먼저 Init/Start)")
        warn "Collect는 Init/Start 후에 사용할 수 있습니다."
        ;;
      "Collect")
        if [[ -z "$RUN_ID" ]]; then pick_run_id_safe || continue; fi
        if ! run_action_safe cmd_collect --run-id "$RUN_ID"; then
          local recovery
          recovery="$(show_recovery_actions "Collect" "full")"
          case "$recovery" in
            "Status 확인") run_action_safe cmd_status --run-id "$RUN_ID" --summary || true ;;
            "RUN 변경") pick_run_id_safe || true ;;
          esac
        fi
        ;;
      "[잠김] Review (먼저 Collect)")
        warn "Review는 Collect 후에 사용할 수 있습니다."
        ;;
      "Review")
        if [[ -z "$RUN_ID" ]]; then pick_run_id_safe || continue; fi
        if ! run_action_safe cmd_review --run-id "$RUN_ID"; then
          local recovery
          recovery="$(show_recovery_actions "Review" "full")"
          case "$recovery" in
            "Collect") run_action_safe cmd_collect --run-id "$RUN_ID" ;;
            "Status 확인") run_action_safe cmd_status --run-id "$RUN_ID" --summary || true ;;
            "RUN 변경") pick_run_id_safe || true ;;
          esac
        fi
        ;;
      "[잠김] Finish (먼저 Review)")
        warn "Finish는 Review 후에 사용할 수 있습니다."
        ;;
      "Finish")
        if [[ -z "$RUN_ID" ]]; then pick_run_id_safe || continue; fi
        if ! run_action_safe cmd_finish --run-id "$RUN_ID"; then
          local recovery
          recovery="$(show_recovery_actions "Finish" "full")"
          case "$recovery" in
            "Review") run_action_safe cmd_review --run-id "$RUN_ID" ;;
            "Status 확인") run_action_safe cmd_status --run-id "$RUN_ID" --summary || true ;;
            "RUN 변경") pick_run_id_safe || true ;;
          esac
        fi
        sync_run_context || true
        ;;
      "[잠김] Cleanup (대상 RUN 없음)")
        warn "Cleanup 대상 RUN이 없습니다."
        ;;
      "Cleanup")
        if [[ -z "$RUN_ID" ]]; then pick_run_id_safe || continue; fi
        if ! run_action_safe cmd_cleanup --run-id "$RUN_ID"; then
          local recovery
          recovery="$(show_recovery_actions "Cleanup" "full")"
          case "$recovery" in
            "Status 확인") run_action_safe cmd_status --run-id "$RUN_ID" --summary || true ;;
            "RUN 변경") pick_run_id_safe || true ;;
          esac
        fi
        ;;
      "Status")
        if [[ -z "$RUN_ID" ]]; then
          run_action_safe cmd_status --summary || warn "Status 단계가 실패했습니다."
        else
          run_action_safe cmd_status --run-id "$RUN_ID" --summary || warn "Status 단계가 실패했습니다."
        fi
        ;;
      "모드 전환") return 10 ;;
      "종료") return 0 ;;
    esac
  done
}

run_review_workflow_loop() {
  has_cmd gum || die "TUI 실행에는 'gum'이 필요합니다. (brew install gum)"
  if [[ -z "$RUN_ID" ]]; then
    if ! pick_run_id_safe; then
      # pick_run_id_safe might trigger cmd_adhoc_init which sets RUN_ID
      return 10
    fi
  fi

  while true; do
    sync_run_context || true
    clear
    show_loop_footer "review"
    
    # 가이드형 메뉴 구성
    local -a menu_options=()
    local state
    state="$(workflow_status_code "review")"
    
    # 상태에 따른 추천 단계 결정
    if [[ "$state" = "new" ]]; then
      menu_options=("1단계: [Review-Pack] 리뷰 준비 (파일 분석 및 프롬프트 생성)" "Status 확인" "RUN 변경" "Cleanup" "종료")
    elif [[ "$state" = "review_pack_ready" ]]; then
      menu_options=("2단계: [Open Review UI] AI 리뷰 시작 (자동 모니터링)" "1단계 다시 수행 (Review-Pack)" "Status 확인" "RUN 변경" "Cleanup" "종료")
    elif [[ "$state" = "reviews_ready" ]]; then
      menu_options=("3단계: [Integrated Review] 최종 종합 결과 확인" "2단계 다시 수행 (Open Review UI)" "Status 확인" "RUN 변경" "Cleanup" "종료")
    elif [[ "$state" = "integrated_ready" ]] && [[ -z "$(git -C "$BASE_REPO" log -1 --pretty=%B | grep -v 'chore(arena): auto-commit')" ]]; then
      # If the last commit is still the auto-commit, suggest auto-apply and amending
      menu_options=("4단계: [Auto-Apply] 리뷰 피드백 내 코드에 자동 적용하기" "5단계: [Amend & Force Push] 임시 커밋 병합(Squash) 및 메시지 자동 작성" "3단계 리포트 다시 보기" "Status 확인" "RUN 변경" "Cleanup" "종료")
    else
      menu_options=("6단계: [Finish] 결과 저장 및 리포트 생성 (종료)" "5단계 다시 수행 (Amend & Force Push)" "Status 확인" "RUN 변경" "Cleanup" "종료")
    fi

    local picked_menu
    picked_menu="$(gum choose "${menu_options[@]}")"

    case "$picked_menu" in
      *"1단계"*)
        if ! run_action_safe cmd_review_only --run-id "$RUN_ID"; then
          local recovery
          recovery="$(show_recovery_actions "Review-Pack" "review")"
          [[ "$recovery" = "RUN 변경" ]] && pick_run_id_safe || true
        fi
        ;;
      *"2단계"*)
        if ! run_action_safe cmd_open_review_ui --run-id "$RUN_ID"; then
          local recovery
          recovery="$(show_recovery_actions "Open Review UI" "review")"
          case "$recovery" in
            "Review-Pack") run_action_safe cmd_review_only --run-id "$RUN_ID" ;;
            "Status 확인") run_action_safe cmd_status --run-id "$RUN_ID" --summary || true ;;
            "RUN 변경") pick_run_id_safe || true ;;
          esac
        fi
        ;;
      *"3단계"*|*"3단계 리포트"*)
        if ! run_action_safe cmd_check_integrated_review --run-id "$RUN_ID"; then
          local recovery
          recovery="$(show_recovery_actions "Integrated Review 확인" "review")"
          case "$recovery" in
            "Open Review UI") run_action_safe cmd_open_review_ui --run-id "$RUN_ID" ;;
            "Status 확인") run_action_safe cmd_status --run-id "$RUN_ID" --summary || true ;;
            "RUN 변경") pick_run_id_safe || true ;;
          esac
        fi
        ;;
      *"4단계"*) run_action_safe cmd_apply_feedback --run-id "$RUN_ID" || true ;;
      *"5단계"*) run_action_safe cmd_amend_commit --run-id "$RUN_ID" || true ;;
      *"6단계"*)
        if ! run_action_safe cmd_finish --run-id "$RUN_ID" --no-cleanup; then
          local recovery
          recovery="$(show_recovery_actions "Finish" "review")"
          case "$recovery" in
            "Integrated Review 확인") run_action_safe cmd_check_integrated_review --run-id "$RUN_ID" ;;
            "Status 확인") run_action_safe cmd_status --run-id "$RUN_ID" --summary || true ;;
            "RUN 변경") pick_run_id_safe || true ;;
          esac
        fi
        sync_run_context || true
        ;;
      "Status 확인") run_action_safe cmd_status --run-id "$RUN_ID" --summary ;;
      "RUN 변경") pick_run_id_safe || true ;;
      "Cleanup") run_action_safe cmd_cleanup --run-id "$RUN_ID" ;;
      "종료") return 0 ;;
    esac
  done
}

run_tui_mode() {
  local mode rc
  while true; do
    mode="$(show_entry_mode_menu)"
    case "$mode" in
      "이어서 진행 ("*)
        if [[ "$(detect_tui_workflow_mode)" = "review" ]]; then
          set +e; run_review_workflow_loop; rc=$?; set -e
        else
          set +e; run_full_workflow_loop; rc=$?; set -e
        fi
        [[ "$rc" -eq 10 ]] && continue
        return 0
        ;;
      "전체 루프 (AI 코딩 + 리뷰)")
        set +e; run_full_workflow_loop; rc=$?; set -e
        [[ "$rc" -eq 10 ]] && continue
        return 0
        ;;
      "리뷰 전용 (현재 코드 리뷰받기)")
        set +e; run_review_workflow_loop; rc=$?; set -e
        [[ "$rc" -eq 10 ]] && continue
        return 0
        ;;
      "히스토리 관리 (기록 삭제)")
        set +e; run_history_management_loop; rc=$?; set -e
        [[ "$rc" -eq 10 ]] && continue
        return 0
        ;;
      *) die "알 수 없는 시작 모드입니다: $mode" ;;
    esac
  done
}
