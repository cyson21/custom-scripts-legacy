#!/usr/bin/env python3
"""todo.json을 검증하고 todo.validation.json을 갱신한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import jsonschema
except ImportError:
    print(
        "[ERROR] jsonschema 패키지가 설치되지 않았습니다.\n"
        "  설치 명령: pip install jsonschema",
        file=sys.stderr,
    )
    sys.exit(3)


VALID_STATUS = {"pending", "in_progress", "completed", "failed", "blocked"}


def now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def iter_depends(depends_on):
    if depends_on is None:
        return []
    if isinstance(depends_on, str):
        return [depends_on]
    if isinstance(depends_on, list):
        return [item for item in depends_on if isinstance(item, str)]
    return []


def validate_todo_data(data: dict, schema: dict) -> list[str]:
    errors: list[str] = []

    validator = jsonschema.Draft7Validator(schema)
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        path = " → ".join(map(str, err.path)) or "<root>"
        errors.append(f"{path}: {err.message}")

    tasks = data.get("tasks", [])
    ids = [task.get("id") for task in tasks if isinstance(task, dict)]
    task_id_set = set(ids)
    dup_ids = sorted({task_id for task_id in ids if ids.count(task_id) > 1})
    if dup_ids:
        errors.append(f"중복 task id: {dup_ids}")

    global_state = data.get("global_state", {})
    allowed_agents = set(global_state.get("allowed_agents", []))
    current_task_id = global_state.get("current_task_id")
    if current_task_id is not None and current_task_id not in task_id_set:
        errors.append(f"global_state.current_task_id '{current_task_id}' 가 tasks에 없음")

    for task in tasks:
        if not isinstance(task, dict):
            continue

        task_id = task.get("id")
        status = task.get("status")
        if status not in VALID_STATUS:
            errors.append(f"{task_id}.status='{status}' 는 허용되지 않는 상태")

        for key in ("assigned_to", "completed_by"):
            value = task.get(key)
            if value is not None and allowed_agents and value not in allowed_agents:
                errors.append(f"{task_id}.{key}='{value}' 는 allowed_agents에 없음")

        for dep in iter_depends(task.get("depends_on")):
            if dep not in task_id_set:
                errors.append(f"{task_id}.depends_on='{dep}' 가 tasks에 없음")
            if dep == task_id:
                errors.append(f"{task_id}.depends_on 이 자기 자신을 참조함")

        if task.get("completed_by") is not None and status not in {"completed", "failed"}:
            errors.append(
                f"{task_id}.completed_by 는 status가 completed/failed일 때만 설정 가능"
            )

    visited: set[str] = set()
    stack: set[str] = set()
    adjacency = {
        task.get("id"): iter_depends(task.get("depends_on"))
        for task in tasks
        if isinstance(task, dict) and task.get("id")
    }

    def walk(node: str) -> None:
        if node in stack:
            errors.append(f"순환 의존성 감지: {node}")
            return
        if node in visited:
            return
        visited.add(node)
        stack.add(node)
        for dep in adjacency.get(node, []):
            if dep in adjacency:
                walk(dep)
        stack.remove(node)

    for node in adjacency:
        walk(node)

    return errors


def process(todo_path: Path, schema_path: Path, validation_path: Path) -> int:
    for path in (todo_path, schema_path):
        if not path.exists():
            print(f"[ERROR] 파일을 찾을 수 없습니다: {path}", file=sys.stderr)
            return 2

    try:
        todo_data = load_json(todo_path)
        schema_data = load_json(schema_path)
    except json.JSONDecodeError as exc:
        print(f"[ERROR] JSON 파싱 실패: {exc}", file=sys.stderr)
        return 2

    errors = validate_todo_data(todo_data, schema_data)
    result = {
        "version": "2.0",
        "schema_file": str(schema_path.resolve()),
        "schema_sha256": sha256_file(schema_path),
        "todo_file": str(todo_path.resolve()),
        "todo_sha256": sha256_file(todo_path),
        "validated_at": now_iso(),
        "valid": len(errors) == 0,
        "error_count": len(errors),
        "errors": errors[:200],
    }
    write_json(validation_path, result)

    if errors:
        print(f"[FAIL] todo.validation.json 갱신 완료, 오류 {len(errors)}건")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("[OK] todo.validation.json 갱신 완료")
    print(f"  todo: {todo_path.resolve()}")
    print(f"  validation: {validation_path.resolve()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="todo.json 검증 및 validation 산출물 갱신")
    parser.add_argument("--todo", default="todo.json", help="검증할 todo 파일 경로")
    parser.add_argument("--schema", default="todo.schema.json", help="JSON Schema 파일 경로")
    parser.add_argument(
        "--validation-output",
        default="todo.validation.json",
        help="검증 결과 출력 경로",
    )
    args = parser.parse_args(argv)
    return process(
        Path(args.todo),
        Path(args.schema),
        Path(args.validation_output),
    )


if __name__ == "__main__":
    raise SystemExit(main())
