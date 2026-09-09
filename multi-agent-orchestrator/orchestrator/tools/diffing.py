"""
Architectural Role: Code Change Tracking & Diff Generation.
This module provides utilities to calculate the difference between two 
versions of a file and records these changes in the mission context. 
It enables agents to 'see' what they or their peers have modified.
"""
import difflib
from typing import Dict, Any

from orchestrator.core.context import OrchestrationContext
from rich.panel import Panel
from rich.syntax import Syntax

def generate_diff(old_content: str, new_content: str, file_path: str) -> str:
    """
    Function: Computes a standard unified diff.
    Why: Diff format is compact and easily understandable by both humans 
    and LLMs, making it the ideal protocol for reviewing code changes 
    before final application.
    """
    old_lines = old_content.splitlines(keepends=True) if old_content else []
    new_lines = new_content.splitlines(keepends=True) if new_content else []
    
    diff = list(difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        n=3
    ))
    return "".join(diff)

def render_side_by_side_diff(diff_str: str, title: str = "Proposed Changes"):
    """
    Function: Renders a unified diff in a more readable format.
    Why: Standard diffs can be hard to read. This provides a clear view 
    of added/removed lines with syntax highlighting.
    """
    if not diff_str:
        return Panel("No changes detected.", title=title, border_style="dim")

    syntax = Syntax(diff_str, "diff", theme="monokai", line_numbers=True)
    return Panel(syntax, title=f"[bold yellow]{title}[/bold yellow]", border_style="yellow")

def hook_generate_diff(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Function: Hook to automatically generate diffs after any file write operation.
    Why: By intercepting 'edit_file' and 'write_file' tools, we ensure that every 
    single modification made by an agent is tracked in 'diff_memory'. This 
    cumulative memory is essential for the Synthesis phase and for generating 
    final reports.
    """
    tool_name = payload.get("tool_name")
    
    if tool_name in ["edit_file", "write_file"]:
        old_content = payload.get("old_content", "")
        new_content = payload.get("new_content", "")
        file_path = payload.get("file_path", "unknown_file")
        context: OrchestrationContext = payload.get("context")
        
        # Why: We only want to record meaningful changes. If the agent 'wrote' 
        # identical content, we skip recording to keep the report clean.
        if old_content != new_content:
            diff_str = generate_diff(old_content, new_content, file_path)
            
            # Inject diff into payload for immediate response back to the agent.
            payload["diff"] = diff_str
            
            # Why: Appending to context.diff_memory builds up the 'audit trail' 
            # for the current mission.
            if context and hasattr(context, "diff_memory"):
                context.diff_memory.append({
                    "tool_name": tool_name,
                    "file_path": file_path,
                    "diff": diff_str
                })

    return payload
