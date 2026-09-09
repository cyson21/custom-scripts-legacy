"""
Architectural Role: Persistent Data Storage & Registry Management.
This module handles low-level file I/O operations, directory creation for session 
artifacts, and maintains a centralized JSON registry of all orchestration missions.
It uses standard file locking (fcntl) to handle concurrent access safely.
"""
from __future__ import annotations

import json
import fcntl
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from orchestrator.core.models import AgentResult, SessionManifest


def create_artifact_dir(base_dir: Path) -> Path:
    """
    Function: Creates a timestamped directory for session artifacts.
    Why: Organizing artifacts by timestamp ensures distinct execution contexts and 
    facilitates historical auditing of agent behaviors.
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    artifact_dir = base_dir / "artifacts" / timestamp
    (artifact_dir / "errors").mkdir(parents=True, exist_ok=True)
    return artifact_dir


def write_text(path: Path, content: str) -> None:
    """Standard UTF-8 text writer with path safety."""
    path.write_text(content, encoding="utf-8")


def write_agent_result(path: Path, result: AgentResult) -> None:
    """Saves the standard output of an agent execution to a specific path."""
    write_text(path, result.stdout)


def write_error(path: Path, result: AgentResult) -> None:
    """Saves the standard error output of an agent execution for debugging."""
    write_text(path, result.stderr)


class RegistryManager:
    """
    Function: Manages the 'registry.json' index for all known sessions.
    Why: RegistryManager ensures atomic updates to the registry index using fcntl 
    file locking. This prevents race conditions when multiple agents or UI 
    actions attempt to update history concurrently, especially in multi-user 
    or multi-process environments.
    """
    @staticmethod
    def _get_registry_path() -> Path:
        """
        Function: Dynamic path resolution for the registry file.
        Why: Uses __file__ to resolve to the project root, ensuring that the registry 
        is always found regardless of the current working directory of the process.
        """
        return Path(__file__).parent.parent.parent / "artifacts" / "registry.json"

    @classmethod
    def load_registry(cls) -> List[Dict[str, Any]]:
        """
        Function: Safely loads the session index.
        Why: Includes robust error handling for JSON corruption or file access 
        interruptions to prevent UI crashes during history loading.
        """
        path = cls._get_registry_path()
        if not path.exists():
            return []
        try:
            with open(path, "r") as f:
                content = f.read()
                if not content:
                    return []
                return json.loads(content)
        except (json.JSONDecodeError, IOError):
            return []

    @classmethod
    def register_session(cls, manifest: SessionManifest) -> None:
        """
        Function: Atomically adds or updates a session entry in the registry.
        Why: Uses fcntl.flock(LOCK_EX) to lock the file during the Read-Modify-Write cycle, 
        ensuring that no other process can corrupt the index during registration.
        """
        path = cls._get_registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        entry = {
            "session_id": manifest.session_id,
            "timestamp": manifest.timestamp,
            "user_prompt": manifest.user_prompt,
            "status": manifest.status,
            "artifacts_path": str(manifest.artifacts_path),
            "workspace": manifest.workspace,
            "checkpoint_name": manifest.checkpoint_name
        }

        # Locking strategy: Apply EXCLUSIVE lock on the registry file itself
        with open(path, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            try:
                content = f.read()
                if content:
                    data = json.loads(content)
                else:
                    data = []
            except json.JSONDecodeError:
                data = []

            # Deduplication: Replace existing entry with same ID or append new
            for i, existing in enumerate(data):
                if existing.get("session_id") == manifest.session_id:
                    data[i] = entry
                    break
            else:
                data.append(entry)

            # Atomic Rewrite: Truncate and write full JSON back
            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2)
            f.flush()
            fcntl.flock(f, fcntl.LOCK_UN)

    @classmethod
    def update_session_status(cls, session_id: str, status: str) -> None:
        """
        Function: Updates the execution status (e.g., PENDING -> SUCCESS) of a session.
        Why: Allows the UI to reflect real-time progress while maintaining index consistency.
        """
        path = cls._get_registry_path()
        if not path.exists():
            return

        with open(path, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                content = f.read()
                if content:
                    data = json.load(content)
                else:
                    data = []
            except json.JSONDecodeError:
                fcntl.flock(f, fcntl.LOCK_UN)
                return

            updated = False
            for entry in data:
                if entry.get("session_id") == session_id:
                    entry["status"] = status
                    updated = True
                    break

            if updated:
                f.seek(0)
                f.truncate()
                json.dump(data, f, indent=2)
                f.flush()

            fcntl.flock(f, fcntl.LOCK_UN)
