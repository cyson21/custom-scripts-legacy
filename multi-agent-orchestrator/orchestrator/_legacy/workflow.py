from __future__ import annotations

# TODO(LEGACY): 이 파일은 2-에이전트(Gemini+Codex) 교차 리뷰 시대의 레거시 워크플로우입니다.
# 현재 실행 경로는 orchestrator/swarm.py → run_swarm_logic() 으로 완전히 대체되었습니다.
# OrchestrationContext의 turns / consensus / max_rounds 필드도 이 파일만 사용합니다.
# 정리 전 확인 사항:
#   1. 외부에서 run_workflow()를 호출하는 진입점이 없는지 재확인
#   2. 확인 후 이 파일을 _legacy/ 디렉토리로 이동하거나 삭제
# 담당자 승인 후 처리 바람.

import asyncio
import time
from orchestrator.core.console import Spinner
from orchestrator.core.context import OrchestrationContext
from orchestrator.agents.io_provider import AgentIOProvider
from orchestrator.core.prompts import REVIEW_PROMPT_TEMPLATE, ROUND1_PROMPT_TEMPLATE
from orchestrator.core.reporting import build_final_report
from orchestrator.core.storage import write_consensus, write_text
from orchestrator.core.models import ConsensusResult, TurnResult

MAX_REVIEW_CHARS = 4000

class Spinner:
    def __init__(self, message="진행 중..."):
        self.message = message
        self.is_running = False
        self.task = None

    async def _spin(self):
        spinner_chars = itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])
        try:
            while self.is_running:
                sys.stdout.write(f"\r\033[96m[{next(spinner_chars)}]\033[0m {self.message} ")
                sys.stdout.flush()
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    def start(self):
        self.is_running = True
        self.task = asyncio.create_task(self._spin())

    async def stop(self):
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        sys.stdout.write(f"\r\033[92m[✔]\033[0m {self.message} 완료!       \n")
        sys.stdout.flush()


def summarize_for_review(text: str, limit: int = MAX_REVIEW_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[truncated]"


async def run_workflow(
    context: OrchestrationContext,
    gemini_io: AgentIOProvider,
    codex_io: AgentIOProvider,
) -> OrchestrationContext:
    context.round1_prompt = ROUND1_PROMPT_TEMPLATE.format(user_prompt=context.user_prompt)

    # Trigger initial before hook
    gemini_payload = await context.hooks.emit("tool.execute.before", {"agent": "gemini", "action": "ask", "prompt": context.round1_prompt})
    codex_payload = await context.hooks.emit("tool.execute.before", {"agent": "codex", "action": "ask", "prompt": context.round1_prompt})

    # 1. 병렬 1차 답변 수집 (Async)
    spinner = Spinner("라운드 1: Gemini & Codex 1차 답변 생성 중 (병렬)")
    spinner.start()
    
    task_g = gemini_io.ask(
        prompt=gemini_payload["prompt"],
        target_path=context.artifact_dir / "gemini_round1.txt",
        title="Gemini 1차 답변"
    )
    task_c = codex_io.ask(
        prompt=codex_payload["prompt"],
        target_path=context.artifact_dir / "codex_round1.txt",
        title="Codex 1차 답변"
    )
    
    gemini_ans, codex_ans = await asyncio.gather(task_g, task_c)
    await spinner.stop()

    # Trigger after hooks
    gemini_res = await context.hooks.emit("tool.execute.after", {"agent": "gemini", "action": "ask", "answer": gemini_ans})
    codex_res = await context.hooks.emit("tool.execute.after", {"agent": "codex", "action": "ask", "answer": codex_ans})
    
    gemini_ans = gemini_res.get("answer", gemini_ans)
    codex_ans = codex_res.get("answer", codex_ans)
    
    context.turns.append(TurnResult(round_num=1, gemini_answer=gemini_ans, codex_answer=codex_ans))
    
    current_gemini = gemini_ans
    current_codex = codex_ans

    # 2. 멀티 턴 교차 리뷰 (Dynamic Rounds)
    for round_num in range(2, context.max_rounds + 1):
        spinner = Spinner(f"라운드 {round_num}: 상대방 의견 상호 리뷰 중 (병렬)")
        spinner.start()
        
        gemini_summary = summarize_for_review(current_gemini)
        codex_summary = summarize_for_review(current_codex)

        gemini_review_prompt = REVIEW_PROMPT_TEMPLATE.format(
            user_prompt=context.user_prompt,
            peer_answer=codex_summary,
        )
        codex_review_prompt = REVIEW_PROMPT_TEMPLATE.format(
            user_prompt=context.user_prompt,
            peer_answer=gemini_summary,
        )

        task_g_rev = gemini_io.review(
            user_prompt=context.user_prompt,
            peer_answer=codex_summary,
            prompt=gemini_review_prompt,
            target_path=context.artifact_dir / f"gemini_review_r{round_num}.txt",
            title=f"Gemini 라운드 {round_num} 리뷰"
        )
        task_c_rev = codex_io.review(
            user_prompt=context.user_prompt,
            peer_answer=gemini_summary,
            prompt=codex_review_prompt,
            target_path=context.artifact_dir / f"codex_review_r{round_num}.txt",
            title=f"Codex 라운드 {round_num} 리뷰"
        )

        current_gemini, current_codex = await asyncio.gather(task_g_rev, task_c_rev)
        
        context.turns.append(TurnResult(
            round_num=round_num, 
            gemini_review=current_gemini, 
            codex_review=current_codex
        ))
        await spinner.stop()

    # 최종 라운드 결과 저장 (호환성 유지)
    context.gemini_round1 = context.turns[0].gemini_answer
    context.codex_round1 = context.turns[0].codex_answer
    context.gemini_review = current_gemini
    context.codex_review = current_codex

    # 3. LLM-as-a-Judge 기반 스마트 합의 도출
    spinner = Spinner("스마트 합의 도출 중 (LLM-as-a-Judge by Gemini)")
    spinner.start()
    
    judge_prompt = f"""당신은 공정하고 통찰력 있는 시니어 아키텍트이자 기술 재판관입니다. 
아래 사용자의 질문과 두 AI 에이전트(Gemini, Codex)의 최종 토론 리뷰를 바탕으로, 두 의견을 종합한 '가장 완벽하고 균형 잡힌 최종 권고안'을 작성해 주세요. 
단, 두 에이전트의 의견 차이가 심할 경우, 어떤 상황에서 어떤 선택이 더 유리한지 조건을 나누어 설명하세요.

[사용자 질문]
{context.user_prompt}

[Gemini 최종 의견]
{context.gemini_review}

[Codex 최종 의견]
{context.codex_review}
"""
    # Gemini를 재판관으로 활용
    judge_result = await gemini_io.ask(
        prompt=judge_prompt,
        target_path=context.artifact_dir / "smart_consensus.txt",
        title="스마트 합의 판정"
    )
    await spinner.stop()

    context.consensus = ConsensusResult(
        status="smart_consensus",
        recommended_final=judge_result
    )
    write_consensus(context.artifact_dir / "consensus.json", context.consensus)

    final_report = build_final_report(
        user_prompt=context.user_prompt,
        gemini_result=context.gemini_round1,
        codex_result=context.codex_round1,
        gemini_review=context.gemini_review,
        codex_review=context.codex_review,
        consensus_status=context.consensus.status,
        shared_points=[],
        open_issues=[],
        recommended_final=context.consensus.recommended_final,
    )
    write_text(context.artifact_dir / "final_report.md", final_report)
    return context
