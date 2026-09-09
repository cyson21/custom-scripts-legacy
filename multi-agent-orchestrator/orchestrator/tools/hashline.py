"""
Architectural Role: Concurrency Safety & Hallucination Prevention (Hashlines).
This module implements the 'Hashline' protocol. It injects unique, content-based 
IDs into every line of code displayed to an agent and validates these IDs before 
allowing any edits. This ensures that the agent is editing exactly what it 
thinks it is editing, preventing 'optimistic concurrency' collisions and 
hallucinated text replacements.
"""
import hashlib
from typing import Dict, Any

class HashlineMismatchError(Exception):
    """Raised when the submitted hashline ID does not match the actual content hash."""
    pass

def generate_line_hash(line: str) -> str:
    """
    Function: Generates a 4-character MD5 prefix for a line.
    Why: A short hash is sufficient to detect if a line has changed since the 
    agent last read it, while keeping the TUI display clean.
    """
    return hashlib.md5(line.encode('utf-8')).hexdigest()[:4]

def generate_hashline(line_num: int, line: str) -> str:
    """
    Function: Formats code for agent consumption.
    Why: By prepending '1#ab3k|' to code, we provide the agent with a durable 
    anchor for its edits that is independent of whitespace or line shifts 
    in other parts of the file.
    """
    h = generate_line_hash(line)
    return f"{line_num}#{h}| {line}"

def validate_hashline(submitted_id: str, current_line: str) -> bool:
    """
    Function: Integrity check for incoming edits.
    Why: If the hash doesn't match the current disk content, it means another 
    agent (or a previous round) modified this line. We raise an error to force 
     the agent to re-read the file, preventing corruption.
    """
    try:
        line_num_str, expected_hash = submitted_id.split('#')
    except ValueError:
        raise ValueError(f"Invalid hashline ID format: {submitted_id}. Expected format like '1#ab3k'")
    
    actual_hash = generate_line_hash(current_line)
    if expected_hash != actual_hash:
        raise HashlineMismatchError(
            f"Hashline mismatch at line {line_num_str}. Expected hash {expected_hash}, but found {actual_hash}"
        )
    return True

# -----------------------------------------------------------------------------
# Hook Callbacks for HookManager
# -----------------------------------------------------------------------------

def hook_inject_hashlines(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Function: Post-processing hook for 'read_file'.
    Why: Automatically transforms raw file content into the Hashline protocol 
    format before the agent ever sees it.
    """
    if payload.get("tool_name") == "read_file":
        output = payload.get("output", "")
        if isinstance(output, str):
            lines = output.split('\n')
            hashed_lines = [generate_hashline(i + 1, line) for i, line in enumerate(lines)]
            payload["output"] = '\n'.join(hashed_lines)
    return payload

def hook_validate_hashlines(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Function: Pre-processing hook for 'edit_file'.
    Why: Intercepts and validates edit requests at the gateway level. If 
    validation fails here, the edit tool is never executed, protecting the 
    integrity of the filesystem.
    """
    if payload.get("tool_name") == "edit_file":
        edits = payload.get("edits", [])
        current_content = payload.get("current_file_content", "")
        current_lines = current_content.split('\n')
        
        for edit in edits:
            hashline_id = edit.get("hashline_id")
            if not hashline_id:
                continue
                
            try:
                line_num_str = hashline_id.split('#')[0]
                line_idx = int(line_num_str) - 1
            except ValueError:
                raise ValueError(f"Invalid hashline ID format: {hashline_id}")

            if line_idx < 0 or line_idx >= len(current_lines):
                raise HashlineMismatchError(f"Line number {line_num_str} is out of bounds.")
            
            # Validate actual hash against current physical content
            validate_hashline(hashline_id, current_lines[line_idx])
            
    return payload
