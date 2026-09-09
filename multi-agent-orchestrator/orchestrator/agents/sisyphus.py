"""
Architectural Role: Recursive Task Execution & Quality Assurance.
This module implements the 'Sisyphus' pattern—a self-correcting loop that 
delegates tasks to agents and automatically re-prompts them with feedback if 
the initial output fails validation. It ensures high reliability for complex tasks.
"""
import asyncio
import time
import random
from typing import Callable, Awaitable, Tuple, Any
from pathlib import Path

from orchestrator.core.context import OrchestrationContext
from orchestrator.agents.io_provider import AgentIOProvider

# Add TUI imports if available
try:
    from orchestrator.core.state import OrchestratorState, AgentStatus
except ImportError:
    OrchestratorState = Any
    AgentStatus = Any

class MaxRetriesExceededError(Exception):
    """Raised when the Sisyphus loop exceeds the maximum number of retries."""
    pass

class SisyphusAgent:
    """
    Function: Orchestrates a 'Think-Verify-Correct' loop for a single agent.
    Why: LLMs often make small errors on the first pass. By defining a clear 
    verification function and providing specific error feedback, we significantly 
    increase the probability of a successful outcome compared to a single-shot request.
    """
    def __init__(self, max_retries: int = 3, backoff_factor: float = 1.5):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    async def delegate_task(
        self, 
        io_provider: AgentIOProvider, 
        prompt: str, 
        target_path: Path, 
        title: str
    ) -> str:
        """
        Function: Executes a single task through the IO provider with system-level retries.
        Why: Shields the orchestration logic from transient network or API errors 
        using exponential backoff.
        """
        system_retries = 3
        last_exception = None
        
        for i in range(system_retries):
            try:
                return await io_provider.ask(prompt, target_path, title)
            except Exception as e:
                last_exception = e
                # Why: Adding jitter prevents 'thundering herd' issues if multiple agents fail simultaneously.
                wait = (self.backoff_factor ** i) + (random.random() * 0.1)
                await asyncio.sleep(wait)
        
        raise last_exception

    async def verify_result(
        self, 
        result: str, 
        verification_fn: Callable[[str], Awaitable[Tuple[bool, str]]]
    ) -> Tuple[bool, str]:
        """
        Function: Wraps the provided verification function with safety handling.
        Why: Ensures that a crash in the verification logic (e.g. regex error) 
        is reported as a system error rather than hanging the orchestration.
        """
        try:
            return await verification_fn(result)
        except Exception as e:
            return False, f"SYSTEM_ERROR: Verification engine crashed: {str(e)}"

    async def run(
        self, 
        context: OrchestrationContext, 
        io_provider: AgentIOProvider, 
        task_prompt: str,
        verification_fn: Callable[[str], Awaitable[Tuple[bool, str]]],
        title: str = "Sisyphus Task",
        state_manager: OrchestratorState = None
    ) -> str:
        """
        Function: The main loop that drives the recursion.
        Why: It maintains the state of previous failures and constructs a 
        progressively more informative prompt for the agent in each attempt.
        """
        agent_name = getattr(io_provider, "agent_name", "agent")
        if state_manager:
            state_manager.register_agent(agent_name, max_retries=self.max_retries)

        current_prompt = task_prompt
        last_result = ""
        last_error = ""

        for attempt in range(1, self.max_retries + 1):
            if state_manager:
                state_manager.update_agent_status(agent_name, AgentStatus.THINKING, action="Thinking...", attempt=attempt)

            target_path = context.artifact_dir / f"sisyphus_attempt_{attempt}.txt"
            loop_title = f"{title} (Attempt {attempt}/{self.max_retries})"
            
            # 1. Delegate task (Execution)
            try:
                last_result = await self.delegate_task(io_provider, current_prompt, target_path, loop_title)
            except Exception as e:
                last_error = f"FATAL SYSTEM ERROR: {str(e)}"
                break # Hard fail on persistent system error
            
            if state_manager:
                state_manager.update_agent_status(agent_name, AgentStatus.VERIFYING, action="Verifying result...")

            # 2. Verify result (Quality Gate)
            is_success, error_msg = await self.verify_result(last_result, verification_fn)
            
            # Record trace (Thread-safe)
            # Why: Using a context lock ensures that multiple parallel Sisyphus 
            # agents can write to the shared mission trace without data corruption.
            async with context.lock:
                trace_entry = {
                    "attempt": attempt,
                    "prompt": current_prompt,
                    "action": last_result,
                    "observation": "Success" if is_success else error_msg,
                    "hint": "",
                    "success": is_success
                }
                if not is_success and "Hint" in error_msg:
                    parts = error_msg.split("💡 Hint")
                    if len(parts) > 1:
                        trace_entry["hint"] = "💡 Hint" + parts[1]
                context.execution_trace.append(trace_entry)
            
            if is_success:
                if state_manager:
                    state_manager.update_agent_status(agent_name, AgentStatus.SUCCESS, action="Task Completed!")
                return last_result
            
            if state_manager:
                state_manager.update_agent_status(agent_name, AgentStatus.FAILURE, action=f"Failed: {error_msg[:50]}...")

            # 3. Handle failure & Feedback (Recursive Loop Setup)
            # Why: Explicitly including the previous failure reason and the agent's 
            # previous output allows the LLM to learn from its own mistakes.
            last_error = error_msg
            current_prompt = (
                f"{task_prompt}\n\n"
                f"--- PREVIOUS ATTEMPT FAILED ---\n"
                f"Your previous attempt failed the verification process.\n"
                f"Please fix the following errors and try again:\n\n"
                f"VERIFICATION ERROR:\n{error_msg}\n\n"
                f"YOUR PREVIOUS RESULT:\n{last_result}\n"
            )

        raise MaxRetriesExceededError(
            f"Graceful degradation: Sisyphus Loop '{title}' failed after {self.max_retries} attempts.\n"
            f"Last verification error: {last_error}"
        )
