#!/usr/bin/env python3
"""호환용 todo 검증 래퍼.

기존 `python scripts/validate_todo.py` 호출은 유지하되,
실제 표준 갱신 경로는 `python scripts/manage_todo.py`로 통일한다.
"""

from __future__ import annotations

import sys

try:
    from manage_todo import main as manage_todo_main
except ImportError:  # pragma: no cover
    from scripts.manage_todo import main as manage_todo_main


if __name__ == "__main__":
    print(
        "[INFO] validate_todo.py는 호환용 래퍼입니다. "
        "표준 경로는 `python scripts/manage_todo.py` 입니다.",
        file=sys.stderr,
    )
    raise SystemExit(manage_todo_main(sys.argv[1:]))
