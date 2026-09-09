import pytest
from orchestrator.core.reporting import generate_execution_trace_md


def test_generate_execution_trace_md_empty():
    md = generate_execution_trace_md([], [])
    assert "No execution traces recorded" in md
    assert "No files were modified" in md


def test_generate_execution_trace_md_populated():
    execution_trace = [
        {
            "attempt": 1,
            "action": '{"tool_name": "ast_grep"}',
            "observation": "Success",
            "hint": "",
            "success": True
        },
        {
            "attempt": 2,
            "action": '{"tool_name": "ast_grep", "mock": true}',
            "observation": "No results found for your query.",
            "hint": "💡 Hint - Your pattern ends with a colon",
            "success": False
        }
    ]

    diff_memory = [
        {
            "tool_name": "edit_file",
            "file_path": "test.py",
            "diff": "--- a/test.py\n+++ b/test.py\n-pass\n+return True"
        }
    ]

    md = generate_execution_trace_md(execution_trace, diff_memory)

    # Check attempts
    assert "### Attempt 1" in md
    assert "✅ Yes" in md
    assert "### Attempt 2" in md
    assert "❌ No" in md

    # Check hints
    assert "💡 Hint - Your pattern ends with a colon" in md

    # Check diffs
    assert "### 1. edit_file on `test.py`" in md
    assert "+return True" in md


if __name__ == "__main__":
    pytest.main([__file__])
