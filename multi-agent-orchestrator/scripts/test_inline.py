import asyncio
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, FormattedTextControl, Window
from prompt_toolkit.key_binding import KeyBindings

async def inline_select(options, prompt_text="Select: "):
    selected_idx = 0
    
    kb = KeyBindings()
    
    @kb.add("down")
    def _(event):
        nonlocal selected_idx
        selected_idx = (selected_idx + 1) % len(options)
        
    @kb.add("up")
    def _(event):
        nonlocal selected_idx
        selected_idx = (selected_idx - 1) % len(options)
        
    @kb.add("enter")
    def _(event):
        event.app.exit(result=options[selected_idx])
        
    def get_text():
        result = [("class:title", f"? {prompt_text}\n")]
        for i, opt in enumerate(options):
            if i == selected_idx:
                result.append(("class:selected", f"  > {opt}\n"))
            else:
                result.append(("", f"    {opt}\n"))
        return result
        
    control = FormattedTextControl(get_text)
    window = Window(content=control)
    layout = Layout(window)
    
    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=False,
    )
    return await app.run_async()

if __name__ == "__main__":
    result = asyncio.run(inline_select(["A", "B", "C"], "Choose:"))
    print(f"Result: {result}")
