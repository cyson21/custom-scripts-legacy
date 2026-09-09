import re

with open('orchestrator/adapters/factory.py', 'r') as f:
    content = f.read()

# Add _apply_fallback_chain helper
helper = """
    @staticmethod
    def _apply_fallback_chain(auto_agent: AutoAgentAdapter, timeout: int, tui_controller: object = None) -> AgentIOProvider:
        from orchestrator.core.cli_registry import registry
        from orchestrator.agents.io_provider import FallbackAgentProvider, ManualAgentAdapter
        from orchestrator.agents.adapters.claude_adapter import ClaudeAdapter
        try:
            if registry.lookup("claude"):
                claude_model = getattr(tui_controller, "claude_model", None) if tui_controller else None
                claude_adapter = ClaudeAdapter(timeout=timeout, model=claude_model)
                claude_auto = AutoAgentAdapter(claude_adapter, tui_controller=tui_controller)
                return FallbackAgentProvider(
                    primary=auto_agent,
                    fallback=FallbackAgentProvider(primary=claude_auto, fallback=ManualAgentAdapter())
                )
        except Exception:
            pass
        return FallbackAgentProvider(primary=auto_agent, fallback=ManualAgentAdapter())

    @staticmethod
    def create"""

content = content.replace("    @staticmethod\n    def create", helper)

# Now wrap the AutoAgentAdapter(adapter, ...) for Gemini returns
content = re.sub(
    r'(return AutoAgentAdapter\(adapter,\s*tui_controller=tui_controller\))',
    r'return AgentFactory._apply_fallback_chain(\1, timeout, tui_controller)',
    content
)

with open('orchestrator/adapters/factory.py', 'w') as f:
    f.write(content)
