"""
Architectural Role: Code Merging & Diff Application Engine.
This module provides the mechanisms to extract changes from agent sandboxes 
and safely merge them back into the main codebase. It acts as the final 
'executor' of AI-suggested code changes, including security auditing of paths.
"""
import subprocess
import tempfile
import os
import re
from pathlib import Path
from typing import Tuple

class DiffCollector:
    """
    Function: Extracts and applies Git-compatible diffs.
    Why: By using standard Git diffs and 'git apply', we leverage a proven, 
    reliable industry standard for code merging that handles line offsets 
    and context much better than raw string manipulation.
    """
    @staticmethod
    def extract_diff(sandbox_path: Path) -> str:
        """
        Function: Generates a diff from a sandbox worktree.
        Why: Agents work in 'untracked' sandboxes. We 'git add' their changes 
        temporarily just to extract a clean diff against the sandbox's base state.
        """
        if not sandbox_path.exists():
            return ""
            
        subprocess.run(["git", "add", "."], cwd=sandbox_path, capture_output=True)
        result = subprocess.run(["git", "diff", "--cached"], cwd=sandbox_path, capture_output=True, text=True)
        return result.stdout.strip()

    @staticmethod
    def _is_safe_diff(diff_content: str, base_repo_path: Path) -> Tuple[bool, str]:
        """
        Function: Security audit for incoming diffs.
        Why: Prevents 'Path Traversal' attacks. An agent might hallucinate a 
        diff header like '--- a/../../etc/passwd'. We resolve all paths 
        absolutely and verify they are within the project root.
        """
        # Scan for path indicators in diff headers (--- a/ or +++ b/)
        paths = re.findall(r'^[+-]{3} [ab]/(.*)$', diff_content, re.MULTILINE)
        base_abs = base_repo_path.resolve()
        
        for p in paths:
            try:
                target_abs = (base_repo_path / p).resolve()
                if not str(target_abs).startswith(str(base_abs)):
                    return False, f"Security Violation: Diff attempts to modify file outside root: {p}"
            except Exception as e:
                return False, f"Security Violation: Invalid path in diff: {p}"
        
        return True, ""

    @staticmethod
    def apply_diff(diff_content: str, base_repo_path: Path) -> Tuple[bool, str]:
        """
        Function: Safely applies a diff to the main repository.
        Why: Uses a 3-step safety process: 1) Path validation, 2) Dry-run check 
        (git apply --check) to ensure context matches, and 3) Final application.
        This atomic approach prevents partial or corrupted merges.
        """
        if not diff_content.strip():
            return True, "No changes to apply."
            
        # 1. Path Sanitization (Security)
        is_safe, error = DiffCollector._is_safe_diff(diff_content, base_repo_path)
        if not is_safe:
            return False, error

        # 2. Temporary file for Git compatibility
        fd, diff_file = tempfile.mkstemp(suffix=".diff")
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(diff_content + "\n")
            
        try:
            # 3. Atomic Check (Dry-run)
            # Why: git apply --check verifies that the file content has not 
            # shifted in a way that makes the diff un-appliable.
            check_result = subprocess.run(
                ["git", "apply", "--check", diff_file], 
                cwd=base_repo_path, capture_output=True, text=True
            )
            if check_result.returncode != 0:
                return False, f"Pre-merge validation failed (git apply --check):\n{check_result.stderr}"

            # 4. Actual Apply
            result = subprocess.run(
                ["git", "apply", diff_file], 
                cwd=base_repo_path, capture_output=True, text=True
            )
            if result.returncode == 0:
                return True, "Diff applied successfully."
            else:
                return False, f"git apply failed:\n{result.stderr}"
        finally:
            # Cleanup
            if os.path.exists(diff_file):
                os.remove(diff_file)
