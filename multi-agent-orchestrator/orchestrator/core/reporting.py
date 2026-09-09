from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime


class SwarmEventLogger:
    def __init__(self, artifact_dir: Path):
        self.log_path = artifact_dir / "events.jsonl"
        self.artifact_dir = artifact_dir

    def log_event(self, event_type: str, data: dict):
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "data": data
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")


def build_final_report(
    user_prompt: str,
    gemini_result: str,
    codex_result: str,
    gemini_review: str,
    codex_review: str,
    consensus_status: str,
    shared_points: list[str],
    open_issues: list[str],
    recommended_final: str,
) -> str:
    shared = "\n".join(f"- {item}" for item in shared_points) or "- 없음"
    issues = "\n".join(f"- {item}" for item in open_issues) or "- 없음"
    return f"""# Final Report

## 사용자 질문
{user_prompt}

## 합의 상태
{consensus_status}

## 공통 결론
{shared}

## Gemini 관점 보완점
{gemini_review}

## Codex 관점 보완점
{codex_review}

## 남은 쟁점
{issues}

## 최종 권고안
{recommended_final}

## 원본 답변
### Gemini
{gemini_result}

### Codex
{codex_result}
"""

def generate_execution_trace_md(execution_trace: list[dict], diff_memory: list[dict]) -> str:
    """
    Generates a markdown summary of the execution trace and accumulated diffs.
    """
    lines = ["# Execution Trace Report\n"]
    
    lines.append("## Sisyphus Loop Timeline\n")
    if not execution_trace:
        lines.append("*No execution traces recorded.*\n")
    
    for entry in execution_trace:
        lines.append(f"### Attempt {entry.get('attempt', '?')}")
        lines.append(f"**Success:** {'✅ Yes' if entry.get('success') else '❌ No'}")
        
        action = entry.get('action', '')
        if len(action) > 500:
            action = action[:500] + "\n...[truncated]"
        lines.append(f"\n**Action Taken:**\n```json\n{action}\n```\n")
        
        obs = entry.get('observation', '')
        if obs:
            lines.append(f"**Observation:**\n```\n{obs}\n```\n")
            
        hint = entry.get('hint', '')
        if hint:
            lines.append(f"**Hint Provided:**\n> {hint.replace(chr(10), chr(10) + '> ')}\n")
            
        lines.append("---\n")
        
    lines.append("\n## Accumulated Changes (Diff Memory)\n")
    if not diff_memory:
        lines.append("*No files were modified.*\n")
        
    for idx, diff_record in enumerate(diff_memory, 1):
        lines.append(f"### {idx}. {diff_record.get('tool_name', 'tool')} on `{diff_record.get('file_path', 'unknown')}`")
        lines.append(f"```diff\n{diff_record.get('diff', '')}\n```\n")
        
    return "\n".join(lines)
