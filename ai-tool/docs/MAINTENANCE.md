# AI-Tool — 유지보수 워크플로우

> **이 프로젝트는 Gemini · Claude · Codex 세 AI 엔진이 세션 단위로 교대하며 유지보수한다.**
> 각 엔진은 이전 엔진이 남긴 `todo.json` 을 인계받아 작업을 이어가고,
> 완료 후 `completed_by` 에 자신의 이름을 기록하여 다음 엔진에 넘긴다.
> 인간 개발자 승인 없이 코드를 커밋·푸시·실행하지 않는다.
> 모든 변경은 **계획 제안 → 승인 → 실행** 순서를 따른다.

---

## 1. 시작 전 필수 확인

```
1. git status                — 미커밋 변경사항 확인
2. git branch                — 현재 브랜치 확인 (작업은 feature/* 브랜치에서)
3. python validate_todo.py   — todo.json 스키마·규칙 통과 여부 확인
4. docs/MAINTENANCE.md       — 현재 아키텍처·불변 조건 재확인 (이 파일)
```

작업 전 `todo.json`의 `global_state.current_task_id` 를 확인해 어떤 태스크가 활성화 중인지 파악한다.

---

## 2. 프로젝트 핵심 검수/검증/리뷰 (QA) 규칙

아래 조건이 깨지면 시스템이 무음 실패하거나 데이터가 손상된다. **수정 전후 이 목록을 반드시 검토한다.**

| # | 불변 조건 | 근거 모듈 |
|---|-----------|-----------|
| I-1 | `todo.json` 변경 후 `python validate_todo.py` 를 통과해야만 유효한 상태다 | `validate_todo.py` |
| I-2 | `assigned_to` / `completed_by` 값은 반드시 `allowed_agents` 배열 내 항목이어야 한다 | `todo.schema.json` |
| I-3 | 정적 분석 통과: `flake8 ai_tool.py --extend-ignore=E501,E266,E731,W503,E704,E241,W504` 실행 시 에러 0건이어야 한다. | `AGENTS.md` |
| I-4 | TUI 단위 테스트 통과: `pytest tests/test_tui_headless.py` 실행 시 100% Pass해야 한다. | `AGENTS.md` |
| I-5 | TUI 터미널 독점 실행 금지: 에이전트는 `python ai_tool.py`를 직접 백그라운드로 실행해선 안 된다. | `AGENTS.md` |

---

## 3. 테스트 및 정적 검사 실행 가이드

> **주의**: 에이전트는 TUI 애플리케이션을 직접 실행하지 않는다. 아래 명령은 사용자가 실행하거나, 에이전트가 `run_shell_command`를 통해 검증용으로만 실행한다.

```bash
# 1. 정적 검사 (문법, 임포트, 코딩 스타일 등)
cd ~/ai-tool
flake8 ai_tool.py --extend-ignore=E501,E266,E731,W503,E704,E241,W504

# 2. TUI 헤드리스 QA (모든 버튼 및 상호작용 지점 자동 검수)
export PYTHONPATH=. 
pytest tests/test_tui_headless.py
```

---

## 4. 커밋 규칙

```
Feat: 새 기능 추가
Fix: 버그 수정
Refactor: 동작 변경 없는 코드 개선
Docs: 문서만 변경
Test: 테스트만 변경
Chore: 빌드·의존성·설정 변경
```

형식: `Prefix: 요약` (50자 이내, 한국어)
브랜치: `feature/*`, `fix/*`, `refactor/*`, `docs/*`, `chore/*`
