import pytest
import asyncio
from pathlib import Path

from orchestrator.core.context import OrchestrationContext
from orchestrator.agents.io_provider import AgentIOProvider
from orchestrator.agents.sisyphus import SisyphusAgent, MaxRetriesExceededError


class MockAgentProvider(AgentIOProvider):
    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0

    async def ask(
        self, prompt: str, target_path: Path, title: str, **kwargs
    ) -> str:
        res = self.responses[self.call_count]
        self.call_count += 1
        return res

    async def review(
        self, user_prompt: str, peer_answer: str, prompt: str,
        target_path: Path, title: str
    ) -> str:
        return ""


def test_sisyphus_success_first_try(tmp_path):
    async def run_test():
        context = OrchestrationContext(artifact_dir=tmp_path)
        provider = MockAgentProvider(["def sum(a, b): return a + b"])

        loop = SisyphusAgent(max_retries=3)

        async def verify_fn(result: str):
            if "return a + b" in result:
                return True, ""
            return False, "Missing return statement."

        final_result = await loop.run(
            context, provider, "Write a sum function.", verify_fn)

        assert final_result == "def sum(a, b): return a + b"
        assert provider.call_count == 1

    asyncio.run(run_test())


def test_sisyphus_success_after_retries(tmp_path):
    async def run_test():
        context = OrchestrationContext(artifact_dir=tmp_path)
        provider = MockAgentProvider([
            "def sum(a, b): pass",  # 1st attempt
            "def sum(a, b): return a - b",  # 2nd attempt
            "def sum(a, b): return a + b"  # 3rd attempt
        ])

        loop = SisyphusAgent(max_retries=3)

        async def verify_fn(result: str):
            if "return a + b" in result:
                return True, ""
            return False, "Incorrect implementation."

        final_result = await loop.run(
            context, provider, "Write a sum function.", verify_fn)

        assert final_result == "def sum(a, b): return a + b"
        assert provider.call_count == 3

    asyncio.run(run_test())


def test_sisyphus_max_retries_exceeded(tmp_path):
    async def run_test():
        context = OrchestrationContext(artifact_dir=tmp_path)
        provider = MockAgentProvider([
            "def sum(a, b): pass",
            "def sum(a, b): pass",
            "def sum(a, b): pass",
        ])

        loop = SisyphusAgent(max_retries=3)

        async def verify_fn(result: str):
            return False, "Always fails."

        with pytest.raises(MaxRetriesExceededError) as exc:
            await loop.run(
                context, provider, "Write a sum function.", verify_fn)

        assert "Always fails" in str(exc.value)
        assert provider.call_count == 3

    asyncio.run(run_test())


if __name__ == "__main__":
    pytest.main([__file__])
