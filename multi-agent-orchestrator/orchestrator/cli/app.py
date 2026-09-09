import asyncio
import os
import sys
from typing import List

from prompt_toolkit import PromptSession
from prompt_toolkit.shortcuts import radiolist_dialog, checkboxlist_dialog, message_dialog, yes_no_dialog, button_dialog
from prompt_toolkit.styles import Style
from prompt_toolkit.completion import Completer, Completion, PathCompleter
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.table import Table
from rich.tree import Tree
from rich.layout import Layout

from orchestrator.core.state import OrchestratorState, AgentStatus
from orchestrator.core.models import DeploymentUnit, ExecutionMode
from orchestrator.agents.swarm import run_swarm_logic
from orchestrator.core.cli_registry import registry
from orchestrator.core.history import HistoryManager
from prompt_toolkit.shortcuts import radiolist_dialog, checkboxlist_dialog, message_dialog, yes_no_dialog, button_dialog
from orchestrator.cli.inline_ui import (
    inline_radio_dialog, inline_searchable_radio_dialog, render_swarm_timeline, render_progress_dashboard
)
from orchestrator.tools.diffing import render_side_by_side_diff

console = Console()

class MissionCompleter(Completer):
    def __init__(self):
        self.path_completer = PathCompleter(expanduser=True)

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if '@' in text:
            last_at_idx = text.rfind('@')
            path_prefix = text[last_at_idx + 1:]
            
            from prompt_toolkit.document import Document
            sub_doc = Document(path_prefix, cursor_position=len(path_prefix))
            for completion in self.path_completer.get_completions(sub_doc, complete_event):
                yield Completion(
                    completion.text,
                    start_position=completion.start_position,
                    display=completion.display,
                    display_meta=completion.display_meta,
                )

async def permission_check_hook(payload: dict) -> dict:
    """
    Hook to verify permission before an agent executes a tool or shell command.
    Automatically approves in headless or DRY_RUN mode to avoid blocking.
    """
    if os.environ.get("DRY_RUN") == "1":
        payload["approved"] = True
        return payload
        
    tool_name = payload.get("tool_name", payload.get("action", "unknown_action"))
    command = payload.get("command", str(payload))
    
    # In interactive mode, prompt the user.
    # Note: yes_no_dialog is async in prompt_toolkit.
    user_approved = await yes_no_dialog(
        title="⚠️ 권한 승인 필요",
        text=f"에이전트가 다음 명령/툴을 실행하려고 합니다. 승인하시겠습니까?\n\nTool: {tool_name}\nDetails: {command}",
        style=cli_style
    ).run_async()
    
    payload["approved"] = user_approved
    return payload

# Modern, less harsh dark theme for prompt_toolkit dialogs
cli_style = Style.from_dict({
    'dialog': 'bg:#2b2b2b #d4d4d4',
    'dialog.body': 'bg:#262626 #e4e4e4',
    'dialog.border': '#0087af',
    'dialog shadow': 'bg:#121212',
    'button': 'bg:#444444 #e4e4e4',
    'button.focused': 'bg:#0087af #ffffff bold',
    'radio-selected': 'fg:#00afff bold',
    'radio-checked': 'fg:#00afff bold',
    'title': 'bg:#0087af #ffffff bold',
})

async def consume_logs(state: OrchestratorState, log_list: List[str]):
    """Background task to consume logs and update a shared list for the Live Dashboard."""
    while not state.emergency_stop.is_set():
        try:
            # We use a short timeout so we can periodically check the stop event
            log_line = await asyncio.wait_for(state.message_queue.get(), timeout=0.1)
            log_list.append(log_line)
            # Keep only the last 10 logs for the dashboard
            if len(log_list) > 10:
                log_list.pop(0)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            break

async def setup_mission(state: OrchestratorState) -> tuple[str, List[DeploymentUnit], ExecutionMode]:
    """Prompts the user to set up a new mission."""
    
    # 0. Select Workspace
    from collections import Counter
    sessions = state.history_manager.list_sessions()
    ws_counts = Counter(s.workspace for s in sessions if s.workspace and s.workspace != "Unknown")
    recent_workspaces = [ws for ws, _ in ws_counts.most_common(5)]

    ws_options = [(ws, f"[자주 사용] {ws}") for ws in recent_workspaces]
    ws_options.append((".", "[기본] 현재 디렉토리 (.)"))
    ws_options.append(("__new__", "새로운 경로 입력..."))

    selected_ws = await inline_radio_dialog(
        title="워크스페이스 선택",
        text="미션을 수행할 작업 디렉토리를 선택하세요:",
        values=ws_options
    )

    if selected_ws is None:
        console.print("[yellow]미션 설정이 취소되었습니다.[/yellow]")
        return None, None, None

    if selected_ws == "__new__":
        console.print("\n[bold cyan]새로운 작업 디렉토리 경로를 입력하세요 (Tab으로 자동완성):[/bold cyan]")
        from prompt_toolkit.completion import PathCompleter
        session_ws = PromptSession(completer=PathCompleter(only_directories=True, expanduser=True))
        new_ws = (await session_ws.prompt_async("> ")).strip()
        if not new_ws:
            console.print("[yellow]경로가 입력되지 않아 현재 디렉토리로 진행합니다.[/yellow]")
            selected_ws = "."
        else:
            selected_ws = new_ws

    state.workspace_dir = selected_ws

    # 1. Mission Prompt
    console.print("\n[bold cyan]새로운 미션을 입력하세요 (Enter를 두 번 누르면 완료됩니다):[/bold cyan]")
    console.print("[dim]@ 경로 입력 시 로컬 파일/디렉토리 자동완성이 지원됩니다.[/dim]")
    
    # Custom key bindings to submit on double enter
    from prompt_toolkit.key_binding import KeyBindings
    kb = KeyBindings()
    @kb.add("enter")
    def _(event):
        buffer = event.current_buffer
        if buffer.text.endswith("\n") or not buffer.text:
            # If the buffer ends with a newline (i.e. second Enter) or is completely empty, submit
            buffer.validate_and_handle()
        else:
            buffer.insert_text("\n")
            
    session = PromptSession(completer=MissionCompleter())
    user_prompt = (await session.prompt_async("> ", multiline=True, key_bindings=kb)).strip()
    if not user_prompt:
        console.print("[yellow]미션이 입력되지 않았습니다. 메인 메뉴로 돌아갑니다.[/yellow]")
        return None, None, None

    # 2. Select Personas and Engines
    state.discover_resources()
    units = []
    
    # 2-a. Select Mission Leader (Architect)
    engine_opts = [(e, e) for e in state.available_engines]
    leader_engine = await inline_radio_dialog("미션 리더(Architect) 엔진 선택", "설계와 청사진을 담당할 리더 엔진을 골라주세요:", engine_opts)
    if not leader_engine:
        console.print("[yellow]리더 엔진이 선택되지 않아 기본(gemini)으로 진행합니다.[/yellow]")
        leader_engine = "gemini"
    
    units.append(DeploymentUnit(persona="architect", engine=leader_engine))
    console.print(f"[bold cyan]? 미션 리더(Architect) 설정 완료:[/bold cyan] [bold green]✓ {leader_engine}[/bold green]\n")

    # 2-b. Select additional team members
    while True:
        persona_opts = [(p, p) for p in state.available_personas if p != "architect"]
        persona_opts.append(("__done__", ">> 팀원 추가 완료 <<"))
        
        p = await inline_radio_dialog("팀원 역할 추가", f"현재 추가된 팀원: {len(units)-1}명", persona_opts)
        if not p or p == "__done__":
            break
            
        engine = await inline_radio_dialog(f"{p}의 엔진 선택", "어떤 모델 엔진을 사용할까요?", engine_opts)
        if not engine: continue
        
        count_opts = [(str(i), f"{i}명") for i in range(1, 6)]
        count_str = await inline_radio_dialog(f"{p} ({engine}) 수량", "몇 명을 투입할까요?", count_opts)
        if not count_str: continue
        
        for _ in range(int(count_str)):
            units.append(DeploymentUnit(persona=p, engine=engine))
            
    if len(units) == 1:
        console.print("[yellow]팀원이 없어 아키텍트 단독으로 진행합니다.[/yellow]")

    # Summary of selected agents
    table = Table(title="👥 배정된 전문가 리스트", show_header=True, header_style="bold magenta")
    table.add_column("역할 (Persona)", style="cyan")
    table.add_column("엔진 (Engine)", style="green")
    
    # Count occurrences for a cleaner summary
    from collections import Counter
    counts = Counter([(u.persona, u.engine) for u in units])
    for (p, e), count in counts.items():
        table.add_row(p, f"{e} x{count}")
    
    console.print("\n")
    console.print(table)
    
    confirm = await yes_no_dialog(
        title="전문가 구성 확인",
        text="이 구성으로 미션을 시작할까요?",
        style=cli_style
    ).run_async()
    
    if not confirm:
        console.print("[yellow]에이전트 설정을 취소하고 다시 시작합니다.[/yellow]")
        return await setup_mission(state)

    # 3. Execution Mode
    mode_str = await inline_radio_dialog(
        title="실행 모드 선택",
        text="에이전트들이 어떻게 협업할지 선택하세요:",
        values=[
            (ExecutionMode.PARALLEL.value, "Parallel (병렬 실행 후 취합)"),
            (ExecutionMode.DISCUSSION.value, "Discussion/Relay (순차적 릴레이 토론)")
        ]
    )
    
    mode = ExecutionMode(mode_str) if mode_str else ExecutionMode.PARALLEL

    # 4. Show Mission Flowchart
    tree = Tree(f"🚀 [bold sea_green1]Mission Plan: {mode.value.upper()}[/bold sea_green1]")
    tree.add("[bold cyan]1. Architect[/bold cyan]: 청사진(Blueprint) 설계")
    
    work_node = tree.add(f"[bold cyan]2. {mode.value.title()} Execution[/bold cyan]")
    if mode == ExecutionMode.PARALLEL:
        for u in units:
            work_node.add(f"[dim]{u.persona}[/dim] ({u.engine})")
    else:
        current_node = work_node
        for u in units:
            current_node = current_node.add(f"[dim]{u.persona}[/dim] ({u.engine})")
            
    tree.add("[bold cyan]3. Synthesis[/bold cyan]: 결과물 종합 및 Diffs 생성")
    tree.add("[bold cyan]4. Judge[/bold cyan]: 품질 검수 및 최종 승인 (APPROVE)")
    
    console.print("\n[bold]수행 예정 작업 흐름도:[/bold]")
    console.print(tree)
    console.print("\n[dim]계속하려면 Enter를 누르세요...[/dim]")
    input() # Simple wait for user to see the flowchart

    return user_prompt, units, mode

async def execute_mission(state: OrchestratorState, user_prompt: str, units: List[DeploymentUnit], mode: ExecutionMode, history_context: str = "") -> str | None:
    """Executes the swarm logic and manages the log consuming task with a Live Dashboard."""
    if os.environ.get("DRY_RUN") == "1":
        console.print(Panel(f"[bold]Mission:[/bold] {user_prompt}\n[bold]Mode:[/bold] {mode.value}", title="🚀 Starting Mission"))
        console.print("[bold green]DRY_RUN mode enabled. Skipping actual swarm execution.[/bold green]")
        console.print("\n[bold green]✅ 미션이 완료되었습니다![/bold green]")
        return "dry-run-session"

    # Setup log list for dashboard
    recent_logs = []
    log_task = asyncio.create_task(consume_logs(state, recent_logs))
    state.blueprint_approved.set() # Ensure we don't hang if autonomous_mode isn't picked up
    
    # Create the Live Dashboard Layout
    layout = Layout()
    layout.split_column(
        Layout(name="progress", size=3),
        Layout(name="top", size=3),
        Layout(name="middle", ratio=1),
        Layout(name="diff", size=10, visible=False),
        Layout(name="bottom", size=10)
    )
    
    def generate_layout() -> Layout:
        # Top Header: Project Progress (Persistent)
        layout["progress"].update(render_progress_dashboard())

        # Mission Summary
        short_prompt = user_prompt[:80] + "..." if len(user_prompt) > 80 else user_prompt
        layout["top"].update(Panel(f"🚀 [bold]Mission:[/bold] {short_prompt} | [bold]Mode:[/bold] {mode.value}", border_style="cyan"))
        
        # Middle: Agent Status Swimlanes
        layout["middle"].update(render_swarm_timeline(state.agents, state.global_status))
        
        # Phase 3: Side-by-Side Diff
        if state.current_diff:
            layout["diff"].visible = True
            layout["diff"].update(render_side_by_side_diff(state.current_diff))
        else:
            layout["diff"].visible = False
        
        # Bottom: Scrolling log window
        log_text = Text()
        # Why: Showing colored logs from multiple agents in a single stream 
        # helps the user follow the conversation/execution context.
        for log in recent_logs:
            # We strip rich tags for Text.from_markup if needed, 
            # but Rich's Text object handles them if we use Console.render
            pass
            
        # Using Text.from_markup to ensure colors in logs are rendered
        markup_logs = "\n".join(recent_logs)
        layout["bottom"].update(Panel(Text.from_markup(markup_logs), title="📜 Live Logs", border_style="green"))
        
        return layout

    session_id = None
    try:
        # Use Live to render the dashboard in real-time
        with Live(generate_layout(), console=console, refresh_per_second=4):
            session_id = await run_swarm_logic(
                controller=state,
                user_prompt=user_prompt,
                deployment_units=units,
                judge_agent="judge",
                auditor_agent="auditor",
                execution_mode=mode,
                history_context=history_context
            )
    except asyncio.CancelledError:
        state.cancel_all_tasks()
        console.print("[red]Mission cancelled![/red]")
    except Exception as e:
        console.print(f"[bold red]Critical Error during execution: {e}[/bold red]")
    finally:
        state.emergency_stop.set()
        await log_task
        console.print("\n[bold green]✅ 미션이 완료되었습니다![/bold green]")
        return session_id

async def follow_up_loop(state: OrchestratorState, session_id: str, units: List[DeploymentUnit], mode: ExecutionMode):
    
    from prompt_toolkit.key_binding import KeyBindings
    kb = KeyBindings()
    @kb.add("enter")
    def _(event):
        buffer = event.current_buffer
        if buffer.text.endswith("\n") or not buffer.text:
            buffer.validate_and_handle()
        else:
            buffer.insert_text("\n")
            
    while session_id:
        action = await inline_radio_dialog("후속 조치", "다음 작업을 선택하세요:", [
            ("followup", "현재 컨텍스트에서 이어서 대화하기 (Follow-up)"),
            ("restore", "방금 수행한 작업 되돌리기 (Restore/Undo)"),
            ("menu", "메인 메뉴로 돌아가기")
        ])
        
        if action == "followup":
            session = PromptSession()
            console.print("\n[bold cyan]후속 미션을 입력하세요 (Enter를 두 번 누르면 완료됩니다):[/bold cyan]")
            user_prompt = (await session.prompt_async("> ", multiline=True, key_bindings=kb)).strip()
            
            if user_prompt:
                state.emergency_stop.clear()
                hist_session = state.history_manager.get_session(session_id)
                hist_context = hist_session.get_markdown() if hist_session else ""
                session_id = await execute_mission(state, user_prompt, units, mode, history_context=hist_context)
            else:
                console.print("[yellow]후속 미션이 취소되었습니다.[/yellow]")
        elif action == "restore":
            if state.history_manager.restore_session_checkpoint(session_id):
                console.print("[bold green]✅ 작업이 성공적으로 복구되었습니다![/bold green]")
            else:
                console.print("[bold red]❌ 복구할 수 없는 상태이거나 체크포인트가 없습니다.[/bold red]")
        else:
            break

async def show_history(state: OrchestratorState):
    """Displays history and allows managing past sessions."""
    
    from prompt_toolkit import PromptSession

    while True:
        # Include archived sessions in the list so users can manage them
        sessions = state.history_manager.list_sessions(include_archived=True)
        if not sessions:
            console.print("[yellow]저장된 세션 히스토리가 없습니다.[/yellow]")
            return

        sessions.sort(key=lambda s: s.timestamp, reverse=True)
        
        # Display a tag if archived
        def get_display_name(s):
            prefix = "[보관됨] " if getattr(s, 'archived', False) else ""
            date_str = s.timestamp.split('T')[0] if 'T' in s.timestamp else s.timestamp
            return f"{prefix}[{date_str}] {s.title}"
            
        options = [(s.id, get_display_name(s)) for s in sessions]
        options.append(("__back__", "뒤로 가기 (Back to Main Menu)"))

        selected_id = await inline_searchable_radio_dialog(
            title="세션 히스토리 (검색 가능)",
            text="관리할 세션을 선택하세요 (검색어를 입력하면 필터링됩니다):",
            values=options
        )

        if not selected_id or selected_id == "__back__":
            break

        session_meta = next((s for s in sessions if s.id == selected_id), None)
        if not session_meta:
            console.print("[red]세션 정보를 찾을 수 없습니다.[/red]")
            continue

        while True:
            archive_action_text = "보관 해제 (Unarchive)" if getattr(session_meta, 'archived', False) else "보관 (Archive)"
            action = await inline_radio_dialog(
                title=f"세션 관리: {session_meta.title[:30]}...",
                text="어떤 작업을 수행하시겠습니까?",
                values=[
                    ("followup", "이어서 대화하기 (Follow-up)"),
                    ("view", "세션 결과 보기 (View Details)"),
                    ("rename", "이름 변경 (Rename)"),
                    ("archive", archive_action_text),
                    ("restore", "작업 상태 복구 (Restore Checkpoint)"),
                    ("delete", "삭제 (Delete)"),
                    ("back", "히스토리 목록으로 돌아가기")
                ]
            )

            if not action or action == "back":
                break
                
            if action == "followup":
                hist_session = state.history_manager.get_session(selected_id, include_archived=True)
                if hist_session:
                    hist_context = hist_session.get_markdown()
                    console.print(f"\n[bold green]선택된 세션:[/bold green] {session_meta.title}")
                    user_prompt, units, mode = await setup_mission(state)
                    if user_prompt:
                        new_session_id = await execute_mission(state, user_prompt, units, mode, history_context=hist_context)
                        if new_session_id:
                            await follow_up_loop(state, new_session_id, units, mode)
                            return # Go back to main menu after follow-up is done
                else:
                    console.print("[red]세션 컨텍스트를 불러올 수 없습니다.[/red]")
                    
            elif action == "view":
                hist_session = state.history_manager.get_session(selected_id, include_archived=True)
                if hist_session:
                    from rich.markdown import Markdown
                    console.print("\n[bold cyan]--- 세션 결과 ---[/bold cyan]")
                    content = hist_session.get_markdown()
                    # Use Markdown instead of plain text for better visualization
                    md = Markdown(content)
                    console.print(md)
                    console.print("[bold cyan]-------------------[/bold cyan]\n")
                else:
                    console.print("[red]세션을 불러올 수 없습니다.[/red]")
                    
            elif action == "rename":
                prompt_session = PromptSession()
                console.print(f"\n[cyan]현재 이름:[/cyan] {session_meta.title}")
                new_title = (await prompt_session.prompt_async("새 이름 > ")).strip()
                if new_title:
                    success = state.history_manager.rename_session(selected_id, new_title, getattr(session_meta, 'archived', False))
                    if success:
                        console.print("[green]이름이 변경되었습니다.[/green]")
                        session_meta.title = new_title
                    else:
                        console.print("[red]이름 변경 실패.[/red]")
                        
            elif action == "archive":
                is_archived = getattr(session_meta, 'archived', False)
                if is_archived:
                    if state.history_manager.unarchive_session(selected_id):
                        console.print("[green]세션 보관이 해제되었습니다.[/green]")
                        session_meta.archived = False
                else:
                    if state.history_manager.archive_session(selected_id):
                        console.print("[green]세션이 보관되었습니다.[/green]")
                        session_meta.archived = True
                        
            elif action == "restore":
                confirm = await yes_no_dialog(
                    title="복구 확인",
                    text=f"이 미션이 시작되기 전 상태로 워크스페이스({session_meta.workspace})를 되돌리시겠습니까?\n이후의 모든 변경사항이 유실될 수 있습니다.",
                    style=cli_style
                ).run_async()
                if confirm:
                    if state.history_manager.restore_session_checkpoint(selected_id):
                        console.print("[bold green]✅ 작업이 성공적으로 복구되었습니다![/bold green]")
                    else:
                        console.print("[bold red]❌ 복구할 수 없는 상태이거나 체크포인트가 없습니다.[/bold red]")
                        
            elif action == "delete":
                confirm = await yes_no_dialog(
                    title="삭제 확인",
                    text="정말로 이 세션을 삭제하시겠습니까? (복구할 수 없습니다)",
                    style=cli_style
                ).run_async()
                if confirm:
                    if state.history_manager.delete_session(selected_id, getattr(session_meta, 'archived', False)):
                        console.print("[green]세션이 삭제되었습니다.[/green]")
                        break # Break inner loop since session is gone
                    else:
                        console.print("[red]세션 삭제 실패.[/red]")

async def show_settings(state: OrchestratorState):
    """Simple loop to view/change configuration settings."""
    
    while True:
        options = [
            ("autonomous_mode", f"Autonomous Mode: {'ON (Auto)' if state.autonomous_mode else 'OFF (Manual/Step)'}"),
            ("max_rounds", f"Max Rounds: {state.max_rounds}"),
            ("default_judge", f"Default Judge: {state.default_judge}"),
            ("gemini_model", f"Gemini Model: {state.gemini_model}"),
            ("claude_model", f"Claude Model: {state.claude_model}"),
            ("codex_model", f"Codex Model: {state.codex_model}"),
            ("back", "메인 메뉴로 돌아가기")
        ]
        
        choice = await inline_radio_dialog("Settings (설정 변경)", "변경할 설정을 선택하세요:", options)
        
        if not choice or choice == "back":
            break
            
        if choice == "autonomous_mode":
            mode = await inline_radio_dialog("Autonomous Mode", "에이전트가 단계를 자동으로 진행할까요?", [
                ("true", "ON (자동 진행)"),
                ("false", "OFF (단계별 승인 필요)")
            ])
            if mode:
                state.autonomous_mode = (mode == "true")
        elif choice == "max_rounds":
            rounds = await inline_radio_dialog("Max Rounds", "최대 라운드 수를 선택하세요:", [(str(i), f"{i} rounds") for i in range(1, 11)])
            if rounds:
                state.max_rounds = int(rounds)
        elif choice == "default_judge":
            # Combine all available models across engines for the judge selection
            all_model_opts = []
            for m in state.available_gemini_models:
                all_model_opts.append((m, f"[Gemini] {m}"))
            for m in state.available_codex_models:
                all_model_opts.append((m, f"[Codex] {m}"))
            for m in state.available_claude_models:
                all_model_opts.append((m, f"[Claude] {m}"))
                
            if not all_model_opts:
                # Fallback if discovery hasn't finished or failed
                all_model_opts = [("gemini-3.1-pro", "gemini-3.1-pro (기본)")]

            judge = await inline_radio_dialog("Default Judge", "기본 판정 모델을 선택하세요:", all_model_opts)
            if judge:
                state.default_judge = judge
        elif choice == "gemini_model":
            model_opts = [(m, m) for m in state.available_gemini_models]
            model = await inline_radio_dialog("Gemini Model", "사용할 Gemini 모델을 선택하세요:", model_opts)
            if model:
                state.gemini_model = model
        elif choice == "claude_model":
            model_opts = [(m, m) for m in state.available_claude_models]
            model = await inline_radio_dialog("Claude Model", "사용할 Claude 모델을 선택하세요:", model_opts)
            if model:
                state.claude_model = model
        elif choice == "codex_model":
            model_opts = [(m, m) for m in state.available_codex_models]
            model = await inline_radio_dialog("Codex Model", "사용할 Codex 모델을 선택하세요:", model_opts)
            if model:
                state.codex_model = model
        
        state.save_settings()
        console.print("[green]✅ 설정이 저장되었습니다.[/green]")

async def show_mcp_management(state: OrchestratorState):
    """Displays MCP servers and their status."""
    from orchestrator.core.mcp import MCPManager
    
    manager = MCPManager()
    
    while True:
        options = []
        # Access mcp_servers from settings data if not directly on state
        mcp_servers = getattr(state, "mcp_servers", {})
        
        if not mcp_servers:
            console.print("[yellow]설정된 MCP 서버가 없습니다.[/yellow]")
            break
            
        for name, config in mcp_servers.items():
            status = "[bold green][Active][/bold green]" if name in manager.clients else "[dim][Inactive][/dim]"
            options.append((name, f"{status} {name}"))
            
        options.append(("__back__", "뒤로 가기 (Back to Main Menu)"))
        
        choice = await inline_radio_dialog(
            title="MCP Server Management",
            text="연동된 MCP 서버 상태입니다. 상세 정보를 보려면 선택하세요:",
            values=options
        )
        
        if not choice or choice == "__back__":
            break
            
        config = mcp_servers[choice]
        cmd = " ".join(config.get("command", []))
        env = json.dumps(config.get("env", {}), indent=2)
        
        await message_dialog(
            title=f"MCP Server: {choice}",
            text=f"Command: {cmd}\n\nEnvironment:\n{env}",
            style=cli_style
        ).run_async()

def print_cheat_sheet():
    """Prints a panel showing global shortcuts."""
    shortcuts = [
        ("s", "Start Mission"),
        ("h", "History"),
        ("c", "Settings"),
        ("q", "Quit")
    ]
    text_content = " | ".join([f"[bold cyan]{k}[/bold cyan]: {v}" for k, v in shortcuts])
    console.print(Panel(text_content, title="⌨️ Shortcuts", border_style="dim", expand=False))

async def main_loop():
    """Main CLI event loop."""
    console.print(Panel("[bold cyan]Sovereign Workstation CLI[/bold cyan]\n다중 에이전트 오케스트레이터", border_style="cyan"))
    
    state = OrchestratorState()

    async def wait_for_human_hook_local(payload: dict) -> dict:
        """
        Hook called before an agent performs a reasoning step (ask).
        In non-autonomous mode, it prompts the user for approval.
        """
        if payload.get("autonomous_mode", True):
            return payload
            
        result = await button_dialog(
            title=f"🛡️ Step Approval: {payload['agent_name']}",
            text=f"Agent '{payload['agent_name']}' is ready to: {payload['title']}\n\nProceed with this step?",
            buttons=[
                ("Yes", True),
                ("Auto (All)", "auto"),
                ("Stop", False)
            ],
            style=cli_style
        ).run_async()
        
        if result == "auto":
            payload["autonomous_mode"] = True
            state.autonomous_mode = True
            state.wait_for_human_event.set()
        elif result is True:
            state.wait_for_human_event.set()
        else:
            state.cancel_all_tasks()
            
        return payload

    state.is_interactive = True  # We are in CLI interactive mode
    # autonomous_mode is loaded from settings in OrchestratorState.__init__
    state.hooks.register("tool.execute.before", permission_check_hook)
    state.hooks.register("agent.ask.before", wait_for_human_hook_local)
    
    from orchestrator.tools.mcp_tools import hook_execute_mcp_tool
    state.hooks.register("tool.execute.after", hook_execute_mcp_tool)
    
    state.run_preflight()
    
    # Render pre-flight results as a table for better visualization
    table = Table(title="🔍 Pre-flight System Check", show_header=True, header_style="bold cyan")
    table.add_column("Check", style="dim")
    table.add_column("Status", justify="center")
    
    for check, passed in state.preflight_results.items():
        status = "[green]✅ Pass[/green]" if passed else "[red]❌ Fail[/red]"
        table.add_row(check, status)
    
    console.print(table)
    console.print()
    
    await state.discover_models()

    

    while True:
        console.print(render_progress_dashboard())
        print_cheat_sheet()
        choice = await inline_radio_dialog(
            title="메인 메뉴",
            text="원하는 작업을 선택하세요:",
            values=[
                ("start", "새로운 미션 시작 (Start Mission)"),
                ("history", "과거 히스토리 이어하기 (History)"),
                ("mcp", "MCP 서버 관리 (MCP Management)"),
                ("settings", "Settings (설정 변경)"),
                ("quit", "종료 (Exit)")
            ],
            shortcuts={
                "s": "start",
                "h": "history",
                "m": "mcp",
                "c": "settings",
                "q": "quit"
            }
        )

        if choice == "quit" or choice is None:
            break
        elif choice == "start":
            state.emergency_stop.clear()
            user_prompt, units, mode = await setup_mission(state)
            if user_prompt:
                session_id = await execute_mission(state, user_prompt, units, mode)
                if session_id:
                    await follow_up_loop(state, session_id, units, mode)
        elif choice == "history":
            state.emergency_stop.clear()
            await show_history(state)
        elif choice == "mcp":
            await show_mcp_management(state)
        elif choice == "settings":
            await show_settings(state)

def run():
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        console.print("\n[yellow]프로그램을 종료합니다.[/yellow]")
        sys.exit(0)

if __name__ == "__main__":
    run()
