import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from orchestrator.core.state import OrchestratorState
from orchestrator.core.models import ExecutionMode
from orchestrator.core.history import SessionMetadata
from orchestrator.cli.app import setup_mission, show_history, main_loop
from orchestrator.agents.swarm import run_swarm_logic
from orchestrator.core.models import DeploymentUnit, SynthesisProposal
from contextlib import contextmanager

@pytest.fixture(autouse=True)
def mock_settings(monkeypatch):
    monkeypatch.setattr(OrchestratorState, "load_settings", lambda self: None)

@contextmanager
def patch_swarm_deps():
    """Helper to patch all external dependencies of run_swarm_logic."""
    with patch("orchestrator.agents.swarm.SwarmEventLogger"), \
         patch("orchestrator.agents.swarm.CodeIndexer") as mock_indexer, \
         patch("orchestrator.agents.swarm.SynthesisEngine") as mock_synth_cls, \
         patch("orchestrator.agents.swarm.SandboxManager"), \
         patch("orchestrator.agents.swarm.Path"), \
         patch("orchestrator.core.storage.RegistryManager"):
        
        # Mock SynthesisEngine instance methods
        mock_synth = mock_synth_cls.return_value
        mock_synth.synthesize.return_value = asyncio.Future()
        mock_synth.synthesize.return_value.set_result(SynthesisProposal(
            proposal_id="test",
            agents_involved=[],
            synthesized_diff="diff contents"
        ))
        mock_synth.apply_final.return_value = asyncio.Future()
        mock_synth.apply_final.return_value.set_result(None)
        
        yield

@pytest.mark.asyncio
async def test_run_swarm_logic_parallel():
    controller = MagicMock()
    controller.workspace_dir = "."
    controller.total_tokens = 0
    controller.max_rounds = 3
    controller.emergency_stop.is_set.return_value = False
    
    units = [DeploymentUnit(persona="engineer", engine="gemini")]
    
    with patch("orchestrator.agents.swarm.AgentFactory.create") as mock_factory:
        mock_agent = MagicMock()
        mock_agent.ask.return_value = asyncio.Future()
        mock_agent.ask.return_value.set_result("APPROVE")
        mock_factory.return_value = mock_agent
        
        with patch_swarm_deps():
            await run_swarm_logic(
                controller,
                "Test prompt",
                units,
                execution_mode=ExecutionMode.PARALLEL
            )
            
            assert controller.set_task_status.called
            assert mock_agent.ask.called

@pytest.mark.asyncio
async def test_run_swarm_logic_relay():
    controller = MagicMock()
    controller.workspace_dir = "."
    controller.total_tokens = 0
    controller.max_rounds = 3
    controller.emergency_stop.is_set.return_value = False
    
    units = [
        DeploymentUnit(persona="engineer", engine="gemini"),
        DeploymentUnit(persona="reviewer", engine="claude")
    ]
    
    with patch("orchestrator.agents.swarm.AgentFactory.create") as mock_factory:
        mock_agent = MagicMock()
        mock_agent.ask.return_value = asyncio.Future()
        mock_agent.ask.return_value.set_result("APPROVE")
        mock_factory.return_value = mock_agent
        
        with patch_swarm_deps():
            await run_swarm_logic(
                controller,
                "Test prompt",
                units,
                execution_mode=ExecutionMode.DISCUSSION
            )
            
            # architect (blueprint) + engineer + reviewer + judge
            assert mock_agent.ask.call_count >= 3 

@pytest.mark.asyncio
async def test_run_swarm_logic_max_rounds():
    controller = MagicMock()
    controller.workspace_dir = "."
    controller.total_tokens = 0
    controller.max_rounds = 2
    controller.emergency_stop.is_set.return_value = False
    
    units = [DeploymentUnit(persona="engineer", engine="gemini")]
    
    with patch("orchestrator.agents.swarm.AgentFactory.create") as mock_factory:
        mock_agent = MagicMock()
        mock_agent.ask.return_value = asyncio.Future()
        # Always return feedback, never APPROVE
        mock_agent.ask.return_value.set_result("Need more work")
        mock_factory.return_value = mock_agent
        
        with patch_swarm_deps():
            await run_swarm_logic(
                controller,
                "Test prompt",
                units,
                execution_mode=ExecutionMode.PARALLEL
            )
            
            # Should have run for 2 rounds
            assert controller.add_tokens.call_count == 2

@pytest.mark.asyncio
async def test_run_swarm_logic_emergency_stop():
    controller = MagicMock()
    controller.workspace_dir = "."
    controller.total_tokens = 0
    controller.max_rounds = 5
    # Simulate stop after first check
    controller.emergency_stop.is_set.side_effect = [False, True, True, True, True]
    
    units = [DeploymentUnit(persona="engineer", engine="gemini")]
    
    with patch("orchestrator.agents.swarm.AgentFactory.create") as mock_factory:
        mock_agent = MagicMock()
        mock_agent.ask.return_value = asyncio.Future()
        mock_agent.ask.return_value.set_result("Feedback")
        mock_factory.return_value = mock_agent
        
        with patch_swarm_deps():
            await run_swarm_logic(
                controller,
                "Test prompt",
                units,
                execution_mode=ExecutionMode.PARALLEL
            )
            
            # Should stop early
            assert controller.add_tokens.call_count <= 1

@pytest.mark.asyncio
async def test_run_swarm_logic_sandbox_failure():
    controller = MagicMock()
    controller.workspace_dir = "."
    
    with patch("orchestrator.agents.swarm.SandboxManager") as mock_sandbox:
        mock_sandbox.side_effect = Exception("Sandbox Error")
        
        with pytest.raises(Exception) as excinfo:
            await run_swarm_logic(controller, "Prompt", [])
        
        assert "Sandbox Error" in str(excinfo.value)
        controller.set_task_status.assert_called_with("sandbox_init", "FAILED: Sandbox Error")

@pytest.mark.asyncio
async def test_run_swarm_logic_agent_failure():
    controller = MagicMock()
    controller.workspace_dir = "."
    controller.max_rounds = 1
    controller.emergency_stop.is_set.return_value = False
    
    units = [DeploymentUnit(persona="engineer", engine="gemini")]
    
    with patch("orchestrator.agents.swarm.AgentFactory.create") as mock_factory:
        mock_agent = MagicMock()
        mock_agent.ask.side_effect = Exception("Agent API Error")
        mock_factory.return_value = mock_agent
        
        with patch_swarm_deps():
            # It shouldn't crash the whole thing, but log failure
            await run_swarm_logic(controller, "Prompt", units)
            
            # Check if failure was logged (by checking if _FAILURE.log would be written)
            # SynthesisEngine won't be called if agent fails
            # We check the 'finally' block still runs or the log is added
            controller.add_log.assert_any_call("system", "Error: Agent API Error")

@pytest.mark.asyncio
async def test_run_swarm_logic_indexing_failure():
    controller = MagicMock()
    controller.workspace_dir = "."
    controller.emergency_stop.is_set.return_value = False
    
    with patch("orchestrator.agents.swarm.CodeIndexer") as mock_indexer:
        mock_indexer.return_value.scan.side_effect = Exception("Indexing Error")
        
        # It should still proceed to blueprint generation or at least not crash the runner
        # but in swarm.py, indexing is before blueprint.
        units = [DeploymentUnit(persona="engineer", engine="gemini")]
        
        with patch("orchestrator.agents.swarm.AgentFactory.create") as mock_factory:
            mock_agent = MagicMock()
            mock_agent.ask.return_value = asyncio.Future()
            mock_agent.ask.return_value.set_result("APPROVE")
            mock_factory.return_value = mock_agent
            
            with patch_swarm_deps():
                # Re-patching Indexer inside patch_swarm_deps to use our side_effect
                with patch("orchestrator.agents.swarm.CodeIndexer", return_value=mock_indexer.return_value):
                    await run_swarm_logic(controller, "Prompt", units)
                
                # Check if it reported error but finished (manifest registration in finally)
                controller.add_log.assert_any_call("system", "Error: Indexing Error")

@pytest.mark.asyncio
async def test_setup_mission_empty_prompt():
    state = OrchestratorState()
    state.history_manager = MagicMock()
    state.history_manager.list_sessions.return_value = []
    
    with patch("orchestrator.cli.app.inline_radio_dialog", new_callable=AsyncMock) as mock_radio:
        mock_radio.return_value = "."

        with patch("orchestrator.cli.app.PromptSession") as mock_session:
            future_prompt = asyncio.Future()
            future_prompt.set_result("")
            mock_session.return_value.prompt_async = MagicMock(return_value=future_prompt)
            
            prompt, units, mode = await setup_mission(state)
            assert prompt is None
            assert units is None
            assert mode is None

@pytest.mark.asyncio
async def test_setup_mission_success():
    state = OrchestratorState()
    state.discover_resources = MagicMock()
    state.available_personas = ["architect", "engineer"]
    state.history_manager = MagicMock()
    state.history_manager.list_sessions.return_value = []
    
    with patch("orchestrator.cli.app.PromptSession") as mock_session:
        future_ws_prompt = asyncio.Future()
        future_ws_prompt.set_result("/tmp")
        
        future_mission = asyncio.Future()
        future_mission.set_result("Fix bugs")
        
        mock_session.return_value.prompt_async.side_effect = [future_ws_prompt, future_mission]
        
        with patch("orchestrator.cli.app.inline_radio_dialog", new_callable=AsyncMock) as mock_radio:
            mock_radio.side_effect = [
                "__new__", 
                "gemini", # leader engine
                "engineer", 
                "gemini", 
                "1", 
                "__done__", 
                ExecutionMode.PARALLEL.value
            ]

            with patch("orchestrator.cli.app.yes_no_dialog") as mock_yes_no:
                future_confirm = asyncio.Future()
                future_confirm.set_result(True)
                mock_yes_no.return_value.run_async = MagicMock(return_value=future_confirm)

                with patch("orchestrator.cli.app.input", return_value=""): # mock flowchart wait
                    prompt, units, mode = await setup_mission(state)
                    assert prompt == "Fix bugs"
                    assert len(units) == 2
                    assert units[0].persona == "architect"
                    assert units[0].engine == "gemini"
                    assert units[1].persona == "engineer"
                    assert units[1].engine == "gemini"
                    assert mode == ExecutionMode.PARALLEL
                    assert state.workspace_dir == "/tmp"

@pytest.mark.asyncio
async def test_show_history_no_sessions():
    state = OrchestratorState()
    state.history_manager.list_sessions = MagicMock(return_value=[])
    
    with patch("orchestrator.cli.app.console.print") as mock_print:
        await show_history(state)
        mock_print.assert_called_once()

@pytest.mark.asyncio
async def test_show_history_with_sessions():
    state = OrchestratorState()
    fake_session_meta = SessionMetadata(
        id="test-id",
        title="Test Session",
        timestamp="2026-03-24T12:00:00Z"
    )
    state.history_manager.list_sessions = MagicMock(return_value=[fake_session_meta])
    
    mock_session = MagicMock()
    mock_session.get_markdown.return_value = "Old context"
    state.history_manager.get_session = MagicMock(return_value=mock_session)
    
    with patch("orchestrator.cli.app.inline_searchable_radio_dialog", new_callable=AsyncMock) as mock_searchable, \
         patch("orchestrator.cli.app.inline_radio_dialog", new_callable=AsyncMock) as mock_radio:
        
        # First choice: select a session (searchable). 
        # Second choice: followup (radio). 
        # Third: back to exit inner loop (radio).
        # Fourth: __back__ to exit outer loop (searchable).
        mock_searchable.side_effect = ["test-id", "__back__"]
        mock_radio.side_effect = ["followup", "back"]
        
        with patch("orchestrator.cli.app.setup_mission") as mock_setup:
            mock_setup.return_value = (None, None, None) # simulate cancel at prompt
            
            await show_history(state)
            
            assert mock_searchable.call_count == 2
            assert mock_radio.call_count == 2
            mock_setup.assert_called_once()
            state.history_manager.get_session.assert_called_once_with("test-id", include_archived=True)
            mock_session.get_markdown.assert_called_once()

@pytest.mark.asyncio
async def test_main_loop_quit():
    with patch("orchestrator.cli.app.inline_radio_dialog", new_callable=AsyncMock) as mock_radio:
        mock_radio.return_value = "quit"
        
        # We also need to mock OrchestratorState methods that get called on init
        with patch("orchestrator.cli.app.OrchestratorState") as mock_state_cls:
            mock_state = MagicMock()
            future_discover = asyncio.Future()
            future_discover.set_result(None)
            mock_state.discover_models = MagicMock(return_value=future_discover)
            mock_state_cls.return_value = mock_state
            
            # This should immediately break out of the loop and return
            await main_loop()
            
            mock_radio.assert_called_once()
            mock_state.run_preflight.assert_called_once()
            mock_state.discover_models.assert_called_once()
