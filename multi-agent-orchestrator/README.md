# Multi-Agent Orchestrator v5

자율 실행·자기 복구 멀티 에이전트 스웜 오케스트레이터.
Gemini CLI · Codex CLI · Claude CLI 세 엔진을 병렬로 구동하고, 합의·심판·합성 파이프라인을 통해 단일 고품질 패치를 도출한다.

> 운영 규칙과 인수인계 절차의 정본은 [`AGENTS.md`](AGENTS.md) 이다.

---

## 아키텍처 개요

```
main.py
  └─ SovereignWorkstationApp (Textual TUI)
       └─ run_swarm_logic()          ← 핵심 오케스트레이션 루프
            ├─ CodeIndexer           ← 코드베이스 인덱스 / AST-Grep
            ├─ SandboxManager        ← Git Worktree 격리 샌드박스
            ├─ HookManager           ← before/after 훅 파이프라인
            ├─ SisyphusAgent × N      ← 에이전트별 자기 복구 루프
            ├─ SynthesisEngine       ← LLM 기반 Diff 통합
            ├─ DiffCollector         ← 3단계 Diff 적용 (git apply → patch → rollback)
            └─ create_post_mortem_report()
```

### 4대 핵심 기둥

| 기둥 | 모듈 | 설명 |
|------|------|------|
| Sisyphus Loop | `orchestrator/sisyphus.py` | 에이전트별 재시도 루프. stagnation 감지·토큰 예산·지수 백오프 포함 |
| Git Worktree Sandbox | `orchestrator/sandbox.py` | 에이전트마다 독립 워크트리. 충돌 없는 병렬 편집 보장 |
| Hashline 편집 검증 | `orchestrator/hashline.py` | CRC32 기반 라인 ID로 환각 편집 차단. 미스매치 시 즉시 실패 |
| AST-Grep 구조 검색 | `orchestrator/ast_grep.py` | 정규식 초월 문법 트리 탐색. 실패 시 Smart Fallback Hint 제공 |

---

## 디렉토리 구조

```
multi-agent-orchestrator/
├── main.py                        # 진입점 (Textual TUI 실행)
├── todo.json                      # 미완료 태스크 목록 (스키마 검증 필수)
├── todo.schema.json               # todo.json JSON Schema (draft-07)
├── scripts/manage_todo.py         # todo.validation.json 갱신 표준 스크립트
├── scripts/validate_todo.py       # 호환용 래퍼
│
├── orchestrator/
│   ├── core/                      # 핵심 파이프라인 (hooks, models, context 등)
│   ├── agents/                    # SisyphusAgent, swarm, adapters 등 구동 및 I/O
│   ├── tools/                     # AST-Grep, 샌드박스, 파일 입출력 훅 등 기능 도구
│   └── tui/                       # Textual 기반 UI 화면 및 컨트롤러
│
├── scripts/                       # 유틸리티 및 오프라인 테스트 스크립트
├── configs/agents/                # 셸 스크립트 기반 커스텀 에이전트 설정
├── tests/                         # 단위 · 통합 테스트
└── artifacts/                     # 실행 결과물 (trace.json, final_report.md 등)
```

---

## 실행

```bash
# TUI 실행 (기본)
python main.py

# 의존성 설치 (최초 1회)
pip install textual jsonschema

# todo.validation.json 갱신 및 검증
python scripts/manage_todo.py

# 기존 검증 명령 호환
python scripts/validate_todo.py
```

### 에이전트 엔진 사전 요건

| 엔진 | 설치 명령 |
|------|-----------|
| Gemini CLI | `npm install -g @google/gemini-cli` |
| Codex CLI | Codex CLI 공식 설치 가이드 참조 |
| Claude CLI | `npm install -g @anthropic-ai/claude-cli` (또는 brew) |

---

## 아티팩트 구조

실행마다 `artifacts/YYYYMMDD-HHMMSS/` 디렉토리가 생성된다.

```
artifacts/20260315-120000/
├── execution_trace.md   # 전체 실행 흐름 로그
├── trace.json           # 구조화된 trace 데이터
├── final_report.md      # 사후 분석 보고서
├── synthesis_raw_*.txt  # SynthesisEngine 원본 응답
└── sisyphus_attempt_*.txt  # 에이전트별 시도 기록
```

---

## 유지보수 — 3-엔진 로테이션 모델

이 프로젝트는 **Gemini · Claude · Codex** 가 세션 단위로 교대하며 유지보수한다.
세부 인수인계 절차와 `todo.json` 상태 전이 규칙은 [`AGENTS.md`](AGENTS.md) 를 참조한다.

```
[Gemini 세션] → todo.json 업데이트 → [Claude 세션] → todo.json 업데이트 → [Codex 세션] → ...
```

---

## 문서 안내

- 운영 규칙: [`AGENTS.md`](AGENTS.md)
- 유지보수/인수인계/보안 포함 통합 규칙: [`AGENTS.md`](AGENTS.md)

---

## 개발 히스토리

v1(CLI pipe) → v2(workflow 분리) → v3~4(자동화 돌파) → v5(Swarm + TUI).
