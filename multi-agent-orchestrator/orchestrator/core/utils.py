import json
import re
import subprocess
import sys
import os
import platform


def strip_ansi(text: str) -> str:
    """Strips ANSI escape codes from text."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


def copy_to_clipboard(text: str) -> bool:
    """Copies text to the system clipboard using platform-specific commands."""
    try:
        data = text.encode('utf-8')
        if sys.platform == 'darwin':
            subprocess.run(['pbcopy'], input=data, check=True, timeout=10)
        elif sys.platform == 'win32':
            subprocess.run(['clip'], input=data, check=True, timeout=10)
        else:  # Linux and others
            try:
                subprocess.run(['xclip', '-selection', 'clipboard'],
                               input=data, check=True, timeout=10)
            except (subprocess.CalledProcessError, FileNotFoundError):
                subprocess.run(['xsel', '--clipboard', '--input'],
                               input=data, check=True, timeout=10)
        return True
    except Exception:
        return False


def extract_json(text: str) -> dict | None:
    """Extracts JSON from text, handling markdown blocks and filler."""
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    match = re.search(r'```(?:json)?\s*(.*?)\s*```',
                      text,
                      re.DOTALL | re.IGNORECASE)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    start_idx = text.find('{')
    end_idx = text.rfind('}')
    if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
        json_str = text[start_idx:end_idx + 1]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    return None


def get_git_hash() -> str | None:
    """Returns the current Git hash of the repository."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_os_info() -> str:
    """Returns basic OS information."""
    return f"{platform.system()} {platform.release()} ({platform.machine()})"


def get_filtered_env_vars() -> dict:
    """Returns key environment variables, excluding sensitive ones."""
    keys = [
        'PATH', 'PYTHONPATH', 'LANG', 'SHELL', 'USER', 'HOME',
        'VIRTUAL_ENV', 'CONDA_DEFAULT_ENV', 'TERM', 'PWD'
    ]
    return {k: os.environ.get(k) for k in keys if k in os.environ}


def extract_context_paths(text: str) -> list[str]:
    """Finds all @path/to/file patterns in the text."""
    # Matches @ followed by non-whitespace characters that look like a path
    return re.findall(r'@([\w\.\/\-\\]+)', text)


def resolve_and_read_context(paths: list[str], workspace_dir: str) -> str:
    """Reads the contents of the given paths and returns a formatted string."""
    from pathlib import Path
    context_lines = []
    base_path = Path(workspace_dir).resolve()

    for p in set(paths):
        full_path = (base_path / p).resolve()
        # Security: Ensure resolved path is within workspace_dir
        if not str(full_path).startswith(str(base_path)):
            continue

        if full_path.exists() and full_path.is_file():
            try:
                content = full_path.read_text(encoding='utf-8')
                context_lines.append(f"--- [File: {p}] ---")
                context_lines.append("```")
                context_lines.append(content)
                context_lines.append("```\n")
            except Exception as e:
                context_lines.append(f"--- [Error reading {p}: {str(e)}] ---\n")
        elif full_path.exists() and full_path.is_dir():
            context_lines.append(f"--- [Directory: {p}] ---")
            files = sorted([f.name for f in full_path.iterdir() if f.is_file()])
            context_lines.append(f"Files: {', '.join(files)}\n")

    return "\n".join(context_lines)


def get_todo_progress() -> dict:
    """
    Function: Parses todo.json and todo.validation.json to provide progress metrics.
    Why: Fuels the Live Progress Dashboard in the CLI.
    """
    try:
        from pathlib import Path
        todo_path = Path("todo.json")
        validation_path = Path("todo.validation.json")

        if not todo_path.exists():
            return {"task_id": "N/A", "progress": 0, "valid": False}

        with open(todo_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        global_state = data.get("global_state", {})
        current_task_id = global_state.get("current_task_id", "N/A")
        if not current_task_id:
            current_task_id = "N/A"

        # Calculate overall progress across all workstreams
        total_tasks = 0
        completed_tasks = 0

        workstreams = data.get("workstreams", [])
        for ws in workstreams:
            stats = ws.get("status_summary", {})
            total_tasks += stats.get("total", 0)
            completed_tasks += stats.get("completed", 0)

        progress = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0

        valid = False
        if validation_path.exists():
            with open(validation_path, "r", encoding="utf-8") as f:
                v_data = json.load(f)
                valid = v_data.get("valid", False)

        return {
            "task_id": current_task_id,
            "progress": progress,
            "valid": valid,
            "total": total_tasks,
            "completed": completed_tasks
        }
    except Exception:
        return {"task_id": "Error", "progress": 0, "valid": False}
