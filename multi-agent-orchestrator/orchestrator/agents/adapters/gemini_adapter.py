from __future__ import annotations

"""
Gemini Adapter for the Multi-Agent Orchestrator.

This module provides a specialized bridge between the orchestrator and the Gemini CLI tool.
It handles model selection, automatic fallback logic for quota management, and token
usage extraction from CLI output. It's designed to be resilient against transient
API errors and quota exhaustion by cycling through available models.
"""

import os
import re
import time
from pathlib import Path
from typing import Optional, Callable

from orchestrator.core.models import AgentResult
from orchestrator.agents.adapters.shell_adapter import execute_cli
from orchestrator.core.cli_registry import registry


class GeminiAdapter:
    """
    Adapter for interacting with Gemini models via a CLI bridge.
    
    This class abstracts the complexity of calling the external Gemini binary,
    managing API keys via environment variables, and implementing a robust
    fallback strategy to ensure high availability even when primary models
    hit rate limits or quotas.
    """
    def __init__(
        self, timeout: int = 240, model: str | None = None
    ) -> None:
        self.agent_name = "gemini"
        self.timeout = timeout
        self.model = model

        # Robust discovery via registry
        # We look up both 'gemini' and 'gemini-cli' to account for different
        # installation names across various environments and OS package managers.
        cli_path = registry.lookup("gemini") or registry.lookup("gemini-cli")

        if cli_path:
            self.gemini_bin = str(cli_path)
            # If it's a JS file, we need node. This occurs when the CLI is
            # installed via npm/yarn but not globally linked as a binary.
            if self.gemini_bin.endswith(".js"):
                self.node_exe = "node.exe" if os.name == 'nt' else "node"
                self.is_js = True
            else:
                self.is_js = False
            self.available = True
        else:
            self.available = False
            self.gemini_bin = None

    def is_available(self) -> bool:
        """Checks if the underlying Gemini CLI tool is reachable on this system."""
        return self.available

    async def ask(
        self, prompt: str, on_log: Optional[Callable[[str], None]] = None
    ) -> AgentResult:
        """
        Sends a prompt to the Gemini model and returns the result.
        Uses fallback logic to handle potential API issues.
        """
        if not self.is_available():
            return AgentResult(
                "gemini", False, "", "Gemini CLI not found", -1, 0
            )
        return await self._run_with_fallbacks(prompt, on_log=on_log)

    async def review(
        self, user_prompt: str, peer_answer: str, review_prompt: str,
        on_log: Optional[Callable[[str], None]] = None
    ) -> AgentResult:
        """
        Performs a peer review of another agent's output.
        Semantically similar to 'ask' but used in a different context in the orchestrator.
        """
        if not self.is_available():
            return AgentResult(
                "gemini", False, "", "Gemini CLI not found", -1, 0
            )
        return await self._run_with_fallbacks(review_prompt, on_log=on_log)

    async def _run_with_fallbacks(
        self, prompt: str, on_log: Optional[Callable[[str], None]] = None
    ) -> AgentResult:
        """
        Executes the prompt with an ordered list of fallback models.
        
        This is critical because Gemini models often have different quota limits.
        If the primary model (e.g., Ultra) fails due to rate limiting (429),
        we can automatically try Flash or Pro models to maintain workflow continuity.
        """
        models_to_try = [self.model] if self.model else []
        # Predefined hierarchy of models from most capable to least/cheapest
        # to ensure we don't just fail if one tier is unavailable.
        fallbacks = [
            "gemini-3.0-flash", "gemini-2.5-pro", "gemini-2.5-flash"
        ]
        for f in fallbacks:
            if f not in models_to_try:
                models_to_try.append(f)

        last_result = None
        for i, current_model in enumerate(models_to_try):
            if i > 0 and on_log:
                on_log(
                    f"⚠️ [Fallback] API Quota/Model Error detected. "
                    f"Attempting with fallback model: {current_model}"
                )

            last_result = await self._execute_single(
                prompt, current_model, on_log
            )

            if last_result.ok:
                return last_result

            err = last_result.stderr.lower()
            # If the error is related to quota, rate limits, or the model not
            # existing, try the next model. We catch 'modelnotfounderror' because
            # model availability varies by region and API version.
            retry_errors = [
                "modelnotfounderror", "not found", "404", "429", "quota",
                "rate limit", "exhausted"
            ]
            if any(x in err for x in retry_errors):
                continue
            else:
                # If it's a different execution or syntax error, do not retry
                # as the prompt itself might be the cause, or there's a system issue.
                return last_result

        # If all fallbacks fail, append a hint to the final error message
        # to help the user diagnose if it's a configuration or quota issue.
        if last_result and not last_result.ok:
            try:
                import json
                settings_path = Path(".orchestrator_settings.json")
                lang = "en"
                if settings_path.exists():
                    with open(settings_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        lang = data.get("language", "en")

                from orchestrator.tui.i18n import t
                hint = t("model_not_found_hint", lang)
                last_result.stderr += (
                    f"\n\n{hint}\n(All fallback models were also "
                    f"exhausted or out of quota.)"
                )
            except Exception:
                last_result.stderr += (
                    "\n\n💡 Tip: Model not found or out of quota. "
                    "(All fallback models failed.)"
                )

        return last_result

    async def _execute_single(
        self, prompt: str, current_model: str,
        on_log: Optional[Callable[[str], None]] = None
    ) -> AgentResult:
        """
        Actually executes the CLI command for a specific model.
        
        Handles environment setup (API keys) and parses the CLI output
        to extract token usage metadata which is reported via stderr by the CLI.
        """
        started = time.perf_counter()

        env = os.environ.copy()
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            env["GEMINI_API_KEY"] = api_key

        if self.is_js:
            command = [self.node_exe, self.gemini_bin]
        else:
            command = [self.gemini_bin]

        if current_model:
            command.extend(["--model", current_model])

        try:
            returncode, stdout, stderr = await execute_cli(
                command=command,
                input_data=prompt,
                cwd=str(Path(os.getcwd()).resolve()),
                env=env,
                timeout=self.timeout,
                on_log=on_log
            )

            # Extract token count from stderr. The CLI tool prints usage metrics
            # to stderr to keep stdout clean for the actual model response.
            tokens = 0
            match = re.search(r'\[TOKEN_USAGE\] Total Tokens: (\d+)', stderr)
            if match:
                tokens = int(match.group(1))

            ok = (returncode == 0) and bool(stdout)

            result = AgentResult(
                agent_name="gemini",
                ok=ok,
                stdout=stdout,
                stderr=stderr,
                returncode=returncode,
                duration_ms=int((time.perf_counter() - started) * 1000),
                tokens=tokens
            )
            return result

        except TimeoutError as e:
            # Timeouts are treated as failed results to allow the orchestrator
            # to decide whether to retry or give up.
            return AgentResult(
                "gemini", False, "", str(e), -1,
                int((time.perf_counter() - started) * 1000)
            )
        except Exception as e:
            return AgentResult(
                "gemini", False, "", str(e), -1,
                int((time.perf_counter() - started) * 1000)
            )
