import shutil
from pathlib import Path
from typing import Dict, Any, List


class BackupManager:
    """Manages file backups for the 'Undo/Rollback System'."""

    def __init__(self, backup_dir: Path):
        self.backup_dir = backup_dir
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.history: List[Dict[str, Any]] = []

    def create_backup(self, file_path: Path) -> Path:
        """Creates a timestamped backup of the given file."""
        import time
        timestamp = int(time.time() * 1000)
        backup_name = f"{file_path.name}.{timestamp}.bak"
        backup_path = self.backup_dir / backup_name
        shutil.copy2(file_path, backup_path)

        self.history.append({
            "original_path": file_path,
            "backup_path": backup_path,
            "timestamp": timestamp
        })
        return backup_path

    def rollback(self) -> bool:
        """Rolls back the last change."""
        if not self.history:
            return False

        last_change = self.history.pop()
        shutil.copy2(last_change["backup_path"], last_change["original_path"])
        return True


def hook_execute_read_file(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transparent Tool Augmentation for 'read_file'.
    Executes the actual file reading if not already handled.
    """
    if payload.get("tool_name") == "read_file" and "output" not in payload:
        file_path_str = payload.get("file_path")
        if not file_path_str:
            payload["success"] = False
            payload["output"] = (
                "Error: 'file_path' is required for 'read_file' tool."
            )
            return payload

        # Resolve path relative to sandbox if provided, otherwise absolute
        sandbox_path = payload.get("sandbox_path")
        if sandbox_path:
            file_path = Path(sandbox_path) / file_path_str
        else:
            file_path = Path(file_path_str)

        if file_path.exists():
            try:
                payload["output"] = file_path.read_text(encoding="utf-8")
                payload["success"] = True
            except Exception as e:
                payload["success"] = False
                payload["output"] = f"Error reading file: {str(e)}"
        else:
            payload["success"] = False
            payload["output"] = f"File not found: {file_path_str}"

    return payload


def hook_execute_edit_file(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transparent Tool Augmentation for 'edit_file'.
    Executes hashline-based edits.
    """
    if payload.get("tool_name") == "edit_file" and "output" not in payload:
        file_path_str = payload.get("file_path")
        edits = payload.get("edits", [])

        if not file_path_str:
            payload["success"] = False
            payload["output"] = (
                "Error: 'file_path' is required for 'edit_file' tool."
            )
            return payload

        sandbox_path = payload.get("sandbox_path")
        if sandbox_path:
            file_path = Path(sandbox_path) / file_path_str
        else:
            file_path = Path(file_path_str)

        if not file_path.exists():
            payload["success"] = False
            payload["output"] = f"File not found: {file_path_str}"
            return payload

        try:
            current_content = file_path.read_text(encoding="utf-8")
            payload["old_content"] = current_content

            lines = current_content.splitlines()

            # Apply edits based on hashline_id
            for edit in edits:
                hashline_id = edit.get("hashline_id")
                new_content = edit.get("new_content")

                if not hashline_id:
                    continue

                try:
                    line_num = int(hashline_id.split('#')[0])
                    line_idx = line_num - 1
                    if 0 <= line_idx < len(lines):
                        lines[line_idx] = new_content
                    else:
                        payload["success"] = False
                        payload["output"] = (
                            f"Error: Line number {line_num} out of range."
                        )
                        return payload
                except (ValueError, IndexError):
                    payload["success"] = False
                    payload["output"] = (
                        f"Error: Invalid hashline_id format: {hashline_id}"
                    )
                    return payload

            final_content = "\n".join(lines)
            if current_content.endswith("\n"):
                final_content += "\n"

            backup_mgr = payload.get("_backup_manager")
            if backup_mgr:
                backup_mgr.create_backup(file_path)

            file_path.write_text(final_content, encoding="utf-8")
            payload["new_content"] = final_content
            payload["success"] = True
            payload["output"] = "File edited successfully."

        except Exception as e:
            payload["success"] = False
            payload["output"] = f"Error editing file: {str(e)}"

    return payload
