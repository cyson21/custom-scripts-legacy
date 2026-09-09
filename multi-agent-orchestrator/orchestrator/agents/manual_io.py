"""
Architectural Role: Manual Input Collection Utility.
This module provides the low-level CLI interaction logic for manual agent mode. 
It allows the orchestrator to pause execution and wait for a human developer to 
provide a response (e.g. code blocks, review comments) via a designated 
terminal marker.
"""
from __future__ import annotations

from pathlib import Path

from orchestrator.core.storage import write_text

# Why: A unique marker is required to identify the end of a multi-line input block 
# in a standard CLI environment without complex TTY handling.
MANUAL_END_MARKER = "__END__"


def collect_manual_block(title: str, target_path: Path, seed_text: str | None = None) -> str:
    """
    Function: Blocks execution and collects multi-line text from the terminal.
    Why: Provides a simple, reliable way for developers to interact with the 
    swarm when automated agents fail or require explicit human approval.
    """
    print()
    print(title)
    print(f"아래 내용을 붙여넣고 마지막 줄에 {MANUAL_END_MARKER} 만 입력하세요.")
    print(f"저장 파일: {target_path}")
    if seed_text:
        # Why: Displaying the prompt that triggered the manual mode helps the 
        # human developer understand the required context.
        print()
        print("참고 프롬프트:")
        print(seed_text)
    lines: list[str] = []
    while True:
        try:
            line = input()
            if line == MANUAL_END_MARKER:
                break
            lines.append(line)
        except EOFError:
            # Why: Handle Ctrl+D gracefully during manual input.
            break
            
    content = "\n".join(lines).strip()
    write_text(target_path, content)
    return content
