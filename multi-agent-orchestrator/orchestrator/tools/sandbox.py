"""
Architectural Role: Agent Isolation & Sandbox Management.
This module uses Git Worktrees to create strictly isolated environments for each 
agent or mission. It ensures that file modifications by one agent do not 
accidentally leak into other concurrent processes and provides a robust 
mechanism for extracting clean diffs.
"""
import os
import shutil
import subprocess
import uuid
import json
import atexit
from pathlib import Path
from typing import Dict, Optional, Any

class SandboxManager:
    """
    Function: Lifecycle manager for Git-based sandboxes.
    Why: LLMs can be destructive when given filesystem access. By forcing them 
    to work in a Git Worktree, we gain:
    1) Immediate isolation (independent filesystem view).
    2) Easy diff extraction (changes are tracked against HEAD).
    3) Zero-impact trials (sandboxes are deleted after synthesis).
    """
    def __init__(self, base_repo_dir: Path, sandboxes_dir: Optional[Path] = None):
        self.base_repo_dir = base_repo_dir.resolve()
        
        # Why: Git Worktrees require a base repository. If the user hasn't 
        # initialized one, we do it automatically to enable sandboxing features.
        if not (self.base_repo_dir / ".git").exists():
            subprocess.run(["git", "init"], cwd=self.base_repo_dir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "bot@orchestrator.local"], cwd=self.base_repo_dir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Orchestrator Bot"], cwd=self.base_repo_dir, capture_output=True)
            subprocess.run(["git", "add", "."], cwd=self.base_repo_dir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial commit for sandbox"], cwd=self.base_repo_dir, capture_output=True)
            
        if sandboxes_dir:
            self.sandboxes_dir = sandboxes_dir.resolve()
        else:
            self.sandboxes_dir = self.base_repo_dir / ".sandboxes"
            
        self.sandboxes_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.sandboxes_dir / "state.json"
        self.active_sandboxes: Dict[str, str] = self._load_state()

        # Why: atexit handler ensures that orphaned worktrees are cleaned up 
        # even if the process crashes or is terminated by the user.
        atexit.register(self.cleanup_all)

    def _load_state(self) -> Dict[str, str]:
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                # Why: Handle legacy or corrupted state files that might be a list.
                if isinstance(data, dict):
                    return data
                return {}
            except json.JSONDecodeError:
                # If file is corrupt, treat as empty.
                return {}
        return {}

    def _save_state(self):
        self.state_file.write_text(json.dumps(self.active_sandboxes, indent=2))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup_all()

    def create_sandbox(self, agent_name: str, run_id: Optional[str] = None) -> Path:
        """
        Function: Spawns a new Git worktree.
        Why: We use a separate branch for each sandbox to allow Git to track 
        agent changes natively, making the 'Consensus' and 'Synthesis' 
        steps much more reliable.
        """
        if not run_id:
            run_id = str(uuid.uuid4())[:8]
            
        sandbox_name = f"{agent_name}_{run_id}"
        sandbox_path = self.sandboxes_dir / sandbox_name
        branch_name = f"sandbox/{sandbox_name}"
        
        try:
            # Atomic worktree creation with a new branch
            subprocess.run(
                ["git", "worktree", "add", "-b", branch_name, str(sandbox_path)],
                cwd=self.base_repo_dir,
                capture_output=True,
                text=True,
                check=True
            )
        except subprocess.CalledProcessError:
            # Fallback for complex repo states
            subprocess.run(
                ["git", "worktree", "add", "--detach", str(sandbox_path)],
                cwd=self.base_repo_dir,
                capture_output=True,
                text=True
            )
            
        self.active_sandboxes[sandbox_name] = str(sandbox_path)
        self._save_state()
        return sandbox_path

    def get_sandbox_path(self, sandbox_name: str) -> Optional[Path]:
        path_str = self.active_sandboxes.get(sandbox_name)
        return Path(path_str) if path_str else None

    def remove_sandbox(self, sandbox_name: str, force: bool = True) -> bool:
        """
        Function: Safely deletes a worktree and its associated branch.
        Why: Regular cleanup prevents disk bloat and keeps the Git history clean 
        of transient agent branches.
        """
        if sandbox_name not in self.active_sandboxes:
            return False
            
        sandbox_path = Path(self.active_sandboxes[sandbox_name])
        
        cmd = ["git", "worktree", "remove", str(sandbox_path)]
        if force:
            cmd.insert(3, "--force")
            
        try:
            subprocess.run(cmd, cwd=self.base_repo_dir, capture_output=True)
        except:
            # Emergency cleanup if Git fails
            if sandbox_path.exists():
                shutil.rmtree(sandbox_path, ignore_errors=True)
            subprocess.run(["git", "worktree", "prune"], cwd=self.base_repo_dir, capture_output=True)

        branch_name = f"sandbox/{sandbox_name}"
        subprocess.run(["git", "branch", "-D", branch_name], cwd=self.base_repo_dir, capture_output=True)
            
        del self.active_sandboxes[sandbox_name]
        self._save_state()
        return True

    def cleanup_all(self):
        """Removes all active sandboxes. Safe to call multiple times."""
        names = list(self.active_sandboxes.keys())
        for name in names:
            self.remove_sandbox(name, force=True)
        
        # Why: 'git worktree prune' is the final safety net to clean up metadata.
        subprocess.run(["git", "worktree", "prune"], cwd=self.base_repo_dir, capture_output=True)

    def create_checkpoint(self) -> str:
        """
        Creates a Git stash checkpoint of the current repository state.
        Returns the stash ID or a reference.
        """
        checkpoint_name = f"orchestrator_checkpoint_{uuid.uuid4().hex[:8]}"
        # -u includes untracked files
        subprocess.run(
            ["git", "stash", "push", "-u", "-m", checkpoint_name],
            cwd=self.base_repo_dir,
            capture_output=True
        )
        # Apply it immediately so the user doesn't lose their uncommitted work
        subprocess.run(
            ["git", "stash", "apply", "stash@{0}"],
            cwd=self.base_repo_dir,
            capture_output=True
        )
        return checkpoint_name

    def restore_checkpoint(self, checkpoint_name: str):
        """
        Reverts the repository to the state captured in the checkpoint.
        """
        # 1. Hard reset to clear agent changes
        subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=self.base_repo_dir, capture_output=True)
        subprocess.run(["git", "clean", "-fd"], cwd=self.base_repo_dir, capture_output=True)
        
        # 2. Find and apply the stash
        result = subprocess.run(
            ["git", "stash", "list"],
            cwd=self.base_repo_dir,
            capture_output=True,
            text=True
        )
        
        for line in result.stdout.splitlines():
            if checkpoint_name in line:
                stash_ref = line.split(":")[0]
                subprocess.run(["git", "stash", "apply", stash_ref], cwd=self.base_repo_dir, capture_output=True)
                break

def hook_route_to_sandbox(payload: dict) -> dict:
    """
    Function: Middleware hook to redirect tool operations into the sandbox.
    Why: Transparent redirection. Agents 'think' they are editing the project root, 
    but this hook silently rewrites paths to point into the agent's private 
    sandbox. This allows agents to work without knowing about worktree mechanics.
    """
    tool_name = payload.get("tool_name")
    if tool_name in ["read_file", "edit_file", "write_file", "ast_grep"]:
        context = payload.get("context")
        sandbox_path = payload.get("sandbox_path")
        
        if context and hasattr(context, "sandbox_manager") and context.sandbox_manager:
            if sandbox_path:
                original_path = payload.get("file_path", "")
                if original_path:
                    abs_path = Path(original_path)
                    if not abs_path.is_absolute():
                        new_path = Path(sandbox_path) / original_path
                        payload["file_path"] = str(new_path.resolve())
                        payload["original_file_path"] = str(original_path)
                        
    return payload
