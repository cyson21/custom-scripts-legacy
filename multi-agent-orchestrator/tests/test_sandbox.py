import pytest
import os

from orchestrator.tools.sandbox import SandboxManager, hook_route_to_sandbox
from orchestrator.core.context import OrchestrationContext


@pytest.fixture
def repo_dir(tmp_path):
    # Set up a dummy git repo
    repo = tmp_path / "test_repo"
    repo.mkdir()
    os.system(f"""
        cd {repo} && \\
        git init && \\
        git config user.email test@test.com && \\
        git config user.name Test && \\
        echo 'def sum(a, b): return a + b' > math.py && \\
        git add . && \\
        git commit -m 'init'
    """)
    return repo


def test_sandbox_creation_and_removal(repo_dir):
    manager = SandboxManager(repo_dir)
    sandbox_path = manager.create_sandbox("agent_a", "run_123")

    assert sandbox_path.exists()
    assert (sandbox_path / "math.py").exists()

    # Check it's tracked
    assert manager.get_sandbox_path("agent_a_run_123") == sandbox_path

    # Remove
    assert manager.remove_sandbox("agent_a_run_123") is True
    assert not sandbox_path.exists()


def test_sandbox_concurrent_modification(repo_dir):
    manager = SandboxManager(repo_dir)
    sb_a = manager.create_sandbox("agent_a", "run_1")
    sb_b = manager.create_sandbox("agent_b", "run_1")

    # Agent A modifies math.py
    file_a = sb_a / "math.py"
    file_a.write_text("def sum(a, b): return a + b\n# A modified this")

    # Agent B modifies math.py concurrently
    file_b = sb_b / "math.py"
    file_b.write_text("def sum(a, b): return a + b\n# B modified this")

    # Verify isolation
    assert "A modified this" in file_a.read_text()
    assert "B modified this" not in file_a.read_text()

    assert "B modified this" in file_b.read_text()
    assert "A modified this" not in file_b.read_text()

    manager.cleanup_all()


def test_hook_route_to_sandbox(repo_dir):
    manager = SandboxManager(repo_dir)
    sb = manager.create_sandbox("agent_a", "run_1")

    context = OrchestrationContext(artifact_dir=repo_dir / "artifacts")
    context.sandbox_manager = manager

    payload = {
        "tool_name": "read_file",
        "file_path": "math.py",
        "context": context,
        "sandbox_path": sb
    }

    result = hook_route_to_sandbox(payload)

    assert "file_path" in result
    assert result["original_file_path"] == "math.py"
    assert result["file_path"] == str((sb / "math.py").resolve())

    manager.cleanup_all()


if __name__ == "__main__":
    pytest.main([__file__])
