# ai-tool (Python TUI v1.0)

Gemini CLI와 Claude Code의 세션 파일을 단일 인터페이스에서 탐색·관리하는 **터미널 TUI 도구**입니다.
[Textual](https://github.com/Textualize/textual) 기반으로 구현되어 있으며, 시작 시 사용 가능한 CLI를 자동 감지하여 선택합니다.

---

## 목차

1. [실행 방법](#실행-방법)
2. [기능 목록](#기능-목록)
3. [단축키](#단축키)
4. [아키텍처](#아키텍처)
5. [세션 파일 구조](#세션-파일-구조)
6. [에러 로그](#에러-로그)
7. [수정 가이드 (AI 에이전트 필독)](#수정-가이드-ai-에이전트-필독)
8. [개발 히스토리](#개발-히스토리)
9. [변경 이력](#변경-이력)

---

## 실행 방법

### 자동 설치 (권장)

macOS 및 Linux 환경에서 의존성 패키지를 쉽게 설치하고 단축키 등록을 안내하는 스크립트를 제공합니다.

```bash
cd ~/ai-tool
./scripts/install.sh
```

### 수동 설치 (의존성)

```bash
pip3 install -r requirements.txt
```

### 실행

```bash
python3 ~/ai-tool/ai_tool.py
```

### 전역 alias 등록 (`~/.zshrc` 등)

`install.sh` 실행 시 안내되는 alias를 등록하면 어디서든 편하게 사용할 수 있습니다.

```bash
alias aitool="python3 ~/ai-tool/ai_tool.py"
```

---

## 기능 목록

### 런처 (LauncherScreen)

- 시작 시 Gemini CLI / Claude Code 양쪽의 가용성을 **백그라운드 스레드**에서 자동 체크
- 버전 문자열 또는 "사용 불가" 표시 → 불가한 CLI는 선택 비활성
- 두 CLI 모두 불가 시 설치 안내 메시지 표시

```
┌─────────────────────────────────────────────────┐
│            AI Session Manager v1.0              │
│                                                 │
│  [1]  Gemini CLI    0.1.20                      │
│  [2]  Claude Code   1.2.3                       │
│                                                 │
│               [q / ESC]  종료                   │
└─────────────────────────────────────────────────┘
```

### 세션 탐색 및 검색

- **fzf 스타일 탐색**: 검색창에 포커스가 있어도 `↑`/`↓` 키로 목록 탐색 가능
- **전체 텍스트 검색**: 날짜, 워크스페이스명, 요약, **대화 본문 전체**를 실시간 필터링
- **빈 세션 자동 제외**: 메시지가 1개 이하인 세션은 목록에 표시하지 않음
- **최신순 정렬**: Claude는 `timestamp`, Gemini는 `lastUpdated` → `startTime` 기준

### 세션 관리

| 기능 | 단축키 | 설명 |
|---|---|---|
| 세션 재개 | `Enter` | 해당 워크스페이스에서 `--resume` 실행 후 TUI 종료 |
| 보관 / 삭제 | `Ctrl+D` | 활성 → archived 폴더 이동 / 보관함 → 영구 삭제 |
| 복구 | `Ctrl+S` | archived → 활성 폴더 복구 |
| 보관함 전환 | `Ctrl+O` | 활성 목록 ↔ 보관함 목록 토글 |
| 이동 / 복사 | `Ctrl+W` | 다른 워크스페이스로 세션 복사 또는 이동 |
| 제목 변경 | `Ctrl+R` | 수동으로 세션 요약(제목) 변경 |
| AI 제목 요약 | `Ctrl+A` | 최근 대화 3개 메시지 기반 한국어 제목 자동 생성 |

### 내보내기 / 보기

| 기능 | 단축키 | 설명 |
|---|---|---|
| 크게 보기 | `Ctrl+V` | 전체 화면 모달로 대화 내용 보기 |
| 클립보드 복사 | `Ctrl+Y` | 마지막 메시지를 클립보드에 복사 |
| 마크다운 저장 | `Ctrl+E` | 현재 경로에 `.md` 파일로 저장 |
| 새로고침 | `Ctrl+L` | 세션 목록 재로드 |
| 도움말 | `Ctrl+T` | 단축키 목록 모달 표시 |

### 레이아웃

| 기능 | 단축키 |
|---|---|
| 목록 패널 축소 | `[` |
| 목록 패널 확장 | `]` |
| 미리보기 포커스 | `→` |
| 목록 포커스 | `←` |
| 페이지 이동 | `Page Up` / `Page Down` |

---

## 단축키

```
ENTER       세션 재개 (Resume)
ESC / C-q   종료
C-d         (활성) 보관 / (보관함) 영구 삭제
C-o         활성 ↔ 보관함 전환
C-s         보관함 → 활성 복구
C-w         다른 워크스페이스로 이동/복사
C-r         제목 수동 변경
C-a         AI 자동 제목 요약
C-v         크게 보기
C-y         마지막 답변 클립보드 복사
C-e         마크다운 저장
C-l         새로고침
C-t         도움말
[ / ]       목록 패널 축소/확장
← / →       패널 포커스 이동
Page Up/Dn  페이지 이동

─── Launcher ───────────────────────────
1           Gemini CLI 선택
2           Claude Code 선택
q / ESC     종료
```

---

## 아키텍처

### 클래스 구조

```
ai_tool.py
│
├── [섹션 2] 데이터 모델
│   ├── BaseSession (ABC)        # 세션 공통 인터페이스
│   ├── ClaudeSession            # JSONL 파싱, cwd 필드에서 워크스페이스 추출
│   └── GeminiSession            # JSON 파싱, .project_root에서 워크스페이스 추출
│
├── [섹션 3] Provider
│   ├── BaseProvider (ABC)       # 로드/보관/복구/삭제/이름변경/이동/AI요약 인터페이스
│   ├── ClaudeProvider           # ~/.claude/projects 기반, META_FILE 제목 관리
│   └── GeminiProvider           # ~/.gemini/tmp 기반, JSON summary 필드 직접 수정
│
├── [섹션 4] HELP_TEXT
│
├── [섹션 5] 공통 모달
│   ├── HelpScreen (ModalScreen)
│   ├── InputModal (ModalScreen)
│   ├── ChoiceModal (ModalScreen)
│   └── LargeViewModal (ModalScreen)
│
├── [섹션 6] LauncherScreen (ModalScreen)
│   └── @work(thread=True) _check_availability()
│
└── [섹션 7] AiTool (App)
    ├── compose()                # 레이아웃 정의
    ├── on_mount()               # LauncherScreen push → provider 주입
    ├── on_key()                 # fzf 스타일 ↑/↓ 탐색
    ├── load_sessions()          # provider.load_sessions() 위임
    ├── update_list()            # 목록 필터링 및 갱신
    ├── update_preview()         # 우측 미리보기 갱신
    ├── @work _run_ai_summary()  # AI 요약 (백그라운드 스레드)
    └── action_*()               # 각 단축키 액션
```

### 레이아웃

```
┌─────────────────────────────────────────────────────┐
│ Header (시계 + provider 이름)                        │
├──────────────────────┬─┬────────────────────────────┤
│ [활성] 총 N개         │ │                            │
│ ─────────────────    │ │   미리보기 (RichLog)        │
│ ListView             │R│   마크다운 렌더링           │
│  ...세션 목록...      │u│                            │
│                      │l│                            │
│ > [검색창]           │e│                            │
│ #list_container      │ │ #preview_container         │
│ (40fr, 가변)         │ │ (60fr, 가변)               │
├──────────────────────┴─┴────────────────────────────┤
│ Footer (단축키 바)                                   │
└─────────────────────────────────────────────────────┘
```

### Provider별 차이점

| 항목 | ClaudeProvider | GeminiProvider |
|---|---|---|
| 세션 파일 | `~/.claude/projects/{encoded}/*.jsonl` | `~/.gemini/tmp/{hash}/chats/*.json` |
| 워크스페이스 | JSONL `cwd` 필드 | `.project_root` 파일 |
| 제목 저장 | `~/.claude/ai-tool-meta.json` (별도) | JSON `summary` 필드 직접 수정 |
| 아카이브 경로 | `{proj_dir}/archived/` | `{hash_dir}/archived/` |
| 복구 경로 | `{proj_dir}/` | `{hash_dir}/chats/` |
| 경로 인코딩 | `/` `.` → `-` + 선두 `-` | base_name + counter |
| AI 요약 플래그 | `--output-format text --no-session-persistence` | `-o text --yolo` + tempfile |
| 환경변수 | `_CLAUDE_PROMPT` | `_GEMINI_PROMPT` + `GEMINI_CLI_HOME` |
| Resume 명령 | `claude --resume {id}` | `gemini --resume {id}` |

---

## 세션 파일 구조

### Claude Code

```
~/.claude/
├── projects/
│   └── {encoded-path}/          # 예: /Users/foo/proj → -Users-foo-proj
│       ├── {session_id}.jsonl   # 활성 세션
│       └── archived/
│           └── {session_id}.jsonl
└── ai-tool-meta.json            # 커스텀 제목 저장소 (session_id → 제목)
```

JSONL 각 줄이 독립 JSON 객체이며, `type: "user"` / `type: "assistant"` 레코드만 파싱합니다.

```jsonl
{"type":"user","cwd":"/Users/foo/proj","sessionId":"uuid","timestamp":"...","message":{"role":"user","content":"질문"}}
{"type":"assistant","cwd":"/Users/foo/proj","sessionId":"uuid","timestamp":"...","message":{"role":"assistant","content":[{"type":"text","text":"답변"}]}}
```

### Gemini CLI

```
~/.gemini/tmp/
└── {workspace_hash}/
    ├── .project_root            # 워크스페이스 절대 경로
    ├── chats/
    │   └── {session_id}.json
    └── archived/
        └── {session_id}.json
```

```json
{
  "sessionId": "string",
  "summary": "세션 제목",
  "startTime": "2026-03-14T10:00:00Z",
  "lastUpdated": "2026-03-14T10:30:00Z",
  "messages": [
    { "type": "user", "content": [{ "text": "질문" }] },
    { "type": "model", "content": [{ "text": "답변" }], "thoughts": [{ "subject": "..." }] }
  ]
}
```

### META_FILE 마이그레이션

`claude-tool`의 레거시 경로(`~/.claude/claude-tool-meta.json`)를 자동으로 신규 경로(`~/.claude/ai-tool-meta.json`)로 복사합니다. 레거시 파일은 삭제하지 않습니다.

---

## 에러 로그

치명적 에러는 자동으로 `logs/` 폴더에 날짜별로 기록됩니다.

```
ai-tool/
└── logs/
    └── ai_tool_YYYY-MM-DD.log
```

확인 방법:

```bash
cat ~/ai-tool/logs/ai_tool_$(date +%Y-%m-%d).log
```

---

## 수정 가이드 (AI 에이전트 필독)

### 절대 변경 금지 사항

#### 1. Claude AI 요약 subprocess

```python
# ClaudeProvider.run_ai_summary()
env["TERM"] = "dumb"
result = subprocess.run(
    ["zsh", "-ic",
     'claude -p "$_CLAUDE_PROMPT" --output-format text --no-session-persistence'],
    stdin=subprocess.DEVNULL,
    capture_output=True,
    text=True,
    timeout=60,
    start_new_session=True,  # 필수: setsid() → 터미널 제어 완전 분리
    env=env,
)
```

- `zsh -ic`: `.zshrc` 소싱 → nvm/PATH 확보 (절대 `zsh -c`로 변경 금지)
- `start_new_session=True`: TUI raw mode 간섭 방지
- `TERM=dumb`: 터미널 제어 시퀀스 출력 방지
- `--no-session-persistence`: AI 요약 호출이 Claude 세션 목록에 오염되는 것 방지

#### 2. Gemini AI 요약 subprocess

```python
# GeminiProvider.run_ai_summary()
with _tempfile.TemporaryDirectory() as temp_home:
    env = {**os.environ, "GEMINI_CLI_HOME": temp_home, "_GEMINI_PROMPT": prompt}
    env["TERM"] = "dumb"
    result = subprocess.run(
        ["zsh", "-ic", 'gemini -p "$_GEMINI_PROMPT" -o text --yolo'],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        start_new_session=True,
        env=env,
    )
```

- `TemporaryDirectory()` + `GEMINI_CLI_HOME`: 임시 홈으로 격리 → 세션 오염 방지
- `--yolo`: Gemini CLI의 비대화형 모드 플래그

#### 3. `@work(exclusive=True, thread=True)` 데코레이터

`AiTool._run_ai_summary()`에 반드시 `exclusive=True`가 있어야 합니다.
없으면 Ctrl+A를 연속 입력 시 여러 요약이 동시에 실행됩니다.

#### 4. `on_key()` fzf 스타일 탐색

검색창(`#search_input`)에 포커스가 있을 때 `↑`/`↓`가 ListView를 탐색하는 로직은
`on_key()`에서 수동 처리합니다. 제거하면 검색 중 키보드 탐색이 불가능합니다.

#### 5. `rich.markup.escape()` 적용

목록 표시 시 `escape(s.workspace_name)`, `escape(prefix)`, `escape(s.summary)` 모두
반드시 escape 처리해야 합니다. 빠뜨리면 특수문자(`[`, `]` 등) 포함 제목에서 마크업 오류가 발생합니다.

#### 6. ChoiceModal 버튼 ID

버튼 ID는 반드시 `c{index}` 형식(예: `c0`, `c1`)을 유지해야 합니다.
워크스페이스 경로 등 특수문자가 포함된 값을 HTML ID로 직접 사용할 수 없기 때문입니다.

### Provider 확장 가이드

새 AI CLI를 추가하려면:

1. `BaseSession` 상속 → `get_markdown()`, `extract_recent_texts()`, `get_last_message_text()` 구현
2. `BaseProvider` 상속 → 모든 `@abstractmethod` 구현
3. `LauncherScreen.__init__()` 에 새 provider 인스턴스 추가
4. `compose()` 에 새 provider 행 추가
5. 새 숫자 키 Binding + `action_select_*()` 메서드 추가

### 에러 처리 규칙

모든 `except` 블록은 다음 패턴을 따릅니다:

```python
except Exception as e:
    logger.error("설명: %s\n%s", e, traceback.format_exc())
    self.notify(f"설명: {e}", severity="error", markup=False)
```

### 금지 사항

- `zsh -c`로 변경 금지 (`.zshrc` 미소싱 → CLI 명령 not found)
- `start_new_session=True` 제거 금지 (터미널 raw mode 간섭)
- `TERM=dumb` 제거 금지 (터미널 제어 시퀀스 출력)
- `--no-session-persistence` 제거 금지 (Claude 세션 오염)
- 프롬프트를 `shlex.quote()`로 전달 금지 → 반드시 환경변수(`_CLAUDE_PROMPT` / `_GEMINI_PROMPT`) 사용
- `exclusive=True` 제거 금지
- META_FILE 저장 시 반드시 `json.dump(..., ensure_ascii=False, indent=2)` 사용
- tilde 경로 치환 시 수동 문자열 처리 금지 → 반드시 `Path(p).expanduser()` 사용

---

## 개발 히스토리

### 배경

`gemini-tool`은 2026년 초 bash + fzf 기반 스크립트(v3.5)로 시작되었습니다.
이후 fzf 의존성 제거와 모달 UI 필요성으로 Python Textual 기반 TUI로 전환(v4.0)되었습니다.
`claude-tool`은 `gemini-tool v4.0`의 아키텍처를 그대로 차용하여 Claude Code용으로 구현되었습니다.

두 도구는 레이아웃, 단축키, 모달 4개, 검색/프리뷰 로직이 거의 동일한 구조를 가졌지만,
파일 형식(JSONL vs JSON), 세션 경로, 제목 저장 방식, AI 요약 플래그 등이 달랐습니다.
동일한 버그(마크업 이스케이프 누락 등)를 두 파일에서 각각 수정해야 하는 유지보수 비용이
지속적으로 발생하면서 통합 필요성이 제기되었습니다.

### 아키텍처 결정: Provider 패턴 채택

통합 방식으로 **Option A: Provider 패턴**을 채택했습니다.

> 공통 UI 로직은 `AiTool(App)` 단일 클래스에 두고,
> provider별 차이(세션 로드, 보관/복구, 이름변경, AI 요약, 경로 인코딩 등)를
> `BaseProvider` 인터페이스를 구현하는 `ClaudeProvider` / `GeminiProvider`에 위임합니다.

이 방식은 다음을 보장합니다:
- 버그 수정이 두 provider 모두에 자동 반영
- 새 CLI 추가 시 Provider 클래스 하나만 추가
- UI 코드와 CLI별 세부 구현의 완전한 분리

### 주요 설계 결정

| 결정 | 이유 |
|---|---|
| `LauncherScreen`을 ModalScreen으로 구현 | `on_mount`에서 push하여 메인 앱 위에 오버레이 → provider 선택 후 `handle` 콜백으로 주입 |
| CLI 가용성 체크를 백그라운드 스레드로 분리 | subprocess 실행이 블로킹 → `@work(thread=True)` 로 UI 응답성 유지 |
| `BaseSession` 추상 메서드 3개 | `get_markdown()`, `extract_recent_texts()`, `get_last_message_text()`만 추상화하여 AI 요약 / 클립보드 / 미리보기를 provider 무관하게 처리 |
| META_FILE 신규 경로 (`ai-tool-meta.json`) | `claude-tool-meta.json`은 구 도구에서만 쓰도록 분리. 레거시 자동 마이그레이션 지원 |
| `load_sessions()` 를 App이 아닌 Provider에 위임 | App이 파일시스템 구조를 몰라도 됨 |
| `ChoiceModal` 버튼 ID `c{index}` 유지 | 워크스페이스 경로를 HTML ID로 직접 쓸 수 없는 기존 설계를 그대로 계승 |

### 이전 도구와의 관계

| 도구 | 상태 | 경로 |
|---|---|---|
| `gemini-tool/gemini_tool.py` | Deprecated (파일 유지) | `$HOME/customScripts/gemini-tool/` |
| `claude-tool/claude_tool.py` | Deprecated (파일 유지) | `$HOME/customScripts/claude-tool/` |
| `ai-tool/ai_tool.py` | **현행 (이 파일)** | `~/ai-tool/` |

---

## 변경 이력

| 버전 | 날짜 | 내용 |
|---|---|---|
| v1.0 | 2026-03-15 | `gemini-tool v4.0` + `claude-tool v1.0` 통합. Provider 패턴 도입. LauncherScreen 신규 구현. META_FILE 마이그레이션 지원. |

### 전신 도구 변경 이력

#### gemini-tool

| 버전 | 날짜 | 내용 |
|---|---|---|
| v3.5 | 2026-02 | bash + fzf 기반 원본 (gemini-tool.sh.bak) |
| v4.0 | 2026-03-14 | bash/fzf → Python Textual TUI 전면 재작성 |
| v4.0.1 | 2026-03-14 | AI 요약 터미널 간섭 버그 수정 (`start_new_session`, `TERM=dumb`) |
| v4.0.2 | 2026-03-14 | `logs/` 폴더 에러 로깅 추가, `exclusive=True` 추가 |
| v4.0.3 | 2026-03-14 | Windows 호환성 개선: AI 요약 PowerShell 분기, 프롬프트 env var 전달, `Path.expanduser()` 적용 |

#### claude-tool

| 버전 | 날짜 | 내용 |
|---|---|---|
| v1.0 | 2026-03-14 | gemini-tool v4.0 아키텍처 기반 Claude Code 세션 매니저 최초 구현 |
