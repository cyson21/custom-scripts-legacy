"""
Architectural Role: Dynamic Agent Instantiation & Dependency Injection.
This module implements the Factory Pattern for creating agent adapters. 
It encapsulates the complex logic of resolving CLI paths, parsing user 
settings (like models and effort levels), and wrapping the base adapters 
in safety layers like the FallbackAgentProvider.
"""
from __future__ import annotations

from pathlib import Path

from orchestrator.agents.adapters.gemini_adapter import GeminiAdapter
from orchestrator.agents.adapters.codex_adapter import CodexAdapter
from orchestrator.agents.adapters.claude_adapter import ClaudeAdapter
from orchestrator.agents.adapters.shell_adapter import ShellAgentAdapter
from orchestrator.agents.io_provider import AutoAgentAdapter, AgentIOProvider


class AgentFactory:
    """
    Function: Centralizes the creation of agent adapters.
    Why: By routing all agent creation through this factory, the orchestrator 
    remains completely decoupled from the specific instantiation details of 
    Gemini, Claude, or Codex. It also allows us to inject global UI controllers 
    for telemetry and seamlessly wrap agents in fallback chains.
    """

    @staticmethod
    def _find_shell_script(agent_name: str) -> Path | None:
        """
        Function: Scans standard directories for custom shell-based agents.
        Why: Provides an extensibility hook so users can define their own 
        agents using bash scripts without modifying the core Python code.
        """
        search_dirs = [
            Path("configs/agents"),
            Path.home() / ".codex" / "orchestrator" / "agents"
        ]

        for search_dir in search_dirs:
            if search_dir.exists():
                script_path = search_dir / f"{agent_name}.sh"
                if script_path.exists():
                    return script_path
                script_path_no_ext = search_dir / agent_name
                if script_path_no_ext.exists():
                    return script_path_no_ext

        return None

    @staticmethod
    def _apply_fallback_chain(
        auto_agent: AutoAgentAdapter, timeout: int,
        state_manager: object = None
    ) -> AgentIOProvider:
        """
        Function: Wraps the primary agent in a safety net of secondary agents.
        Why: LLM APIs often fail due to rate limits or safety filters. By 
        automatically chaining (Primary -> Claude -> Manual), we ensure the 
        swarm mission doesn't crash from a single API hiccup.
        """
        from orchestrator.core.cli_registry import registry
        from orchestrator.agents.io_provider import (
            FallbackAgentProvider, ManualAgentAdapter
        )
        from orchestrator.agents.adapters.claude_adapter import ClaudeAdapter
        try:
            if registry.lookup("claude"):
                claude_model = (
                    getattr(state_manager, "claude_model", None)
                    if state_manager else None
                )
                claude_effort = (
                    getattr(state_manager, "claude_effort", "medium")
                    if state_manager else "medium"
                )
                claude_adapter = ClaudeAdapter(
                    timeout=timeout, model=claude_model, effort=claude_effort
                )
                claude_auto = AutoAgentAdapter(
                    claude_adapter, state_manager=state_manager
                )
                return FallbackAgentProvider(
                    primary=auto_agent,
                    fallback=FallbackAgentProvider(
                        primary=claude_auto, fallback=ManualAgentAdapter()
                    )
                )
        except Exception:
            pass
        return FallbackAgentProvider(
            primary=auto_agent, fallback=ManualAgentAdapter()
        )

    @staticmethod
    def create(
        engine_name: str, timeout: int = 120, state_manager: object = None
    ) -> AgentIOProvider:
        """
        Function: The primary constructor method for generating agent adapters.
        Why: Extracts UI controller settings (like selected models) and 
        translates them into the specific arguments required by each underlying 
        CLI tool.
        """
        from orchestrator.core.cli_registry import registry

        engine_name_low = engine_name.lower().strip()

        # Meta-agents defaulting to selection from state
        meta_agents = ["auditor", "judge", "architect", "security", "optimizer"]
        is_meta = engine_name_low in meta_agents
        
        # Extract user-selected models from the TUI state
        model = None
        if state_manager:
            if is_meta:
                model = getattr(state_manager, "default_judge", None)
                # Auto-detect engine based on the selected model name
                if model:
                    if model in getattr(state_manager, "available_claude_models", []):
                        current_engine = "claude"
                    elif model in getattr(state_manager, "available_codex_models", []):
                        current_engine = "codex"
                    else:
                        current_engine = "gemini"
                else:
                    current_engine = "gemini"
            else:
                current_engine = engine_name_low
            
            gemini_meta = [
                "gemini", "auditor", "judge", "architect", "security",
                "optimizer"
            ]
            if not model and current_engine in gemini_meta:
                model = getattr(state_manager, "gemini_model", None)
            elif current_engine == "codex":
                model = getattr(state_manager, "codex_model", None)
            elif current_engine == "claude":
                model = getattr(state_manager, "claude_model", None)
        else:
            current_engine = engine_name_low

        # Why: Strict binary lookups prevent runtime crashes during execution.
        # If a required CLI is missing, we fail fast with a clear error message.
        if current_engine == "gemini":
            if (not registry.lookup("gemini-cli") and
                    not registry.lookup("gemini")):
                raise FileNotFoundError(
                    "Engine binary 'gemini-cli' not found. "
                    "Please install it (e.g., npm install -g "
                    "@google/gemini-cli)."
                )
            adapter = GeminiAdapter(timeout=timeout, model=model)
            if is_meta:
                adapter.agent_name = engine_name_low
            return AgentFactory._apply_fallback_chain(
                AutoAgentAdapter(adapter, state_manager=state_manager),
                timeout, state_manager
            )

        elif current_engine == "codex":
            if not registry.lookup("codex"):
                raise FileNotFoundError(
                    "Engine binary 'codex' not found. "
                    "Please install the Codex CLI tool."
                )
            adapter = CodexAdapter(
                timeout=timeout,
                model=model,
                effort=getattr(state_manager, "codex_effort", "medium")
            )
            if is_meta:
                adapter.agent_name = engine_name_low
            return AutoAgentAdapter(
                adapter,
                state_manager=state_manager
            )

        elif current_engine == "claude":
            if not registry.lookup("claude"):
                raise FileNotFoundError(
                    "Engine binary 'claude' not found. "
                    "Please install the Claude CLI tool."
                )
            adapter = ClaudeAdapter(
                timeout=timeout,
                model=model,
                effort=getattr(state_manager, "claude_effort", "medium")
            )
            if is_meta:
                adapter.agent_name = engine_name_low
            return AutoAgentAdapter(
                adapter,
                state_manager=state_manager
            )

        # Custom Shell-script fallback
        script_path = AgentFactory._find_shell_script(engine_name_low)
        if script_path:
            return AutoAgentAdapter(
                ShellAgentAdapter(
                    str(script_path), engine_name, timeout=timeout, model=model
                ),
                state_manager=state_manager
            )

        # Generic CLI binary fallback
        cli_path = registry.lookup(engine_name_low)
        if cli_path:
            return AutoAgentAdapter(
                ShellAgentAdapter(
                    str(cli_path), engine_name, timeout=timeout, model=model
                ),
                state_manager=state_manager
            )

        raise ValueError(
            f"Unknown agent engine or configuration not found for: "
            f"{engine_name}"
        )
