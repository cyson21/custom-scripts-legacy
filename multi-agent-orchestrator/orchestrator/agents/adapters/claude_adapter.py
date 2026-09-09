from __future__ import annotations

"""
Claude Adapter for the Multi-Agent Orchestrator.

This module integrates Anthropic's Claude models via a CLI bridge. It supports
advanced model features such as 'effort' levels (reasoning budget) and ensures
consistent IO handling across the orchestrator's agent pool.
"""

import os
import time
from pathlib import Path
from typing import Optional, Callable

from orchestrator.core.models import AgentResult
from orchestrator.agents.adapters.shell_adapter import execute_cli
from orchestrator.core.cli_registry import registry


class ClaudeAdapter:
    """
    Adapter for interacting with Claude models via an external CLI tool.
    
    Claude models, particularly the 3.7+ series, support varying levels of
    reasoning effort. This adapter captures that constraint to allow the
    orchestrator to tune performance vs. cost/latency for complex tasks.
    """
    def __init__(
        self, timeout: int = 120, model: str | None = None,
        effort: str = "medium"
    ) -> None:
        self.agent_name = "claude"
        self.timeout = timeout
        self.model = model
        # 'effort' allows controlling the reasoning budget for models like
        # Claude 3.7 Sonnet. Higher effort improves quality for complex
        # logic but increases latency and token cost.
        self.effort = effort
        cli_path = registry.lookup("claude")
        if cli_path:
            self.claude_bin = str(cli_path)
            self.available = True
        else:
            self.claude_bin = None
            self.available = False

    def is_available(self) -> bool:
        """Determines if the 'claude' CLI binary is present and registered."""
        return self.available

    async def ask(
        self, prompt: str, on_log: Optional[Callable[[str], None]] = None
    ) -> AgentResult:
        """
        Executes a standard completion request. 
        Fail-fast if the binary is missing to avoid hanging subprocess calls.
        """
        if not self.is_available():
            return AgentResult(
                "claude", False, "", "Claude CLI not found in environment",
                -1, 0)
        return await self._run(prompt, on_log=on_log)

    async def review(
        self, user_prompt: str, peer_answer: str, review_prompt: str,
        on_log: Optional[Callable[[str], None]] = None
    ) -> AgentResult:
        """
        Executes a review request. 
        Reuses the standard execution path as Claude CLI handles prompt context via stdin.
        """
        if not self.is_available():
            return AgentResult(
                "claude", False, "", "Claude CLI not found in environment",
                -1, 0)
        return await self._run(review_prompt, on_log=on_log)

    async def _run(
        self, prompt: str, on_log: Optional[Callable[[str], None]] = None
    ) -> AgentResult:
        """
        Manages the subprocess execution for the Claude CLI.
        
        This method constructs the CLI arguments including model and effort
        overrides, then captures output via the shared execute_cli utility
        to ensure unified logging and timeout handling.
        """
        started = time.perf_counter()

        env = os.environ.copy()

        command = [self.claude_bin, "-p"]
        if self.model:
            command.extend(["--model", self.model])

        if self.effort:
            command.extend(["--effort", self.effort])

        try:
            returncode, stdout, stderr = await execute_cli(
                command=command,
                input_data=prompt,
                cwd=str(Path(os.getcwd()).resolve()),
                env=env,
                timeout=self.timeout,
                on_log=on_log
            )

            ok = (returncode == 0) and bool(stdout)

            result = AgentResult(
                agent_name="claude",
                ok=ok,
                stdout=stdout,
                stderr=stderr,
                returncode=returncode,
                duration_ms=int((time.perf_counter() - started) * 1000))

            return result

        except TimeoutError as e:
            # We explicitly catch TimeoutError to provide accurate duration_ms
            # which helps the orchestrator track agent performance/bottlenecks.
            duration_ms = int((time.perf_counter() - started) * 1000)
            return AgentResult("claude", False, "", str(e), -1, duration_ms)
        except Exception as e:
            duration_ms = int((time.perf_counter() - started) * 1000)
            return AgentResult("claude", False, "", str(e), -1, duration_ms)
