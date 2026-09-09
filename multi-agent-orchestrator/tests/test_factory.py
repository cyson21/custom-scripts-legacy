import pytest
import os
from unittest.mock import patch
from orchestrator.agents.adapters.factory import AgentFactory
from orchestrator.agents.io_provider import (
    AutoAgentAdapter, FallbackAgentProvider)


def test_factory_creates_gemini():
    agent = AgentFactory.create("gemini")
    assert isinstance(agent, FallbackAgentProvider)


def test_factory_creates_codex():
    agent = AgentFactory.create("codex")
    assert isinstance(agent, AutoAgentAdapter)


def test_factory_creates_shell_agent(tmp_path):
    # Mock search dirs to look in tmp_path
    script_path = tmp_path / "mistral.sh"
    script_path.write_text("#!/bin/bash\necho 'hello'")
    os.chmod(script_path, 0o755)

    with patch(
            "orchestrator.agents.adapters.factory.AgentFactory"
            "._find_shell_script",
            return_value=script_path):
        agent = AgentFactory.create("mistral")
        assert isinstance(agent, AutoAgentAdapter)


def test_factory_unknown_agent():
    with pytest.raises(ValueError) as exc:
        AgentFactory.create("unknown_agent")
    assert "Unknown agent engine" in str(exc.value)


if __name__ == "__main__":
    pytest.main([__file__])
