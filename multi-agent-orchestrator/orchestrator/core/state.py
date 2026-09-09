"""
Architectural Role: Global Application State Manager.
This module acts as the centralized authority for application state within the
TUI layer. It manages agent status, telemetry, settings persistence, and 
provides the communication bridge between the background orchestration logic 
and the reactive UI components.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import asyncio
import os
import json
from pathlib import Path
from enum import Enum

from orchestrator.core.history import HistoryManager
from orchestrator.core.models import (
    DeploymentUnit, ExecutionMode, AgentStatus, AgentState
)


class UIState(Enum):
    """Tracks the high-level UI mode to facilitate screen transitions and conditional rendering."""
    PREFLIGHT = "PREFLIGHT"
    HOME = "HOME"
    CONFIG = "CONFIG"
    MISSION_INPUT = "MISSION_INPUT"
    AGENT_SELECTION = "AGENT_SELECTION"
    BLUEPRINT_REVIEW = "BLUEPRINT_REVIEW"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"


class OrchestratorState:
    """
    Architectural Role: Central Application State Manager.
    Why: By centralizing all shared state (agents, logs, settings, costs) in 
    a single controller, we ensure that multiple screens (Home, Execution, 
    Settings) stay synchronized without complex prop-drilling or event spaghetti.
    """

    def __init__(self):
        self.agents: Dict[str, AgentState] = {}
        # Resources
        self.available_agents: Dict[str, str] = {}
        self.available_engines: List[str] = []
        self.available_personas: List[str] = []

        # Models
        self.available_gemini_models: List[str] = []
        self.available_codex_models: List[str] = []
        self.available_claude_models: List[str] = []

        # App State
        self.global_status: str = "Initializing..."
        self.start_time: float = 0
        self.is_active: bool = False
        self.ui_state: UIState = UIState.HOME
        self.preflight_results: Dict[str, bool] = {}
        self.is_interactive: bool = True
        
        # Why: message_queue is a thread-safe pipe for logs produced by 
        # background agents, ensuring high-frequency updates don't lag the UI.
        self.message_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.mission_query: str = ""
        self.selected_units: List["DeploymentUnit"] = []
        self.agent_sandboxes: Dict[str, Dict[str, str]] = {}
        self.language: str = "en"

        # Blueprint Interactivity
        self.current_blueprint: str = ""
        self.blueprint_approved: asyncio.Event = asyncio.Event()
        self.current_diff: str = ""
        self.diff_approved: asyncio.Event = asyncio.Event()
        self.wait_for_human_event: asyncio.Event = asyncio.Event()
        self.wait_for_human_event.set() # Default to allowed

        # Metrics
        self.total_tokens: int = 0
        self.estimated_cost: float = 0.0

        # Configuration & Defaults
        self.max_rounds: int = 3
        self.default_judge = "gemini-3.1-pro"
        self.workspace_dir: str = "./"
        self.custom_personas: Dict[str, str] = {}
        self.full_session_logs: List[str] = []

        # Active Model Selection
        self.gemini_model: str = "gemini-3.0-flash"
        self.codex_model: str = "codex-5.3"
        self.codex_effort: str = "medium"
        self.claude_model: str = "claude-4.6-sonnet"
        self.claude_effort: str = "medium"

        self.execution_mode: ExecutionMode = ExecutionMode.PARALLEL
        self.history_context: str = ""
        self.autonomous_mode: bool = False

        # Lifecycle Controls
        self.background_tasks: Dict[str, str] = {}
        self.emergency_stop: asyncio.Event = asyncio.Event()

        # Why: OrchestratorState holds its own HistoryManager to provide 
        # a unified data access layer for all UI components.
        self.history_manager = HistoryManager()
        
        from orchestrator.core.hooks import HookManager
        self.hooks = HookManager()

        self.discover_resources()
        self.load_settings()
        self.write_runtime_diagnostics()

    def write_runtime_diagnostics(self):
        """
        Function: Dumps critical path and state information to an external log.
        Why: Serves as a forensic 'black box' for debugging path resolution 
        and initialization issues that might be invisible during TUI execution.
        """
        try:
            log_path = Path(__file__).parent.parent.parent / "orchestrator_diagnostics.log"
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("=== MULTI-AGENT ORCHESTRATOR RUNTIME DIAGNOSTICS ===\n")
                f.write(f"CWD: {os.getcwd()}\n")
                f.write(f"Project Root (Resolved): {Path(__file__).parent.parent.parent.resolve()}\n")
                f.write(f"History Base Path: {self.history_manager.base_path.resolve()}\n")
                
                sessions = self.history_manager.list_sessions()
                f.write(f"\nLoaded Sessions Count: {len(sessions)}\n")
                for s in sessions[:10]:
                    f.write(f"  - [{s.workspace}] {s.id}: {s.title}\n")
                if len(sessions) > 10:
                    f.write(f"  ... and {len(sessions) - 10} more.\n")
        except Exception as e:
            pass

    def set_task_status(self, task_id: str, status: str):
        """Updates the status of a background operation (e.g. Indexing)."""
        self.background_tasks[task_id] = status
        self.add_log("system", f"Task [{task_id}] status changed to: {status}")

    def get_system_stats(self) -> Dict[str, str]:
        """Returns real-time CPU/Memory stats for telemetry."""
        try:
            import psutil
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            return {"cpu": f"{cpu}%", "memory": f"{mem}%"}
        except ImportError:
            return {"cpu": "N/A", "memory": "N/A"}

    def cancel_all_tasks(self):
        """Triggers emergency stop for all background workers."""
        self.emergency_stop.set()
        self.set_global_status("EMERGENCY STOP TRIGGERED")
        self.add_log("system", "Emergency stop signal sent to all workers.")

    def load_settings(self) -> None:
        """Loads and repairs application configuration from JSON."""
        settings_path = Path(".orchestrator_settings.json")
        if settings_path.exists():
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.language = data.get("language", self.language)
                    self.max_rounds = data.get("max_rounds", self.max_rounds)
                    self.default_judge = data.get("default_judge", self.default_judge)
                    self.workspace_dir = data.get("workspace_dir", self.workspace_dir)
                    self.custom_personas = data.get("agent_personas", {})

                    # Persistence & Migration Logic
                    self.gemini_model = data.get("gemini_model", "gemini-3.1-pro")
                    self.codex_model = data.get("codex_model", "codex-5.3")
                    self.codex_effort = data.get("codex_effort", "medium")
                    self.claude_model = data.get("claude_model", "claude-4.6-sonnet")
                    self.claude_effort = data.get("claude_effort", "medium")

                    mode_val = data.get("execution_mode", "parallel")
                    try:
                        self.execution_mode = ExecutionMode(mode_val)
                    except ValueError:
                        self.execution_mode = ExecutionMode.PARALLEL
                        
                    # MCP Integration
                    self.mcp_servers = data.get("mcp_servers", {})
                    if self.mcp_servers:
                        try:
                            from orchestrator.core.mcp import MCPManager
                            manager = MCPManager()
                            for name, config in self.mcp_servers.items():
                                if "command" in config:
                                    import asyncio
                                    # Non-blocking async spawn
                                    try:
                                        loop = asyncio.get_running_loop()
                                        loop.create_task(manager.add_server(name, config["command"], config.get("env")))
                                    except RuntimeError:
                                        # No running event loop yet (e.g. during sync __init__)
                                        # We will lazy connect them when needed or rely on discover_resources
                                        pass
                        except ImportError:
                            self.add_log("system", "MCPManager not found. Skipping MCP setup.")


                    self.autonomous_mode = data.get("autonomous_mode", self.autonomous_mode)

                    if self.custom_personas:
                        from orchestrator.core.models import AGENT_PERSONAS
                        for k, v in self.custom_personas.items():
                            if k in AGENT_PERSONAS:
                                AGENT_PERSONAS[k] = v
            except Exception:
                pass

    def save_settings(self) -> None:
        """Persists current controller state to disk."""
        settings_path = Path(".orchestrator_settings.json")
        try:
            data = {
                "language": self.language,
                "max_rounds": self.max_rounds,
                "default_judge": self.default_judge,
                "workspace_dir": self.workspace_dir,
                "agent_personas": self.custom_personas,
                "gemini_model": self.gemini_model,
                "codex_model": self.codex_model,
                "codex_effort": self.codex_effort,
                "claude_model": self.claude_model,
                "claude_effort": self.claude_effort,
                "execution_mode": self.execution_mode.value,
                "autonomous_mode": self.autonomous_mode
            }
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    def add_tokens(self, tokens: int):
        """Tracks token usage and estimates session costs."""
        self.total_tokens += tokens
        self.estimated_cost = (self.total_tokens / 1_000_000) * 0.50

    def discover_resources(self):
        """Refreshes available engines and personas."""
        self.available_engines = ["gemini", "codex", "claude"]
        from orchestrator.core.models import AGENT_PERSONAS
        self.available_personas = list(AGENT_PERSONAS.keys())

    async def discover_models(self):
        """Fetches dynamic model lists from registered CLI tools."""
        from orchestrator.core.cli_registry import registry
        self.available_gemini_models = await registry.get_available_models("gemini")
        self.available_codex_models = await registry.get_available_models("codex")
        self.available_claude_models = await registry.get_available_models("claude")
        
        # Connect MCP Servers if configured
        if hasattr(self, "mcp_servers") and self.mcp_servers:
            from orchestrator.core.mcp import MCPManager
            manager = MCPManager()
            for name, config in self.mcp_servers.items():
                if "command" in config and name not in manager.clients:
                    try:
                        await manager.add_server(name, config["command"], config.get("env"))
                        self.add_log("system", f"Connected to MCP Server: {name}")
                    except Exception as e:
                        self.add_log("system", f"Failed to connect MCP Server {name}: {e}")

    def run_preflight(self):
        """
        Function: Performs strict system readiness checks.
        Why: Ensures that all required API keys and CLI tools are available 
        before allowing the user to start a mission, preventing mid-run failures.
        """
        from orchestrator.core.cli_registry import registry
        results = {}
        results["Gemini API Key"] = bool(os.getenv("GEMINI_API_KEY"))
        results["Git Repository"] = Path(".git").exists()
        results["Gemini CLI"] = bool(registry.lookup("gemini") or registry.lookup("gemini-cli"))
        results["Codex CLI"] = bool(registry.lookup("codex"))
        results["Claude CLI"] = bool(registry.lookup("claude"))

        self.preflight_results = results
        essential_ok = all([
            results["Gemini API Key"],
            results["Git Repository"],
            results["Gemini CLI"] or results["Codex CLI"] or results["Claude CLI"],
        ])

        self.global_status = "System Ready" if essential_ok else "System Check Failed"
        return essential_ok

    def register_agent(self, name: str, max_retries: int = 0):
        """Initializes state for a specific agent in the execution view."""
        self.agents[name] = AgentState(name=name, max_retries=max_retries)

    def update_agent_status(self, name: str, status: AgentStatus,
                            action: str = "", attempt: int = None):
        """Updates agent progress for UI rendering."""
        if name in self.agents:
            agent = self.agents[name]
            agent.status = status
            if action: agent.last_action = action
            if attempt is not None: agent.attempt = attempt

    def add_log(self, name: str, log_line: str):
        """
        Function: Centralized log router.
        Why: Routes logs from different sources (system, agents) to 1) TUI Queue, 
        2) Full Session Memory, and 3) Agent-Specific buffers, ensuring that 
        telemetry is consistent across the entire application.
        """
        from orchestrator.core.cli_registry import registry
        tool_path = registry.lookup(name)
        icon = "⚡" if tool_path else "🤖"
        
        # Apply color coding based on agent name/persona
        colors = {
            "system": "white",
            "architect": "cyan",
            "engineer": "green",
            "reviewer": "yellow",
            "debugger": "magenta",
            "uiux": "blue",
            "judge": "bold red",
            "auditor": "bold yellow"
        }
        color = colors.get(name.lower(), "white")
        full_line = f"[{icon} [{color}]{name}[/{color}] >] {log_line}"

        self.full_session_logs.append(full_line)
        if name in self.agents:
            self.agents[name].logs.append(full_line)
            if len(self.agents[name].logs) > 1000: self.agents[name].logs.pop(0)

        try:
            self.message_queue.put_nowait(full_line)
        except asyncio.QueueFull:
            pass

    def set_global_status(self, status: str):
        self.global_status = status
