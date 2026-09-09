"""
Architectural Role: Centralized configuration and logging subsystem.
This module handles global settings, directory path resolutions, and persistent
metadata storage for custom session titles.
"""
import re
import json
import logging
from datetime import datetime
from pathlib import Path

# Why: We use an external JSON meta file (META_FILE) because the underlying
# Claude Code session files (.jsonl) are managed by an external binary.
# Storing custom titles here ensures they persist across app restarts without
# tampering with the raw session data.
_LOG_DIR = Path(__file__).parent / "log"
_LOG_DIR.mkdir(exist_ok=True)
_LOG_FILE = _LOG_DIR / f"ai_tool_{datetime.now().strftime('%Y-%m-%d')}.log"

logging.basicConfig(
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(_LOG_FILE, encoding="utf-8")],
)
logger = logging.getLogger("ai_tool")

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
META_FILE = Path.home() / ".claude" / "ai-tool-meta.json"
AITOOL_CONFIG_FILE = Path.home() / ".claude" / "ai-tool-config.json"
_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
LEGACY_META_FILE = Path.home() / ".claude" / "claude-tool-meta.json"

def load_config() -> dict:
    default_config = {
        "excluded_workspaces": [],
        "terminal_open_mode": "window",  # "window" or "tab"
        "ide_command": "code",  # Default IDE command (e.g. code, cursor, idea)
        "auto_ai_summary": False  # Automatically summarize sessions with no title
    }
    if AITOOL_CONFIG_FILE.exists():
        try:
            with open(AITOOL_CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                # Merge with defaults to ensure all keys exist
                for k, v in default_config.items():
                    if k not in config:
                        config[k] = v
                return config
        except Exception as e:
            logger.error(f"Error loading config: {e}")
    return default_config

def save_config(config: dict):
    try:
        with open(AITOOL_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving config: {e}")

