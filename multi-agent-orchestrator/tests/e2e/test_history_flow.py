import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from orchestrator.core.state import OrchestratorState
from orchestrator.core.history import SessionMetadata
from orchestrator.cli.app import main_loop

@pytest.mark.asyncio
async def test_e2e_history_flow(mock_ui, monkeypatch):
    """
    히스토리 메뉴 전수 검증: 세션 선택 및 상세 보기 플로우.
    """
    state = OrchestratorState()
    # Mocking history manager
    fake_session = SessionMetadata(id="session_1", title="Test Mission 1", timestamp="2026-04-08T12:00:00")
    state.history_manager.list_sessions = MagicMock(return_value=[fake_session])
    state.history_manager.get_session = MagicMock(return_value=MagicMock(get_markdown=lambda: "Fake markdown context"))
    
    monkeypatch.setattr("orchestrator.cli.app.OrchestratorState", lambda: state)

    # 입력 시퀀스:
    # main menu -> history
    # history list -> session_1 (searchable)
    # session menu -> view
    # session menu -> back
    # history list -> __back__ (searchable)
    # main menu -> quit
    mock_ui["radio"].side_effect = ["history", "view", "back", "quit"]
    mock_ui["search"].side_effect = ["session_1", "__back__"]
    
    with patch("orchestrator.cli.app.console.print"):
        try:
            await asyncio.wait_for(main_loop(), timeout=5.0)
        except asyncio.TimeoutError:
            pytest.fail("History flow test timed out!")

    assert state.history_manager.list_sessions.called
    assert state.history_manager.get_session.called
    assert mock_ui["search"].call_count == 2
