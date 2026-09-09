from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Add current directory to path
sys.path.append(os.getcwd())

from orchestrator.agents.adapters.gemini_adapter import GeminiAdapter
from orchestrator.agents.adapters.codex_adapter import CodexAdapter
from orchestrator.core.context import OrchestrationContext
from orchestrator.agents.io_provider import AutoAgentAdapter
from orchestrator.core.storage import create_artifact_dir, write_text
from orchestrator.agents.swarm import run_workflow

def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

async def amain() -> None:
    base_dir = Path(__file__).resolve().parent
    load_env_file(base_dir / '.env')

    parser = argparse.ArgumentParser(description="Multi-Agent Orchestrator v5 (Auto Mode, Mac/Win/WSL Support)")
    parser.add_argument("-q", "--query", type=str, help="토론 주제 또는 질문 (직접 입력)")
    parser.add_argument("-f", "--file", type=str, help="질문에 컨텍스트로 첨부할 파일 경로")
    parser.add_argument("--rounds", type=int, default=2, help="최대 교차 리뷰 라운드 수 (기본: 2)")
    args = parser.parse_args()

    print("\n\033[95m=== Multi-Agent Orchestrator ===\033[0m")
    print("\033[90m(Auto environment detection: Mac/Win/WSL supported)\033[0m\n")
    
    user_prompt = args.query
    if not user_prompt:
        try:
            user_prompt = input("\033[93m질문을 입력하세요:\033[0m ").strip()
        except EOFError:
            return
            
        if not user_prompt:
            print("질문이 입력되지 않아 종료합니다.")
            return

    if args.file:
        file_path = Path(args.file)
        if file_path.exists():
            content = file_path.read_text(encoding="utf-8")
            user_prompt = f"{user_prompt}\n\n[첨부 파일: {file_path.name}]\n```\n{content}\n```"
        else:
            print(f"\033[91m[오류] 첨부 파일을 찾을 수 없습니다: {args.file}\033[0m")
            return

    artifact_dir = create_artifact_dir(base_dir)
    context = OrchestrationContext(
        artifact_dir=artifact_dir,
        user_prompt=user_prompt,
        max_rounds=args.rounds
    )
    write_text(artifact_dir / 'prompt.txt', context.user_prompt)

    # Gemini & Codex: Pure Auto Mode
    gemini_io = AutoAgentAdapter(GeminiAdapter())
    codex_io = AutoAgentAdapter(CodexAdapter())

    print("\n\033[94m[Workflow Start]\033[0m")
    context = await run_workflow(context, gemini_io=gemini_io, codex_io=codex_io)

    print("\n\033[94m[Workflow Completed]\033[0m")
    print(f"Artifacts saved to: \033[92m{context.artifact_dir}\033[0m")
    print(f"최종 리포트 확인: \033[92m{context.artifact_dir / 'final_report.md'}\033[0m\n")


def main() -> None:
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        print("\n\n\033[91m[시스템] 사용자에 의해 강제 종료되었습니다.\033[0m")

if __name__ == '__main__':
    main()
