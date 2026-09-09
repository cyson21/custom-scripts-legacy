"""
Architectural Role: Session History Management.
This module defines the data structures and providers responsible for persisting,
retrieving, and managing the lifecycle of swarm orchestration sessions.
It abstracts the physical storage (artifacts directory) into a logical history tree.
"""
import json
import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict, field
from datetime import datetime

from abc import ABC, abstractmethod
from orchestrator.core.storage import RegistryManager


@dataclass
class SessionMetadata:
    """
    Function: Holds high-level information about a session for TUI list rendering.
    Why: Separating metadata from full session traces allows for rapid list loading 
    and filtering without parsing large JSON artifacts for every item.
    """
    id: str
    title: str
    timestamp: str
    archived: bool = False
    tokens: int = 0
    cost: float = 0.0
    status: str = "completed"
    workspace: str = "Unknown"
    full_text: str = ""
    path: str = ""  # Why: Stores the actual physical directory path for the session.
    checkpoint_name: Optional[str] = None
    mission_data: Dict[str, Any] = field(default_factory=dict)


class BaseSession(ABC):
    """Abstract base for session data retrieval."""
    @abstractmethod
    def get_markdown(self) -> str:
        """Returns the full session results as a Markdown string."""
        ...

    @abstractmethod
    def get_last_message_text(self) -> str:
        """Returns the last significant text output for quick previews."""
        ...


class SwarmSession(BaseSession):
    """
    Function: Implementation of a physical session stored in the artifacts directory.
    Why: Handles lazy-loading of trace data to minimize memory footprint in the history view.
    """
    def __init__(self, metadata: SessionMetadata, session_dir: Path):
        self.metadata = metadata
        self.session_dir = session_dir
        self._trace_data: Optional[Dict[str, Any]] = None

    def _ensure_trace(self) -> Dict[str, Any]:
        """Loads trace.json on demand."""
        if self._trace_data is None:
            trace_path = self.session_dir / "trace.json"
            if trace_path.exists():
                try:
                    with open(trace_path, "r", encoding="utf-8") as f:
                        self._trace_data = json.load(f)
                except Exception:
                    self._trace_data = {}
        return self._trace_data or {}

    def get_markdown(self) -> str:
        """
        Function: Resolves the best visual representation of the session.
        Why: Prioritizes the final report if it exists, falling back to raw logs for failed/interrupted missions.
        """
        report_path = self.session_dir / "final_report.md"
        if report_path.exists():
            return report_path.read_text(encoding="utf-8")
        
        logs_path = self.session_dir / "session_logs.txt"
        if logs_path.exists():
            return f"```\n{logs_path.read_text(encoding='utf-8')}\n```"
            
        return "No report or logs found for this session."

    def get_last_message_text(self) -> str:
        return self.metadata.title


class BaseHistoryProvider(ABC):
    """Abstract interface for session storage backends."""
    @abstractmethod
    def load_sessions(self, include_archived: bool = False) -> List[SwarmSession]:
        ...

    @abstractmethod
    def get_session_from_disk(self, session_id: str, archived: bool = False) -> Optional[SwarmSession]:
        ...

    @abstractmethod
    def archive_session(self, path: Path) -> bool:
        ...

    @abstractmethod
    def unarchive_session(self, path: Path) -> bool:
        ...

    @abstractmethod
    def delete_session(self, path: Path) -> bool:
        ...

    @abstractmethod
    def rename_session(self, path: Path, new_title: str) -> bool:
        ...


class SwarmHistoryProvider(BaseHistoryProvider):
    """
    Function: File-system based history management.
    Why: Uses a dual-strategy (Registry + Directory Scan) to ensure no sessions 
    are lost even if the registry file is corrupted or manually edited.
    """
    def __init__(self, artifacts_dir: Path):
        self.artifacts_dir = artifacts_dir
        self.archived_dir = artifacts_dir / "archived"
        self.archived_dir.mkdir(parents=True, exist_ok=True)

    def _load_metadata(self, session_dir: Path) -> SessionMetadata:
        """
        Function: Aggregates metadata from multiple JSON files.
        Why: We prefer manifest.json as the primary source of truth (runtime data), 
        but fallback to metadata.json (user edits) or the directory name to 
        ensure robustness during partial failures or manual refactoring.
        """
        session_id = session_dir.name
        manifest_path = session_dir / "manifest.json"
        metadata_path = session_dir / "metadata.json"

        data = {}
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    m = json.load(f)
                    ts = m.get("timestamp")
                    ts_iso = datetime.fromtimestamp(ts).isoformat() if ts else None
                    data.update({
                        "id": m.get("session_id"),
                        "title": m.get("user_prompt", session_id)[:60],
                        "timestamp": ts_iso,
                        "status": m.get("status"),
                        "tokens": m.get("total_tokens", 0),
                        "checkpoint_name": m.get("checkpoint_name"),
                        "mission_data": {
                            "prompt": m.get("user_prompt"),
                            "units": m.get("deployment_units", [])
                        }
                    })
            except Exception:
                pass

        if metadata_path.exists():
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    data.update(json.load(f))
            except Exception:
                pass

        return SessionMetadata(
            id=data.get("id", session_id),
            title=data.get("title", session_id),
            timestamp=data.get("timestamp", "Unknown"),
            archived=(self.archived_dir in session_dir.parents),
            tokens=data.get("tokens", 0),
            status=data.get("status", "completed"),
            workspace=data.get("workspace", "multi-agent-orchestrator"),
            full_text=data.get("full_text", ""),
            path=str(session_dir),
            mission_data=data.get("mission_data", {})
        )

    def load_sessions(self, include_archived: bool = False) -> List[SwarmSession]:
        """
        Function: Retrieves all available sessions, sorted by time.
        Why: RegistryManager provides the indexed list of sessions for performance,
        but we also scan the physical artifacts directory to find any unregistered 
        sessions (e.g., from manual file moves or legacy versions).
        """
        sessions = []
        seen_ids = set()
        seen_paths = set()
        
        # 1. Load from indexed registry
        registry = RegistryManager.load_registry()
        for entry in registry:
            sid = entry.get("session_id")
            path = Path(entry.get("artifacts_path", ""))
            if path.exists() and path.is_dir():
                sessions.append(SwarmSession(self._load_metadata(path), path))
                seen_ids.add(sid)
                seen_paths.add(str(path))

        # 2. Safety scan for unregistered items
        if self.artifacts_dir.exists():
            for item in self.artifacts_dir.iterdir():
                if item.is_dir() and item.name != "archived" and str(item) not in seen_paths:
                    sessions.append(SwarmSession(self._load_metadata(item), item))

        if include_archived:
            if self.archived_dir.exists():
                for item in self.archived_dir.iterdir():
                    if item.is_dir() and str(item) not in seen_paths:
                        sessions.append(SwarmSession(self._load_metadata(item), item))

        return sorted(sessions, key=lambda x: x.metadata.timestamp, reverse=True)

    def get_session_from_disk(self, session_id: str, archived: bool = False) -> Optional[SwarmSession]:
        """Attempt to find a session by ID directly on disk if not in registry/cache."""
        # This is a bit expensive, but used as a fallback
        target_dir = self.archived_dir if archived else self.artifacts_dir
        if target_dir.exists():
            # Check by folder name first (ID might match folder name)
            item = target_dir / session_id
            if item.exists() and item.is_dir():
                return SwarmSession(self._load_metadata(item), item)
            
            # Then scan (last resort)
            for item in target_dir.iterdir():
                if item.is_dir() and item.name != "archived":
                    meta = self._load_metadata(item)
                    if meta.id == session_id:
                        return SwarmSession(meta, item)
        return None

    def archive_session(self, path: Path) -> bool:
        """Moves session to the archived subfolder."""
        if not path.exists():
            return False
        dst = self.archived_dir / path.name
        if path.parent == self.archived_dir:
            return True # already archived
        shutil.move(str(path), str(dst))
        return True

    def unarchive_session(self, path: Path) -> bool:
        """Restores session from archive to active status."""
        if not path.exists():
            return False
        dst = self.artifacts_dir / path.name
        if path.parent == self.artifacts_dir:
            return True # already unarchived
        shutil.move(str(path), str(dst))
        return True

    def delete_session(self, path: Path) -> bool:
        """Permanently removes session files from disk."""
        if path.exists():
            shutil.rmtree(path)
            return True
        return False

    def rename_session(self, path: Path, new_title: str) -> bool:
        """Updates the session title in metadata.json."""
        if not path.exists():
            return False
        meta_path = path / "metadata.json"
        meta = self._load_metadata(path)
        meta.title = new_title
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(asdict(meta), f, indent=4)
        return True


class HistoryManager:
    """
    Architectural Role: Main entry point for session retrieval.
    Why: Acts as a bridge between the TUI and the storage providers, ensuring 
    path resolution is handled centrally and absolute paths are used regardless of CWD.
    """
    def __init__(self, artifacts_dir: str = None):
        if artifacts_dir is None:
            # Why: Dynamically resolve to project root to prevent path errors 
            # when the application is launched from different terminal locations.
            self.base_path = Path(__file__).parent.parent.parent / "artifacts"
        else:
            self.base_path = Path(artifacts_dir)
        self.provider = SwarmHistoryProvider(self.base_path)
        self._session_cache: Dict[str, SessionMetadata] = {}

    def _clear_cache(self) -> None:
        self._session_cache.clear()

    def list_sessions(self, include_archived: bool = False) -> List[SessionMetadata]:
        """Returns a sorted list of all session metadata, utilizing a cache."""
        if not self._session_cache or (include_archived and not any(s.archived for s in self._session_cache.values())):
            sessions = self.provider.load_sessions(include_archived)
            for s in sessions:
                self._session_cache[s.metadata.id] = s.metadata
        
        return sorted(
            [s for s in self._session_cache.values() if include_archived or not s.archived],
            key=lambda x: x.timestamp, reverse=True
        )

    def get_session(self, session_id: str, include_archived: bool = False) -> Optional[SwarmSession]:
        """Retrieves a specific session by ID from cache or provider."""
        if session_id in self._session_cache:
            meta = self._session_cache[session_id]
            return SwarmSession(meta, Path(meta.path))
        
        # If not in cache, try loading directly from disk
        s = self.provider.get_session_from_disk(session_id, include_archived)
        if s:
            self._session_cache[s.metadata.id] = s.metadata
            return s
        return None
    
    def delete_session(self, session_id: str, archived: bool = False) -> bool:
        meta = self._session_cache.get(session_id)
        if meta:
            if self.provider.delete_session(Path(meta.path)):
                del self._session_cache[session_id]
                return True
        else:
            # Fallback if not in cache (though unlikely in current TUI flow)
            s = self.provider.get_session_from_disk(session_id, archived)
            if s and self.provider.delete_session(s.session_dir):
                return True
        return False

    def archive_session(self, session_id: str) -> bool:
        meta = self._session_cache.get(session_id)
        if meta:
            old_path = Path(meta.path)
            if self.provider.archive_session(old_path):
                meta.archived = True
                meta.path = str(self.base_path / "archived" / old_path.name)
                return True
        return False

    def unarchive_session(self, session_id: str) -> bool:
        meta = self._session_cache.get(session_id)
        if meta:
            old_path = Path(meta.path)
            if self.provider.unarchive_session(old_path):
                meta.archived = False
                meta.path = str(self.base_path / old_path.name)
                return True
        return False

    def rename_session(self, session_id: str, new_title: str, archived: bool = False) -> bool:
        meta = self._session_cache.get(session_id)
        if meta:
            if self.provider.rename_session(Path(meta.path), new_title):
                meta.title = new_title
                return True
        return False

    def restore_session_checkpoint(self, session_id: str) -> bool:
        """
        Reverts the workspace to the pre-mission state captured in the session's checkpoint.
        """
        meta = self._session_cache.get(session_id)
        if not meta or not meta.checkpoint_name or not meta.workspace:
            return False
        
        from orchestrator.tools.sandbox import SandboxManager
        try:
            manager = SandboxManager(Path(meta.workspace))
            manager.restore_checkpoint(meta.checkpoint_name)
            return True
        except Exception:
            return False
