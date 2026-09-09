"""
Architectural Role: Main Swarm Orchestration Logic.
This module implements the high-level coordination logic for multi-agent 
collaboration. It handles mission lifecycle management from blueprinting 
and iterative task execution to final result synthesis and validation.
"""
import uuid
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime

from orchestrator.core.models import DeploymentUnit, ExecutionMode, SessionManifest
from orchestrator.core.context import OrchestrationContext
from orchestrator.agents.adapters.factory import AgentFactory
from orchestrator.agents.sisyphus import SisyphusAgent
from orchestrator.core.reporting import SwarmEventLogger
from orchestrator.tools.sandbox import SandboxManager
from orchestrator.tools.indexer import CodeIndexer
from orchestrator.core.synthesis import SynthesisEngine

logger = logging.getLogger("swarm")

async def run_swarm_logic(
    controller,
    user_prompt: str,
    deployment_units: List[DeploymentUnit],
    judge_agent: str = "judge",
    auditor_agent: str = "auditor",
    execution_mode: ExecutionMode = ExecutionMode.PARALLEL,
    history_context: str = ""
) -> None:
    """
    Function: Primary entry point for executing a swarm mission.
    Why: Coordinates multiple specialized agents and tools in a structured pipeline. 
    It ensures that all artifacts are correctly stored and that the UI controller 
    is updated with real-time telemetry.
    """
    # Why: Absolute path resolution via controller's workspace_dir prevents 
    # data leakage or incorrect artifact storage when run from different CWDs.
    base_dir = Path(controller.workspace_dir).resolve()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    artifact_dir = base_dir / "artifacts" / timestamp
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # Low-level file-based logging for black box debugging
    (artifact_dir / "_START.log").touch()

    session_id = str(uuid.uuid4())
    
    # Function: Initialize Streaming Event Logger for real-time trace recording.
    event_logger = SwarmEventLogger(artifact_dir)
    event_logger.log_event("session_start", {
        "session_id": session_id,
        "user_prompt": user_prompt,
        "deployment_units": [u.__dict__ for u in deployment_units],
        "execution_mode": str(execution_mode)
    })

    ctx_kwargs = {}
    if getattr(controller, "hooks", None):
        ctx_kwargs["hooks"] = controller.hooks
    
    # Extract and inject file context if @path syntax is used
    from orchestrator.core.utils import extract_context_paths, resolve_and_read_context
    tagged_paths = extract_context_paths(user_prompt)
    injected_context = ""
    if tagged_paths:
        controller.add_log("system", f"태그된 파일 컨텍스트 추출 중: {', '.join(tagged_paths)}")
        injected_context = resolve_and_read_context(tagged_paths, controller.workspace_dir)

    context = OrchestrationContext(
        artifact_dir=artifact_dir, user_prompt=user_prompt, **ctx_kwargs)

    # Why: Registering agents in the controller allows the UI to pre-allocate 
    # slots in the Swarm Reasoning Timeline/Dashboard.
    from orchestrator.core.models import AgentStatus
    controller.register_agent("architect")
    controller.register_agent("judge")
    for i, unit in enumerate(deployment_units):
        controller.register_agent(f"{unit.persona}_{i}")

    # 0. Sandbox Initialization
    # Why: Using an executor for sandbox creation prevents blocking the main 
    # TUI event loop during potentially slow filesystem operations.
    controller.set_task_status("sandbox_init", "STARTING")
    loop = asyncio.get_running_loop()
    checkpoint_name = None
    try:
        context.sandbox_manager = await loop.run_in_executor(
            None, lambda: SandboxManager(base_dir)
        )
        # Create a checkpoint before making any changes
        checkpoint_name = await loop.run_in_executor(
            None, context.sandbox_manager.create_checkpoint
        )
        controller.set_task_status("sandbox_init", "FINISHED")
    except Exception as e:
        controller.set_task_status("sandbox_init", f"FAILED: {str(e)}")
        raise

    mission_status = "FAILURE"

    try:
        # 0b. Project Indexing
        # Why: Code indexing allows agents to understand the codebase structure 
        # (symbols, classes, functions) without reading every file manually.
        controller.set_global_status("프로젝트 심볼 인덱싱 중...")
        controller.set_task_status("indexing", "STARTING")
        indexer = CodeIndexer(base_dir)

        def sync_scan():
            indexer.scan(on_progress=lambda msg: loop.call_soon_threadsafe(
                controller.add_log, "system", msg))

        await loop.run_in_executor(None, sync_scan)
        context.indexer = indexer
        controller.set_task_status("indexing", "FINISHED")

        # 1. Blueprint Generation
        # Why: A detailed plan (blueprint) helps agents align on a common technical 
        # direction and minimizes conflicting changes during parallel execution.
        controller.set_global_status("미션 청사진 생성 중...")
        controller.set_task_status("blueprint_gen", "STARTING")
        
        # The user's selected architect is always the first unit now.
        architect_unit = deployment_units[0]
        blueprint_agent = AgentFactory.create(
            architect_unit.engine, state_manager=controller
        )
        # Update the adapter's agent_name so logs reflect it's the architect persona
        blueprint_agent.agent_name = "architect"
        
        blueprint_prompt = f"당신은 아키텍트입니다. 다음 미션을 위한 상세 실행 계획(Blueprint)을 작성하세요: {user_prompt}"
        full_context = history_context
        if injected_context:
            full_context = (f"태그된 파일/디렉토리 정보:\n{injected_context}\n\n" + full_context).strip()
            
        # Inject MCP Tools Prompt
        try:
            from orchestrator.core.mcp import MCPManager
            mcp_manager = MCPManager()
            if mcp_manager.clients:
                mcp_prompt = await mcp_manager.get_tools_prompt()
                if mcp_prompt:
                    full_context += "\n\n" + mcp_prompt
        except Exception:
            pass

        if full_context:
            blueprint_prompt = f"컨텍스트 정보:\n{full_context}\n\n" + blueprint_prompt
        mission_plan_path = artifact_dir / "mission_plan.md"
        
        mission_plan = await blueprint_agent.ask(
            blueprint_prompt, mission_plan_path, "Generate Mission Blueprint"
        )
        
        controller.current_blueprint = mission_plan
        controller.set_task_status("blueprint_gen", "FINISHED")

        # 2. Blueprint Approval (if not in autonomous mode)
        # Why: Forcing human-in-the-loop review of the plan prevents agents 
        # from starting down a lengthy and incorrect implementation path.
        if getattr(controller, 'is_interactive', False):
            if not controller.autonomous_mode:
                controller.set_global_status("청사진 검토 대기 중...")
                # Why: Lazy import avoids circular dependency
                # (tui.app → swarm → tui.controller would create a cycle).
                try:
                    from orchestrator.core.state import UIState
                    controller.set_ui_state(UIState.BLUEPRINT_REVIEW)
                except Exception:
                    pass
                await controller.blueprint_approved.wait()
                if controller.emergency_stop.is_set():
                    raise Exception("Mission stopped by user during blueprint review.")
        else: # For headless mode, auto-approve
            pass
        
        # 3. Recursive Swarm Loop
        # Function: Iteratively executes tasks based on the blueprint and feedback.
        synthesis_engine = SynthesisEngine(
            controller=controller, artifact_dir=artifact_dir
        )
        feedback = ""
        swarm_state = SwarmState(getattr(controller, 'max_rounds', 3))

        # Why: Emergency stop allows users to interrupt long-running swarms immediately.
        while not controller.emergency_stop.is_set() and swarm_state.current_round <= swarm_state.max_rounds:
            controller.set_global_status(f"Round {swarm_state.current_round}: 전문가 작업 중...")
            
            results = []
            if execution_mode == ExecutionMode.DISCUSSION:
                # Relay Mode: Sequential execution where each agent sees the previous agent's output.
                discussion_context = full_context
                # Why: All units including the architect should participate in the mission tasks.
                for unit in deployment_units:
                    if controller.emergency_stop.is_set(): break
                    agent = AgentFactory.create(
                        unit.engine, state_manager=controller
                    )
                    prompt = f"청사진: {mission_plan}\n\n피드백: {feedback}\n\n컨텍스트: {discussion_context}\n\n작업을 수행하세요."
                    output_path = artifact_dir / f"discussion_r{swarm_state.current_round}_{unit.persona}.md"
                    title = f"Discussion Round {swarm_state.current_round}: {unit.persona}"
                    output = await agent.ask(prompt, output_path, title)
                    results.append((unit.persona, output))
                    discussion_context += f"\n[{unit.persona}의 결과]:\n{output}\n"
            else:
                # Parallel Mode: Simultaneous execution for speed and independent perspectives.
                tasks = []
                for unit in deployment_units:
                    agent = AgentFactory.create(
                        unit.engine, state_manager=controller
                    )
                    prompt = f"청사진: {mission_plan}\n\n피드백: {feedback}\n\n작업을 수행하세요."
                    if full_context:
                        prompt = f"컨텍스트 정보:\n{full_context}\n\n" + prompt
                        
                    output_path = artifact_dir / f"parallel_r{swarm_state.current_round}_{unit.persona}.md"
                    title = f"Parallel Round {swarm_state.current_round}: {unit.persona}"
                    tasks.append(agent.ask(prompt, output_path, title))
                
                outputs = await asyncio.gather(*tasks)
                for i, unit in enumerate(deployment_units):
                    results.append((unit.persona, outputs[i]))

            # 4. Synthesis & Evaluation
            # Why: The Synthesis Engine merges raw agent outputs into a unified diff, 
            # and the Judge agent provides a final quality gate before application.
            controller.set_global_status(f"Round {swarm_state.current_round}: 결과 종합 및 검증 중...")
            
            # Reset agent statuses to IDLE after they finished their work
            for i, unit in enumerate(deployment_units):
                controller.update_agent_status(f"{unit.persona}_{i}", AgentStatus.IDLE)
            
            controller.update_agent_status("judge", AgentStatus.VERIFYING, action="Synthesizing Results")
            
            # results is a list of (persona, output). 
            # synthesis_engine expects a dict of {persona: output} if we want distinct keys.
            # But wait, persona might not be unique if there are 2 reviewers.
            # Let's check what synthesis_engine.synthesize expects.
            # It expects agent_diffs: Dict[str, str] in some places, but in synthesis.py:
            # def synthesize(self, user_prompt: str, agent_diffs: Dict[str, str], ...)
            
            # Since persona might not be unique, we should use a unique key.
            unique_results = {}
            for i, (persona, output) in enumerate(results):
                key = f"{persona}_{i}"
                unique_results[key] = output

            synthesized_diff_proposal = await synthesis_engine.synthesize(
                user_prompt=user_prompt, agent_diffs=unique_results
            )
            synthesized_diff = synthesized_diff_proposal.synthesized_diff
            
            judge_agent_obj = AgentFactory.create(
                "judge", state_manager=controller
            )
            judge_agent_obj.agent_name = "judge" # Ensure it matches registered name
            judge_prompt = f"다음 종합된 결과를 평가하세요. 만족스러우면 'APPROVE', 아니면 피드백을 주세요.\n\n{synthesized_diff}"
            eval_path = artifact_dir / f"judgement_r{swarm_state.current_round}.md"
            title = f"Judgement Round {swarm_state.current_round}"
            evaluation = await judge_agent_obj.ask(judge_prompt, eval_path, title)
            
            controller.update_agent_status("judge", AgentStatus.IDLE)
            
            if "APPROVE" in evaluation.upper():
                mission_status = "SUCCESS"
                
                # Phase 3: Review Changes (Side-by-Side)
                if getattr(controller, 'is_interactive', False):
                    if not controller.autonomous_mode:
                        controller.current_diff = synthesized_diff
                        controller.set_global_status("최종 결과 검토 대기 중...")
                        # UI will set diff_approved event
                        await controller.diff_approved.wait()
                        if controller.emergency_stop.is_set():
                            raise Exception("Mission stopped by user during diff review.")
                
                await synthesis_engine.apply_final(synthesized_diff)
                break
            else:
                feedback = evaluation
                # Increment round counter
                swarm_state.current_round += 1
                controller.add_tokens(1) # Legacy: increments internal round counter for telemetry

        # Finalize
        controller.set_global_status("미션 완료")
        mission_status = "SUCCESS" if mission_status == "SUCCESS" else "FAILURE"

    except Exception as e:
        logger.error(f"Swarm logic failed: {str(e)}")
        (artifact_dir / "_FAILURE.log").write_text(str(e))
        controller.add_log("system", f"Error: {str(e)}")
    finally:
        # Finalization: Register the session so it appears in the user's history tree.
        manifest = SessionManifest(
            session_id=session_id,
            timestamp=datetime.now().timestamp(),
            user_prompt=user_prompt,
            deployment_units=[u.__dict__ for u in deployment_units],
            status=mission_status,
            artifacts_path=str(artifact_dir),
            checkpoint_name=checkpoint_name,
            workspace=str(base_dir)
        )
        (artifact_dir / "_SUCCESS.log").touch()
        from orchestrator.core.storage import RegistryManager
        RegistryManager.register_session(manifest)
        return session_id

class SwarmState:
    """Helper class to track the internal state of the recursive swarm loop."""
    def __init__(self, max_rounds: int):
        self.current_round = 1
        self.max_rounds = max_rounds
