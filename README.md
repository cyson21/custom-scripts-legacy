# custom-scripts-legacy

macOS에서 사용하던 AI CLI 도구의 코드 스냅샷입니다. 현재 유지보수와 Windows 포팅은 하지 않습니다. GitHub의 보관 상태와 별개로, 이 README에서 운영 상태를 **레거시·유지보수 중단**으로 표시합니다.

## 도구별 진입점

| 경로 | 역할 | 사용 안내 |
|---|---|---|
| `ai-tool/` | Gemini CLI·Claude Code 세션을 탐색하고 관리하는 Python/Textual TUI | [README](ai-tool/README.md) |
| `multi-agent-orchestrator/` | 여러 CLI 엔진을 실행하고 결과를 모으는 Python TUI | [README](multi-agent-orchestrator/README.md) |
| `arena/` | bash 기반 코드 작성·교차 리뷰·패치 적용 도구 | [README](arena/README.md) |

세 도구는 각각의 진입점과 설정을 가진 별도 도구입니다. 순서대로 실행해야 하는 하나의 파이프라인은 아닙니다. 하위 README의 CLI 설치 명령과 경로는 스냅샷 작성 당시 기준이므로 재사용 전에 현재 공식 배포 문서와 실제 파일을 확인합니다.

## 실행 범위

macOS/Linux 터미널을 전제로 합니다. Windows에서는 이 저장소를 설치하거나 자동 실행하지 않으며, 이 작업에서 TUI나 외부 모델 호출을 실행하지 않았습니다.

`ai-tool`을 검토하려면 해당 디렉터리에서 의존성을 설치하고 진입 파일을 실행합니다.

```bash
cd ai-tool
python3 -m pip install -r requirements.txt
python3 ai_tool.py
```

오케스트레이터의 환경 설정 예시는 `multi-agent-orchestrator/.env.example`입니다. API 키는 로컬 `.env` 또는 실행 환경에만 두고 저장소에 올리지 않습니다. Arena의 자동 패치·커밋·푸시 기능은 각 도구의 설정을 읽고 별도로 선택해야 합니다.

## 현재 관리 체계와의 관계

현재 Windows 프로젝트에 이 코드가 자동으로 연결되지는 않습니다. 도구를 다시 쓰려면 하위 README와 소스를 함께 검토하고 별도 작업 브랜치에서 호환성을 확인합니다. 실행 로그·세션·인증 파일은 코드 백업 범위에 포함하지 않습니다.

공개 프로젝트 안내는 [웹 포트폴리오](https://cyson21.github.io/)에서 제공합니다. 이 저장소는 서비스 백엔드나 공개 사이트의 실행 의존성이 아닙니다.
