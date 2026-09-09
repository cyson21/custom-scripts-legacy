"""
Architectural Role: Semantic Code Search & Transformation Tool (ast-grep).
This module wraps the 'ast-grep' CLI tool to provide structural code analysis. 
Unlike regex-based search, this uses abstract syntax trees (AST) to ensure 
that searches are aware of code structure (e.g., matching a function definition 
regardless of whitespace).
"""
import subprocess
from pathlib import Path
from typing import Dict, Any, Tuple

from orchestrator.core.path_resolver import get_sg_cli_path

class ASTGrepTool:
    """
    Function: Interface for semantic code manipulation.
    Why: Agents need a way to modify code that is safer than raw text 
    replacement. ast-grep allows agents to target specific nodes (like 
    function bodies) semantically, reducing the risk of broken syntax.
    """
    def __init__(self):
        self.sg_path = get_sg_cli_path()

    def _get_empty_result_hint(self, pattern: str, language: str = "") -> str:
        """
        Function: Provides diagnostic hints when a query returns no results.
        Why: ast-grep patterns can be tricky for LLMs. By analyzing the 
        failed pattern and providing specific 'Smart Hints' (e.g. about 
        trailing colons or unbalanced parentheses), we help the agent 
        self-correct in the next Sisyphus loop iteration.
        """
        hints = []
        if pattern.endswith(':'):
            hints.append("- Your pattern ends with a colon (':'). If you are matching a Python function or class definition, ast-grep usually matches the node without the trailing colon. Try removing it.")
        
        if "(" in pattern and ")" not in pattern:
            hints.append("- Unbalanced parenthesis detected. Check your syntax.")
        
        if "$" in pattern and "$$$" not in pattern:
            hints.append("- You used a meta-variable (e.g., $VAR). To match multiple nodes, use '$$$' instead of '$VAR'.")

        hint_msg = "No results found for your query.\n"
        if hints:
            hint_msg += "\n💡 Hints:\n" + "\n".join(hints)
        else:
            hint_msg += "\n💡 Hint: Try to broaden your search pattern, or check if it exactly matches the AST structure."
            
        return hint_msg

    def execute(self, pattern: str, rewrite: str = None, file_path: str = None, lang: str = "python") -> Tuple[bool, str]:
        """
        Function: Spawns the ast-grep process.
        Why: Handles low-level CLI execution details, including path resolution 
        and output capturing.
        """
        if not self.sg_path:
            return False, "ast-grep (sg) is not installed. Please install it via `npm install -g @ast-grep/cli` or similar."

        cmd = [str(self.sg_path), "--pattern", pattern, "--lang", lang]
        if rewrite:
            cmd.extend(["--rewrite", rewrite])
        
        if file_path:
            cmd.append(file_path)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                output = result.stdout.strip()
                if not output:
                    return False, self._get_empty_result_hint(pattern)
                return True, output
            else:
                return False, f"AST-Grep execution failed:\n{result.stderr.strip()}"
                
        except Exception as e:
            return False, f"Error executing ast-grep: {e}"

def hook_ast_grep(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Function: Middleware hook to intercept and execute 'ast_grep' tool requests.
    Why: This follows the 'Hooks' architectural pattern, allowing the 
    orchestrator to intercept tool calls for logging, mocking, or auditing 
    before they reach the physical system.
    """
    if payload.get("tool_name") == "ast_grep":
        tool = ASTGrepTool()
        pattern = payload.get("pattern", "")
        rewrite = payload.get("rewrite")
        file_path = payload.get("file_path")
        lang = payload.get("lang", "python")
        
        # Why: Mock support facilitates headless testing without requiring 
        # the physical ast-grep binary to be installed in the CI environment.
        if payload.get("mock"):
            output = "" # simulate empty result
            if not output:
                payload["success"] = False
                payload["output"] = tool._get_empty_result_hint(pattern)
            return payload

        success, output = tool.execute(pattern, rewrite, file_path, lang)
        payload["success"] = success
        payload["output"] = output

    return payload
