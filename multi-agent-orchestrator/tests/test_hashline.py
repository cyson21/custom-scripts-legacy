import pytest
from orchestrator.tools.hashline import (
    generate_hashline,
    generate_line_hash,
    validate_hashline,
    HashlineMismatchError,
    hook_inject_hashlines,
    hook_validate_hashlines
)
from orchestrator.core.hooks import HookManager


def test_generate_hashline():
    line = "def test():"
    h = generate_line_hash(line)
    result = generate_hashline(1, line)
    assert result == f"1#{h}| def test():"


def test_validate_hashline_success():
    line = "def main():"
    h = generate_line_hash(line)
    submitted_id = f"1#{h}"
    assert validate_hashline(submitted_id, line) is True


def test_validate_hashline_failure():
    line = "def main():"
    submitted_id = "1#abcd"  # Wrong hash
    with pytest.raises(HashlineMismatchError):
        validate_hashline(submitted_id, line)


def test_hook_inject_hashlines():
    manager = HookManager()
    manager.register("tool.execute.after", hook_inject_hashlines)

    payload = {
        "tool_name": "read_file",
        "output": "line 1\nline 2"
    }

    # Run hook synchronously
    result = manager._hooks["tool.execute.after"][0](payload)

    output = result["output"]
    assert "1#" in output
    assert "| line 1" in output
    assert "2#" in output
    assert "| line 2" in output


def test_hook_validate_hashlines_success():
    manager = HookManager()
    manager.register("tool.execute.before", hook_validate_hashlines)

    content = "line 1\nline 2"
    h1 = generate_line_hash("line 1")

    payload = {
        "tool_name": "edit_file",
        "current_file_content": content,
        "edits": [
            {"hashline_id": f"1#{h1}", "new_content": "line 1 modified"}
        ]
    }

    # Should not raise
    manager._hooks["tool.execute.before"][0](payload)


def test_hook_validate_hashlines_failure():
    manager = HookManager()
    manager.register("tool.execute.before", hook_validate_hashlines)

    content = "line 1\nline 2"

    payload = {
        "tool_name": "edit_file",
        "current_file_content": content,
        "edits": [
            {"hashline_id": "1#abcd",
             "new_content": "line 1 modified"}  # Wrong hash
        ]
    }

    with pytest.raises(HashlineMismatchError):
        manager._hooks["tool.execute.before"][0](payload)


if __name__ == "__main__":
    pytest.main([__file__])
