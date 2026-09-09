import pytest
from orchestrator.tools.ast_grep import ASTGrepTool, hook_ast_grep


def test_ast_grep_empty_result_hints():
    tool = ASTGrepTool()

    # Test colon hint
    hint = tool._get_empty_result_hint("def $FUNC():", "python")
    assert "ends with a colon" in hint

    # Test unbalanced parenthesis hint
    hint = tool._get_empty_result_hint("def $FUNC(", "python")
    assert "Unbalanced parenthesis" in hint

    # Test meta-variable without $$$ hint
    hint = tool._get_empty_result_hint("def $FUNC($A, $B)", "python")
    assert "use '$$$' instead of '$VAR'" in hint

    # Test generic hint
    hint = tool._get_empty_result_hint("some_pattern", "python")
    assert "broaden your search" in hint


def test_hook_ast_grep_mock():
    # We will test the hook with a mock payload to simulate an empty result.
    payload = {
        "tool_name": "ast_grep",
        "pattern": "def $A():",
        "mock": True
    }

    result = hook_ast_grep(payload)

    assert "success" in result
    assert result["success"] is False
    assert "output" in result
    # It should return the hint string for a pattern ending with colon
    assert "ends with a colon" in result["output"]


def test_ast_grep_not_installed(monkeypatch):
    # Force sg_path to None
    monkeypatch.setattr(
        "orchestrator.core.path_resolver.get_sg_cli_path",
        lambda: None)

    tool = ASTGrepTool()
    tool.sg_path = None  # also set locally just in case

    success, output = tool.execute("def test()")
    assert success is False
    assert "is not installed" in output


if __name__ == "__main__":
    pytest.main([__file__])
