# AI-Tool 배포 가이드 (Git 미사용)

Git 등 버전 관리 도구를 사용하지 않고 `ai-tool`을 순수 파일 기반으로 배포하는 방법입니다.
아래 절차를 따라 배포용 압축 파일을 만들고, 사용자에게 전달하여 설치를 유도할 수 있습니다.

## 1. 배포 전 필수 확인 사항 (클린업)
배포 파일에 불필요한 캐시, 로그 파일, 민감한 정보(개인 세션/임시 파일)가 포함되지 않도록 정리해야 합니다.
프로젝트 루트 디렉토리(`$HOME/customScripts/ai-tool`)에서 다음 작업들을 수행하세요.

### 제거해야 할 파일 및 폴더
- `__pycache__` 폴더 (모든 하위 디렉토리 포함)
- `.pytest_cache` 폴더
- `log` 또는 `logs` 폴더 내부의 `.log` 파일들
- `outputs` 폴더 내부의 테스트/개인 출력물
- `.env` 파일 (만약 존재하며 개인 API 키가 들어있다면 절대 포함 금지)
- 임시 테스트용 파일 (예: `test_move.py`, `test_bindings.py`)

## 2. 배포용 압축 파일(Tar/Zip) 생성

터미널에서 다음 명령어를 실행하여 정리된 코드만 포함된 배포용 압축 파일을 만듭니다.

```bash
# 프로젝트 디렉토리로 이동
cd $HOME/customScripts/ai-tool

# 배포판을 저장할 임시 디렉토리 생성
mkdir -p /tmp/ai-tool-release

# 필요한 파일만 골라서 복사 (원치 않는 파일 배제)
# (rsync를 사용하면 불필요한 파일을 쉽게 제외할 수 있습니다)
rsync -av --exclude='__pycache__' \
          --exclude='.pytest_cache' \
          --exclude='log/*.log' \
          --exclude='*.pyc' \
          --exclude='.env' \
          --exclude='test_*.py' \
          --exclude='*.json' \
          ./ /tmp/ai-tool-release/

# 압축 파일(tar.gz) 생성
cd /tmp
tar -czvf ai-tool-v1.0.tar.gz ai-tool-release/
```

생성된 `ai-tool-v1.0.tar.gz` 파일이 바로 **최종 배포본**입니다.
이 파일을 사내 메신저, 이메일, 슬랙, 또는 사내 공유 드라이브를 통해 배포하세요.

---

## 3. 사용자(수신자) 측 설치 가이드
압축 파일을 전달받은 사용자는 아래의 절차를 따라 쉽게 설치할 수 있습니다.
*(이 내용을 복사하여 압축 파일 전달 시 함께 메시지로 보내면 좋습니다.)*

### 📥 AI Session Manager (ai-tool) 설치 가이드

1. **파일 압축 해제**
   전달받은 `ai-tool-v1.0.tar.gz` 파일을 원하는 위치(예: `~/ai-tool`)에 압축 해제합니다.
   ```bash
   tar -xzvf ai-tool-v1.0.tar.gz -C ~/
   mv ~/ai-tool-release ~/ai-tool
   ```

2. **자동 설치 스크립트 실행**
   압축 푼 폴더로 이동하여 설치 스크립트를 실행합니다. 이 스크립트가 필요한 Python 패키지를 자동으로 설치해 줍니다.
   ```bash
   cd ~/ai-tool
   ./scripts/install.sh
   ```

3. **단축키(Alias) 등록**
   `install.sh` 스크립트 실행이 완료되면 화면 마지막에 나타나는 `alias` 관련 가이드를 복사하여 본인의 `~/.zshrc` 또는 `~/.bash_profile`에 붙여넣습니다.
   *(예시)*
   ```bash
   echo "alias aitool='python3 ~/ai-tool/ai_tool.py'" >> ~/.zshrc
   source ~/.zshrc
   ```

4. **실행**
   이제 터미널 어디서든 아래 명령어로 프로그램을 실행할 수 있습니다.
   ```bash
   aitool
   ```

> **참고**: 원활한 사용을 위해 사전에 [Node.js](https://nodejs.org/)를 설치한 후 `npm install -g @google/gemini-cli` 또는 `npm install -g @anthropic-ai/claude-code`를 통해 AI CLI 툴을 최소 하나 이상 설치해야 합니다.