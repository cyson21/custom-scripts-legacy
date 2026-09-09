import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from orchestrator.agents.swarm import run_swarm_logic
from orchestrator.core.models import DeploymentUnit, ExecutionMode, SynthesisProposal


class MockController:
    """
    Minimal controller stub covering all attributes and methods
    that run_swarm_logic touches.
    """
    def __init__(self, workspace_dir: str):
        self.global_status = ""
        self.logs = []
        self.workspace_dir = workspace_dir
        self.total_tokens = 0
        self.emergency_stop = asyncio.Event()
        self.blueprint_approved = asyncio.Event()
        self.blueprint_approved.set()   # auto-approve blueprint
        self.is_interactive = False     # skip interactive blueprint wait
        self.current_blueprint = ""

    def set_global_status(self, status: str):
        self.global_status = status

    def add_log(self, agent: str, msg: str):
        self.logs.append((agent, msg))

    def set_task_status(self, task: str, status: str):
        pass

    def add_tokens(self, n: int):
        self.total_tokens += n

    def register_agent(self, *args, **kwargs):
        pass

    def update_agent_status(self, *args, **kwargs):
        pass


def _make_agent_mock(ask_side_effect=None, ask_return=None):
    """Helper: AsyncMock agent whose ask() is controllable."""
    agent = MagicMock()
    if ask_side_effect is not None:
        agent.ask = AsyncMock(side_effect=ask_side_effect)
    else:
        agent.ask = AsyncMock(return_value=ask_return or "agent output")
    return agent


@pytest.mark.asyncio
async def test_swarm_recursive_loop_success(tmp_path):
    """
    Verifies that run_swarm_logic terminates after a single round
    when the judge responds with APPROVE.

    AgentFactory.create call order (1 unit, PARALLEL mode):
      call 1  → architect (blueprint)
      call 2  → unit.engine (round-1 execution)
      call 3  → "judge"    (round-1 evaluation → APPROVE)
    """
    controller = MockController(str(tmp_path))
    units = [DeploymentUnit(engine="gemini", persona="engineer")]

    blueprint_agent = _make_agent_mock(ask_return="Blueprint: fix the bug")
    exec_agent      = _make_agent_mock(ask_return="Patch applied")
    judge_agent     = _make_agent_mock(ask_return="APPROVE: solution looks correct")

    synth_mock = MagicMock()
    synth_mock.synthesize  = AsyncMock(return_value=SynthesisProposal(
        proposal_id="test", agents_involved=[], synthesized_diff="synthesized_diff_v1"
    ))
    synth_mock.apply_final = AsyncMock()

    with patch("orchestrator.agents.swarm.SandboxManager"),         \
         patch("orchestrator.agents.swarm.CodeIndexer"),             \
         patch("orchestrator.agents.swarm.SwarmEventLogger"),        \
         patch("orchestrator.agents.swarm.SynthesisEngine",
               return_value=synth_mock),                             \
         patch("orchestrator.agents.swarm.AgentFactory.create",
               side_effect=[blueprint_agent, exec_agent, judge_agent]), \
         patch("orchestrator.core.storage.RegistryManager.register_session"):

        await run_swarm_logic(controller, "Fix bug", units)

    # Judge approved in the first round → exactly 1 call each
    assert exec_agent.ask.call_count  == 1, "Execution agent should run exactly once"
    assert judge_agent.ask.call_count == 1, "Judge should be called exactly once"

    # Synthesis should have been triggered once and its result applied
    assert synth_mock.synthesize.call_count  == 1
    assert synth_mock.apply_final.call_count == 1

    # Final status reflects completion
    assert controller.global_status == "미션 완료"


@pytest.mark.asyncio
async def test_swarm_recursive_loop_refinement(tmp_path):
    """
    Verifies that run_swarm_logic runs an additional round when the
    judge challenges, and terminates on the second APPROVE.

    AgentFactory.create call order (1 unit, 2 rounds):
      call 1  → architect  (blueprint)
      call 2  → unit.engine (round-1 execution)
      call 3  → "judge"     (round-1 → CHALLENGE)
      call 4  → unit.engine (round-2 execution)
      call 5  → "judge"     (round-2 → APPROVE)
    """
    controller = MockController(str(tmp_path))
    units = [DeploymentUnit(engine="gemini", persona="engineer")]

    blueprint_agent  = _make_agent_mock(ask_return="Blueprint")
    exec_agent_r1    = _make_agent_mock(ask_return="Round-1 patch")
    exec_agent_r2    = _make_agent_mock(ask_return="Round-2 patch (revised)")
    judge_agent_r1   = _make_agent_mock(ask_return="CHALLENGE: missing edge case handling")
    judge_agent_r2   = _make_agent_mock(ask_return="APPROVE: edge case now covered")

    synth_mock = MagicMock()
    synth_mock.synthesize  = AsyncMock(side_effect=[
        SynthesisProposal(proposal_id="r1", agents_involved=[], synthesized_diff="diff_r1"),
        SynthesisProposal(proposal_id="r2", agents_involved=[], synthesized_diff="diff_r2")
    ])
    synth_mock.apply_final = AsyncMock()

    with patch("orchestrator.agents.swarm.SandboxManager"),         \
         patch("orchestrator.agents.swarm.CodeIndexer"),             \
         patch("orchestrator.agents.swarm.SwarmEventLogger"),        \
         patch("orchestrator.agents.swarm.SynthesisEngine",
               return_value=synth_mock),                             \
         patch("orchestrator.agents.swarm.AgentFactory.create",
               side_effect=[
                   blueprint_agent,
                   exec_agent_r1, judge_agent_r1,   # round 1
                   exec_agent_r2, judge_agent_r2,   # round 2
               ]),                                                   \
         patch("orchestrator.core.storage.RegistryManager.register_session"):

        await run_swarm_logic(controller, "Fix bug", units)

    # Each round's execution agent ran once
    assert exec_agent_r1.ask.call_count == 1, "Round-1 exec agent ran once"
    assert exec_agent_r2.ask.call_count == 1, "Round-2 exec agent ran once"

    # Judge was called once per round
    assert judge_agent_r1.ask.call_count == 1
    assert judge_agent_r2.ask.call_count == 1

    # Synthesis ran for both rounds; apply_final only on approval
    assert synth_mock.synthesize.call_count  == 2
    assert synth_mock.apply_final.call_count == 1

    # Feedback from round-1 challenge was passed into round-2 context
    r2_call_args = exec_agent_r2.ask.call_args
    r2_prompt = r2_call_args.args[0] if r2_call_args.args else r2_call_args.kwargs.get("prompt", "")
    assert "CHALLENGE" in r2_prompt, "Round-2 prompt should contain round-1 challenge feedback"

    assert controller.global_status == "미션 완료"
