import asyncio
import difflib
import re
import time
from pathlib import Path
from typing import Dict, List, Tuple
from orchestrator.core.models import SynthesisProposal
from orchestrator.core.prompts import (
    SWARM_SYNTHESIS_PROMPT_TEMPLATE,
    CONFLICT_RESOLUTION_PROMPT_TEMPLATE,
)
from orchestrator.agents.adapters.factory import AgentFactory

from orchestrator.core.utils import extract_json


class SynthesisEngine:
    """
    Intelligent Merge Engine that analyzes multiple Diffs and synthesizes a
    final solution.
    It uses an LLM to resolve complex conflicts and ensure architectural
    consistency.
    """

    def __init__(self, controller=None, artifact_dir=None,
                 synthesis_agent: str = "architect"):
        self.controller = controller
        self.artifact_dir = artifact_dir
        self.synthesis_agent_name = synthesis_agent

    async def synthesize(
        self,
        user_prompt: str,
        agent_diffs: Dict[str, str],
        is_doc_update: bool = False
    ) -> SynthesisProposal:
        """
        Main entry point for synthesis.
        """
        if not agent_diffs:
            return SynthesisProposal(
                proposal_id="empty", agents_involved=[], synthesized_diff=""
            )

        if len(agent_diffs) == 1:
            agent_name, diff = list(agent_diffs.items())[0]
            return SynthesisProposal(
                proposal_id=f"single_{agent_name}",
                agents_involved=[agent_name],
                synthesized_diff=diff,
                rationale="Only one proposal available.",
            )

        proposals_text = ""
        for agent_name, diff in agent_diffs.items():
            proposals_text += f"--- AGENT: {agent_name} ---\n{diff}\n\n"

        if self.controller:
            self.controller.set_global_status(
                "Synthesizing multiple solutions...")

        if is_doc_update:
            from orchestrator.core.prompts import (
                SWARM_DOC_SYNTHESIS_PROMPT_TEMPLATE
            )
            prompt = SWARM_DOC_SYNTHESIS_PROMPT_TEMPLATE.format(
                user_prompt=user_prompt, proposals=proposals_text
            )
        else:
            prompt = SWARM_SYNTHESIS_PROMPT_TEMPLATE.format(
                user_prompt=user_prompt, proposals=proposals_text
            )

        # Why: Lazy creation ensures that mock side_effects in tests are 
        # consumed in the expected order (Blueprint -> Workers -> Synthesis -> Judge).
        agent_io = AgentFactory.create(
            self.synthesis_agent_name, state_manager=self.controller
        )
        _ts = int(time.time())
        if self.artifact_dir:
            _synthesis_path = self.artifact_dir / f"synthesis_raw_{_ts}.txt"
        else:
            _synthesis_path = Path(f"/tmp/synthesis_raw_{_ts}.txt")

        raw_synthesis = await agent_io.ask(
            prompt, _synthesis_path, "Synthesis"
        )

        data = extract_json(raw_synthesis)
        if data:
            rationale = data.get("rationale", "")
            conflicts = data.get("conflicts", [])
            final_diff = data.get("synthesized_diff", "")
        else:
            rationale, conflicts, final_diff = (
                self._parse_synthesis_response_fallback(
                    raw_synthesis
                )
            )

        if not final_diff.strip():
            return SynthesisProposal(
                proposal_id="empty_synthesis",
                agents_involved=list(agent_diffs.keys()),
                synthesized_diff="",
                rationale="LLM failed to produce a valid diff.",
            )

        return SynthesisProposal(
            proposal_id=f"synth_{list(agent_diffs.keys())[0]}",
            agents_involved=list(agent_diffs.keys()),
            synthesized_diff=final_diff,
            conflicts=conflicts,
            rationale=rationale,
        )

    def _parse_synthesis_response_fallback(
        self, text: str
    ) -> Tuple[str, List[str], str]:
        """Legacy parser for the LLM output if JSON fails."""
        rationale = ""
        conflicts = []
        final_diff = ""

        rationale_match = re.search(
            r"### 1\. 통합 논리 \(Rationale\)\n(.*?)(?=###|$)", text, re.DOTALL
        )
        if rationale_match:
            rationale = rationale_match.group(1).strip()

        conflicts_match = re.search(
            r"### 2\. 충돌 해결 내역 \(Conflict Resolution\)\n(.*?)(?=###|$)",
            text,
            re.DOTALL,
        )
        if conflicts_match:
            conflicts = [
                c.strip()
                for c in conflicts_match.group(1).strip().split("\n")
                if c.strip()
            ]

        diff_match = re.search(r"```diff\n(.*?)\n```", text, re.DOTALL)
        if diff_match:
            final_diff = diff_match.group(1).strip()
        else:
            diff_match = re.search(r"--- a/.*", text, re.DOTALL)
            if diff_match:
                final_diff = diff_match.group(0).strip()

        return rationale, conflicts, final_diff

    async def dry_run_conflict_resolver(
        self, diff_content: str, work_dir: Path
    ) -> Tuple[bool, str, str]:
        """
        Performs a dry-run of applying a diff to check for conflicts
        (`git apply --check`).
        If conflicts exist, it uses an LLM to generate a resolved version
        of the code, computes a new diff, and returns it.

        Returns:
            A tuple (can_proceed, message, diff).
            - If successful, (True, "Dry-run successful...", original_diff).
            - If conflict is resolved, (True, "Conflict resolved...",
              new_diff).
            - If conflict is not resolved, (False, "Conflict detected...",
              original_diff).
        """
        if not diff_content.strip():
            return True, "Dry-run successful. Diff is empty.", diff_content

        temp_patch_path = work_dir / f"temp_patch_{int(time.time())}.diff"
        try:
            temp_patch_path.write_text(diff_content)

            from orchestrator.tools.sandbox import SandboxManager
            sandbox_manager = SandboxManager(work_dir)
            cmd = [
                "git",
                "apply",
                "--check",
                "--ignore-space-change",
                "--ignore-whitespace",
                str(temp_patch_path)
            ]
            if not sandbox_manager.validate_command(cmd, work_dir):
                raise PermissionError(f"Command execution denied: {cmd}")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
            )
            try:
                _, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=30.0)
            except asyncio.TimeoutError:
                process.kill()
                return (False, "Dry-run timed out after 30 seconds.",
                        diff_content)

            if process.returncode == 0:
                return (True,
                        "Dry-run successful. No conflicts detected.",
                        diff_content)

            if self.controller:
                self.controller.set_global_status(
                    "Conflict detected. Attempting to resolve with LLM...")
            error_output = stderr.decode()

            all_conflicts = re.findall(
                r"error: patch failed: (.*?):\d+", error_output)
            if len(all_conflicts) > 1:
                return False, (
                    f"Multi-file conflict detected "
                    f"({len(all_conflicts)} files: "
                    f"{', '.join(all_conflicts)}). "
                    "Automated resolution not supported."
                ), diff_content

            file_path_match = re.search(
                r"error: patch failed: (.*?):\d+", error_output
            )
            if file_path_match:
                relative_path = file_path_match.group(1)
                conflicted_file_path = work_dir / relative_path
                try:
                    original_content = conflicted_file_path.read_text()
                except FileNotFoundError:
                    original_content = (
                        f"File not found at: {conflicted_file_path}")
            else:
                original_content = (
                    "Could not automatically determine the "
                    "conflicted file from git error."
                )
                relative_path = "N/A"

            prompt = CONFLICT_RESOLUTION_PROMPT_TEMPLATE.format(
                file_path=relative_path,
                original_code=original_content,
                proposed_diff=diff_content,
                error_message=error_output,
            )

            agent_io = self._agent_io
            resolution_suggestion_path = (
                work_dir / f"resolution_suggestion_{int(time.time())}.txt"
            )
            llm_suggestion = await agent_io.ask(
                prompt, resolution_suggestion_path, "Conflict Resolution"
            )

            if not llm_suggestion or \
                    llm_suggestion.strip() == original_content.strip():
                failure_message = (
                    f"Dry-run failed: Conflict in `{relative_path}`. "
                    "LLM failed to provide a valid resolution."
                )
                return False, failure_message, diff_content

            new_diff = "".join(difflib.unified_diff(
                original_content.splitlines(keepends=True),
                llm_suggestion.splitlines(keepends=True),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
            ))

            if not new_diff:
                failure_message = (
                    f"Dry-run failed: Conflict in `{relative_path}`. "
                    "LLM resolution resulted in no changes."
                )
                return False, failure_message, diff_content

            success_message = (
                f"Dry-run conflict in `{relative_path}` "
                "automatically resolved by LLM."
            )
            return True, success_message, new_diff

        finally:
            if temp_patch_path.exists():
                temp_patch_path.unlink()

    async def apply_final(self, diff_content: str):
        """
        Function: Applies the final synthesized diff to the main workspace.
        Why: This is the 'Apply' phase of the mission lifecycle. 
        It applies the patches approved by the judge.
        """
        if not diff_content.strip():
            return

        temp_patch_path = Path("final_apply.diff")
        try:
            temp_patch_path.write_text(diff_content)
            
            # Apply the patch using git
            process = await asyncio.create_subprocess_exec(
                "git", "apply", "--ignore-space-change", "--ignore-whitespace", str(temp_patch_path),
                cwd=self.controller.workspace_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                self.controller.add_log("system", f"Final apply failed: {stderr.decode()}")
                raise Exception(f"Failed to apply final diff: {stderr.decode()}")
            
            self.controller.add_log("system", "Final synthesized diff applied successfully.")
        finally:
            if temp_patch_path.exists():
                temp_patch_path.unlink()
