# 전체 기능 100% 검수 기능 매트릭스 (Headless QA Matrix)

이 문서는 `multi-agent-orchestrator`의 모든 핵심 기능을 헤드리스 환경에서 100% 검증하기 위한 테스트 매트릭스를 정의합니다.

## 1. 미션 수립 및 오케스트레이션 (Orchestration)

| ID | 기능 | 테스트 시나리오 | 검증 방법 |
| :--- | :--- | :--- | :--- |
| ORCH-01 | 청사진(Blueprint) 생성 | 미션 입력 시 Architect 에이전트가 `mission_plan.md`를 생성하는지 확인 | 파일 존재 및 내용 비어있지 않음 |
| ORCH-02 | Parallel 모드 실행 | 다수의 에이전트가 동시에 독립적으로 작업을 수행하고 결과가 수집되는지 확인 | `parallel_{round}_{persona}.md` 파일들 생성 확인 |
| ORCH-03 | Relay (Discussion) 모드 실행 | 에이전트들이 순차적으로 앞선 에이전트의 컨텍스트를 이어받아 실행되는지 확인 | `discussion_{round}_{persona}.md` 파일들 생성 및 컨텍스트 전달 여부 |
| ORCH-04 | 루프 탈출 (APPROVE) | Judge 에이전트가 'APPROVE'를 반환할 때 미션이 성공으로 종료되는지 확인 | `_SUCCESS.log` 생성 및 status=SUCCESS |
| ORCH-05 | 최대 라운드 제한 (Max Rounds) | Judge가 승인하지 않더라도 `max_rounds` 도달 시 루프가 종료되는지 확인 | 루프 횟수 확인 및 status=FAILURE (또는 PARTIAL) |
| ORCH-06 | 긴급 중단 (Emergency Stop) | 실행 중 `emergency_stop` 시그널 발생 시 즉시 중단되는지 확인 | 예외 발생 및 `_FAILURE.log` (또는 중단 로그) 확인 |

## 2. 에이전트 및 어댑터 (Agents & Adapters)

| ID | 기능 | 테스트 시나리오 | 검증 방법 |
| :--- | :--- | :--- | :--- |
| AGENT-01 | 다중 에이전트 조합 | Gemini + Claude + Codex 조합으로 미션 수행 시 각 어댑터가 정상 호출되는지 확인 | 각 어댑터의 `ask` 메서드 호출 횟수 및 인자 검증 |
| AGENT-02 | 에이전트 Fallback | 특정 모델 호출 실패 시 (예: 429) Fallback 모델로 전환되어 미션이 계속되는지 확인 | Mocking을 통한 에러 주입 후 대체 모델 호출 확인 |
| AGENT-03 | Sisyphus 자가 수정 | Sisyphus 에이전트가 검증 실패 시 피드백을 바탕으로 재시도하는지 확인 | `verification_fn` 실패 유도 후 재시도 루프 확인 |

## 3. 히스토리 및 컨텍스트 (History & Context)

| ID | 기능 | 테스트 시나리오 | 검증 방법 |
| :--- | :--- | :--- | :--- |
| HIST-01 | 세션 레지스트리 등록 | 미션 완료 후 `RegistryManager`를 통해 세션이 정상 등록되는지 확인 | `history.json` 또는 레지스트리 상태 확인 |
| HIST-02 | Follow-up (Multi-turn) | 이전 세션의 컨텍스트를 불러와서 새로운 미션을 시작할 때 컨텍스트 주입 확인 | `history_context`가 `run_swarm_logic`에 전달되는지 확인 |
| HIST-03 | 아티팩트 관리 | 미션별로 타임스탬프 기반의 독립적인 아티팩트 디렉토리가 생성되는지 확인 | 디렉토리 구조 및 파일 위치 검증 |

## 4. CLI 인터페이스 및 흐름 (CLI Interface)

| ID | 기능 | 테스트 시나리오 | 검증 방법 |
| :--- | :--- | :--- | :--- |
| CLI-01 | 메인 루프 종료 | 'quit' 선택 시 프로그램이 안전하게 종료되는지 확인 | `main_loop` 반환 확인 |
| CLI-02 | 미션 설정 취소 | 미션 입력 중 ESC 또는 빈 값 입력 시 초기 화면으로 돌아가는지 확인 | `setup_mission` 반환값 (None) 확인 |
| CLI-03 | 히스토리 탐색 | 저장된 히스토리가 없을 때와 있을 때의 다이얼로그 노출 분기 확인 | Mocking을 통한 다이얼로그 호출 여부 확인 |

## 5. 예외 처리 및 견고성 (Robustness)

| ID | 기능 | 테스트 시나리오 | 검증 방법 |
| :--- | :--- | :--- | :--- |
| ERR-01 | 샌드박스 초기화 실패 | 파일 시스템 권한 등으로 샌드박스 생성 실패 시 에러 핸들링 확인 | `_FAILURE.log` 기록 및 사용자 로그 출력 |
| ERR-02 | 인덱싱 오류 | 코드 인덱싱 중 예외 발생 시 미션 중단 없이 계속되는지(또는 안전 종료) 확인 | 예외 격리 여부 확인 |
| ERR-03 | API 모델 부재 | 설정된 모델이 실제 사용 불가능할 때의 예외 메시지 처리 | `AgentFactory` 에러 전파 및 처리 확인 |
