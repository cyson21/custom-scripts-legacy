import logging
import json
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict

# Get project root (where logger.py's parent is orchestrator/)
PROJECT_ROOT = Path(__file__).parent.parent
LOG_FILE = PROJECT_ROOT / "orchestrator.log"
MAX_BYTES = 5 * 1024 * 1024  # 5MB
BACKUP_COUNT = 5
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging():
    """Sets up the global logging configuration."""
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Prevent adding multiple handlers if setup_logging is called repeatedly
    if not logger.handlers:
        # Formatter
        formatter = logging.Formatter(LOG_FORMAT)

        # File Handler (Rotating)
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT
        )

        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # Optional: Console Handler (can be disabled if TUI is active)
        # console_handler = logging.StreamHandler()
        # console_handler.setFormatter(formatter)
        # logger.addHandler(console_handler)


def get_logger(name: str):
    """Returns a logger instance for the given name."""
    if not logging.getLogger().handlers:
        setup_logging()
    return logging.getLogger(name)


class SwarmEventLogger:
    """
    Streaming event logger for swarm operations.
    Appends structured JSON objects to events.jsonl in real-time.
    """

    def __init__(self, artifact_dir: Path):
        self.artifact_dir = artifact_dir
        self.event_file = artifact_dir / "events.jsonl"
        self._ensure_dir()

    def _ensure_dir(self):
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def log_event(self, event_type: str, payload: Dict[str, Any]):
        """Logs a generic event with a type and payload."""
        event = {
            "timestamp": time.time(),
            "event_type": event_type,
            **payload
        }
        with open(self.event_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def log_action(self, agent: str, action: str,
                   metadata: Dict[str, Any] = None):
        """Logs an agent action."""
        payload = {
            "agent": agent,
            "action": action
        }
        if metadata:
            payload.update(metadata)
        self.log_event("agent_action", payload)

    def log_observation(self, agent: str, observation: str,
                        metadata: Dict[str, Any] = None):
        """Logs an observation (result of an action)."""
        payload = {
            "agent": agent,
            "observation": observation
        }
        if metadata:
            payload.update(metadata)
        self.log_event("agent_observation", payload)

    def log_thought(self, agent: str, thought: str):
        """Logs an agent's internal thought process."""
        self.log_event("agent_thought", {
            "agent": agent,
            "thought": thought
        })
