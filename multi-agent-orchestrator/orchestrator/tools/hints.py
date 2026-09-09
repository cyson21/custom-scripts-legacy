import json
import re
import time
from pathlib import Path
from typing import List, Optional
from orchestrator.core.models import Hint

DB_MAX_SIZE = 1000
CONFIDENCE_THRESHOLD = 10
MAX_HINT_AGE_DAYS = 30
CONFIDENCE_BOOST = 10
CONFIDENCE_DECAY_RATE = 1  # Per day


class HintDatabase:
    """
    Manages a database of 'Smart Hints' to help agents correct common mistakes.
    Inspired by OmO's empty result hints.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.hints: List[Hint] = self._load_hints()

    def _load_hints(self) -> List[Hint]:
        if not self.db_path.exists():
            # Default hints
            return [
                Hint(pattern=r"sed: -e expression #\d+, char \d+: "
                             r"expected newer version",
                     message="It looks like you are using an incompatible sed "
                             "syntax. Try using a simpler regex or the "
                             "'replace' tool.",
                     category="shell"),
                Hint(pattern=r"SyntaxError: invalid syntax",
                     message="You have a python syntax error. Check for "
                             "missing colons or unmatched parentheses.",
                     category="python"),
                Hint(pattern=r"ast-grep.*no match",
                     message="Your ast-grep query returned no results. "
                             "Did you include unnecessary syntax like "
                             "trailing colons or semi-colons?",
                     category="ast-grep")
            ]

        loaded_hints = []
        try:
            data = json.loads(self.db_path.read_text())
            for h_data in data:
                # For backward compatibility with old format
                if 'created_at' not in h_data:
                    h_data['created_at'] = time.time()
                if 'last_hit_at' not in h_data:
                    h_data['last_hit_at'] = time.time()
                if 'confidence_score' not in h_data:
                    h_data['confidence_score'] = 100.0
                loaded_hints.append(Hint(**h_data))
        except (json.JSONDecodeError, TypeError):
            return []

        return self._prune_and_decay(loaded_hints)

    def _prune_and_decay(self, hints: List[Hint]) -> List[Hint]:
        """
        Prunes old/unreliable hints and applies decay to confidence scores.
        """
        now = time.time()
        max_age_seconds = MAX_HINT_AGE_DAYS * 24 * 60 * 60

        updated_hints = []
        for hint in hints:
            # Pruning logic
            age_seconds = now - hint.created_at
            if age_seconds > max_age_seconds:
                continue  # Hint is too old
            if hint.confidence_score < CONFIDENCE_THRESHOLD:
                continue  # Confidence is too low

            # Decay logic
            days_since_last_hit = (now - hint.last_hit_at) / (24 * 60 * 60)
            decay = days_since_last_hit * CONFIDENCE_DECAY_RATE
            hint.confidence_score = max(0, hint.confidence_score - decay)

            updated_hints.append(hint)

        return updated_hints

    def save_hints(self):
        # Ensure FIFO limit before saving
        if len(self.hints) > DB_MAX_SIZE:
            self.hints.sort(key=lambda h: h.created_at)
            self.hints = self.hints[-DB_MAX_SIZE:]

        self.db_path.write_text(
            json.dumps([h.__dict__ for h in self.hints], indent=2)
        )

    def find_hint(self, error_message: str) -> Optional[str]:
        """Finds a matching hint for the given error message."""
        now = time.time()
        for hint in self.hints:
            if re.search(hint.pattern, error_message, re.IGNORECASE):
                hint.hit_count += 1
                hint.last_hit_at = now
                hint.confidence_score = min(
                    150, hint.confidence_score + CONFIDENCE_BOOST)
                self.save_hints()
                return hint.message
        return None

    def add_hint(self, pattern: str, message: str, category: str = "general"):
        # Check for duplicates
        for hint in self.hints:
            if hint.pattern == pattern:
                return

        new_hint = Hint(pattern=pattern, message=message, category=category)
        self.hints.append(new_hint)
        self.save_hints()
