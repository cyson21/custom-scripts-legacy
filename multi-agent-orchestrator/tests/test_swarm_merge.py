import pytest
import os
import asyncio
from pathlib import Path

from orchestrator.tools.sandbox import SandboxManager
from orchestrator.tools.merger import DiffCollector
from orchestrator.core.prompts import SWARM_JUDGE_PROMPT_TEMPLATE
from orchestrator.agents.io_provider import AgentIOProvider


class MockJudgeProvider(AgentIOProvider):
    def __init__(self, winner: str):
        self.winner = winner

    async def ask(
        self, prompt: str, target_path: Path, title: str, **kwargs
    ) -> str:
        # Mock the judge's response
        return f"WINNER: {self.winner}\n\n### 3. 최종 판정 (Final Status)\nAGREE\n"

    async def review(
        self, user_prompt: str, peer_answer: str, prompt: str,
        target_path: Path, title: str
    ) -> str:
        return ""


@pytest.fixture
def repo_dir(tmp_path):
    repo = tmp_path / "test_repo"
    repo.mkdir()
    os.system(f"""
        cd {repo} && \\
        git init && \\
        git config user.email test@test.com && \\
        git config user.name Test && \\
        echo 'def calculate():\\n    return 0' > logic.py && \\
        git add . && \\
        git commit -m 'init'
    """)
    return repo


def test_swarm_merge_e2e(repo_dir):
    async def run_test():
        manager = SandboxManager(repo_dir)

        # 1. Create sandboxes
        sb_a = manager.create_sandbox("agent_a", "run_1")
        sb_b = manager.create_sandbox("agent_b", "run_1")

        # 2. Agents modify files in their sandboxes
        # Agent A changes to return 1
        (sb_a / "logic.py").write_text("def calculate():\n    return 1\n")
        # Agent B changes to return 2
        (sb_b / "logic.py").write_text("def calculate():\n    return 2\n")

        # 3. Collect diffs
        diff_a = DiffCollector.extract_diff(sb_a)
        diff_b = DiffCollector.extract_diff(sb_b)

        assert "+    return 1" in diff_a
        assert "+    return 2" in diff_b

        # 4. Form proposals for judge
        proposals = f"--- Agent A ---\n{diff_a}\n\n--- Agent B ---\n{diff_b}\n"
        prompt = SWARM_JUDGE_PROMPT_TEMPLATE.format(
            user_prompt="Make it return 2.",
            proposals=proposals,
            audit_report="No audit report."
        )

        # 5. Judge selects winner
        judge = MockJudgeProvider(winner="agent_b")
        judge_res = await judge.ask(prompt, repo_dir / "judge.txt", "Judge")

        assert "WINNER: agent_b" in judge_res

        # Extract winner from judge response
        winner_str = ""
        for line in judge_res.splitlines():
            if line.startswith("WINNER:"):
                winner_str = line.split("WINNER:")[1].strip()
                break

        assert winner_str == "agent_b"

        # 6. Apply winning diff
        if winner_str == "agent_a":
            winning_diff = diff_a
        elif winner_str == "agent_b":
            winning_diff = diff_b
        else:
            winning_diff = ""

        success, msg = DiffCollector.apply_diff(winning_diff, repo_dir)
        assert success is True

        # Check the base repo file
        base_file = repo_dir / "logic.py"
        content = base_file.read_text()
        assert "return 2" in content

        # 7. Cleanup
        manager.cleanup_all()
        assert not sb_a.exists()
        assert not sb_b.exists()

    asyncio.run(run_test())


if __name__ == "__main__":
    pytest.main([__file__])
