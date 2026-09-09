import json
import pytest
import asyncio
from pathlib import Path
from typing import Tuple

from orchestrator.core.context import OrchestrationContext
from orchestrator.agents.io_provider import AgentIOProvider
from orchestrator.agents.sisyphus import SisyphusAgent
from orchestrator.tools.hashline import (
    hook_inject_hashlines, hook_validate_hashlines, generate_line_hash
)
from orchestrator.tools.ast_grep import hook_ast_grep
from orchestrator.tools.diffing import hook_generate_diff
from orchestrator.core.prompts import SISYPHUS_PROMPT_TEMPLATE


class MockAgentProvider(AgentIOProvider):
    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0

    async def ask(
        self, prompt: str, target_path: Path, title: str, **kwargs
    ) -> str:
        # In real scenario, the agent would see the prompt containing errors
        # and adjust its response. We simulate this by returning predefined
        # responses.
        res = self.responses[self.call_count]
        self.call_count += 1
        return res

    async def review(
        self, user_prompt: str, peer_answer: str, prompt: str,
        target_path: Path, title: str
    ) -> str:
        return ""


def test_integration_v5_workflow(tmp_path):
    async def run_test():
        # 1. Setup context and hooks
        context = OrchestrationContext(artifact_dir=tmp_path)
        context.hooks.register("tool.execute.after", hook_inject_hashlines)
        context.hooks.register("tool.execute.before", hook_validate_hashlines)
        context.hooks.register("tool.execute.after", hook_ast_grep)
        context.hooks.register("tool.execute.after", hook_generate_diff)

        # 2. Initial target file
        target_file = tmp_path / "app.py"
        target_file.write_text("def old_function():\n    return 1\n")

        h_wrong = "1#ffff"
        h_correct = generate_line_hash("def old_function():")
        h_correct_id = f"1#{h_correct}"

        # Pre-scripted Agent Responses simulating learning from errors
        responses = [
            # Attempt 1: AST-Grep empty hint test
            json.dumps({"tool_name": "ast_grep",
                       "pattern": "def $A():", "mock": True}),

            # Attempt 2: Hashline Mismatch test
            json.dumps({
                "tool_name": "edit_file",
                "file_path": str(target_file),
                "edits": [{
                    "hashline_id": h_wrong,
                    "new_content": "def new_function():"
                }]
            }),

            # Attempt 3: Correct Hashline edit
            json.dumps({
                "tool_name": "edit_file",
                "file_path": str(target_file),
                "edits": [{
                    "hashline_id": h_correct_id,
                    "new_content": "def new_function():"
                }]
            }),

            # Attempt 4: Task completion
            "[TASK_COMPLETED]"
        ]

        provider = MockAgentProvider(responses)
        loop = SisyphusAgent(max_retries=5)

        # 3. Verification & Execution Engine
        async def verify_and_execute(result: str) -> Tuple[bool, str]:
            if "[TASK_COMPLETED]" in result:
                return True, ""

            try:
                payload = json.loads(result)
                payload["context"] = context

                # Setup file content state for tools
                current_content = target_file.read_text()
                payload["current_file_content"] = current_content

                # --- A. BEFORE HOOKS ---
                try:
                    payload = await context.hooks.emit(
                        "tool.execute.before", payload
                    )
                except Exception as e:
                    return False, f"Before Hook Error: {str(e)}"

                # --- B. TOOL EXECUTION ---
                if payload.get("tool_name") == "edit_file":
                    edits = payload.get("edits", [])
                    lines = current_content.splitlines()
                    payload["old_content"] = current_content
                    for edit in edits:
                        line_idx = int(edit["hashline_id"].split('#')[0]) - 1
                        lines[line_idx] = edit["new_content"]
                    payload["new_content"] = "\n".join(lines) + "\n"
                    target_file.write_text(payload["new_content"])

                # --- C. AFTER HOOKS ---
                payload = await context.hooks.emit(
                    "tool.execute.after", payload
                )

                # Check for AST Grep failure hints
                if payload.get("tool_name") == "ast_grep" and payload.get(
                        "success") is False:
                    return (
                        False,
                        f"AST-Grep Execution Failed.\n{payload.get('output')}"
                    )

                # Provide diff memory to agent in next prompt
                if "diff" in payload:
                    msg = (
                        f"File successfully updated. "
                        f"Diff memory generated:\n{payload['diff']}\n"
                        f"Please proceed or mark as completed."
                    )
                    return False, msg

                return (
                    False,
                    "Tool executed successfully, but no completion "
                    "signal sent. Continue."
                )

            except json.JSONDecodeError:
                return False, "Failed to parse JSON tool execution request."

        initial_prompt = SISYPHUS_PROMPT_TEMPLATE.format(
            user_prompt=(
                "Change 'old_function' to 'new_function' using "
                "AST-Grep and Hashline Edit."
            ),
            mission_plan="Execute the refactoring.",
            diff_memory=json.dumps(
                context.diff_memory))

        # 4. Run Sisyphus Loop
        final_result = await loop.run(
            context, provider, initial_prompt, verify_and_execute
        )

        # 5. Assertions (Total Integration Verifications)
        assert "[TASK_COMPLETED]" in final_result

        # Verify Diff memory was saved
        assert len(context.diff_memory) > 0
        diff_str = context.diff_memory[0]["diff"]
        assert "-def old_function():" in diff_str
        assert "+def new_function():" in diff_str

        # Verify actual file mutation
        final_content = target_file.read_text()
        assert "def new_function():" in final_content
        assert "old_function" not in final_content

    asyncio.run(run_test())


if __name__ == "__main__":
    pytest.main([__file__])
