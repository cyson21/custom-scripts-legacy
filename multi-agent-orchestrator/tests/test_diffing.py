import pytest

from orchestrator.core.context import OrchestrationContext
from orchestrator.core.hooks import HookManager
from orchestrator.tools.diffing import generate_diff, hook_generate_diff


def test_generate_diff():
    old_content = "def test():\n    pass\n"
    new_content = "def test():\n    return True\n"
    file_path = "src/app.py"

    diff = generate_diff(old_content, new_content, file_path)

    assert "--- a/src/app.py" in diff
    assert "+++ b/src/app.py" in diff
    assert "-    pass" in diff
    assert "+    return True" in diff


def test_hook_generate_diff_edit_file(tmp_path):
    context = OrchestrationContext(artifact_dir=tmp_path)
    manager = HookManager()
    manager.register("tool.execute.after", hook_generate_diff)

    old_content = "def sum(a, b):\n    pass\n"
    new_content = "def sum(a, b):\n    return a + b\n"

    payload = {
        "tool_name": "edit_file",
        "file_path": "math.py",
        "old_content": old_content,
        "new_content": new_content,
        "context": context
    }

    result = manager._hooks["tool.execute.after"][0](payload)

    assert "diff" in result
    assert "+    return a + b" in result["diff"]

    assert len(context.diff_memory) == 1
    assert context.diff_memory[0]["tool_name"] == "edit_file"
    assert context.diff_memory[0]["file_path"] == "math.py"
    assert context.diff_memory[0]["diff"] == result["diff"]


def test_hook_generate_diff_no_change(tmp_path):
    context = OrchestrationContext(artifact_dir=tmp_path)
    manager = HookManager()
    manager.register("tool.execute.after", hook_generate_diff)

    content = "def same():\n    pass\n"

    payload = {
        "tool_name": "edit_file",
        "file_path": "math.py",
        "old_content": content,
        "new_content": content,
        "context": context
    }

    result = manager._hooks["tool.execute.after"][0](payload)

    assert "diff" not in result
    assert len(context.diff_memory) == 0


def test_hook_generate_diff_ignored_tool(tmp_path):
    context = OrchestrationContext(artifact_dir=tmp_path)
    manager = HookManager()
    manager.register("tool.execute.after", hook_generate_diff)

    payload = {
        "tool_name": "read_file",
        "file_path": "math.py",
        "old_content": "old",
        "new_content": "new",
        "context": context
    }

    result = manager._hooks["tool.execute.after"][0](payload)

    assert "diff" not in result
    assert len(context.diff_memory) == 0


if __name__ == "__main__":
    pytest.main([__file__])
