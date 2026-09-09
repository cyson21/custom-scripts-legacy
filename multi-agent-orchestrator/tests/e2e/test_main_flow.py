import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from orchestrator.core.state import OrchestratorState
from orchestrator.cli.app import main_loop
from orchestrator.core.models import ExecutionMode

@pytest.mark.asyncio
async def test_e2e_full_mission_flow(mock_ui):
    """
    Fixtures를 활용한 메인 미션 플로우 전수 검증.
    """
    # 1. 시퀀스 입력 설정 (Main Menu -> Start -> WS -> Prompt -> Agent Setup -> Mode -> Menu -> Quit)
    mock_ui["radio"].side_effect = [
        "start",       # 메인 메뉴
        ".",           # 워크스페이스
        "gemini",      # 아키텍트 엔진
        "engineer",    # 팀원 추가
        "claude",      # 엔지니어 엔진
        "1",           # 인원수
        "__done__",    # 추가 완료
        "parallel",    # 실행 모드
        "menu",        # 후속 조치
        "quit"         # 메인 메뉴 종료
    ]
    
    # 2. 텍스트 입력 및 대화창 설정
    future_mission = asyncio.Future()
    future_mission.set_result("Headless Test Mission")
    mock_ui["session"].return_value.prompt_async.return_value = future_mission
    
    future_confirm = asyncio.Future()
    future_confirm.set_result(True)
    mock_ui["yes_no"].return_value.run_async.return_value = future_confirm
    
    # 3. 실제 미션 실행 로직 모킹 (네트워크 호출 방지)
    with patch("orchestrator.cli.app.execute_mission", new_callable=AsyncMock) as mock_exec, \
         patch("orchestrator.cli.app.console.print"):
        
        mock_exec.return_value = "session_123"
        
        # 4. 실행 (타임아웃 설정을 통해 무한 대기 방지)
        try:
            await asyncio.wait_for(main_loop(), timeout=5.0)
        except asyncio.TimeoutError:
            pytest.fail("Test timed out! main_loop did not exit correctly.")

        # 5. 검증
        assert mock_exec.called
        args, _ = mock_exec.call_args
        assert args[1] == "Headless Test Mission"
        assert len(args[2]) == 2 # architect + 1 engineer
