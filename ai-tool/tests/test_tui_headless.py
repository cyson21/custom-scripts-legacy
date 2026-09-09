import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from aitool.ui.app import AiTool
from aitool.ui.launcher import LauncherScreen
from pathlib import Path
from datetime import datetime
from aitool.models import BaseSession

@pytest.mark.asyncio
async def test_tui_headless_basic_startup():
    """TUI Headless Basic Startup Test."""
    app = AiTool()
    async with app.run_test(size=(120, 60)) as pilot:
        assert isinstance(app.screen, LauncherScreen)
        await pilot.press("1")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, LauncherScreen)
        assert app.provider is not None
        assert app.provider.short_name == "gemini"
        from textual.widgets import Input
        search_input = app.screen.query_one("#search_input", Input)
        assert search_input is not None

class DummySession(BaseSession):
    def __init__(self, p: str):
        self.file_path = Path(p)
        self.session_id = str(self.file_path.name)
        self.cwd = '/fake/cwd'
        self.workspace_name = 'fake_workspace'
        self.is_archived = False
        self.summary = 'Dummy Summary'
        self.date_str = '2025-01-01 12:00'
        self.messages = []
        self._full_text = None
    def _compute_full_text(self): return ''
    def get_markdown(self): return 'markdown'
    def extract_recent_texts(self, n=10): return []
    def get_last_message_text(self): return ''

@pytest.mark.asyncio
async def test_checkbox_toggle():
    """체크박스 토글 기능 검증 (Command Mode)"""
    app = AiTool()
    async with app.run_test(size=(120, 60)) as pilot:
        # Select Gemini
        await pilot.press("1")
        await pilot.pause(0.2)

        # Inject dummy sessions
        s1 = DummySession('/fake/dir/session1.json')
        s1.date_str = "2025-01-01 10:00"
        s2 = DummySession('/fake/dir/session2.json')
        s2.date_str = "2025-01-01 12:00"
        app.sessions = [s1, s2]

        # Change view to list and update
        app.is_tree_view = False
        app.update_list()
        await pilot.pause(0.1)

        from textual.widgets import ListView, Label
        session_list = app.screen.query_one("#session_list", ListView)
        session_list.focus()

        # Find session 1 index
        target_idx = -1
        for i, child in enumerate(session_list.children):
            if not child.disabled:
                lbl = child.query_one(Label)
                if s1.date_str in str(lbl.render()):
                    target_idx = i
                    break
        
        assert target_idx != -1
        session_list.index = target_idx
        app._sync_selection()
        # Wait for reactive selection to finish
        await pilot.pause(0.2)
        assert session_list.index == target_idx
        assert app.selected_session.file_path == s1.file_path
        
        # Press space to toggle check
        await pilot.press("space")
        await pilot.pause(0.2)
        assert str(s1.file_path) in app.checked_sessions
        label_text = str(session_list.children[target_idx].query_one(Label).render())
        assert "[x]" in label_text

        # Toggle again
        await pilot.press("space")
        await pilot.pause(0.1)
        assert str(s1.file_path) not in app.checked_sessions
        label_text2 = str(session_list.children[target_idx].query_one(Label).render())
        assert "[ ]" in label_text2

@pytest.mark.asyncio
async def test_search_highlighting():
    """검색어 하이라이팅 기능 검증"""
    app = AiTool()
    async with app.run_test(size=(120, 60)) as pilot:
        # Select Gemini
        await pilot.press("1")
        await pilot.pause(0.5)

        # Inject dummy sessions via mock
        s1 = DummySession('/fake/dir/abc_session.json')
        s1.summary = 'Hello World'
        s1.workspace_name = 'test-ws'
        
        app.provider.load_sessions = lambda archived=False: [s1]
        app.load_sessions()
        
        # Use List View
        app.is_tree_view = False
        app.update_list()
        await pilot.pause(0.2)
        
        # Verify initial state
        from textual.widgets import ListView, Label
        session_list = app.screen.query_one("#session_list", ListView)
        # Find first non-disabled (not header) item
        target_item = None
        for child in session_list.children:
            if not child.disabled:
                target_item = child
                break
        
        label = target_item.query_one(Label)
        assert "Hello World" in str(label.render())

        # Set search input value directly to test highlighting
        from textual.widgets import Input
        app.query_one("#search_input", Input).value = "hello"
        app.update_list("hello")
        await pilot.pause(0.5)

        # Get the label markup again
        target_item_search = None
        for child in session_list.children:
            if not child.disabled:
                target_item_search = child
                break
        
        label = target_item_search.query_one(Label)
        markup = getattr(label, "_Static__content", "")
        
        # 'Hello' should be highlighted
        assert "[black on yellow]Hello[/]" in markup

@pytest.mark.asyncio
async def test_bulk_actions():
    """다중 세션 일괄 작업(AI 요약, 내보내기) 검증"""
    app = AiTool()
    async with app.run_test(size=(120, 60)) as pilot:
        # Select Gemini
        await pilot.press("1")
        await pilot.pause(0.5)

        # Inject dummy sessions
        s1 = DummySession('/fake/dir/bulk1.json')
        s2 = DummySession('/fake/dir/bulk2.json')
        app.provider.load_sessions = lambda archived=False: [s1, s2]
        app.load_sessions()
        app.is_tree_view = False
        app.update_list()
        await pilot.pause(0.2)

        # Check all sessions
        app.checked_sessions.add(str(s1.file_path))
        app.checked_sessions.add(str(s2.file_path))
        
        # 1. Bulk AI Summary
        app.action_ai_summary()
        # Check if items are in queue
        assert app._ai_pending_count + app._ai_summary_queue.qsize() >= 2
        
        # 2. Bulk Export
        from unittest.mock import patch, mock_open
        with patch("builtins.open", mock_open()):
            app.action_export_md()
            await pilot.pause(0.1)

@pytest.mark.asyncio
async def test_session_stats():
    """세션 통계 정보 표시(Phase 1.3) 검증"""
    app = AiTool()
    async with app.run_test(size=(120, 60)) as pilot:
        # Select Gemini
        await pilot.press("1")
        await pilot.pause(0.5)

        # Inject dummy session
        s1 = DummySession('/fake/dir/stats.json')
        s1.cwd = "/absolute/fake/path"
        s1.messages = [{"a": 1}, {"b": 2}, {"c": 3}]
        s1.date_str = "2026-04-09 10:00"
        
        app.provider.load_sessions = lambda archived=False: [s1]
        app.load_sessions()
        app.is_tree_view = False
        app.update_list()
        await pilot.pause(0.2)
        
        from textual.widgets import RichLog
        assert app.screen.query_one("#preview_log", RichLog) is not None
        assert app.selected_session == s1

@pytest.mark.asyncio
async def test_phase2_features():
    """Phase 2 UX 기능 검증 (IDE 연동, 알림 이력, 구문 강조)"""
    app = AiTool()
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.press("1")
        await pilot.pause(0.5)

        s1 = DummySession('/fake/dir/phase2.json')
        s1.cwd = "/absolute/fake/path"
        app.provider.load_sessions = lambda archived=False: [s1]
        app.load_sessions()
        app.is_tree_view = False
        app.update_list()
        await pilot.pause(0.2)

        # 2.3 Notification Log
        app.notify("Test Notification 123", severity="information")
        assert len(app.notification_log) > 0
        assert app.notification_log[-1][1] == "Test Notification 123"

        # 2.2 IDE 연동
        from unittest.mock import patch
        with patch("subprocess.Popen") as mock_popen:
            app.action_open_ide()
            await pilot.pause(0.1)
            mock_popen.assert_called_once()

@pytest.mark.asyncio
async def test_phase3_features():
    """Phase 3 UX 기능 검증 (Undo, 자동 요약, 날짜 그룹화)"""
    app = AiTool()
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.press("1")
        await pilot.pause(0.5)

        s1 = DummySession('/fake/dir/phase3.json')
        s1.cwd = "/absolute/fake/path"
        app.provider.load_sessions = lambda archived=False: [s1]
        app.load_sessions()
        app.is_tree_view = False
        app.update_list()
        await pilot.pause(0.2)

        # 3.1 Undo
        app.action_delete_or_archive()
        assert app._pending_undo_action is not None
        assert s1 not in app.filtered_sessions
        
        app.action_undo()
        assert app._pending_undo_action is None
        assert any(s.file_path == s1.file_path for s in app.filtered_sessions)

        # 3.3 날짜 그룹화
        today_str = datetime.now().strftime("%Y-%m-%d 10:00")
        group = app._get_date_group(today_str)
        assert group == "오늘"


# ── PathInputModal 헤드리스 테스트 ─────────────────────────────────────

import tempfile
from textual.app import App
from textual.widgets import Input, OptionList
from aitool.ui.modals import PathInputModal

class _PathModalTestApp(App):
    def on_mount(self) -> None:
        self.push_screen(PathInputModal("테스트 경로 입력"))

def _set_input(modal, value: str) -> None:
    inp = modal.query_one("#path_modal_input", Input)
    inp.value = value
    inp.cursor_position = len(value)
    modal._update_completions(value)

@pytest.mark.asyncio
async def test_path_input_modal_completions_shown():
    with tempfile.TemporaryDirectory() as tmpdir:
        import os as _os
        _os.makedirs(_os.path.join(tmpdir, "alpha"))
        _os.makedirs(_os.path.join(tmpdir, "beta"))
        app = _PathModalTestApp()
        async with app.run_test(size=(80, 30)) as pilot:
            modal = app.screen
            _set_input(modal, tmpdir + "/")
            await pilot.pause(0.1)
            ol = modal.query_one("#path_completions", OptionList)
            assert ol.option_count >= 2
            prompts = [str(ol.get_option_at_index(i).prompt) for i in range(ol.option_count)]
            assert any("alpha" in p for p in prompts)
            assert any("beta" in p for p in prompts)

@pytest.mark.asyncio
async def test_path_input_modal_tab_single_completion():
    with tempfile.TemporaryDirectory() as tmpdir:
        import os as _os
        _os.makedirs(_os.path.join(tmpdir, "only_dir"))
        app = _PathModalTestApp()
        async with app.run_test(size=(80, 30)) as pilot:
            modal = app.screen
            _set_input(modal, _os.path.join(tmpdir, "only"))
            await pilot.pause(0.1)
            await pilot.press("tab")
            await pilot.pause(0.1)
            inp = modal.query_one("#path_modal_input", Input)
            assert inp.value.endswith("only_dir/")

@pytest.mark.asyncio
async def test_path_input_modal_no_completions_invalid_path():
    app = _PathModalTestApp()
    async with app.run_test(size=(80, 30)) as pilot:
        modal = app.screen
        _set_input(modal, "/non/existent/path/xyz")
        await pilot.pause(0.1)
        ol = modal.query_one("#path_completions", OptionList)
        assert ol.option_count == 0

@pytest.mark.asyncio
async def test_path_input_modal_escape_dismiss():
    dismissed = []

    class TrackingApp(App):
        def on_mount(self):
            modal = PathInputModal("ESC 테스트")
            self.push_screen(modal, lambda v: dismissed.append(v))
    app = TrackingApp()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.press("escape")
        await pilot.pause(0.1)
    assert dismissed == [""]
