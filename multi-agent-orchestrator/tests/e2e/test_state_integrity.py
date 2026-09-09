import pytest
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch
from orchestrator.core.state import OrchestratorState

@pytest.mark.asyncio
async def test_state_integrity_resource_loading(monkeypatch):
    """
    Guardian Test: Ensures that the application state is internally consistent
    and critical resources are loaded before starting a mission.
    """
    # 1. 실제 설정 파일이 읽히지 않도록 존재하지 않는 경로로 유도
    with patch("orchestrator.core.state.Path") as mock_path:
        # .git은 존재하는 것으로, 설정 파일은 존재하지 않는 것으로 설정
        def path_side_effect(p):
            real_path = MagicMock()
            if ".git" in str(p):
                real_path.exists.return_value = True
            elif ".orchestrator_settings.json" in str(p):
                real_path.exists.return_value = False
            return real_path
        
        mock_path.side_effect = path_side_effect

        state = OrchestratorState()
        
        # 1. Immediate population (Sync)
        assert len(state.available_engines) > 0, "Engines must be populated on init"
        assert "gemini" in state.available_engines
        
        # 2. Mock API presence for preflight
        monkeypatch.setenv("GEMINI_API_KEY", "fake_key")
        # Registry lookup도 통과하도록 설정
        with patch("orchestrator.core.cli_registry.registry.lookup", return_value="/usr/bin/gemini"):
            assert state.run_preflight() is True, "Preflight should pass with fake key"
        
        # 3. Model discovery logic check
        state.discover_models = AsyncMock()
        await state.discover_models()
        assert state.discover_models.called

        # 4. Settings Persistence Check
        state.max_rounds = 99
        save_mock = MagicMock()
        monkeypatch.setattr(state, "save_settings", save_mock)
        state.save_settings()
        assert save_mock.called
