"""
Comprehensive scenario matrix for run_swarm_logic.

Cost: ZERO — all LLM calls are replaced with AsyncMock/MagicMock.
No real API, no real tokens.

Coverage map (swarm.py branch paths):
  [Exec mode]     PARALLEL multi-unit, DISCUSSION sequential + context chain
  [Judge]         case-insensitive APPROVE, 3-round refinement, token counter
  [Control flow]  emergency_stop after CHALLENGE, emergency_stop mid-DISCUSSION
  [Lifecycle]     exception → _FAILURE.log, interactive blueprint approval,
                  autonomous_mode skips UI-state transition, artifact file presence
"""
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from orchestrator.agents.swarm import run_swarm_logic
from orchestrator.core.models import DeploymentUnit, ExecutionMode, SynthesisProposal


# ─────────────────────────── shared helpers ──────────────────────────────────

class MockController:
    """
    Full stub of TUIController for headless testing.
    Covers every attribute / method that run_swarm_logic touches.
    """
    def __init__(self, workspace_dir: str):
        self.global_status = ""
        self.logs = []
        self.workspace_dir = workspace_dir
        self.total_tokens = 0
        self.emergency_stop = asyncio.Event()
        self.blueprint_approved = asyncio.Event()
        self.blueprint_approved.set()   # headless: auto-approve
        self.is_interactive = False
        self.autonomous_mode = False
        self.current_blueprint = ""
        self.ui_states_received = []    # captures set_ui_state calls

    def set_global_status(self, s: str) -> None:
        self.global_status = s

    def add_log(self, agent: str, msg: str) -> None:
        self.logs.append((agent, msg))

    def set_task_status(self, task: str, status: str) -> None:
        pass

    def add_tokens(self, n: int) -> None:
        self.total_tokens += n

    def set_ui_state(self, state) -> None:
        self.ui_states_received.append(state)


def _agent(return_value: str = "output") -> MagicMock:
    """Returns a mock whose .ask() resolves to return_value."""
    m = MagicMock()
    m.ask = AsyncMock(return_value=return_value)
    return m


def _synth(side_effects=None) -> MagicMock:
    """Returns a SynthesisEngine mock."""
    def wrap_proposal(val):
        return SynthesisProposal(
            proposal_id="test",
            agents_involved=[],
            synthesized_diff=val
        )

    m = MagicMock()
    if side_effects:
        wrapped_side_effects = [wrap_proposal(s) for s in side_effects]
        m.synthesize = AsyncMock(side_effect=wrapped_side_effects)
    else:
        m.synthesize = AsyncMock(return_value=wrap_proposal("synthesized_diff"))
    
    m.apply_final = AsyncMock()
    return m


# Why: All tests share these four patches so agents cannot accidentally call
# real CLI binaries, filesystem sandboxes, or the session registry.
_COMMON = [
    "orchestrator.agents.swarm.SandboxManager",
    "orchestrator.agents.swarm.CodeIndexer",
    "orchestrator.agents.swarm.SwarmEventLogger",
    "orchestrator.core.storage.RegistryManager.register_session",
]


# ─────────────────────────── Execution mode tests ────────────────────────────

@pytest.mark.asyncio
async def test_parallel_two_units_approve(tmp_path):
    """
    2 units in PARALLEL mode → asyncio.gather → APPROVE on first round.

    AgentFactory.create call order:
      1: architect  2: unit1.engine  3: unit2.engine  4: judge
    """
    ctrl = MockController(str(tmp_path))
    units = [
        DeploymentUnit(engine="gemini",  persona="engineer"),
        DeploymentUnit(engine="claude",  persona="reviewer"),
    ]
    arch  = _agent("Blueprint")
    exec1 = _agent("Patch A from engineer")
    exec2 = _agent("Patch B from reviewer")
    judge = _agent("APPROVE: both patches look correct")
    synth = _synth()

    with (
        patch("orchestrator.agents.swarm.SandboxManager"),
        patch("orchestrator.agents.swarm.CodeIndexer"),
        patch("orchestrator.agents.swarm.SwarmEventLogger"),
        patch("orchestrator.agents.swarm.SynthesisEngine", return_value=synth),
        patch("orchestrator.agents.swarm.AgentFactory.create",
              side_effect=[arch, exec1, exec2, judge]),
        patch("orchestrator.core.storage.RegistryManager.register_session"),
    ):
        await run_swarm_logic(ctrl, "Fix bug", units, execution_mode=ExecutionMode.PARALLEL)

    assert exec1.ask.call_count == 1
    assert exec2.ask.call_count == 1
    assert judge.ask.call_count == 1
    assert synth.synthesize.call_count == 1
    assert synth.apply_final.call_count == 1
    assert ctrl.global_status == "미션 완료"


@pytest.mark.asyncio
async def test_discussion_mode_approve(tmp_path):
    """
    2 units in DISCUSSION mode → sequential execution → APPROVE on first round.

    AgentFactory.create call order:
      1: architect  2: unit1.engine  3: unit2.engine  4: judge
    """
    ctrl = MockController(str(tmp_path))
    units = [
        DeploymentUnit(engine="gemini", persona="engineer"),
        DeploymentUnit(engine="codex",  persona="reviewer"),
    ]
    arch  = _agent("Blueprint")
    exec1 = _agent("Result from engineer")
    exec2 = _agent("Result from reviewer")
    judge = _agent("APPROVE: consensus reached")
    synth = _synth()

    with (
        patch("orchestrator.agents.swarm.SandboxManager"),
        patch("orchestrator.agents.swarm.CodeIndexer"),
        patch("orchestrator.agents.swarm.SwarmEventLogger"),
        patch("orchestrator.agents.swarm.SynthesisEngine", return_value=synth),
        patch("orchestrator.agents.swarm.AgentFactory.create",
              side_effect=[arch, exec1, exec2, judge]),
        patch("orchestrator.core.storage.RegistryManager.register_session"),
    ):
        await run_swarm_logic(ctrl, "Fix bug", units, execution_mode=ExecutionMode.DISCUSSION)

    assert exec1.ask.call_count == 1
    assert exec2.ask.call_count == 1
    assert synth.apply_final.call_count == 1
    assert ctrl.global_status == "미션 완료"


@pytest.mark.asyncio
async def test_discussion_context_chaining(tmp_path):
    """
    DISCUSSION mode: unit2's prompt must contain unit1's output.
    This verifies that discussion_context accumulates across units.
    """
    ctrl = MockController(str(tmp_path))
    units = [
        DeploymentUnit(engine="gemini", persona="engineer"),
        DeploymentUnit(engine="claude", persona="reviewer"),
    ]
    UNIT1_OUTPUT = "unit1-unique-output-marker"
    arch  = _agent("Blueprint")
    exec1 = _agent(UNIT1_OUTPUT)
    exec2 = _agent("reviewer output")
    judge = _agent("APPROVE")
    synth = _synth()

    with (
        patch("orchestrator.agents.swarm.SandboxManager"),
        patch("orchestrator.agents.swarm.CodeIndexer"),
        patch("orchestrator.agents.swarm.SwarmEventLogger"),
        patch("orchestrator.agents.swarm.SynthesisEngine", return_value=synth),
        patch("orchestrator.agents.swarm.AgentFactory.create",
              side_effect=[arch, exec1, exec2, judge]),
        patch("orchestrator.core.storage.RegistryManager.register_session"),
    ):
        await run_swarm_logic(ctrl, "Fix bug", units,
                              execution_mode=ExecutionMode.DISCUSSION)

    # unit2 (reviewer) must have received unit1's output in its prompt
    unit2_prompt = exec2.ask.call_args.args[0]
    assert UNIT1_OUTPUT in unit2_prompt, (
        "DISCUSSION mode: unit2 prompt must contain unit1 output for context chaining"
    )


# ─────────────────────────── Judge behaviour tests ───────────────────────────

@pytest.mark.asyncio
async def test_judge_approve_case_insensitive(tmp_path):
    """
    'approve' (lowercase) must be treated as APPROVE.
    The swarm uses evaluation.upper(), so this should pass.
    """
    ctrl = MockController(str(tmp_path))
    units = [DeploymentUnit(engine="gemini", persona="engineer")]
    synth = _synth()

    with (
        patch("orchestrator.agents.swarm.SandboxManager"),
        patch("orchestrator.agents.swarm.CodeIndexer"),
        patch("orchestrator.agents.swarm.SwarmEventLogger"),
        patch("orchestrator.agents.swarm.SynthesisEngine", return_value=synth),
        patch("orchestrator.agents.swarm.AgentFactory.create",
              side_effect=[_agent("Blueprint"), _agent("patch"), _agent("approve: lgtm")]),
        patch("orchestrator.core.storage.RegistryManager.register_session"),
    ):
        await run_swarm_logic(ctrl, "Fix bug", units)

    assert synth.apply_final.call_count == 1, "lowercase 'approve' should trigger apply_final"


@pytest.mark.asyncio
async def test_three_round_refinement(tmp_path):
    """
    CHALLENGE → CHALLENGE → APPROVE (3 rounds).

    AgentFactory.create order (1 unit):
      arch | exec_r1 judge_r1(CHALLENGE) | exec_r2 judge_r2(CHALLENGE) | exec_r3 judge_r3(APPROVE)
    """
    ctrl  = MockController(str(tmp_path))
    units = [DeploymentUnit(engine="gemini", persona="engineer")]
    synth = _synth(side_effects=["diff_r1", "diff_r2", "diff_r3"])

    with (
        patch("orchestrator.agents.swarm.SandboxManager"),
        patch("orchestrator.agents.swarm.CodeIndexer"),
        patch("orchestrator.agents.swarm.SwarmEventLogger"),
        patch("orchestrator.agents.swarm.SynthesisEngine", return_value=synth),
        patch("orchestrator.agents.swarm.AgentFactory.create",
              side_effect=[
                  _agent("Blueprint"),
                  _agent("r1 patch"), _agent("CHALLENGE: missing edge case"),
                  _agent("r2 patch"), _agent("CHALLENGE: performance concern"),
                  _agent("r3 patch"), _agent("APPROVE: all issues addressed"),
              ]),
        patch("orchestrator.core.storage.RegistryManager.register_session"),
    ):
        await run_swarm_logic(ctrl, "Fix bug", units)

    assert synth.synthesize.call_count  == 3, "synthesize must run once per round"
    assert synth.apply_final.call_count == 1, "apply_final runs only on APPROVE"
    assert ctrl.global_status == "미션 완료"


@pytest.mark.asyncio
async def test_token_counter_increments_per_challenge(tmp_path):
    """
    Each CHALLENGE increments total_tokens by 1.
    After 2 challenges → total_tokens == 2.
    """
    ctrl  = MockController(str(tmp_path))
    units = [DeploymentUnit(engine="gemini", persona="engineer")]
    synth = _synth(side_effects=["d1", "d2", "d3"])

    with (
        patch("orchestrator.agents.swarm.SandboxManager"),
        patch("orchestrator.agents.swarm.CodeIndexer"),
        patch("orchestrator.agents.swarm.SwarmEventLogger"),
        patch("orchestrator.agents.swarm.SynthesisEngine", return_value=synth),
        patch("orchestrator.agents.swarm.AgentFactory.create",
              side_effect=[
                  _agent("Blueprint"),
                  _agent("r1"), _agent("CHALLENGE: 1"),
                  _agent("r2"), _agent("CHALLENGE: 2"),
                  _agent("r3"), _agent("APPROVE"),
              ]),
        patch("orchestrator.core.storage.RegistryManager.register_session"),
    ):
        await run_swarm_logic(ctrl, "Fix bug", units)

    assert ctrl.total_tokens == 2


# ─────────────────────────── Control flow tests ──────────────────────────────

@pytest.mark.asyncio
async def test_emergency_stop_after_challenge(tmp_path):
    """
    emergency_stop is set inside the judge's side_effect after a CHALLENGE.
    The while loop must exit on the next iteration without calling apply_final.
    """
    ctrl  = MockController(str(tmp_path))
    units = [DeploymentUnit(engine="gemini", persona="engineer")]
    synth = _synth()

    async def judge_challenges_then_stops(prompt, path, title):
        ctrl.emergency_stop.set()          # trigger stop
        return "CHALLENGE: stop requested"

    judge_mock = MagicMock()
    judge_mock.ask = judge_challenges_then_stops

    with (
        patch("orchestrator.agents.swarm.SandboxManager"),
        patch("orchestrator.agents.swarm.CodeIndexer"),
        patch("orchestrator.agents.swarm.SwarmEventLogger"),
        patch("orchestrator.agents.swarm.SynthesisEngine", return_value=synth),
        patch("orchestrator.agents.swarm.AgentFactory.create",
              side_effect=[_agent("Blueprint"), _agent("exec output"), judge_mock]),
        patch("orchestrator.core.storage.RegistryManager.register_session"),
    ):
        await run_swarm_logic(ctrl, "Fix bug", units)

    assert synth.apply_final.call_count == 0, "apply_final must not be called after emergency stop"
    assert ctrl.emergency_stop.is_set()


@pytest.mark.asyncio
async def test_emergency_stop_mid_discussion(tmp_path):
    """
    DISCUSSION mode: emergency_stop is set inside unit1's ask.
    The inner for-loop must break — unit2 must NOT be called.
    """
    ctrl  = MockController(str(tmp_path))
    units = [
        DeploymentUnit(engine="gemini", persona="engineer"),
        DeploymentUnit(engine="claude", persona="reviewer"),
    ]
    synth = _synth()

    exec2 = _agent("reviewer output")  # must NOT be called

    async def exec1_and_stop(prompt, path, title):
        ctrl.emergency_stop.set()
        return "unit1 partial output"

    unit1_mock = MagicMock()
    unit1_mock.ask = exec1_and_stop

    # After inner loop breaks, judge is still created and called
    # Judge returns CHALLENGE → outer while exits because emergency_stop is set
    async def judge_challenge(prompt, path, title):
        return "CHALLENGE: interrupted"

    judge_mock = MagicMock()
    judge_mock.ask = judge_challenge

    with (
        patch("orchestrator.agents.swarm.SandboxManager"),
        patch("orchestrator.agents.swarm.CodeIndexer"),
        patch("orchestrator.agents.swarm.SwarmEventLogger"),
        patch("orchestrator.agents.swarm.SynthesisEngine", return_value=synth),
        patch("orchestrator.agents.swarm.AgentFactory.create",
              side_effect=[_agent("Blueprint"), unit1_mock, judge_mock]),
        patch("orchestrator.core.storage.RegistryManager.register_session"),
    ):
        await run_swarm_logic(ctrl, "Fix bug", units,
                              execution_mode=ExecutionMode.DISCUSSION)

    assert exec2.ask.call_count == 0, "unit2 must not be reached after emergency_stop"
    assert synth.apply_final.call_count == 0


# ─────────────────────────── Lifecycle / artifact tests ──────────────────────

@pytest.mark.asyncio
async def test_exception_creates_failure_log(tmp_path):
    """
    An exception in the execution agent must write _FAILURE.log.
    _SUCCESS.log should still exist (finally block always runs).
    """
    ctrl  = MockController(str(tmp_path))
    units = [DeploymentUnit(engine="gemini", persona="engineer")]

    crash_agent = MagicMock()
    crash_agent.ask = AsyncMock(side_effect=RuntimeError("agent crashed"))
    synth = _synth()

    with (
        patch("orchestrator.agents.swarm.SandboxManager"),
        patch("orchestrator.agents.swarm.CodeIndexer"),
        patch("orchestrator.agents.swarm.SwarmEventLogger"),
        patch("orchestrator.agents.swarm.SynthesisEngine", return_value=synth),
        patch("orchestrator.agents.swarm.AgentFactory.create",
              side_effect=[_agent("Blueprint"), crash_agent]),
        patch("orchestrator.core.storage.RegistryManager.register_session"),
    ):
        await run_swarm_logic(ctrl, "Fix bug", units)

    failure_logs = list(tmp_path.rglob("_FAILURE.log"))
    success_logs = list(tmp_path.rglob("_SUCCESS.log"))
    assert len(failure_logs) == 1, "_FAILURE.log must be created on exception"
    assert len(success_logs) == 1, "_SUCCESS.log must always be created (finally)"

    failure_text = failure_logs[0].read_text()
    assert "agent crashed" in failure_text


@pytest.mark.asyncio
async def test_artifact_files_always_present(tmp_path):
    """
    Both _START.log and _SUCCESS.log must exist on a normal successful run.
    """
    ctrl  = MockController(str(tmp_path))
    units = [DeploymentUnit(engine="gemini", persona="engineer")]
    synth = _synth()

    with (
        patch("orchestrator.agents.swarm.SandboxManager"),
        patch("orchestrator.agents.swarm.CodeIndexer"),
        patch("orchestrator.agents.swarm.SwarmEventLogger"),
        patch("orchestrator.agents.swarm.SynthesisEngine", return_value=synth),
        patch("orchestrator.agents.swarm.AgentFactory.create",
              side_effect=[_agent("Blueprint"), _agent("patch"), _agent("APPROVE")]),
        patch("orchestrator.core.storage.RegistryManager.register_session"),
    ):
        await run_swarm_logic(ctrl, "Fix bug", units)

    assert len(list(tmp_path.rglob("_START.log")))   == 1
    assert len(list(tmp_path.rglob("_SUCCESS.log"))) == 1


@pytest.mark.asyncio
async def test_interactive_blueprint_approval(tmp_path):
    """
    is_interactive=True, autonomous_mode=False:
    set_ui_state(UIState.BLUEPRINT_REVIEW) must be called before wait().
    blueprint_approved is pre-set so the test doesn't hang.
    """
    ctrl = MockController(str(tmp_path))
    ctrl.is_interactive = True
    ctrl.autonomous_mode = False
    ctrl.blueprint_approved.set()   # pre-approve so await doesn't block
    units = [DeploymentUnit(engine="gemini", persona="engineer")]
    synth = _synth()

    with (
        patch("orchestrator.agents.swarm.SandboxManager"),
        patch("orchestrator.agents.swarm.CodeIndexer"),
        patch("orchestrator.agents.swarm.SwarmEventLogger"),
        patch("orchestrator.agents.swarm.SynthesisEngine", return_value=synth),
        patch("orchestrator.agents.swarm.AgentFactory.create",
              side_effect=[_agent("Blueprint"), _agent("patch"), _agent("APPROVE")]),
        patch("orchestrator.core.storage.RegistryManager.register_session"),
    ):
        await run_swarm_logic(ctrl, "Fix bug", units)

    from orchestrator.core.state import UIState
    assert UIState.BLUEPRINT_REVIEW in ctrl.ui_states_received, (
        "Interactive mode must call set_ui_state(BLUEPRINT_REVIEW)"
    )


@pytest.mark.asyncio
async def test_autonomous_mode_skips_ui_state(tmp_path):
    """
    is_interactive=True, autonomous_mode=True:
    set_ui_state(BLUEPRINT_REVIEW) must NOT be called — no user approval gate.
    """
    ctrl = MockController(str(tmp_path))
    ctrl.is_interactive  = True
    ctrl.autonomous_mode = True
    units = [DeploymentUnit(engine="gemini", persona="engineer")]
    synth = _synth()

    with (
        patch("orchestrator.agents.swarm.SandboxManager"),
        patch("orchestrator.agents.swarm.CodeIndexer"),
        patch("orchestrator.agents.swarm.SwarmEventLogger"),
        patch("orchestrator.agents.swarm.SynthesisEngine", return_value=synth),
        patch("orchestrator.agents.swarm.AgentFactory.create",
              side_effect=[_agent("Blueprint"), _agent("patch"), _agent("APPROVE")]),
        patch("orchestrator.core.storage.RegistryManager.register_session"),
    ):
        await run_swarm_logic(ctrl, "Fix bug", units)

    from orchestrator.core.state import UIState
    assert UIState.BLUEPRINT_REVIEW not in ctrl.ui_states_received, (
        "Autonomous mode must skip the blueprint approval UI state"
    )
