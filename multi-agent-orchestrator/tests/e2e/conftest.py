import pytest
from unittest.mock import MagicMock, AsyncMock
from orchestrator.core.state import OrchestratorState

@pytest.fixture
def mock_settings_and_discovery(monkeypatch):
    """
    Prevents E2E tests from reading/writing real settings during UI flows.
    """
    monkeypatch.setattr(OrchestratorState, "load_settings", lambda self: None)
    monkeypatch.setattr(OrchestratorState, "save_settings", lambda self: None)
    monkeypatch.setattr(OrchestratorState, "discover_models", AsyncMock())
    
    from orchestrator.core.cli_registry import CLIRegistry
    monkeypatch.setattr(CLIRegistry, "_discover", lambda self, name: None)
    monkeypatch.setattr(OrchestratorState, "run_preflight", lambda self: True)

@pytest.fixture
def mock_ui(monkeypatch, mock_settings_and_discovery):
    """Provides a centralized way to mock all interactive UI components."""
    mock_radio = AsyncMock()
    mock_search = AsyncMock()
    mock_yes_no = MagicMock()
    mock_btn = MagicMock()
    mock_session = MagicMock()
    
    monkeypatch.setattr("orchestrator.cli.app.inline_radio_dialog", mock_radio)
    monkeypatch.setattr("orchestrator.cli.app.inline_searchable_radio_dialog", mock_search)
    monkeypatch.setattr("orchestrator.cli.app.yes_no_dialog", mock_yes_no)
    monkeypatch.setattr("orchestrator.cli.app.button_dialog", mock_btn)
    monkeypatch.setattr("orchestrator.cli.app.PromptSession", mock_session)
    # Mock global built-in input()
    monkeypatch.setattr("builtins.input", lambda *args: "")
    
    return {
        "radio": mock_radio,
        "search": mock_search,
        "yes_no": mock_yes_no,
        "button": mock_btn,
        "session": mock_session
    }
