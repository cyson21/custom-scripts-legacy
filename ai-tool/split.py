import os
import re

def main():
    with open('ai_tool.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # Split by the section headers
    sections = re.split(r'# -{75}\n# \[섹션 \d\].*?\n# -{75}\n*', content)
    
    # sections[0] is the top imports
    imports_top = sections[0].strip()
    
    # Create directories
    os.makedirs('aitool/ui', exist_ok=True)
    
    # 1. Config
    with open('aitool/config.py', 'w', encoding='utf-8') as f:
        f.write("import os\nimport re\nimport logging\nfrom datetime import datetime\nfrom pathlib import Path\nimport sys\n\n")
        f.write(sections[1].strip() + "\n")
        
    # 2. Models
    with open('aitool/models.py', 'w', encoding='utf-8') as f:
        f.write("import json\nfrom abc import ABC, abstractmethod\nfrom datetime import datetime\nfrom pathlib import Path\nfrom typing import List\n\n")
        f.write(sections[2].strip() + "\n")
        
    # 3. Providers
    with open('aitool/providers.py', 'w', encoding='utf-8') as f:
        f.write("import os\nimport json\nimport glob\nimport shutil\nimport shlex\nimport subprocess\nimport tempfile as _tempfile\nimport traceback\nfrom abc import ABC, abstractmethod\nfrom pathlib import Path\nfrom typing import List, Optional, Tuple, Any\n")
        f.write("from aitool.config import logger, CLAUDE_PROJECTS_DIR, META_FILE, LEGACY_META_FILE, _UUID_RE\n")
        f.write("from aitool.models import BaseSession, ClaudeSession, GeminiSession\n\n")
        f.write(sections[3].strip() + "\n")
        
    # 4. Constants
    with open('aitool/constants.py', 'w', encoding='utf-8') as f:
        f.write(sections[4].strip() + "\n")
        
    # 5. Modals
    with open('aitool/ui/modals.py', 'w', encoding='utf-8') as f:
        f.write("from typing import List, Tuple\n")
        f.write("from textual import events\n")
        f.write("from textual.app import ComposeResult\n")
        f.write("from textual.containers import Horizontal, Vertical\n")
        f.write("from textual.widgets import Button, Input, Label, RichLog\n")
        f.write("from textual.screen import ModalScreen\n")
        f.write("from textual.binding import Binding\n")
        f.write("from rich.markdown import Markdown\n")
        f.write("from aitool.constants import HELP_TEXT\n")
        f.write("from aitool.models import BaseSession\n\n")
        f.write(sections[5].strip() + "\n")
        
    # 6. Launcher
    with open('aitool/ui/launcher.py', 'w', encoding='utf-8') as f:
        f.write("from textual.app import ComposeResult\n")
        f.write("from textual.containers import Horizontal, Vertical\n")
        f.write("from textual.widgets import Label, Static\n")
        f.write("from textual.screen import ModalScreen\n")
        f.write("from textual.binding import Binding\n")
        f.write("from aitool.providers import ClaudeProvider, GeminiProvider\n\n")
        f.write(sections[6].strip() + "\n")
        
    # 7. App
    with open('aitool/ui/app.py', 'w', encoding='utf-8') as f:
        f.write("import os\nimport sys\nimport traceback\nimport subprocess\nfrom datetime import datetime\nfrom pathlib import Path\nfrom typing import List, Optional, Tuple\n")
        f.write("import pyperclip\n")
        f.write("from rich.markdown import Markdown\n")
        f.write("from rich.markup import escape\n")
        f.write("from textual import events, on, work\n")
        f.write("from textual.app import App, ComposeResult\n")
        f.write("from textual.binding import Binding\n")
        f.write("from textual.containers import Horizontal, Vertical\n")
        f.write("from textual.widgets import Header, Footer, ListView, ListItem, Label, Input, Static, RichLog, Rule, Tree\n")
        
        f.write("from aitool.config import logger\n")
        f.write("from aitool.models import BaseSession\n")
        f.write("from aitool.providers import BaseProvider, ClaudeProvider, GeminiProvider\n")
        f.write("from aitool.ui.modals import HelpScreen, InputModal, ChoiceModal, LargeViewModal\n")
        f.write("from aitool.ui.launcher import LauncherScreen\n\n")
        
        # Replace the if __name__ == "__main__": block at the end with just the app class
        app_code = sections[7].strip()
        app_code = re.sub(r'if __name__ == "__main__":.*', '', app_code, flags=re.DOTALL)
        f.write(app_code.strip() + "\n")
        
    # Wrap it all up in __init__.py files
    with open('aitool/__init__.py', 'w') as f:
        pass
    with open('aitool/ui/__init__.py', 'w') as f:
        pass

    # Create the new entry point ai_tool.py
    with open('ai_tool.py', 'w', encoding='utf-8') as f:
        f.write("import os\nimport sys\nimport subprocess\n")
        f.write("from aitool.ui.app import AiTool\n\n")
        f.write("if __name__ == '__main__':\n")
        f.write("    try:\n")
        f.write("        import textual\n")
        f.write("    except ImportError as e:\n")
        f.write("        print(f\"필수 라이브러리가 설치되어 있지 않습니다: {e}\")\n")
        f.write("        print(\"\\n[AI-Tool 설치 안내]\")\n")
        f.write("        print(\"ai-tool을 처음 실행하셨거나 의존성이 누락되었습니다.\")\n")
        f.write("        print(\"제공된 설치 스크립트를 실행하여 환경을 구성해 주세요:\")\n")
        f.write("        print(\"  $ ./scripts/install.sh\")\n")
        f.write("        sys.exit(1)\n\n")
        f.write("    app = AiTool()\n")
        f.write("    result = app.run()\n")
        f.write("    if result:\n")
        f.write("        executable = '/bin/zsh' if os.name != 'nt' else None\n")
        f.write("        subprocess.run(result, shell=True, executable=executable)\n")

if __name__ == '__main__':
    main()
