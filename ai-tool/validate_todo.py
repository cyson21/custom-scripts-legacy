#!/usr/bin/env python3
"""todo.json 하드 검증 스크립트.

사용법:
    python validate_todo.py [--todo todo.json] [--schema todo.schema.json]

종료 코드:
    0  검증 통과
    1  검증 실패 (스키마 위반 또는 비즈니스 규칙 위반)
    2  파일 없음 / 파싱 오류
    3  jsonschema 패키지 미설치
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# 의존성 확인
# ---------------------------------------------------------------------------

try:
    import jsonschema
    from jsonschema import Draft7Validator, validate
except ImportError:
    print(
        "[ERROR] jsonschema 패키지가 설치되지 않았습니다.\n"
        "  설치 명령: pip install jsonschema",
        file=sys.stderr,
    )
    sys.exit(3)


# ---------------------------------------------------------------------------
# 비즈니스 규칙 검증 (스키마로 표현하기 어려운 제약)
# ---------------------------------------------------------------------------

def _check_business_rules(data: dict) -> list[str]:
    """스키마 외 비즈니스 규칙 위반 항목 반환."""
    errors: list[str] = []
    allowed_agents: list[str] = data["global_state"].get("allowed_agents", [])
    tasks: list[dict] = data.get("tasks", [])
    task_ids: set[str] = {t["id"] for t in tasks}

    for task in tasks:
        tid = task["id"]

        # assigned_to / completed_by 는 allowed_agents 내 값이어야 함
        for field in ("assigned_to", "completed_by"):
            value = task.get(field)
            if value is not None and value not in allowed_agents:
                errors.append(
                    f"[{tid}] {field}='{value}' 가 allowed_agents {allowed_agents} 에 없습니다."
                )

        # depends_on 이 존재하면 실제 태스크 ID를 가리켜야 함
        dep = task.get("depends_on")
        if dep is not None and dep not in task_ids:
            errors.append(
                f"[{tid}] depends_on='{dep}' 가 tasks 목록에 존재하지 않습니다."
            )

        # 자기 자신을 의존할 수 없음
        if dep == tid:
            errors.append(f"[{tid}] depends_on 이 자기 자신을 참조합니다.")

        # completed_by 는 status 가 completed/failed 일 때만 의미 있음
        completed_by = task.get("completed_by")
        status = task.get("status", "")
        if completed_by is not None and status not in ("completed", "failed"):
            errors.append(
                f"[{tid}] completed_by='{completed_by}' 가 설정됐으나 status='{status}' 입니다. "
                "completed/failed 상태가 아닌 태스크에 completed_by 를 설정하지 마세요."
            )

    # current_task_id 가 실제 태스크를 가리켜야 함
    current = data["global_state"].get("current_task_id")
    if current is not None and current not in task_ids:
        errors.append(
            f"[global_state] current_task_id='{current}' 가 tasks 목록에 없습니다."
        )

    return errors


# ---------------------------------------------------------------------------
# 순환 의존성 검사
# ---------------------------------------------------------------------------

def _check_cycles(data: dict) -> list[str]:
    """의존 그래프에 사이클이 있으면 오류 반환."""
    graph: dict[str, str | None] = {
        t["id"]: t.get("depends_on") for t in data.get("tasks", [])
    }
    errors: list[str] = []

    for start in graph:
        visited: set[str] = set()
        node: str | None = start
        while node is not None:
            if node in visited:
                errors.append(
                    f"[{start}] depends_on 체인에 순환이 감지됐습니다: {' → '.join(list(visited) + [node])}"
                )
                break
            visited.add(node)
            node = graph.get(node)

    return errors


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="todo.json 스키마 및 비즈니스 규칙 검증")
    parser.add_argument("--todo",   default="todo.json",        help="검증할 todo 파일 경로")
    parser.add_argument("--schema", default="todo.schema.json", help="JSON Schema 파일 경로")
    args = parser.parse_args()

    todo_path   = Path(args.todo)
    schema_path = Path(args.schema)

    # 파일 존재 확인
    for p in (todo_path, schema_path):
        if not p.exists():
            print(f"[ERROR] 파일을 찾을 수 없습니다: {p}", file=sys.stderr)
            sys.exit(2)

    # JSON 파싱
    try:
        todo_data   = json.loads(todo_path.read_text(encoding="utf-8"))
        schema_data = json.loads(schema_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[ERROR] JSON 파싱 실패: {exc}", file=sys.stderr)
        sys.exit(2)

    # 1단계: JSON Schema 검증
    validator = Draft7Validator(schema_data)
    schema_errors = sorted(validator.iter_errors(todo_data), key=lambda e: list(e.path))

    if schema_errors:
        print(f"[FAIL] JSON Schema 위반 {len(schema_errors)}건:\n")
        for err in schema_errors:
            path = " → ".join(str(p) for p in err.absolute_path) or "(root)"
            print(f"  • {path}: {err.message}")
        sys.exit(1)

    print("[OK] JSON Schema 검증 통과")

    # 2단계: 비즈니스 규칙 검증
    biz_errors = _check_business_rules(todo_data)
    if biz_errors:
        print(f"\n[FAIL] 비즈니스 규칙 위반 {len(biz_errors)}건:\n")
        for msg in biz_errors:
            print(f"  • {msg}")
        sys.exit(1)

    print("[OK] 비즈니스 규칙 검증 통과")

    # 3단계: 순환 의존성 검사
    cycle_errors = _check_cycles(todo_data)
    if cycle_errors:
        print(f"\n[FAIL] 순환 의존성 {len(cycle_errors)}건:\n")
        for msg in cycle_errors:
            print(f"  • {msg}")
        sys.exit(1)

    print("[OK] 순환 의존성 없음")
    print("\n검증 완료: todo.json 이상 없음.")


if __name__ == "__main__":
    main()
