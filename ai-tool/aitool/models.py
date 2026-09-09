"""
Architectural Role: Core data models representing AI interaction sessions.
This module provides a provider-agnostic BaseSession abstraction and concrete
implementations for Claude and Gemini, ensuring a unified interface for the UI.
"""
import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import List, Optional

class BaseSession(ABC):
    file_path: Path
    session_id: str
    is_archived: bool
    cwd: str
    workspace_name: str
    summary: str
    date_str: str
    messages: list
    # Why: We use a 2nd-stage lazy evaluation for the full text.
    # Computing this for hundreds of sessions during initial load would be
    # computationally expensive and impact UI responsiveness.
    _full_text: Optional[str] = None

    @property
    def full_text(self) -> str:
        # Why: Lazy loading pattern ensures we only pay the cost of string
        # concatenation and normalization when a search actually hits this session.
        if self._full_text is None:
            self._full_text = self._compute_full_text()
        return self._full_text

    @abstractmethod
    def _compute_full_text(self) -> str: ...

    @abstractmethod
    def get_markdown(self) -> str: ...

    @abstractmethod
    def extract_recent_texts(self, n: int = 10) -> List[str]: ...

    @abstractmethod
    def get_last_message_text(self) -> str: ...


class ClaudeSession(BaseSession):
    def __init__(self, file_path: Path, is_archived: bool = False):
        self.file_path = file_path
        self.session_id = file_path.stem
        self.is_archived = is_archived
        self.cwd = "Unknown"
        self.workspace_name = "Unknown"
        self.summary = "No Summary"
        self.date_str = "Unknown"
        self.messages: list = []
        self._full_text = None
        self.load()

    def load(self):
        try:
            lines = []
            with open(self.file_path, "r", encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        lines.append(json.loads(raw))
                    except Exception:
                        continue

            last_ts = ""
            for obj in lines:
                obj_type = obj.get("type", "")
                if not self.cwd or self.cwd == "Unknown":
                    if obj.get("cwd"):
                        self.cwd = obj["cwd"]
                        self.workspace_name = Path(self.cwd).name
                if obj_type in ("user", "assistant"):
                    self.messages.append(obj)
                    ts = obj.get("timestamp", "")
                    if ts:
                        last_ts = ts

            if last_ts:
                self.date_str = last_ts[:16].replace("T", " ")
            else:
                try:
                    mtime = self.file_path.stat().st_mtime
                    self.date_str = datetime.fromtimestamp(
                        mtime).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pass

            for msg in self.messages:
                if msg.get("type") == "user":
                    text = self._extract_text(
                        msg.get("message", {}).get("content", ""))
                    self.summary = text.strip().replace(
                        "\n", " ")[:80] or "No Summary"
                    break

        except Exception:
            pass

    def _compute_full_text(self) -> str:
        texts = []
        for msg in self.messages:
            texts.append(self._extract_text(
                msg.get("message", {}).get("content", "")))
        return " ".join(texts).replace(
            "\n", " ").replace("\r", " ")

    @staticmethod
    def _extract_text(content) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return " ".join(parts)
        return str(content)

    def get_markdown(self) -> str:
        parts = []
        for msg in self.messages:
            msg_type = msg.get("type", "")
            if msg_type not in ("user", "assistant"):
                continue
            role = "### 🟡 [USER]" if msg_type == "user" else "### 🔵 [CLAUDE]"
            text = self._extract_text(
                msg.get("message", {}).get("content", ""))
            if text.strip():
                parts.append(f"{role}\n\n{text}")
        return "\n\n---\n\n".join(parts)

    def extract_recent_texts(self, n: int = 10) -> List[str]:
        recent = self.messages[-n:] if len(
            self.messages) >= n else self.messages
        texts = []
        for msg in recent:
            text = self._extract_text(
                msg.get("message", {}).get("content", ""))[:2000]
            texts.append(text)
        return texts

    def get_last_message_text(self) -> str:
        if not self.messages:
            return ""
        last_msg = self.messages[-1]
        return self._extract_text(last_msg.get("message", {}).get("content", ""))


class GeminiSession(BaseSession):
    def __init__(self, file_path: Path, workspace_path: str, is_archived: bool = False):
        self.file_path = file_path
        self.cwd = workspace_path
        self.workspace_name = Path(
            workspace_path).name if workspace_path != "Unknown" else "Unknown"
        self.is_archived = is_archived
        self.data: dict = {}
        self.summary = "No Summary"
        self.date_str = "Unknown"
        self.session_id = ""
        self.messages: list = []
        self._full_text = None
        self.load()

    def load(self):
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                self.data = json.load(f)

            self.messages = self.data.get("messages", [])
            self.summary = self.data.get(
                "summary", "No Summary").replace("\n", " ")

            date_raw = self.data.get(
                "lastUpdated", self.data.get("startTime", "Unknown"))
            self.date_str = (
                date_raw[:16].replace("T", " ")
                if date_raw and date_raw != "Unknown"
                else "Unknown"
            )
            self.session_id = self.data.get("sessionId", "")

        except Exception:
            pass

    def _compute_full_text(self) -> str:
        texts = []
        for msg in self.messages:
            content = msg.get("content", "")
            if isinstance(content, list) and content:
                item = content[0]
                texts.append(str(item.get("text", item)
                             if isinstance(item, dict) else item))
            elif isinstance(content, dict):
                texts.append(str(content.get("text", "")))
            else:
                texts.append(str(content))
        return " ".join(texts).replace(
            "\n", " ").replace("\r", " ").replace("|", " ")

    @staticmethod
    def _extract_content(content) -> str:
        if isinstance(content, list) and content:
            item = content[0]
            return str(item.get("text", item) if isinstance(item, dict) else item)
        elif isinstance(content, dict):
            return str(content.get("text", ""))
        return str(content)

    def get_markdown(self) -> str:
        parts = []
        for msg in self.messages:
            role = "### 🟢 [USER]" if msg.get(
                "type") == "user" else "### 🔵 [GEMINI]"
            thoughts_md = ""
            thoughts = msg.get("thoughts", [])
            if isinstance(thoughts, list) and thoughts:
                subject = (
                    thoughts[0].get("subject", "Thinking...")
                    if isinstance(thoughts[0], dict)
                    else "Thinking..."
                )
                thoughts_md = f"> 💭 {subject}\n\n"
            text = self._extract_content(msg.get("content", ""))
            parts.append(f"{role}\n\n{thoughts_md}{text}")
        return "\n\n---\n\n".join(parts)

    def extract_recent_texts(self, n: int = 10) -> List[str]:
        recent = self.messages[-n:] if len(
            self.messages) >= n else self.messages
        texts = []
        for msg in recent:
            text = self._extract_content(msg.get("content", ""))[:2000]
            texts.append(text)
        return texts

    def get_last_message_text(self) -> str:
        if not self.messages:
            return ""
        last_msg = self.messages[-1]
        return self._extract_content(last_msg.get("content", ""))
