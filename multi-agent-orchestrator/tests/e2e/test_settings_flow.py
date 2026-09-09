import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from orchestrator.core.state import OrchestratorState
from orchestrator.cli.app import main_loop

@pytest.mark.asyncio
async def test_e2e_settings_flow(mock_ui, monkeypatch):
    """
    설정 메뉴 전수 검증: 
    Autonomous 모드 변경 및 Default Judge 선택 시 옵션이 정상 노출되는지 확인.
    """
    # 전역 상태 모킹 (discovery 결과를 미리 주입)
    state = OrchestratorState()
    state.available_gemini_models = ["gemini-3.1-pro", "gemini-1.5-flash"]
    state.available_engines = ["gemini", "claude"]
    
    # main_loop 내부의 state 인스턴스를 우리가 제어하는 인스턴스로 대체
    monkeypatch.setattr("orchestrator.cli.app.OrchestratorState", lambda: state)

    # 입력 시퀀스:
    # main menu -> settings
    # settings -> autonomous_mode -> true
    # settings -> default_judge -> gemini-3.1-pro
    # settings -> back
    # main menu -> quit
    mock_ui["radio"].side_effect = [
        "settings",
        "autonomous_mode", "true",
        "default_judge", "gemini-3.1-pro",
        "back",
        "quit"
    ]
    
    with patch("orchestrator.cli.app.console.print"):
        try:
            await asyncio.wait_for(main_loop(), timeout=5.0)
        except asyncio.TimeoutError:
            pytest.fail("Settings flow test timed out!")

    # 검증: 상태가 올바르게 변경되었는가
    assert state.autonomous_mode is True
    assert state.default_judge == "gemini-3.1-pro"
    
    # 중요: Default Judge 선택 시 빈 리스트가 아니었는가 검증
    # 0: Main Menu, 1: Settings(Select Mode), 2: Mode Toggle, 3: Settings(Select Judge), 4: Judge Model List
    args, kwargs = mock_ui["radio"].call_args_list[4]
    # Position 2 is 'values'
    options = args[2] if len(args) > 2 else kwargs.get('values', [])
    assert len(options) > 0, "Default Judge 선택 옵션이 비어 있습니다!"
    assert any("gemini-3.1-pro" in str(opt) for opt in options)
