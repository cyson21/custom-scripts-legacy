from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Static, OptionList
from textual.screen import ModalScreen
from textual.binding import Binding
from aitool.providers import ClaudeProvider, GeminiProvider

class LauncherScreen(ModalScreen):
    DEFAULT_CSS = """
    LauncherScreen { align: center middle; }
    #launcher_container {
        width: 52;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #launcher_title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
        width: 1fr;
    }
    #provider_list {
        height: auto;
        max-height: 10;
        margin: 1 0;
    }
    #launcher_hint {
        text-align: center;
        color: $text-muted;
        margin-top: 1;
        width: 1fr;
    }
    .warning_text {
        text-align: center;
        color: $warning;
        text-style: bold;
        margin-bottom: 1;
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("1", "select_by_index(0)", "Gemini", show=False),
        Binding("2", "select_by_index(1)", "Claude", show=False),
        Binding("q", "cancel", "Quit", show=False),
        Binding("escape", "cancel", "Quit", show=False),
    ]

    def __init__(self):
        super().__init__()
        self._gemini_provider = GeminiProvider()
        self._claude_provider = ClaudeProvider()
        self._providers = [self._gemini_provider, self._claude_provider]

    def compose(self) -> ComposeResult:
        gemini_avail = self._gemini_provider.is_available()
        claude_avail = self._claude_provider.is_available()

        with Vertical(id="launcher_container"):
            yield Static("AI Session Manager v1.0", id="launcher_title")

            if not gemini_avail and not claude_avail:
                yield Static("[!] AI CLI 툴이 설치되어 있지 않습니다.\n설치 후 다시 시도해주세요:\n- npm install -g @google/gemini-cli\n- npm install -g @anthropic-ai/claude-code", id="launcher_warning", classes="warning_text")

            ol = OptionList(id="provider_list")
            status1 = "" if gemini_avail else " (미설치)"
            ol.add_option(f"[1] Gemini CLI{status1}")
            status2 = "" if claude_avail else " (미설치)"
            ol.add_option(f"[2] Claude Code{status2}")
            yield ol

            yield Static("[1 / 2 / Enter] 선택  [q / ESC] 종료", id="launcher_hint")

    def on_mount(self):
        self.query_one("#provider_list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        self.action_select_by_index(event.index)

    def action_select_by_index(self, index: int):
        if index < 0 or index >= len(self._providers):
            return
        provider = self._providers[index]
        if provider.is_available():
            self.dismiss(provider)
        else:
            self.app.notify(f"{provider.name}가 설치되어 있지 않습니다.", severity="error")

    def action_cancel(self):
        self.dismiss(None)
