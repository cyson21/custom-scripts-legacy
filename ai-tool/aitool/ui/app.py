"""
Architectural Role: Main Textual TUI Application.
This module orchestrates the entire user interface, managing the session list/tree,
preview pane, and user interactions through a centralized event loop.
"""
import os
import re
import queue
import sys
import traceback
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
import pyperclip
from rich.markdown import Markdown
from rich.markup import escape
from textual import events, on, work
from textual.reactive import reactive
from textual.app import App, ComposeResult
from textual.screen import ModalScreen
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, ListView, ListItem, Label, Input, Static, RichLog, Rule, Tree
from aitool.config import logger
from aitool.models import BaseSession
from aitool.providers import BaseProvider, ClaudeProvider
from aitool.ui.modals import HelpScreen, InputModal, ChoiceModal, LargeViewModal, PathInputModal, NotificationModal
from aitool.ui.launcher import LauncherScreen

COMMAND_BINDINGS = [
    Binding("space", "toggle_check", "Check"),
    Binding("x", "toggle_check", "Check", show=False),
    Binding("d", "delete_or_archive", "Delete"),
    Binding("s", "restore_session", "Restore"),
    Binding("m", "move_session", "Move", show=False),
    Binding("w", "move_session", "Move"),
    Binding("r", "rename_session", "Rename"),
    Binding("i", "open_ide", "Open IDE"),
    Binding("u", "undo", "Undo"),
    Binding("a", "ai_summary", "AI Summary"),
    Binding("y", "copy_last", "Copy"),
    Binding("v", "view_large", "View Large", show=False),
    Binding("e", "export_md", "Export", show=False),
    Binding("slash", "focus_search", "Search"),
]

class SessionList(ListView):
    BINDINGS = COMMAND_BINDINGS

class SessionTree(Tree):
    BINDINGS = COMMAND_BINDINGS

# Why: We use a custom CheatSheet instead of the standard Textual 'Footer'.
# The Footer is too restrictive for our needs; CheatSheet allows for multi-line
# layouts and rich markup to clearly display the complex command surface.
CHEAT_SHEET_TEXT = """\
[b]Global:[/b] [b]ESC/q[/b] 종료  [b]n[/b] 새세션  [b]p[/b] AI전환  [b]o[/b] 보관함  [b]b[/b] 뷰전환  [b]l[/b] 새로고침  [b]g[/b] 빈세션정리  [b]F1[/b] 도움말
[b]Session:[/b] [b]space/S[/b] 체크/범위  [b]enter[/b] 열기  [b]d[/b] 삭제/보관  [b]s[/b] 복구  [b]w[/b] 이동  [b]r[/b] 이름변경  [b]a[/b] 요약  [b]y[/b] 복사  [b]E/H[/b] 제외/숨김  [b]/[/b] 검색\
"""

class AiTool(App):
    TITLE = "AI Session Manager"
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    Screen { layers: base help; }

    #ai_status_bar {
        dock: bottom;
        height: 1;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
        border-top: solid $primary-darken-1;
    }

    #cheat_sheet {
        dock: bottom;
        height: 3;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
        border-top: solid $primary;
    }

    #main_layout    { height: 1fr; margin: 0; padding: 0; }
    #list_container { width: 40fr; height: 1fr; margin: 0; padding: 0; }
    #fzf_header     { height: auto; padding: 0 1; color: $text-muted; width: 1fr; }
    #session_list, #session_tree { height: 1fr; scrollbar-size: 0 0; }
    #session_tree { display: none; }
    #search_bar     { height: 1; margin: 0 1; }
    #prompt_symbol  { width: 2; text-style: bold; }
    #search_input   { width: 1fr; border: none; padding: 0; background: transparent; }
    #search_input:focus { border: none; }

    Rule { margin: 0; padding: 0; }

    #preview_container { width: 60fr; height: 1fr; padding: 0 1; }

    ListItem   { height: 1; padding: 0 1; }
    .item_label { width: 1fr; overflow: hidden; }

    Tree > .tree--guides {
        color: $primary;
    }
    Tree > .tree--label {
        width: 1fr;
        overflow: hidden;
    }

    #help_container,
    #input_modal_container,
    #path_input_modal_container {
        width: 90;
        max-width: 90vw;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1;
        align: center middle;
    }

    #large_view_container {
        width: 90%;
        height: 90%;
        border: thick $primary;
        background: $surface;
        padding: 1;
    }

    .modal_buttons { margin-top: 1; align: center middle; }
    """

    ai_queue_info = reactive("AI Queue: Idle")

    BINDINGS = [
        Binding("escape",   "quit",              "Quit",          show=False),
        Binding("q",        "quit",              "Quit",          show=False),
        Binding("ctrl+q",   "quit",              "Quit",          show=False),
        Binding("f1",       "show_help",         "Help"),
        Binding("n",        "new_session",       "New Session"),
        Binding("p",        "switch_provider",   "Switch"),
        Binding("o",        "toggle_archive",    "Archive"),
        Binding("b",        "toggle_view",       "Tree/List"),
        Binding("l",        "refresh_list",      "Refresh"),
        Binding("g",        "clean_empty_sessions", "Clean Empty"),
        Binding("[",        "shrink_list",       "Shrink",        show=False),
        Binding("]",        "expand_list",       "Expand",        show=False),
        Binding("pageup",   "page_up",           "Page Up",       show=False),
        Binding("pagedown", "page_down",         "Page Down",     show=False),
        Binding("S",        "toggle_range",      "Range Check (Shift+S)", show=True),
        Binding("A",        "select_all",        "Select All (Shift+A)", show=False),
        Binding("C",        "clear_all",         "Clear All (Shift+C)",  show=False),
        Binding("E",        "toggle_exclude_workspace", "Ex/Inc W/S",     show=True),
        Binding("H",        "toggle_show_excluded", "Show Excluded (H)",  show=False),
        Binding("N",        "show_notifications", "Notification Log (N)", show=False),
        Binding("shift+space", "toggle_range",   "Range (S-Space)",       show=False),
        Binding("shift+down", "select_down",     "Select Down (S-↓)",     show=False),
        Binding("shift+up", "select_up",         "Select Up (S-↑)",       show=False),
        Binding("J",        "select_down",       "Select Down (J)",       show=False),
        Binding("K",        "select_up",         "Select Up (K)",         show=False),
    ]

    def __init__(self):
        super().__init__()
        from aitool.config import load_config
        self.config = load_config()
        self.provider: Optional[BaseProvider] = None
        self.sessions: List[BaseSession] = []
        self.filtered_sessions: List[BaseSession] = []
        self.checked_sessions: set[str] = set()
        self.show_archived = False
        self.is_tree_view = True
        self.excluded_workspaces: set[str] = set(self.config.get("excluded_workspaces", []))
        self.show_excluded: bool = False
        self.selected_session: Optional[BaseSession] = None
        self.list_width_fr = 40
        self.last_checked_path: Optional[str] = None
        self.notification_log = []
        self._pending_undo_action: Optional[dict] = None
        self._undo_timer = None
        self._ai_summary_queue = queue.Queue()
        self._ai_pending_count = 0
        self._ai_current_summary = ""
        # Why: update_list() 내 프로그래밍적 select_node()/index 변경이
        # NodeSelected/Selected 이벤트를 발생시켜 action_resume_session()이
        # 잘못 호출되는 것을 막기 위한 가드 플래그
        self._updating_list = False

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main_layout"):
            with Vertical(id="list_container"):
                yield Static("", id="fzf_header")
                yield SessionList(id="session_list")
                tree = SessionTree("Workspaces", id="session_tree")
                yield tree
                with Horizontal(id="search_bar"):
                    yield Label(">", id="prompt_symbol")
                    yield Input(placeholder="검색...", id="search_input")
            yield Rule(orientation="vertical")
            with Vertical(id="preview_container"):
                yield RichLog(id="preview_log", markup=True, wrap=True)
        yield Static("AI Queue: Idle", id="ai_status_bar")
        yield Static(CHEAT_SHEET_TEXT, id="cheat_sheet")

    def watch_ai_queue_info(self, info: str):
        """ai_queue_info 속성이 바뀔 때마다 하단 상태 바를 업데이트합니다."""
        try:
            self.query_one("#ai_status_bar", Static).update(info)
        except Exception:
            pass

    def action_open_ide(self):
        if not self.selected_session:
            return
        
        from aitool.config import load_config
        config = load_config()
        ide_cmd = config.get("ide_command", "code")
        
        try:
            subprocess.Popen(f"{ide_cmd} '{self.selected_session.cwd}'", shell=True)
            self.notify(f"IDE({ide_cmd})에서 워크스페이스를 열었습니다.")
        except Exception as e:
            logger.error(f"IDE 실행 실패: {e}\n{traceback.format_exc()}")
            self.notify(f"IDE 실행 실패: {e}", severity="error", markup=False)

    def action_focus_search(self):
        self.query_one("#search_input", Input).focus()

    def notify(self, message: str, title: str = "", severity: str = "information", timeout: float = 3.0, **kwargs):
        time_str = datetime.now().strftime("%H:%M:%S")
        self.notification_log.append((time_str, message, severity))
        if len(self.notification_log) > 50:
            self.notification_log.pop(0)
        super().notify(message, title=title, severity=severity, timeout=timeout, **kwargs)

    def action_show_notifications(self):
        self.push_screen(NotificationModal(self.notification_log))

    def on_mount(self):
        self._run_ai_summary_worker()

        def handle(provider: Optional[BaseProvider]):
            if provider is None:
                self.exit()
                return
            self.provider = provider
            self.title = f"AI Session Manager — {provider.name}"
            self.query_one("#prompt_symbol").styles.color = provider.color

            # Initial view setup
            if self.is_tree_view:
                self.query_one("#session_list").display = False
                self.query_one("#session_tree").display = True
            else:
                self.query_one("#session_list").display = True
                self.query_one("#session_tree").display = False

            self.load_sessions()

            if self.is_tree_view:
                self.query_one("#session_tree", Tree).focus()
            else:
                self.query_one("#session_list", ListView).focus()

        self.push_screen(LauncherScreen(), handle)

    def on_unmount(self):
        # AI 요약 워커 종료 신호
        self._ai_summary_queue.put(None)

    # ------------------------------------------------------------------
    # Keyboard: fzf 스타일 - 검색창 포커스 중에도 ↑/↓ 로 목록 탐색
    # ------------------------------------------------------------------

    def on_key(self, event: events.Key) -> None:
        if isinstance(self.screen, ModalScreen):
            # 모달이 활성화된 동안에는 앱 전역 키 핸들러 동작을 차단하여
            # 모달에서의 Enter 등이 부모로 버블링되어 원치 않는 동작을 유발하는 것을 방지함.
            return

        focused = self.focused

        # 1. 트리 뷰에 포커스가 있을 때 (Command Mode)
        if self.is_tree_view and isinstance(focused, Tree) and focused.id == "session_tree":
            if event.key == "right":
                if focused.cursor_node:
                    focused.cursor_node.expand()
                event.stop()
            elif event.key == "left":
                if focused.cursor_node:
                    focused.cursor_node.collapse()
                event.stop()
            elif event.key == "enter":
                if focused.cursor_node:
                    data = focused.cursor_node.data
                    if isinstance(data, BaseSession):
                        self.action_resume_session()
                    else:
                        focused.cursor_node.toggle()
                event.stop()
            elif event.key in ("space", "x"):
                self.action_toggle_check()
                event.stop()
            elif event.key == "d":
                self.action_delete_or_archive()
                event.stop()
            elif event.key == "s":
                self.action_restore_session()
                event.stop()
            elif event.key in ("m", "w"):
                self.action_move_session()
                event.stop()
            elif event.key == "r":
                self.action_rename_session()
                event.stop()
            elif event.key == "a":
                self.action_ai_summary()
                event.stop()
            elif event.key == "v":
                self.action_view_large()
                event.stop()
            elif event.key == "e":
                self.action_export_md()
                event.stop()
            elif event.key == "y":
                self.action_copy_last()
                event.stop()
            elif event.key == "slash":
                self.query_one("#search_input", Input).focus()
                event.stop()
            elif event.key in ("q", "escape"):
                self.action_quit()
                event.stop()
            return

        # 2. 리스트 뷰에 포커스가 있을 때 (Command Mode)
        if not self.is_tree_view and isinstance(focused, ListView) and focused.id == "session_list":
            if event.key == "enter":
                self.action_resume_session()
                event.stop()
            elif event.key in ("space", "x"):
                self.action_toggle_check()
                event.stop()
            elif event.key == "d":
                self.action_delete_or_archive()
                event.stop()
            elif event.key == "s":
                self.action_restore_session()
                event.stop()
            elif event.key in ("m", "w"):
                self.action_move_session()
                event.stop()
            elif event.key == "r":
                self.action_rename_session()
                event.stop()
            elif event.key == "a":
                self.action_ai_summary()
                event.stop()
            elif event.key == "v":
                self.action_view_large()
                event.stop()
            elif event.key == "e":
                self.action_export_md()
                event.stop()
            elif event.key == "y":
                self.action_copy_last()
                event.stop()
            elif event.key == "slash":
                self.query_one("#search_input", Input).focus()
                event.stop()
            elif event.key in ("q", "escape"):
                self.action_quit()
                event.stop()
            return

        # 3. 검색창(Input)에 포커스가 있을 때 (Search Mode / fzf 스타일)
        if not (isinstance(focused, Input) and focused.id == "search_input"):
            return

        if event.key == "escape" or event.key == "tab":
            if self.is_tree_view:
                self.query_one("#session_tree", Tree).focus()
            else:
                self.query_one("#session_list", ListView).focus()
            event.stop()
            return

        if self.is_tree_view:
            tree = self.query_one("#session_tree", Tree)
            if event.key == "up":
                tree.action_cursor_up()
                event.stop()
            elif event.key == "down":
                tree.action_cursor_down()
                event.stop()
            elif event.key == "enter":
                if tree.cursor_node:
                    data = tree.cursor_node.data
                    if isinstance(data, BaseSession):
                        self.action_resume_session()
                    else:
                        tree.cursor_node.toggle()
                event.stop()
            return

        session_list = self.query_one("#session_list", ListView)
        total = len(self.filtered_sessions)

        if event.key == "up":
            if session_list.index is not None and session_list.index > 0:
                session_list.index -= 1
                self._sync_selection()
            event.stop()
        elif event.key == "down":
            if session_list.index is not None:
                if session_list.index < total - 1:
                    session_list.index += 1
                    self._sync_selection()
            elif total > 0:
                session_list.index = 0
                self._sync_selection()
            event.stop()
        elif event.key == "enter":
            self.action_resume_session()
            event.stop()

    def _sync_selection(self):
        session_list = self.query_one("#session_list", ListView)
        idx = session_list.index
        if idx is None:
            return

        # 3.3 날짜별 그룹화로 인한 인덱스 오프셋 보정 (Phase 3)
        # Why: disabled=True 인 헤더 아이템들이 ListView 에 섞여 있으므로
        # 실제 데이터인 self.filtered_sessions 의 인덱스와 1:1 매칭되지 않음.
        data_idx = 0
        for i in range(idx):
            if not session_list.children[i].disabled:
                data_idx += 1
        
        if 0 <= data_idx < len(self.filtered_sessions):
            self.selected_session = self.filtered_sessions[data_idx]
            self.update_preview()

    # ------------------------------------------------------------------
    # Session Loading & Filtering
    # ------------------------------------------------------------------

    def load_sessions(self, filter_text: str = ""):
        if self.provider is None:
            return
        self.sessions = self.provider.load_sessions(self.show_archived)
        
        # 3.2 자동 AI 제목 생성 (Phase 3)
        if self.config.get("auto_ai_summary", False):
            for s in self.sessions:
                # "No Summary" 이고 메시지가 있으며 이미 큐에 없는 경우만 추가
                if s.summary == "No Summary" and len(s.messages) > 0:
                    # 중복 방지를 위한 간단한 체크 (이전에 큐에 넣었던 세션 ID를 추적하는 set 필요할 수 있음)
                    # 여기서는 단순하게 put 함 (큐 워커가 중복 처리 시 이점이 있을 수 있음)
                    self._ai_pending_count += 1
                    self._ai_summary_queue.put(s)
            
            if self._ai_pending_count > 0:
                self.ai_queue_info = f"AI Queue: {self._ai_pending_count}개 자동 요약 중"
        
        self.update_list(filter_text)

    def update_list(self, filter_text: str = ""):
        self._updating_list = True

        def shorten_path(path: str, max_len: int = 40) -> str:
            if not path or path == "Unknown":
                return path
            # 1. 홈 디렉토리 치환 (~/)
            home = str(Path.home())
            if path.startswith(home):
                path = path.replace(home, "~", 1)

            if len(path) <= max_len:
                return path

            # 2. 경로가 너무 길면 중간 생략 (e.g., ~/a/b/c/d -> ~/a/.../d)
            parts = path.split(os.sep)
            if len(parts) > 3:
                # 첫 부분, 중간 생략 표시, 마지막 두 부분 유지
                return os.sep.join([parts[0], "...", parts[-2], parts[-1]])
            return path

        temp_sessions = []
        pending_paths = set()
        if self._pending_undo_action:
            pending_paths = {str(s.file_path) for s in self._pending_undo_action.get("targets", [])}

        for s in self.sessions:
            if not self.show_excluded and s.workspace_name in self.excluded_workspaces:
                continue
            if str(s.file_path) in pending_paths:
                continue
            temp_sessions.append(s)

        if filter_text:
            q = filter_text.lower()
            self.filtered_sessions = [
                s for s in temp_sessions
                if q in s.date_str.lower()
                or q in s.workspace_name.lower()
                or q in s.summary.lower()
                or q in s.full_text.lower()
            ]
        else:
            self.filtered_sessions = temp_sessions

        session_list = self.query_one("#session_list", ListView)
        session_list.clear()

        session_tree = self.query_one("#session_tree", Tree)

        # 1. 현재 선택된 노드 및 확장 상태 저장 (새로고침 시 위치 복구용)
        saved_selected_id = None
        saved_list_index = -1
        saved_tree_line = -1

        if self.is_tree_view:
            saved_tree_line = session_tree.cursor_line
            selected_node = session_tree.cursor_node
            if selected_node and selected_node != session_tree.root:
                if isinstance(selected_node.data, BaseSession):
                    saved_selected_id = ("session", str(selected_node.data.file_path))
                else:
                    # 워크스페이스 노드 (접두어 제거 후 이름만 저장)
                    label_str = str(selected_node.label)
                    # Why: str(node.label)은 Rich 마크업 이스케이프 해제 후 반환되어
                    # "\[ ] " 가 아닌 "[ ] " 형태로 오므로 이스케이프 없는 prefix로 비교
                    for prefix in ["[x] ", "[ ] ", "[-] "]:
                        if label_str.startswith(prefix):
                            label_str = label_str[len(prefix):]
                            break
                    label_str = label_str.removesuffix(" ⊘")
                    saved_selected_id = ("workspace", label_str)
        else:
            if hasattr(session_list, "index") and session_list.index is not None:
                saved_list_index = session_list.index
            if self.selected_session:
                saved_selected_id = ("session", str(self.selected_session.file_path))

        expanded_workspaces = set()
        for node in session_tree.root.children:
            if node.is_expanded:
                label_str = str(node.label)
                for prefix in ["[x] ", "[ ] ", "[-] "]:
                    if label_str.startswith(prefix):
                        label_str = label_str[len(prefix):]
                        break
                label_str = label_str.removesuffix(" ⊘")
                expanded_workspaces.add(label_str)

        session_tree.clear()

        mode_label = "보관함" if self.show_archived else "활성"
        view_label = "TREE" if self.is_tree_view else "LIST"
        provider_name = self.provider.name if self.provider else "Unknown"
        self.query_one("#fzf_header", Static).update(
            f"  [{provider_name} | {mode_label} | {view_label}] 총 {len(self.filtered_sessions)}개"
        )

        # 1. 동일한 워크스페이스명이지만 경로가 다른 경우를 식별
        ws_name_paths = {}
        for s in self.filtered_sessions:
            ws_name_paths.setdefault(s.workspace_name, set()).add(s.cwd)

        unique_ws_labels = {}
        for s in self.filtered_sessions:
            if len(ws_name_paths[s.workspace_name]) > 1:
                short_cwd = shorten_path(s.cwd)
                unique_ws_labels[s.cwd] = f"{s.workspace_name} ({short_cwd})"
            else:
                unique_ws_labels[s.cwd] = s.workspace_name

        workspace_map = {}
        target_node_to_select = None
        target_list_index = -1
        last_date_group = None

        for i, s in enumerate(self.filtered_sessions):
            prefix = "[Archived] " if s.is_archived else ""
            ws_display_name = unique_ws_labels[s.cwd]

            check_mark = r"\[x]" if str(s.file_path) in self.checked_sessions else r"\[ ]"
            is_excluded = s.workspace_name in self.excluded_workspaces

            # 하이라이팅 적용 (escape 처리된 문자열에 적용)
            h_ws_name = self._highlight_text(escape(ws_display_name), filter_text)
            h_prefix = self._highlight_text(escape(prefix), filter_text)
            h_summary = self._highlight_text(escape(s.summary), filter_text)

            label_text = (
                f"{check_mark} {s.date_str}  [{h_ws_name}]  "
                f"{h_prefix}{h_summary}"
            )
            # Why: show_excluded 모드에서 제외 항목과 일반 항목이 구분되지 않아
            # 사용자가 어느 세션이 제외된 워크스페이스인지 파악하기 어려움
            if is_excluded:
                label_text = f"[dim]{label_text} ⊘[/dim]"
            
            # 3.3 날짜별 그룹화 (Phase 3) - ListView 전용 헤더
            if not self.is_tree_view and not filter_text:
                current_group = self._get_date_group(s.date_str)
                if current_group != last_date_group:
                    header_label = f"\n[b blue]── {current_group} ───────────────────[/]"
                    session_list.append(ListItem(Label(header_label), disabled=True))
                    last_date_group = current_group

            session_list.append(
                ListItem(Label(label_text, classes="item_label")))

            # ListView 선택 복구용
            if saved_selected_id == ("session", str(s.file_path)):
                target_list_index = i

            if ws_display_name not in workspace_map:
                # Restore expansion state if it was expanded before, or default to True if searching
                should_expand = ws_display_name in expanded_workspaces or bool(
                    filter_text)
                # Why: show_excluded 모드에서 제외된 워크스페이스를 한눈에 식별할 수 있도록
                # ⊘ 마커를 suffix로 추가. label 파싱 위치에서 removesuffix로 제거함
                is_ws_excluded = s.workspace_name in self.excluded_workspaces
                ws_suffix = " [bold red]⊘[/bold red]" if is_ws_excluded else ""
                
                h_ws_tree = self._highlight_text(escape(ws_display_name), filter_text)
                ws_node = session_tree.root.add(
                    f"\\[ ] {h_ws_tree}{ws_suffix}", expand=should_expand)
                workspace_map[ws_display_name] = ws_node

                # 워크스페이스 노드 선택 복구 확인
                if saved_selected_id == ("workspace", ws_display_name):
                    target_node_to_select = ws_node

            s_node = workspace_map[ws_display_name].add(
                f"{check_mark} {s.date_str} {h_prefix}{h_summary}", data=s)

            # 세션 노드 선택 복구 확인
            if saved_selected_id == ("session", str(s.file_path)):
                target_node_to_select = s_node

        self._refresh_checkbox_display()
        if self.filtered_sessions:
            if self.is_tree_view:
                if target_node_to_select:
                    session_tree.select_node(target_node_to_select)
                    session_tree.scroll_to_node(target_node_to_select)
                elif session_tree.root.children:
                    # 선택 복구가 안 된 경우 (e.g. 삭제됨) 저장된 라인 번호로 복구 시도
                    try:
                        session_tree.cursor_line = saved_tree_line
                        if session_tree.cursor_node:
                            session_tree.select_node(session_tree.cursor_node)
                            session_tree.scroll_to_node(session_tree.cursor_node)
                        else:
                            raise ValueError
                    except Exception:
                        first_ws = session_tree.root.children[0]
                        if first_ws.children:
                            session_tree.select_node(first_ws.children[0])
                        else:
                            session_tree.select_node(first_ws)
            else:
                if target_list_index >= 0:
                    session_list.index = target_list_index
                elif saved_list_index >= 0:
                    session_list.index = min(saved_list_index, len(self.filtered_sessions) - 1)
                else:
                    session_list.index = 0
                self.selected_session = self.filtered_sessions[session_list.index]
                self.update_preview()
        else:
            self.selected_session = None
            self.query_one("#preview_log", RichLog).clear()

        # Why: Textual 이벤트는 비동기 큐로 처리되므로, update_list 내에서
        # 발생한 NodeSelected/Selected 이벤트가 처리된 뒤 플래그를 해제해야 함.
        # call_later 대신 call_after_refresh를 사용하여 모든 렌더링/이벤트 처리가 끝난 후 실행되도록 보강.
        self.call_after_refresh(self._clear_updating_list)

    def _clear_updating_list(self):
        self._updating_list = False

    def _highlight_text(self, text: str, query: str) -> str:
        """Rich 마크업이 적용된 텍스트 내에서 검색어를 하이라이팅합니다."""
        if not query:
            return text
        # 대소문자 구분 없이 매칭하되, 원본의 대소문자는 유지함
        try:
            pattern = re.compile(re.escape(query), re.IGNORECASE)
            return pattern.sub(lambda m: f"[black on yellow]{m.group(0)}[/]", text)
        except Exception:
            return text

    def _get_date_group(self, date_str: str) -> str:
        """날짜 문자열을 기준으로 그룹 이름을 반환합니다."""
        if not date_str or date_str == "Unknown":
            return "기타"
        try:
            # Format: 2026-04-09 10:00
            dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
            now = datetime.now()
            diff = now - dt
            
            if diff.days == 0:
                return "오늘"
            elif diff.days == 1:
                return "어제"
            elif diff.days < 7:
                return "최근 7일"
            elif diff.days < 30:
                return "최근 30일"
            else:
                return dt.strftime("%Y년 %m월")
        except Exception:
            return "기타"

    def update_preview(self):
        log = self.query_one("#preview_log", RichLog)
        log.clear()
        if not self.selected_session:
            return
        try:
            s = self.selected_session
            # 세션 통계 헤더 (Phase 1.3)
            # Why: 세션의 메타데이터를 미리보기 상단에 상시 노출하여
            # 사용자가 세션의 규모와 맥락을 즉각적으로 파악할 수 있도록 함.
            stats_md = (
                f"> 📂 **Workspace:** `{s.cwd}`\n"
                f"> 💬 **Messages:** `{len(s.messages)}`  |  "
                f"🕒 **Updated:** `{s.date_str}`\n\n"
                f"---\n\n"
            )
            log.write(Markdown(stats_md + s.get_markdown(), code_theme="monokai"))
        except Exception as e:
            log.write(f"[red]미리보기 오류: {e}[/red]")

    def _refresh_checkbox_display(self):
        # Update session_list
        try:
            session_list = self.query_one("#session_list", SessionList)
            data_idx = 0
            for item in session_list.children:
                if isinstance(item, ListItem) and not item.disabled:
                    if data_idx < len(self.filtered_sessions):
                        s = self.filtered_sessions[data_idx]
                        is_checked = str(s.file_path) in self.checked_sessions
                        check_mark = r"\[x]" if is_checked else r"\[ ]"
                        label = item.query_one(Label)
                        text = getattr(label, "_Static__content", None)
                        if isinstance(text, str):
                            if text.startswith(r"\[x]") or text.startswith(r"\[ ]"):
                                label.update(check_mark + text[4:])
                        data_idx += 1
        except Exception:
            pass

        # Update session_tree
        try:
            tree = self.query_one("#session_tree", SessionTree)
            for ws_node in tree.root.children:
                all_checked = True
                any_checked = False
                for child_node in ws_node.children:
                    s = child_node.data
                    if isinstance(s, BaseSession):
                        is_checked = str(s.file_path) in self.checked_sessions
                        check_mark = r"\[x]" if is_checked else r"\[ ]"
                        label_text = str(child_node.label)
                        if label_text.startswith("[x]") or label_text.startswith("[ ]"):
                            child_node.set_label(check_mark + label_text[3:])
                        if is_checked:
                            any_checked = True
                        else:
                            all_checked = False

                # Update workspace node checkbox
                ws_label_text = str(ws_node.label)
                if ws_label_text.startswith("[x] ") or ws_label_text.startswith("[ ] ") or ws_label_text.startswith("[-] "):
                    ws_label_text = ws_label_text[4:]

                # Why: str(node.label)은 Rich 마크업을 제거한 plain text를 반환하므로
                # ⊘ suffix를 재조립할 때 bold red 마크업을 다시 적용해야 함
                ws_display_name = ws_label_text.removesuffix(" ⊘")
                ws_name = ws_display_name.rsplit(" (", 1)[0] if " (" in ws_display_name else ws_display_name
                ws_suffix = " [bold red]⊘[/bold red]" if ws_name in self.excluded_workspaces else ""

                if all_checked and ws_node.children:
                    ws_node.set_label(r"\[x] " + ws_display_name + ws_suffix)
                elif any_checked:
                    ws_node.set_label(r"\[-] " + ws_display_name + ws_suffix)
                else:
                    ws_node.set_label(r"\[ ] " + ws_display_name + ws_suffix)
        except Exception:
            pass
    # ------------------------------------------------------------------
    # Event Handlers
    # ------------------------------------------------------------------

    @on(ListView.Highlighted)
    def on_list_view_highlighted(self, event: ListView.Highlighted):
        if not self.is_tree_view:
            self._sync_selection()

    @on(Tree.NodeHighlighted, "#session_tree")
    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted):
        if self.is_tree_view:
            data = event.node.data
            if isinstance(data, BaseSession):
                self.selected_session = data
                self.update_preview()
            else:
                self.selected_session = None
                log = self.query_one("#preview_log", RichLog)
                log.clear()

    @on(ListView.Selected, "#session_list")
    def on_session_list_selected(self, event: ListView.Selected):
        if not self.is_tree_view and not self._updating_list:
            self.action_resume_session()

    @on(Tree.NodeSelected, "#session_tree")
    def on_tree_node_selected(self, event: Tree.NodeSelected):
        if self.is_tree_view and not self._updating_list:
            data = event.node.data
            if isinstance(data, BaseSession):
                self.action_resume_session()
            else:
                # Textual Tree handles toggle automatically on select in many versions,
                # but if it doesn't, we can keep it. Based on user report of "immediately collapses",
                # it's likely toggling twice. Let's make it smarter.
                pass

    @on(Input.Changed, "#search_input")
    def on_search_changed(self, event: Input.Changed):
        self.update_list(event.value)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_toggle_check(self):
        # Why: Mass selection via checkboxes enables bulk operations (move, delete, archive)
        # across multiple sessions and workspaces, significantly increasing efficiency.
        if self.is_tree_view:
            tree = self.query_one("#session_tree", Tree)
            node = tree.cursor_node
            if not node:
                return
            data = node.data
            if isinstance(data, BaseSession):
                path_str = str(data.file_path)
                self.last_checked_path = path_str
                if path_str in self.checked_sessions:
                    self.checked_sessions.remove(path_str)
                else:
                    self.checked_sessions.add(path_str)
            else:
                # Workspace node toggle
                all_checked = True
                for child in node.children:
                    if isinstance(child.data, BaseSession) and str(child.data.file_path) not in self.checked_sessions:
                        all_checked = False
                        break
                if all_checked:
                    for child in node.children:
                        if isinstance(child.data, BaseSession):
                            self.checked_sessions.discard(str(child.data.file_path))
                else:
                    for child in node.children:
                        if isinstance(child.data, BaseSession):
                            self.checked_sessions.add(str(child.data.file_path))
        else:
            session_list = self.query_one("#session_list", ListView)
            idx = session_list.index
            if idx is not None:
                # 3.3 날짜별 그룹화로 인한 인덱스 오프셋 보정 (Phase 3)
                data_idx = 0
                for i in range(idx):
                    if not session_list.children[i].disabled:
                        data_idx += 1
                
                if 0 <= data_idx < len(self.filtered_sessions):
                    s = self.filtered_sessions[data_idx]
                    path_str = str(s.file_path)
                    self.last_checked_path = path_str
                    if path_str in self.checked_sessions:
                        self.checked_sessions.remove(path_str)
                    else:
                        self.checked_sessions.add(path_str)

        self._refresh_checkbox_display()

    def action_toggle_range(self) -> None:
        """Toggles a range of checkboxes from the last checked session to the current one."""
        if not self.last_checked_path:
            self.action_toggle_check()
            return

        if not self.is_tree_view:
            self.action_toggle_check()
            return

        tree = self.query_one("#session_tree", Tree)
        node = tree.cursor_node
        if not (node and node.data and isinstance(node.data, BaseSession)):
            return

        current_path = str(node.data.file_path)

        ordered_sessions = []

        def walk(n):
            if isinstance(n.data, BaseSession):
                ordered_sessions.append(n)
            for child in n.children:
                walk(child)

        walk(tree.root)

        try:
            idx_anchor = next(i for i, n in enumerate(ordered_sessions) if str(n.data.file_path) == self.last_checked_path)
            idx_current = next(i for i, n in enumerate(ordered_sessions) if str(n.data.file_path) == current_path)

            start, end = min(idx_anchor, idx_current), max(idx_anchor, idx_current)
            is_checking = self.last_checked_path in self.checked_sessions

            for i in range(start, end + 1):
                target_node = ordered_sessions[i]
                sid = str(target_node.data.file_path)
                if is_checking:
                    self.checked_sessions.add(sid)
                else:
                    self.checked_sessions.discard(sid)
        except (StopIteration, ValueError):
            self.action_toggle_check()

        self.last_checked_path = current_path
        self._refresh_checkbox_display()

    def action_select_down(self) -> None:
        """Moves cursor down and extends selection."""
        if self.is_tree_view:
            tree = self.query_one("#session_tree", Tree)
            if not self.last_checked_path and tree.cursor_node and tree.cursor_node.data:
                if isinstance(tree.cursor_node.data, BaseSession):
                    self.last_checked_path = str(tree.cursor_node.data.file_path)
            tree.action_cursor_down()
            self.action_toggle_range()

    def action_select_up(self) -> None:
        """Moves cursor up and extends selection."""
        if self.is_tree_view:
            tree = self.query_one("#session_tree", Tree)
            if not self.last_checked_path and tree.cursor_node and tree.cursor_node.data:
                if isinstance(tree.cursor_node.data, BaseSession):
                    self.last_checked_path = str(tree.cursor_node.data.file_path)
            tree.action_cursor_up()
            self.action_toggle_range()

    def action_toggle_view(self):
        self.is_tree_view = not self.is_tree_view
        session_list = self.query_one("#session_list", ListView)
        session_tree = self.query_one("#session_tree", Tree)

        if self.is_tree_view:
            session_list.display = False
            session_tree.display = True
            session_tree.focus()
        else:
            session_list.display = True
            session_tree.display = False
            session_list.focus()

        filter_text = self.query_one("#search_input", Input).value
        self.update_list(filter_text)
        mode = "트리" if self.is_tree_view else "리스트"
        self.notify(f"[{mode} 뷰]로 전환되었습니다.", markup=False)

    def action_show_help(self):
        self.push_screen(HelpScreen())

    def action_switch_provider(self):
        def handle(provider: Optional[BaseProvider]):
            if provider is None:
                return  # 취소 시 현재 provider 유지
            self.provider = provider
            self.title = f"AI Session Manager — {provider.name}"
            self.query_one("#prompt_symbol").styles.color = provider.color
            self.show_archived = False
            self.query_one("#search_input", Input).value = ""
            self.load_sessions()
            self.query_one("#session_list", ListView).focus()
            self.notify(f"{provider.name}으로 전환되었습니다.")

        self.push_screen(LauncherScreen(), handle)

    def action_toggle_archive(self):
        self.show_archived = not self.show_archived
        filter_text = self.query_one("#search_input", Input).value
        self.load_sessions(filter_text)
        mode = "보관함" if self.show_archived else "활성 목록"
        self.notify(f"[{mode}]으로 전환되었습니다.", markup=False)

    def action_toggle_show_excluded(self):
        self.show_excluded = not self.show_excluded
        filter_text = self.query_one("#search_input", Input).value
        self.update_list(filter_text)
        mode = "표시" if self.show_excluded else "숨김"
        self.notify(f"제외된 워크스페이스 [{mode}] 전환됨.", markup=False)

    def action_toggle_exclude_workspace(self):
        workspace_name = None
        if self.is_tree_view:
            tree = self.query_one("#session_tree", Tree)
            if tree.cursor_node:
                data = tree.cursor_node.data
                if isinstance(data, BaseSession):
                    workspace_name = data.workspace_name
                else:
                    label_str = str(tree.cursor_node.label)
                    for prefix in ["[ ] ", "[x] ", "[-] "]:
                        if label_str.startswith(prefix):
                            label_str = label_str[len(prefix):]
                            break
                    label_str = label_str.removesuffix(" ⊘")
                    if " (" in label_str:
                        workspace_name = label_str.rsplit(" (", 1)[0]
                    else:
                        workspace_name = label_str
        else:
            if self.selected_session:
                workspace_name = self.selected_session.workspace_name

        if workspace_name:
            if workspace_name in self.excluded_workspaces:
                self.excluded_workspaces.remove(workspace_name)
                self.notify(f"워크스페이스 포함됨: {workspace_name}", markup=False)
            else:
                self.excluded_workspaces.add(workspace_name)
                self.notify(f"워크스페이스 제외됨: {workspace_name}", markup=False)

            from aitool.config import load_config, save_config
            conf = load_config()
            conf["excluded_workspaces"] = list(self.excluded_workspaces)
            save_config(conf)

            filter_text = self.query_one("#search_input", Input).value
            self.update_list(filter_text)
        else:
            self.notify("워크스페이스를 선택해주세요.", severity="warning")

    def action_select_all(self):
        for s in self.filtered_sessions:
            self.checked_sessions.add(str(s.file_path))
        self._refresh_checkbox_display()
        self.notify(f"현재 목록의 {len(self.filtered_sessions)}개 세션 모두 선택됨.")

    def action_clear_all(self):
        self.checked_sessions.clear()
        self._refresh_checkbox_display()
        self.notify("모든 선택 해제됨.")

    def action_refresh_list(self):
        filter_text = self.query_one("#search_input", Input).value
        self.load_sessions(filter_text)
        self.notify("새로고침 완료")

    def action_clean_empty_sessions(self):
        if not isinstance(self.provider, ClaudeProvider):
            self.notify("이 기능은 Claude Code에서만 사용 가능합니다.", severity="warning")
            return

        empty_files = self.provider.find_empty_sessions()
        if not empty_files:
            self.notify("삭제할 빈 세션이 없습니다.")
            return

        def on_confirm(choice: str):
            if choice != "ok":
                return
            count = 0
            for f in empty_files:
                try:
                    f.unlink()
                    count += 1
                except Exception as e:
                    logger.error("빈 세션 삭제 실패: %s\n%s", e,
                                 traceback.format_exc())
            self.notify(f"{count}개 빈 세션을 삭제했습니다.")
            filter_text = self.query_one("#search_input", Input).value
            self.load_sessions(filter_text)

        self.push_screen(
            ChoiceModal(
                f"빈 세션 {len(empty_files)}개를 삭제합니다. 계속할까요?",
                [("삭제", "ok")],
            ),
            on_confirm,
        )

    def action_focus_preview(self):
        self.query_one("#preview_log", RichLog).focus()

    def action_focus_list(self):
        self.query_one("#search_input", Input).focus()

    def action_page_up(self):
        session_list = self.query_one("#session_list", ListView)
        if session_list.index is not None:
            session_list.index = max(0, session_list.index - 10)
            self._sync_selection()

    def action_page_down(self):
        session_list = self.query_one("#session_list", ListView)
        if session_list.index is not None:
            new_idx = min(len(self.filtered_sessions) -
                          1, session_list.index + 10)
            session_list.index = new_idx
            self._sync_selection()

    def action_shrink_list(self):
        self.list_width_fr = max(10, self.list_width_fr - 5)
        self.query_one(
            "#list_container").styles.width = f"{self.list_width_fr}fr"
        self.query_one(
            "#preview_container").styles.width = f"{100 - self.list_width_fr}fr"

    def action_expand_list(self):
        self.list_width_fr = min(90, self.list_width_fr + 5)
        self.query_one(
            "#list_container").styles.width = f"{self.list_width_fr}fr"
        self.query_one(
            "#preview_container").styles.width = f"{100 - self.list_width_fr}fr"

    def action_delete_or_archive(self):
        targets = []
        if self.checked_sessions:
            targets = [s for s in self.filtered_sessions if str(s.file_path) in self.checked_sessions]
        elif self.selected_session:
            targets = [self.selected_session]

        if not targets or self.provider is None:
            return

        # 이전 대기 중인 작업이 있다면 즉시 커밋
        if self._pending_undo_action:
            self._commit_pending_action()

        action_type = "delete" if targets[0].is_archived else "archive"
        desc = "영구 삭제" if action_type == "delete" else "보관"
        
        self._pending_undo_action = {
            "type": action_type,
            "targets": targets,
            "desc": desc
        }
        
        # UI 업데이트: 목록에서 즉시 제거
        filter_text = self.query_one("#search_input", Input).value
        self.update_list(filter_text)
        
        self.notify(f"{len(targets)}개 세션 {desc} 대기 중... [u] 취소 (5초)", timeout=5.0)
        
        # 5초 뒤 커밋 예약
        if self._undo_timer:
            self._undo_timer.stop()
        self._undo_timer = self.set_timer(5.0, self._commit_pending_action)

    def action_undo(self):
        if not self._pending_undo_action:
            return
        
        if self._undo_timer:
            self._undo_timer.stop()
            self._undo_timer = None
        
        desc = self._pending_undo_action["desc"]
        self._pending_undo_action = None
        
        # UI 업데이트: 목록 복구
        filter_text = self.query_one("#search_input", Input).value
        self.update_list(filter_text)
        self.notify(f"{desc} 작업이 취소되었습니다.")

    def _commit_pending_action(self):
        if not self._pending_undo_action or self.provider is None:
            return
        
        action_type = self._pending_undo_action["type"]
        targets = self._pending_undo_action["targets"]
        desc = self._pending_undo_action["desc"]
        self._pending_undo_action = None
        self._undo_timer = None
        
        count = 0
        for s in targets:
            try:
                if action_type == "delete":
                    self.provider.delete_session(s)
                else:
                    self.provider.archive_session(s)
                count += 1
                self.checked_sessions.discard(str(s.file_path))
            except Exception as e:
                logger.error(f"{desc} 실패: {e}\n{traceback.format_exc()}")
        
        if count > 0:
            # 이미 목록에서 제거된 상태이므로 알림만 표시 (세션 로드는 하지 않음, 필요시만 수행)
            self.notify(f"{count}개 세션 {desc} 완료", severity="warning" if action_type == "delete" else "information")
        
        # 실제 파일이 변경되었으므로 세션 목록 동기화 (백그라운드 데이터 갱신)
        self.load_sessions(self.query_one("#search_input", Input).value)

    def action_restore_session(self):
        targets = []
        if self.checked_sessions:
            targets = [s for s in self.filtered_sessions if str(s.file_path) in self.checked_sessions]
        elif self.selected_session:
            targets = [self.selected_session]

        if not targets or self.provider is None:
            return

        count = 0
        for s in targets:
            if not s.is_archived:
                continue
            try:
                self.provider.restore_session(s)
                count += 1
                self.checked_sessions.discard(str(s.file_path))
            except Exception as e:
                logger.error("복구 실패: %s\n%s", e, traceback.format_exc())

        if count > 0:
            self.notify(f"{count}개 세션이 복구(활성화)되었습니다.")
            filter_text = self.query_one("#search_input", Input).value
            self.load_sessions(filter_text)
        elif not self.checked_sessions:
            self.notify("이미 활성화된 세션입니다.")

    def action_rename_session(self):
        if not self.selected_session or self.provider is None:
            return
        s = self.selected_session

        def handle_rename(new_title: str):
            if not new_title:
                return
            try:
                self.provider.rename_session(s, new_title)
                self.notify(f"제목 변경 완료: {new_title}", markup=False)
                filter_text = self.query_one("#search_input", Input).value
                self.load_sessions(filter_text)
            except Exception as e:
                logger.error("제목 변경 실패: %s\n%s", e, traceback.format_exc())
                self.notify(f"제목 변경 실패: {e}", severity="error", markup=False)

        self.push_screen(
            InputModal("새 제목을 입력하세요", placeholder="제목을 입력하세요",
                       default=s.summary),
            handle_rename,
        )

    @work(thread=True)
    def _run_ai_summary_worker(self):
        logger.info("AI 제목 요약 워커 시작")
        while True:
            try:
                s = self._ai_summary_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if s is None:
                logger.info("AI 제목 요약 워커 종료 신호 수신")
                break

            self._ai_pending_count = max(0, self._ai_pending_count - 1)
            self._ai_current_summary = s.summary
            self.ai_queue_info = f"AI Queue: 처리 중 [{s.summary}]" + (f" ({self._ai_pending_count}개 대기)" if self._ai_pending_count > 0 else "")

            logger.info(f"AI 요약 처리 시작: {s.session_id}")
            texts = s.extract_recent_texts(10)
            chat_content = "\n".join(texts)
            prompt = (
                "다음 대화 내용을 분석해서 아주 짧고 명확한 채팅방 제목"
                "(6단어 이하, 단답형, 따옴표 없이, 사족 없이 제목만 출력, 한국어로)으로 요약해줘:\n\n"
                + chat_content
            )

            try:
                new_title = self.provider.run_ai_summary(prompt)
                if not self.is_running:
                    break

                if new_title and new_title != "null":
                    new_title = f"✨ {new_title}"
                    self.provider.save_ai_summary(s, new_title)
                    s.summary = new_title  # 메모리 객체 즉시 업데이트
                    logger.info(f"AI 요약 완료: {s.session_id} -> {new_title}")
                    # 알림이 소실되지 않도록 확실히 호출
                    if self.is_running:
                        self.call_from_thread(self.notify, f"제목 생성 완료: {new_title}", markup=False)
                        # UI 목록 즉시 갱신 (스레드 세이프하게 현재 검색어 가져와서 반영)

                        def refresh_ui():
                            # s.summary는 이미 워커에서 업데이트됨 (s.summary = new_title)
                            if self.is_tree_view:
                                tree = self.query_one("#session_tree", Tree)
                                # 사용자가 도중에 다른 세션을 클릭했을 수 있으므로, s를 가진 노드를 명시적으로 찾음

                                def find_and_update(node):
                                    if node.data == s:
                                        prefix = "[Archived] " if s.is_archived else ""
                                        is_checked = str(s.file_path) in self.checked_sessions
                                        check_mark = r"\[x]" if is_checked else r"\[ ]"
                                        node.set_label(f"{check_mark} {s.date_str} {escape(prefix)}{escape(s.summary)}")
                                        return True
                                    for child in node.children:
                                        if find_and_update(child):
                                            return True
                                    return False

                                find_and_update(tree.root)
                            else:
                                list_view = self.query_one("#session_list", ListView)
                                for i, item in enumerate(list_view.children):
                                    if i < len(self.filtered_sessions) and self.filtered_sessions[i] == s:
                                        is_checked = str(s.file_path) in self.checked_sessions
                                        check_mark = r"\[x]" if is_checked else r"\[ ]"
                                        # 워크스페이스 명칭은 기존 라벨에서 추출하거나 단순화하여 표시
                                        prefix = "[Archived] " if s.is_archived else ""
                                        label_text = (
                                            f"{check_mark} {s.date_str}  {escape(f'[{s.workspace_name}]')}  "
                                            f"{escape(prefix)}{escape(s.summary)}"
                                        )
                                        item.query_one(Label).update(label_text)
                                        break

                            # 미리보기 갱신 (이미 객체가 바뀌었으므로 update_preview만 호출)
                            if self.selected_session == s:
                                self.update_preview()

                        self.call_from_thread(refresh_ui)
                else:
                    logger.warning(f"AI 요약 실패(결과 없음): {s.session_id}")
                    if self.is_running:
                        self.call_from_thread(
                            self.notify,
                            "AI 요약에 실패했습니다. (결과 없음)",
                            severity="error",
                        )
            except Exception as e:
                logger.error(f"AI 요약 예외({s.session_id}): {e}\n{traceback.format_exc()}")
                if self.is_running:
                    self.call_from_thread(
                        self.notify, f"AI 요약 오류: {e}", severity="error", markup=False)
            finally:
                self._ai_current_summary = ""
                if self._ai_pending_count > 0:
                    self.ai_queue_info = f"AI Queue: {self._ai_pending_count}개 대기 중"
                else:
                    self.ai_queue_info = "AI Queue: Idle"
                self._ai_summary_queue.task_done()
    def action_ai_summary(self):
        targets = []
        if self.checked_sessions:
            targets = [s for s in self.filtered_sessions if str(s.file_path) in self.checked_sessions]
        elif self.selected_session:
            targets = [self.selected_session]

        if not targets or self.provider is None:
            return

        for s in targets:
            self._ai_pending_count += 1
            self._ai_summary_queue.put(s)

        self.ai_queue_info = f"AI Queue: {self._ai_pending_count}개 대기 중" + (f" (처리 중: {self._ai_current_summary})" if self._ai_current_summary else "")
        if len(targets) > 1:
            self.notify(f"{len(targets)}개 세션 요약 요청이 큐에 추가되었습니다.")
        else:
            self.notify("AI 요약 요청이 큐에 추가되었습니다.")

    def action_view_large(self):
        if not self.selected_session:
            return
        self.push_screen(LargeViewModal(self.selected_session))

    def action_copy_last(self):
        if not self.selected_session:
            return
        s = self.selected_session
        if not s.messages:
            self.notify("복사할 메시지가 없습니다.", severity="warning")
            return
        text = s.get_last_message_text()
        try:
            pyperclip.copy(text)
            self.notify("마지막 답변이 클립보드에 복사되었습니다!")
        except Exception as e:
            logger.error("클립보드 복사 실패: %s\n%s", e, traceback.format_exc())
            self.notify(f"클립보드 복사 실패: {e}", severity="error", markup=False)

    def action_export_md(self):
        targets = []
        if self.checked_sessions:
            targets = [s for s in self.filtered_sessions if str(s.file_path) in self.checked_sessions]
        elif self.selected_session:
            targets = [self.selected_session]

        if not targets:
            return

        if len(targets) > 5:
            def on_confirm(choice: str):
                if choice == "ok":
                    self._perform_bulk_export(targets)
            self.push_screen(ChoiceModal(f"{len(targets)}개 세션을 마크다운으로 내보내시겠습니까?", [("내보내기", "ok")]), on_confirm)
        else:
            self._perform_bulk_export(targets)

    def _perform_bulk_export(self, targets: List[BaseSession]):
        success_count = 0
        for s in targets:
            if self._do_export_md(s):
                success_count += 1
        
        if len(targets) > 1:
            self.notify(f"{success_count}개 세션 저장 완료 (현재 경로)")
        elif success_count == 0:
            self.notify("내보내기 실패", severity="error")

    def _do_export_md(self, s: BaseSession) -> bool:
        """단일 세션을 마크다운으로 저장합니다. 성공 여부를 반환합니다."""
        safe_title = "".join(
            c if (c.isalnum() or "\uac00" <= c <= "\ud7a3") else "_"
            for c in s.summary
        ).strip("_") or "ai_session"
        date_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
        # 중복 방지를 위해 session_id 일부 추가
        export_path = Path.cwd() / f"{safe_title}_{date_tag}_{s.session_id[:4]}.md"
        try:
            with open(export_path, "w", encoding="utf-8") as f:
                f.write(f"# {s.summary}\n\n")
                f.write(
                    f"> Exported on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"> Session: {s.session_id}\n")
                f.write(f"> Workspace: {s.cwd}\n\n")
                f.write(s.get_markdown())
            if len(self.checked_sessions) <= 1:  # 단일 저장 시에만 파일명 표시
                self.notify(f"저장 완료: {export_path.name}", markup=False)
            return True
        except Exception as e:
            logger.error("내보내기 실패: %s\n%s", e, traceback.format_exc())
            if len(self.checked_sessions) <= 1:
                self.notify(f"내보내기 실패: {e}", severity="error", markup=False)
            return False

    def action_move_session(self):
        targets = []
        if self.checked_sessions:
            targets = [s for s in self.filtered_sessions if str(s.file_path) in self.checked_sessions]
        elif self.selected_session:
            targets = [self.selected_session]

        if not targets or self.provider is None:
            return

        s_ref = targets[0]
        workspaces = self.provider.get_workspaces(s_ref.cwd if len(targets) == 1 else "")
        cwd_list = [cwd for cwd, _ in workspaces]

        choices: List[Tuple[str, str]] = [
            (f"{Path(cwd).name}  ({cwd})", str(i)) for i, cwd in enumerate(cwd_list)
        ]
        choices.append(("직접 경로 입력...", "manual"))

        def handle_workspace(choice: str):
            if not choice:
                return
            if choice == "manual":
                self.push_screen(
                    PathInputModal(
                        "대상 워크스페이스 절대 경로 입력",
                        placeholder="/absolute/path/to/project",
                    ),
                    lambda path: self._confirm_move_copy(
                        targets, path) if path else None,
                )
            else:
                try:
                    dest_cwd = cwd_list[int(choice)]
                    self._confirm_move_copy(targets, dest_cwd)
                except (ValueError, IndexError):
                    pass

        self.push_screen(ChoiceModal(
            f"대상 워크스페이스 선택 ({len(targets)}개 세션)", choices), handle_workspace)

    def _confirm_move_copy(self, targets: List[BaseSession], dest_cwd: str):
        dest_cwd = dest_cwd.strip()
        try:
            dest_cwd = str(Path(dest_cwd).expanduser())
        except Exception:
            pass
        if not dest_cwd or (len(targets) == 1 and dest_cwd == targets[0].cwd):
            self.notify("현재와 동일한 워크스페이스입니다.", severity="warning")
            return

        choices: List[Tuple[str, str]] = [
            (f"복사 (Copy)  →  {Path(dest_cwd).name}", "copy"),
            (f"이동 (Move)  →  {Path(dest_cwd).name}", "move"),
        ]

        def handle_action(action: str):
            if not action:
                return
            self._do_move_copy(targets, dest_cwd, move=(action == "move"))

        self.push_screen(ChoiceModal("작업 선택", choices), handle_action)

    def _do_move_copy(self, targets: List[BaseSession], dest_cwd: str, move: bool = False):
        if self.provider is None:
            return
        count = 0
        for s in targets:
            try:
                self.provider.move_copy_session(s, dest_cwd, move)
                count += 1
                if move:
                    self.checked_sessions.discard(str(s.file_path))
            except Exception as e:
                logger.error("이동/복사 실패: %s\n%s", e, traceback.format_exc())

        if count > 0:
            self.notify(f"{count}개 세션 {'이동' if move else '복사'} 완료 → {Path(dest_cwd).name}", markup=False)
            filter_text = self.query_one("#search_input", Input).value
            self.load_sessions(filter_text)
        else:
            self.notify(f"{'이동' if move else '복사'} 실패", severity="error")

    def action_new_session(self):
        if self.provider is None:
            return

        workspaces = self.provider.get_workspaces("")
        cwd_list = [cwd for cwd, _ in workspaces]

        choices: List[Tuple[str, str]] = [
            (f"{Path(cwd).name}  ({cwd})", str(i)) for i, cwd in enumerate(cwd_list)
        ]
        choices.insert(0, ("수동 경로 입력 (새 워크스페이스)...", "manual"))

        def handle_workspace(choice: str):
            if not choice:
                return
            if choice == "manual":
                self.push_screen(
                    PathInputModal(
                        "새 세션을 시작할 워크스페이스 절대 경로 입력",
                        placeholder="/absolute/path/to/project",
                    ),
                    lambda path: self._start_new_session(
                        path) if path else None,
                )
            else:
                try:
                    dest_cwd = cwd_list[int(choice)]
                    self._start_new_session(dest_cwd)
                except (ValueError, IndexError):
                    pass

        self.push_screen(ChoiceModal(
            "새 세션을 시작할 워크스페이스 선택", choices), handle_workspace)

    def _start_new_session(self, cwd: str):
        cwd = cwd.strip()
        try:
            cwd = str(Path(cwd).expanduser().resolve())
        except Exception:
            pass
        if not cwd or not Path(cwd).is_dir():
            self.notify(f"유효하지 않은 경로입니다: {cwd}", severity="error", markup=False)
            return
        command = self.provider.get_new_session_command(cwd)
        self._open_in_new_terminal(command)

    def action_resume_session(self):
        if not self.selected_session or self.provider is None:
            return
        s = self.selected_session
        self.selected_session = None  # 이중 호출 방지
        if s.cwd == "Unknown" or not Path(s.cwd).exists():
            self.selected_session = s  # 실패 시 복구
            self.notify(f"프로젝트 폴더를 찾을 수 없습니다: {s.cwd}", severity="error", markup=False)
            return
        command = self.provider.get_resume_command(s)
        self._open_in_new_terminal(command)

    def _open_in_new_terminal(self, command: str):
        mode = self.config.get("terminal_open_mode", "window")
        try:
            if sys.platform == "darwin":
                # Why: AppleScript string에 command를 직접 삽입하면 경로의 따옴표·백슬래시로
                # 구문이 깨지거나 의도치 않은 스크립트가 실행될 수 있어 사전 이스케이프 필요
                command = command.replace("\\", "\\\\").replace('"', '\\"')
                # Why: iTerm2는 /Applications 또는 ~/Applications 어디에도 설치 가능하므로
                # 두 경로를 모두 검사한다.
                _iterm_candidates = [
                    Path("/Applications/iTerm.app"),
                    Path("/Applications/iTerm 2.app"),
                    Path.home() / "Applications" / "iTerm.app",
                    Path.home() / "Applications" / "iTerm 2.app",
                ]
                iterm_exists = any(p.exists() for p in _iterm_candidates)
                
                if iterm_exists:
                    if mode == "tab":
                        # Why: create tab with default profile command 구문은 현재 iTerm2에서
                        # AppleEvent timeout(-1712)을 유발하므로, create tab 후 write text로
                        # 명령을 전달하는 2단계 방식을 사용한다.
                        applescript = f'''
                        tell application "iTerm"
                            if (count windows) is 0 then
                                create window with default profile command "{command}"
                            else
                                tell current window
                                    set newTab to (create tab with default profile)
                                    tell current session of newTab
                                        write text "{command}"
                                    end tell
                                end tell
                            end if
                            activate
                        end tell
                        '''
                    else:
                        # iTerm2 New Window
                        applescript = f'''
                        tell application "iTerm"
                            create window with default profile command "{command}"
                            activate
                        end tell
                        '''
                    subprocess.Popen(["osascript", "-e", applescript])
                    self.notify(f"iTerm2 {'새 탭' if mode == 'tab' else '새 창'}에서 세션이 열렸습니다.")
                else:
                    # Fallback to Apple Terminal.app
                    if mode == "tab":
                        applescript = f'''
                        tell application "Terminal"
                            if (count windows) is 0 then
                                do script "{command}"
                            else
                                activate
                                tell application "System Events" to keystroke "t" using command down
                                delay 0.2
                                do script "{command}" in front window
                            end if
                            activate
                        end tell
                        '''
                    else:
                        applescript = f'''
                        tell application "Terminal"
                            do script "{command}"
                            activate
                        end tell
                        '''
                    subprocess.Popen(["osascript", "-e", applescript])
                    self.notify(f"Terminal {'새 탭' if mode == 'tab' else '새 창'}에서 세션이 열렸습니다.")

            elif os.name == "nt":
                subprocess.Popen(["start", "cmd", "/k", command], shell=True)
                self.notify("새 커맨드 창에서 세션이 열렸습니다.")
            else:
                subprocess.Popen(["x-terminal-emulator", "-e", command])
                self.notify("새 터미널 창에서 세션이 열렸습니다.")
        except Exception as e:
            logger.error("새 터미널 실행 실패: %s\n%s", e, traceback.format_exc())
            self.notify(f"새 터미널 실행 실패: {e}", severity="error", markup=False)
