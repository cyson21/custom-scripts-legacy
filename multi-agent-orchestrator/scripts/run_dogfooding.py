import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Tuple

sys.path.append(os.getcwd())

from orchestrator.core.context import OrchestrationContext
from orchestrator.agents.io_provider import AgentIOProvider
from orchestrator.core.storage import create_artifact_dir, write_text
from orchestrator.agents.sisyphus import SisyphusAgent
from orchestrator.core.prompts import SISYPHUS_PROMPT_TEMPLATE
from orchestrator.tools.hashline import hook_inject_hashlines, hook_validate_hashlines
from orchestrator.tools.ast_grep import hook_ast_grep
from orchestrator.tools.diffing import hook_generate_diff
from orchestrator.core.reporting import generate_execution_trace_md

class MockAgentProvider(AgentIOProvider):
    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0

    async def ask(self, prompt: str, target_path: Path, title: str) -> str:
        if self.call_count < len(self.responses):
            res = self.responses[self.call_count]
            self.call_count += 1
            return res
        return "[TASK_COMPLETED]"

    async def review(self, user_prompt: str, peer_answer: str, prompt: str, target_path: Path, title: str) -> str:
        return ""

async def amain() -> None:
    base_dir = Path(__file__).resolve().parent
    artifact_dir = create_artifact_dir(base_dir)
    user_prompt = "Refactor path_resolver.py to use pathlib instead of os.path where appropriate, keeping the existing logic intact. Return [TASK_COMPLETED] when done."
    
    context = OrchestrationContext(artifact_dir=artifact_dir, user_prompt=user_prompt)
    
    context.hooks.register("tool.execute.after", hook_inject_hashlines)
    context.hooks.register("tool.execute.before", hook_validate_hashlines)
    context.hooks.register("tool.execute.after", hook_ast_grep)
    context.hooks.register("tool.execute.after", hook_generate_diff)

    # Simulated intelligent agent steps
    responses = [
        # Step 1: Read the file
        json.dumps({
            "tool_name": "read_file",
            "file_path": "orchestrator/path_resolver.py"
        }),
        # Step 2: Use ast-grep to see if there is any glob.glob(str(p))
        json.dumps({
            "tool_name": "ast_grep",
            "pattern": "glob.glob($A)",
            "file_path": "orchestrator/path_resolver.py"
        }),
        # Step 3: We will use Hashline Edit to replace the block
        # The agent replaces import glob and glob.glob
        json.dumps({
            "tool_name": "edit_file",
            "file_path": "orchestrator/path_resolver.py",
            "edits": [
                {
                    "hashline_id": "49#7f8c", # Mocked hashline, the real one will be generated below
                    "new_content": "                matches = list(Path(p).parent.glob(Path(p).name))"
                }
            ]
        }),
        # Step 4: Complete
        "[TASK_COMPLETED]"
    ]

    provider = MockAgentProvider(responses)
    loop = SisyphusAgent(max_retries=15)
    
    async def verify_and_execute(result: str) -> Tuple[bool, str]:
        if "[TASK_COMPLETED]" in result:
            return True, ""
            
        try:
            payload = json.loads(result)
            payload["context"] = context
            
            if payload.get("tool_name") == "edit_file":
                file_path = Path(payload.get("file_path"))
                if file_path.exists():
                    payload["current_file_content"] = file_path.read_text()
                    
                    # Fix hashline for mock script so it matches exactly
                    current_content = file_path.read_text()
                    lines = current_content.splitlines()
                    
                    # Find the line with glob.glob(str(p)) to automatically generate the correct hashline_id for the mock
                    target_idx = -1
                    for i, line in enumerate(lines):
                        if "matches = glob.glob(str(p))" in line:
                            target_idx = i
                            break
                            
                    if target_idx != -1:
                        from orchestrator.tools.hashline import generate_line_hash
                        h = generate_line_hash(lines[target_idx])
                        # Inject correct hashline into payload for mock to pass
                        payload["edits"][0]["hashline_id"] = f"{target_idx + 1}#{h}"

            try:
                payload = await context.hooks.emit("tool.execute.before", payload)
            except Exception as e:
                return False, f"Before Hook Error: {str(e)}"
                
            if payload.get("tool_name") == "edit_file":
                file_path = Path(payload.get("file_path"))
                if file_path.exists():
                    current_content = file_path.read_text()
                    payload["old_content"] = current_content
                    
                    edits = payload.get("edits", [])
                    lines = current_content.splitlines()
                    for edit in edits:
                        line_idx = int(edit["hashline_id"].split('#')[0]) - 1
                        lines[line_idx] = edit["new_content"]
                    
                    new_content = "\n".join(lines) + "\n"
                    payload["new_content"] = new_content
                    file_path.write_text(new_content)
                else:
                    return False, f"File not found: {file_path}"
                    
            elif payload.get("tool_name") == "read_file":
                file_path = Path(payload.get("file_path"))
                if file_path.exists():
                    payload["output"] = file_path.read_text()
                else:
                    return False, f"File not found: {file_path}"
                    
            elif payload.get("tool_name") == "ast_grep":
                # Mock ast_grep behavior
                payload["success"] = True
                payload["output"] = "matches = glob.glob(str(p))"
                    
            payload = await context.hooks.emit("tool.execute.after", payload)
            
            if payload.get("tool_name") == "ast_grep" and payload.get("success") is False:
                return False, f"AST-Grep Execution Failed.\n{payload.get('output')}"
            
            if "diff" in payload:
                diff_report = payload['diff']
                return False, f"File successfully updated. Diff memory generated:\n{diff_report}\nPlease proceed or mark as completed."
                
            return False, f"Tool executed successfully. Output: {payload.get('output', 'None')}\nPlease proceed."
            
        except json.JSONDecodeError:
            return False, "Invalid JSON format."

    initial_prompt = SISYPHUS_PROMPT_TEMPLATE.format(
        user_prompt=user_prompt,
        diff_memory=json.dumps(context.diff_memory)
    )

    print("\n\033[94m[Mock Sisyphus Loop Started]\033[0m")
    try:
        final_result = await loop.run(context, provider, initial_prompt, verify_and_execute)
        write_text(artifact_dir / 'final_report.md', final_result)
        
    except Exception as e:
        print(f"\n\033[91m[Sisyphus Loop Failed]\033[0m {e}")
        
    trace_json_path = artifact_dir / 'trace.json'
    write_text(trace_json_path, json.dumps(context.execution_trace, indent=2, ensure_ascii=False))
    
    trace_md_path = artifact_dir / 'execution_trace.md'
    trace_md_content = generate_execution_trace_md(context.execution_trace, context.diff_memory)
    write_text(trace_md_path, trace_md_content)
    
    print(f"\nTelemetry saved:")
    print(f"  - \033[92m{trace_json_path}\033[0m")
    print(f"  - \033[92m{trace_md_path}\033[0m")
    print(f"Artifacts saved to: \033[92m{context.artifact_dir}\033[0m")

def main() -> None:
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(amain())

if __name__ == '__main__':
    main()
