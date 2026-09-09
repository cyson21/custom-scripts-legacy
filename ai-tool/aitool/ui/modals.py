import os
from pathlib import Path
from typing import List, Tuple
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, OptionList, RichLog, Rule
from textual.screen import ModalScreen
from textual.binding import Binding
from rich.markdown import Markdown
from aitool.constants import HELP_TEXT
from aitool.models import BaseSession

class HelpScreen(ModalScreen):
    DEFAULT_CSS = "HelpScreen { align: center middle; }"
    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("ctrl+t", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help_container"):
            yield RichLog(id="help_log", markup=True, wrap=True)
            with Horizontal(classes="modal_buttons"):
                yield Button("닫기 (ESC)", variant="primary", id="close_help")

    def on_mount(self):
        self.query_one("#help_log", RichLog).write(Markdown(HELP_TEXT))

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss()


class InputModal(ModalScreen):
    DEFAULT_CSS = "InputModal { align: center middle; }"

    def __init__(self, title: str, placeholder: str = "", default: str = ""):
        super().__init__()
        self._title = title
        self._placeholder = placeholder
        self._default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="input_modal_container"):
            yield Label(self._title)
            yield Input(value=self._default, placeholder=self._placeholder, id="modal_input")
            with Horizontal(classes="modal_buttons"):
                yield Button("확인", variant="primary", id="confirm")
                yield Button("취소", variant="default", id="cancel")

    def on_mount(self):
        self.query_one("#modal_input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "confirm":
            self.dismiss(self.query_one("#modal_input", Input).value)
        else:
            self.dismiss("")

    def on_key(self, event: events.Key):
        if event.key == "enter":
            self.dismiss(self.query_one("#modal_input", Input).value)
            event.stop()
        elif event.key == "escape":
            self.dismiss("")
            event.stop()


class NotificationModal(ModalScreen):
    DEFAULT_CSS = """
    NotificationModal { align: center middle; }
    #notification_container {
        width: 80%;
        height: 60%;
        background: $panel;
        border: thick $primary;
        padding: 1 2;
    }
    """
    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    def __init__(self, notifications: List[Tuple[str, str, str]]):
        super().__init__()
        self.notifications = notifications

    def compose(self) -> ComposeResult:
        with Vertical(id="notification_container"):
            yield Label("[bold]알림 이력 (최근 50개)[/bold]", classes="modal_title")
            yield Rule()
            
            # (시간, 메시지, severity)
            for time_str, msg, severity in reversed(self.notifications):
                color = "green" if severity == "information" else "yellow" if severity == "warning" else "red" if severity == "error" else "white"
                yield Label(f"[{time_str}] [{color}]{msg}[/]")
            
            if not self.notifications:
                yield Label("표시할 알림이 없습니다.", classes="modal_text")
            
            yield Label("\n(ESC 또는 q로 닫기)", classes="modal_text")


class ChoiceModal(ModalScreen):
    DEFAULT_CSS = """
    ChoiceModal { align: center middle; }
    #choice_modal_container {
        width: 90;
        max-width: 90vw;
        max-height: 80vh;
        border: thick $primary;
        background: $surface;
        padding: 1;
    }
    #choice_list {
        height: auto;
        max-height: 20;
        overflow-y: scroll;
        margin: 1 0;
        border-top: solid $primary-darken-1;
        border-bottom: solid $primary-darken-1;
    }
    .modal_title {
        text-align: center;
        width: 1fr;
        text-style: bold;
    }
    """
    BINDINGS = [
        Binding("up", "focus_previous", "Previous", show=False),
        Binding("down", "focus_next", "Next", show=False),
    ]

    def __init__(self, title: str, choices: List[Tuple[str, str]]):
        super().__init__()
        self._title = title
        self._choices = choices

    def compose(self) -> ComposeResult:
        with Vertical(id="choice_modal_container"):
            yield Label(self._title, classes="modal_title")
            with Vertical(id="choice_list"):
                for i, (label, _) in enumerate(self._choices):
                    yield Button(label, id=f"c{i}")
            with Horizontal(classes="modal_buttons"):
                yield Button("취소", variant="default", id="cancel")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel":
            self.dismiss("")
        else:
            try:
                idx = int(event.button.id[1:])
                self.dismiss(self._choices[idx][1])
            except (ValueError, IndexError):
                self.dismiss("")

    def on_mount(self):
        # 첫 번째 선택지 버튼에 포커스 부여
        if self._choices:
            try:
                self.query_one("#c0", Button).focus()
            except Exception:
                pass

    def action_focus_previous(self):
        self.focus_previous()

    def action_focus_next(self):
        self.focus_next()

    def on_key(self, event: events.Key):
        if event.key == "escape":
            self.dismiss("")
            event.stop()


class PathInputModal(ModalScreen):
    """워크스페이스 경로 입력 + 파일시스템 디렉토리 자동완성 지원 모달."""

    DEFAULT_CSS = """
    PathInputModal { align: center middle; }
    #path_completions {
        height: auto;
        max-height: 10;
        display: none;
        border: solid $primary-darken-1;
        background: $surface-darken-1;
    }
    #path_completions.visible {
        display: block;
    }
    """

    BINDINGS = [
        # Tab 기본 동작(focus_next)을 가로채 자동완성에 사용
        Binding("tab", "complete_tab", "자동완성", show=False),
    ]

    def __init__(self, title: str, placeholder: str = "", default: str = ""):
        super().__init__()
        self._title = title
        self._placeholder = placeholder
        self._default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="path_input_modal_container"):
            yield Label(self._title)
            yield Input(
                value=self._default,
                placeholder=self._placeholder,
                id="path_modal_input",
            )
            yield OptionList(id="path_completions")
            with Horizontal(classes="modal_buttons"):
                yield Button("확인", variant="primary", id="confirm")
                yield Button("취소", variant="default", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#path_modal_input", Input).focus()

    # ── 자동완성 로직 ──────────────────────────────────────────────

    def _get_completions(self, text: str) -> List[str]:
        """입력 중인 경로에 대해 디렉토리 후보를 최대 10개 반환."""
        if not text:
            return []
        try:
            expanded = os.path.expanduser(text)
            p = Path(expanded)
            if text.endswith("/") or text.endswith(os.sep):
                # Trailing slash implies user wants children of this dir.
                # If it doesn't exist, no completions rather than falling back to parent.
                if p.is_dir():
                    parent, prefix = p, ""
                else:
                    return []
            else:
                parent, prefix = p.parent, p.name
            if not parent.is_dir():
                return []
            try:
                entries = sorted(parent.iterdir())
            except PermissionError:
                return []
            result = []
            for entry in entries:
                try:
                    if entry.is_dir() and entry.name.startswith(prefix):
                        result.append(str(entry) + "/")
                except PermissionError:
                    continue
            return result[:10]
        except Exception:
            return []

    def _longest_common_prefix(self, paths: List[str]) -> str:
        """경로 목록의 최장 공통 접두사 반환."""
        if not paths:
            return ""
        prefix = paths[0]
        for p in paths[1:]:
            while not p.startswith(prefix):
                prefix = prefix[:-1]
                if not prefix:
                    return ""
        return prefix

    def _update_completions(self, text: str) -> None:
        completions = self._get_completions(text)
        ol = self.query_one("#path_completions", OptionList)
        ol.clear_options()
        if completions:
            for c in completions:
                ol.add_option(c)
            ol.add_class("visible")
        else:
            ol.remove_class("visible")

    # ── 이벤트 핸들러 ──────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "path_modal_input":
            self._update_completions(event.value)

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """후보 항목 Enter → 입력창에 반영 후 포커스 복귀."""
        if event.option_list.id != "path_completions":
            return
        path = str(event.option.prompt)
        inp = self.query_one("#path_modal_input", Input)
        inp.value = path
        inp.cursor_position = len(path)
        self._update_completions(path)
        inp.focus()
        event.stop()

    def action_complete_tab(self) -> None:
        """Tab: 후보 1개 → 확정, 여러 개 → 최장 공통 접두사 적용."""
        ol = self.query_one("#path_completions", OptionList)
        count = ol.option_count
        if count == 0:
            return
        if count == 1:
            chosen = str(ol.get_option_at_index(0).prompt)
        else:
            prompts = [
                str(ol.get_option_at_index(i).prompt) for i in range(count)
            ]
            chosen = self._longest_common_prefix(prompts)
        inp = self.query_one("#path_modal_input", Input)
        inp.value = chosen
        inp.cursor_position = len(chosen)
        self._update_completions(chosen)
        inp.focus()

    def on_key(self, event: events.Key) -> None:
        inp = self.query_one("#path_modal_input", Input)
        ol = self.query_one("#path_completions", OptionList)
        if event.key == "down" and inp.has_focus:
            if "visible" in ol.classes and ol.option_count > 0:
                ol.focus()
                if ol.highlighted is None:
                    ol.highlighted = 0
                event.stop()
        elif event.key == "up" and ol.has_focus:
            if ol.highlighted == 0 or ol.highlighted is None:
                inp.focus()
                event.stop()
        elif event.key == "enter" and inp.has_focus:
            self.dismiss(inp.value)
            event.stop()
        elif event.key == "escape":
            self.dismiss("")
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.dismiss(self.query_one("#path_modal_input", Input).value)
        else:
            self.dismiss("")


class LargeViewModal(ModalScreen):
    DEFAULT_CSS = "LargeViewModal { align: center middle; }"
    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    def __init__(self, session: BaseSession):
        super().__init__()
        self._session = session

    def compose(self) -> ComposeResult:
        with Vertical(id="large_view_container"):
            yield RichLog(id="large_view_log", markup=True, wrap=True)
            with Horizontal(classes="modal_buttons"):
                yield Button("닫기 (ESC / q)", variant="primary", id="close_large")

    def on_mount(self):
        self.query_one("#large_view_log", RichLog).write(
            Markdown(self._session.get_markdown()))

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss()
