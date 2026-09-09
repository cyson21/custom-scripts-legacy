"""
Architectural Role: Agent Communication Abstraction (I/O Providers).
This module defines the unified interface for interacting with agents, whether 
they are automated (LLM-based) or manual (human-in-the-loop). It enables the 
orchestrator to treat different execution modes polymorphically.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path

from orchestrator.agents.manual_io import collect_manual_block
from orchestrator.core.models import AgentResult
from orchestrator.core.storage import write_text

class AgentIOProvider(ABC):
    """
    Abstract base for agent communication.
    Defines the contract for 'ask' (generation) and 'review' (critique) operations.
    """
    @abstractmethod
    async def ask(self, prompt: str, target_path: Path, title: str) -> str:
        """Sends a primary instruction to the agent."""
        raise NotImplementedError

    @abstractmethod
    async def review(
        self,
        user_prompt: str,
        peer_answer: str,
        prompt: str,
        target_path: Path,
        title: str,
    ) -> str:
        """Sends a peer-review request to the agent."""
        raise NotImplementedError


class ManualAgentAdapter(AgentIOProvider):
    """
    Function: Bridges the orchestrator to a human developer via terminal input.
    Why: Used as a final fallback or for critical decision points where 
    automated reasoning is insufficient.
    """
    async def ask(self, prompt: str, target_path: Path, title: str) -> str:
        loop = asyncio.get_running_loop()
        # Why: run_in_executor is used to prevent the TUI from hanging while waiting for user CLI input.
        return await loop.run_in_executor(None, collect_manual_block, title, target_path, prompt)

    async def review(
        self,
        user_prompt: str,
        peer_answer: str,
        prompt: str,
        target_path: Path,
        title: str,
    ) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, collect_manual_block, title, target_path, prompt)


class AutoAgentAdapter(AgentIOProvider):
    """
    Function: Wraps an automated LLM worker (Gemini, Claude, Codex).
    Why: Handles the conversion between high-level orchestration requests 
    and low-level CLI or API calls, managing logs and error reporting centrally.
    """
    def __init__(self, worker: object, state_manager: object = None) -> None:
        self.worker = worker
        self.last_error = ""
        self.state_manager = state_manager
        self.agent_name = getattr(worker, "agent_name", "agent")

    async def ask(self, prompt: str, target_path: Path, title: str) -> str:
        if not hasattr(self.worker, 'ask'):
            self.last_error = "Worker missing 'ask' method."
            return ""
        
        if self.state_manager:
            from orchestrator.core.models import AgentStatus
            # Why: Reporting status changes to the state manager enables 
            # real-time UI feedback (e.g. Swarm Reasoning Timeline).
            
            # Phase 4: Wait-for-Human logic via Hook
            if hasattr(self.state_manager, 'hooks'):
                payload = {
                    "agent_name": self.agent_name,
                    "title": title,
                    "prompt": prompt,
                    "autonomous_mode": getattr(self.state_manager, 'autonomous_mode', True)
                }
                await self.state_manager.hooks.emit("agent.ask.before", payload)
                
                # Check if hook modified autonomous_mode or explicitly asked to wait
                if not payload.get("autonomous_mode", True):
                    self.state_manager.update_agent_status(
                        self.agent_name, AgentStatus.WAITING, action=f"Waiting for human approval: {title}"
                    )
                    self.state_manager.add_log(self.agent_name, f"WAITING FOR APPROVAL: {title}")
                    if hasattr(self.state_manager, 'wait_for_human_event'):
                        await self.state_manager.wait_for_human_event.wait()
                        self.state_manager.wait_for_human_event.clear() # Reset for next step

            self.state_manager.update_agent_status(
                self.agent_name, AgentStatus.THINKING, action=title
            )
            self.state_manager.add_log(self.agent_name, f"--- ASK: {title} ---")
            
        result: AgentResult = await self.worker.ask(prompt)
        
        if result.ok:
            write_text(target_path, result.stdout)
            if self.state_manager:
                self.state_manager.update_agent_status(self.agent_name, AgentStatus.SUCCESS)
                self.state_manager.add_log(self.agent_name, result.stdout)
            return result.stdout
            
        self.last_error = f"ReturnCode: {result.returncode}, Stderr: {result.stderr}"
        if self.state_manager:
            self.state_manager.update_agent_status(self.agent_name, AgentStatus.FAILURE)
            self.state_manager.add_log(self.agent_name, f"ERROR: {self.last_error}")
        return ""

    async def review(
        self,
        user_prompt: str,
        peer_answer: str,
        prompt: str,
        target_path: Path,
        title: str,
    ) -> str:
        if not hasattr(self.worker, 'review'):
            self.last_error = "Worker missing 'review' method."
            return ""
        result: AgentResult = await self.worker.review(user_prompt, peer_answer, prompt)
        if result.ok:
            write_text(target_path, result.stdout)
            return result.stdout
        self.last_error = f"ReturnCode: {result.returncode}, Stderr: {result.stderr}"
        return ""


class FallbackAgentProvider(AgentIOProvider):
    """
    Function: Implements a fail-over strategy between two providers.
    Why: Critical for production workflows. If an automated API fails 
    (rate limits, safety filters), the system automatically switches to 
    manual mode rather than failing the entire mission.
    """
    def __init__(self, primary: AutoAgentAdapter, fallback: AgentIOProvider) -> None:
        self.primary = primary
        self.fallback = fallback

    def _log_fallback(self, target_path: Path, title: str) -> None:
        error_msg = getattr(self.primary, 'last_error', 'Unknown Error')
        # Why: Explicit warnings help the user understand why the UI suddenly 
        # prompted for manual input.
        print(f"\n[WARN] {title} - 자동 실패. 수동 모드로 전환합니다. (Reason: {error_msg})")
        
        fallback_log = target_path.parent / "fallback.log"
        with open(fallback_log, "a", encoding="utf-8") as f:
            f.write(f"[WARN] {title} - Fallback triggered. Error: {error_msg}\n")

    async def ask(self, prompt: str, target_path: Path, title: str) -> str:
        content = await self.primary.ask(prompt, target_path, title)
        if content:
            return content
            
        self._log_fallback(target_path, title)
        return await self.fallback.ask(prompt, target_path, title)

    async def review(
        self,
        user_prompt: str,
        peer_answer: str,
        prompt: str,
        target_path: Path,
        title: str,
    ) -> str:
        content = await self.primary.review(user_prompt, peer_answer, prompt, target_path, title)
        if content:
            return content
            
        self._log_fallback(target_path, title)
        return await self.fallback.review(user_prompt, peer_answer, prompt, target_path, title)
