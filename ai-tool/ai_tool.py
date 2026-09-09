import os
import sys
import subprocess
from aitool.ui.app import AiTool

if __name__ == '__main__':
    try:
        import textual  # noqa: F401
    except ImportError as e:
        print(f"필수 라이브러리가 설치되어 있지 않습니다: {e}")
        print("\n[AI-Tool 설치 안내]")
        print("ai-tool을 처음 실행하셨거나 의존성이 누락되었습니다.")
        print("제공된 설치 스크립트를 실행하여 환경을 구성해 주세요:")
        print("  $ ./scripts/install.sh")
        sys.exit(1)

    app = AiTool()
    result = app.run()
    if result:
        executable = '/bin/zsh' if os.name != 'nt' else None
        subprocess.run(result, shell=True, executable=executable)
