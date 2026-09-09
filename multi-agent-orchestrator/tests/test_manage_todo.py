import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _write_sample_files(tmp_path: Path) -> None:
    schema = json.loads((REPO_ROOT / "todo.schema.json").read_text(encoding="utf-8"))
    todo = {
        "version": "2.0",
        "project": "sample-project",
        "last_updated": "2026-03-22T12:20:00Z",
        "policy": {
            "commit_policy": "3",
            "require_validation_before_handoff": True,
        },
        "global_state": {
            "objective": "sample todo validation",
            "current_task_id": "t-001",
            "allowed_agents": ["gemini", "claude", "codex"],
            "stagnation_threshold": 3,
            "session_ref": None,
            "reviewed_by": None,
        },
        "tasks": [
            {
                "id": "t-001",
                "title": "sample task",
                "description": "sample task",
                "detail": None,
                "status": "in_progress",
                "priority": "high",
                "assigned_to": "codex",
                "completed_by": None,
                "depends_on": None,
                "retry_count": 0,
                "last_exit_code": None,
                "result_summary": None,
                "target_files": ["README.md"],
                "fallback_plan": None,
                "todo_marker_location": None,
                "tags": ["test"],
                "created_at": "2026-03-22T12:20:00Z",
                "started_at": "2026-03-22T12:20:00Z",
                "completed_at": None,
                "updated_at": "2026-03-22T12:20:00Z",
                "history": [],
            }
        ],
    }
    (tmp_path / "todo.schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "todo.json").write_text(
        json.dumps(todo, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_manage_todo_writes_validation_output(tmp_path):
    _write_sample_files(tmp_path)

    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "manage_todo.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    validation = json.loads((tmp_path / "todo.validation.json").read_text(encoding="utf-8"))
    assert validation["valid"] is True
    assert validation["todo_file"] == str((tmp_path / "todo.json").resolve())
    assert validation["schema_file"] == str((tmp_path / "todo.schema.json").resolve())
    assert "todo_sha256" in validation


def test_validate_todo_wrapper_delegates_to_manage_todo(tmp_path):
    _write_sample_files(tmp_path)

    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "validate_todo.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "manage_todo.py" in result.stderr
    validation = json.loads((tmp_path / "todo.validation.json").read_text(encoding="utf-8"))
    assert validation["valid"] is True
