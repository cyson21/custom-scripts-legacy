#!/usr/bin/env bash

# --- Report Helpers ---
render_report_pre() {
  local title="$1" file="$2" max_lines="${3:-120}"
  printf '<h3>%s</h3>\n' "$title"
  if [[ -f "$file" ]]; then
    printf '<pre>'
    head -n "$max_lines" "$file" | html_escape_stream
    printf '</pre>\n'
  else
    printf '<pre>(없음)</pre>\n'
  fi
}

generate_integrated_report() {
  ensure_run_layout
  local report_file="$RUN_DIR/summary/report.html"
  local winner="(미선택)" cleanup_state="미실행"
  local now
  now="$(current_ts)"

  if [[ -f "$RUN_DIR/handoff/result.md" ]]; then
    winner="$(grep -m1 '^- Winner:' "$RUN_DIR/handoff/result.md" | sed 's/^- Winner:[[:space:]]*//' || true)"
    [[ -n "$winner" ]] || winner="(알 수 없음)"
  fi
  [[ -f "$RUN_DIR/cleanup/result.md" ]] && cleanup_state="완료"

  {
    cat <<EOF
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Arena Report - ${RUN_ID}</title>
  <style>
    :root { --bg:#f4f5f7; --panel:#ffffff; --ink:#17202a; --muted:#5d6d7e; --line:#d5d8dc; }
    body { margin:0; padding:24px; background:var(--bg); color:var(--ink); font-family:"Pretendard","Apple SD Gothic Neo","Noto Sans KR",sans-serif; }
    .panel { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:16px; margin-bottom:16px; }
    h1,h2,h3 { margin:0 0 10px 0; }
    ul { margin:8px 0 0 20px; }
    pre { background:#111827; color:#e5e7eb; padding:12px; border-radius:8px; overflow:auto; white-space:pre-wrap; word-break:break-word; }
    .muted { color:var(--muted); }
  </style>
</head>
<body>
  <div class="panel">
    <h1>Arena Integrated Report</h1>
    <p class="muted">생성 시각: ${now}</p>
    <ul>
      <li>RUN_ID: ${RUN_ID}</li>
      <li>기준 저장소: ${BASE_REPO}</li>
      <li>기준 브랜치: ${BASE_BRANCH}</li>
      <li>작업 파일: ${TASK_FILE}</li>
      <li>에이전트: ${AGENTS}</li>
      <li>통합 리뷰 모델: ${INTEGRATED_REVIEWER:-"(미선택)"}</li>
      <li>승자: ${winner}</li>
      <li>정리 상태: ${cleanup_state}</li>
    </ul>
  </div>
  <div class="panel">
    <h2>Summary</h2>
EOF

    render_report_pre "비교 요약" "$RUN_DIR/summary/comparison.md" 200
    render_report_pre "통합 리뷰" "$RUN_DIR/summary/integrated_review.md" 250
    echo "</div>"

    agents_csv_to_array "$AGENTS"
    local agent
    for agent in "${AGENT_ARRAY[@]}"; do
      local review_count test_exit
      review_count="$(find "$RUN_DIR/prompts" -maxdepth 1 -type f -name "review_${agent}_on_*.md" 2>/dev/null | wc -l | tr -d ' ')"
      test_exit="$(cat "$RUN_DIR/tests/${agent}.exit_code" 2>/dev/null || echo "미실행")"
      cat <<EOF
  <div class="panel">
    <h2>Agent: ${agent}</h2>
    <ul>
      <li>리뷰 프롬프트 수: ${review_count}</li>
      <li>테스트 결과 코드: ${test_exit}</li>
    </ul>
EOF
      render_report_pre "${agent} shortstat" "$RUN_DIR/summary/${agent}_shortstat.txt" 60
      render_report_pre "${agent} branch commits" "$RUN_DIR/summary/${agent}_branch_commits.txt" 120
      render_report_pre "${agent} tests" "$RUN_DIR/tests/${agent}.log" 180
      printf '<h3>%s patch file</h3>\n<pre>%s</pre>\n' "$agent" "$(cat "$RUN_DIR/diff/${agent}_vs_base.patch" | html_escape_stream)"
      echo "  </div>"
    done

    cat <<'EOF'
</body>
</html>
EOF
  } > "$report_file"

  printf '%s\n' "$report_file"
}
