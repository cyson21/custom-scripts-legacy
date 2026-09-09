from prompt_toolkit.application import Application
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from typing import Dict

from orchestrator.core.models import AgentState, AgentStatus

console = Console()

inline_style = Style.from_dict({
    "pointer": "fg:#00afff bold",
    "selected": "fg:#00afff bold",
    "unselected": "",
    "instruction": "fg:#888888",
    "prompt": "bold cyan",
})

async def inline_radio_dialog(title: str, text: str, values: list, shortcuts: dict = None):
    """
    Displays an inline radio list selection that doesn't clear the screen.
    values: list of tuples (value, label)
    shortcuts: optional dict mapping single-letter keys to values
    """
    selected_idx = 0

    kb = KeyBindings()

    @kb.add("down")
    def _(event):
        nonlocal selected_idx
        if values:
            selected_idx = (selected_idx + 1) % len(values)

    @kb.add("up")
    def _(event):
        nonlocal selected_idx
        if values:
            selected_idx = (selected_idx - 1) % len(values)

    @kb.add("enter")
    def _(event):
        if values and 0 <= selected_idx < len(values):
            event.app.exit(result=values[selected_idx][0])
        else:
            event.app.exit(result=None)

    @kb.add("c-c")
    def _(event):
        event.app.exit(result=None)

    if shortcuts:
        for key, value in shortcuts.items():
            def _create_shortcut_handler(val):
                @kb.add(key)
                def _(event):
                    event.app.exit(result=val)
            _create_shortcut_handler(value)

    def get_text():
        result = []
        result.append(("class:prompt", f"? {title} "))
        result.append(("class:instruction", f"{text}\n"))
        
        for i, (val, label) in enumerate(values):
            if i == selected_idx:
                result.append(("class:pointer", "  > "))
                result.append(("class:selected", f"{label}\n"))
            else:
                result.append(("class:unselected", f"    {label}\n"))
        return result

    control = FormattedTextControl(get_text)
    window = Window(content=control)
    layout = Layout(window)

    app = Application(
        layout=layout,
        key_bindings=kb,
        style=inline_style,
        full_screen=False,
    )
    
    result = await app.run_async()
    
    # Print the chosen value to leave it in history
    if result is not None:
        try:
            selected_label = next(l for v, l in values if v == result)
            console.print(f"[bold cyan]? {title}[/bold cyan] [bold green]✓ {selected_label}[/bold green]")
        except StopIteration:
            # Fallback if value not found (shouldn't happen)
            console.print(f"[bold cyan]? {title}[/bold cyan] [bold green]✓ {result}[/bold green]")
    else:
        console.print(f"[bold cyan]? {title}[/bold cyan] [yellow]취소됨[/yellow]")
        
    return result

async def inline_searchable_radio_dialog(title: str, text: str, values: list):
    """
    Displays an inline radio list selection with a fuzzy search filter.
    """
    search_text = ""
    selected_idx = 0

    kb = KeyBindings()

    @kb.add("down")
    def _(event):
        nonlocal selected_idx
        filtered = [v for v in values if search_text.lower() in v[1].lower()]
        if filtered:
            selected_idx = (selected_idx + 1) % len(filtered)

    @kb.add("up")
    def _(event):
        nonlocal selected_idx
        filtered = [v for v in values if search_text.lower() in v[1].lower()]
        if filtered:
            selected_idx = (selected_idx - 1) % len(filtered)

    @kb.add("enter")
    def _(event):
        filtered = [v for v in values if search_text.lower() in v[1].lower()]
        if filtered and 0 <= selected_idx < len(filtered):
            event.app.exit(result=filtered[selected_idx][0])
        else:
            event.app.exit(result=None)

    @kb.add("c-c")
    def _(event):
        event.app.exit(result=None)

    @kb.add("backspace")
    def _(event):
        nonlocal search_text, selected_idx
        search_text = search_text[:-1]
        selected_idx = 0

    @kb.add("<any>")
    def _(event):
        nonlocal search_text, selected_idx
        if len(event.data) == 1 and event.data.isprintable():
            search_text += event.data
            selected_idx = 0

    def get_text():
        filtered = [v for v in values if search_text.lower() in v[1].lower()]
        
        result = []
        result.append(("class:prompt", f"? {title} "))
        result.append(("class:instruction", f"{text}\n"))
        result.append(("class:selected", f"  Search: {search_text}_\n"))
        
        if not filtered:
            result.append(("class:instruction", "    (검색 결과 없음)\n"))
        else:
            for i, (val, label) in enumerate(filtered):
                if i == selected_idx:
                    result.append(("class:pointer", "  > "))
                    result.append(("class:selected", f"{label}\n"))
                else:
                    result.append(("class:unselected", f"    {label}\n"))
        return result

    control = FormattedTextControl(get_text)
    window = Window(content=control)
    layout = Layout(window)

    app = Application(
        layout=layout,
        key_bindings=kb,
        style=inline_style,
        full_screen=False,
    )
    
    result = await app.run_async()
    
    if result is not None:
        try:
            selected_label = next(l for v, l in values if v == result)
            console.print(f"[bold cyan]? {title}[/bold cyan] [bold green]✓ {selected_label}[/bold green]")
        except StopIteration:
            console.print(f"[bold cyan]? {title}[/bold cyan] [bold green]✓ {result}[/bold green]")
    else:
        console.print(f"[bold cyan]? {title}[/bold cyan] [yellow]취소됨[/yellow]")
        
    return result

async def inline_checkbox_dialog(title: str, text: str, values: list):
    """
    Displays an inline checkbox list selection that doesn't clear the screen.
    values: list of tuples (value, label)
    """
    selected_idx = 0
    checked = set()

    kb = KeyBindings()

    @kb.add("down")
    def _(event):
        nonlocal selected_idx
        selected_idx = (selected_idx + 1) % len(values)

    @kb.add("up")
    def _(event):
        nonlocal selected_idx
        selected_idx = (selected_idx - 1) % len(values)

    @kb.add(" ")
    def _(event):
        val = values[selected_idx][0]
        if val in checked:
            checked.remove(val)
        else:
            checked.add(val)

    @kb.add("enter")
    def _(event):
        event.app.exit(result=list(checked))

    @kb.add("c-c")
    def _(event):
        event.app.exit(result=None)

    def get_text():
        result = []
        result.append(("class:prompt", f"? {title} "))
        result.append(("class:instruction", f"{text} (Space로 선택, Enter로 완료)\n"))
        
        for i, (val, label) in enumerate(values):
            prefix = "  > " if i == selected_idx else "    "
            prefix_class = "class:pointer" if i == selected_idx else "class:unselected"
            
            box = "[x]" if val in checked else "[ ]"
            box_class = "class:selected" if val in checked else "class:unselected"
            
            result.append((prefix_class, prefix))
            result.append((box_class, f"{box} {label}\n"))
        return result

    control = FormattedTextControl(get_text)
    window = Window(content=control)
    layout = Layout(window)

    app = Application(
        layout=layout,
        key_bindings=kb,
        style=inline_style,
        full_screen=False,
    )
    
    result = await app.run_async()
    
    if result is not None:
        selected_labels = [l for v, l in values if v in result]
        text_labels = ", ".join(selected_labels) if selected_labels else "선택 없음"
        console.print(f"[bold cyan]? {title}[/bold cyan] [bold green]✓ {text_labels}[/bold green]")
    else:
        console.print(f"[bold cyan]? {title}[/bold cyan] [yellow]취소됨[/yellow]")
        
    return result

def render_swarm_timeline(agents: Dict[str, AgentState], global_status: str = ""):
    """
    Function: Renders a Swimlane UI for agent collaboration.
    Why: Visualizes "who is doing what" in real-time, making the swarm's 
    internal reasoning process transparent to the user.
    """
    if not agents:
        return Panel(Text("Waiting for agents to initialize...", justify="center"), title="[bold blue]Swarm Reasoning Timeline[/bold blue]", border_style="blue")

    table = Table(box=None, expand=True)
    table.add_column("Agent", style="bold cyan", width=20)
    table.add_column("Status", width=15)
    table.add_column("Activity", style="italic white")
    
    # Sort agents for consistent rendering
    sorted_agent_names = sorted(agents.keys())
    
    for name in sorted_agent_names:
        state = agents[name]
        status_color = "white"
        if state.status == AgentStatus.THINKING: status_color = "yellow"
        elif state.status == AgentStatus.ACTING: status_color = "blue"
        elif state.status == AgentStatus.VERIFYING: status_color = "magenta"
        elif state.status == AgentStatus.SUCCESS: status_color = "green"
        elif state.status == AgentStatus.FAILURE: status_color = "red"
        elif state.status == AgentStatus.WAITING: status_color = "cyan"
        
        status_text = Text(state.status.value, style=status_color)
        
        table.add_row(
            name,
            status_text,
            state.last_action or "-"
        )
    
    return Panel(
        table, 
        title="[bold blue]Swarm Reasoning Timeline[/bold blue]",
        subtitle=f"[dim]{global_status}[/dim]",
        border_style="blue"
    )

def render_progress_dashboard():
    """
    Function: Renders a sticky header with current task and progress.
    Why: Keeps the user informed about the overall project state without 
    manual todo.json inspection.
    """
    from orchestrator.core.utils import get_todo_progress
    stats = get_todo_progress()
    
    task_id = stats["task_id"]
    progress = stats["progress"]
    is_valid = stats["valid"]
    
    # Progress Bar
    bar_width = 20
    filled = int(progress / 100 * bar_width)
    bar = "█" * filled + "░" * (bar_width - filled)
    
    valid_status = "[green]VALID[/green]" if is_valid else "[red]INVALID[/red]"
    
    return Panel(
        f"[bold]Task:[/bold] {task_id} | [bold]Progress:[/bold] [{bar}] {progress:.1f}% | [bold]State:[/bold] {valid_status}",
        style="white on blue",
        expand=True
    )
