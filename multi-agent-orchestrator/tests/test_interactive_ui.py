import pytest
import asyncio
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import PathCompleter
from prompt_toolkit.key_binding import KeyBindings

@pytest.mark.asyncio
async def test_path_completer_expanduser():
    """Verify that PathCompleter correctly expands ~ to home directory."""
    with create_pipe_input() as inp:
        completer = PathCompleter(only_directories=True, expanduser=True)
        session = PromptSession(completer=completer, input=inp)
        
        # We simulate typing ~/ and then hitting Tab to see if completions are generated
        # However, to just test the completer behavior:
        from prompt_toolkit.document import Document
        doc = Document("~/", cursor_position=2)
        completions = list(completer.get_completions(doc, None))
        
        # Ensure that it found directories inside the home directory
        assert len(completions) > 0, "PathCompleter should yield completions for '~/'"
        assert any(c.text for c in completions), "Completions should have valid text"

@pytest.mark.asyncio
async def test_double_enter_keybinding():
    """Verify that pressing Enter twice submits the mission prompt."""
    with create_pipe_input() as inp:
        kb = KeyBindings()
        @kb.add("enter")
        def _(event):
            buffer = event.current_buffer
            if buffer.text.endswith("\n") or not buffer.text:
                buffer.validate_and_handle()
            else:
                buffer.insert_text("\n")
                
        session = PromptSession(input=inp, multiline=True, key_bindings=kb)
        
        # Simulate typing text, then Enter, then Enter again
        inp.send_text("Test Mission\n\n")
        
        result = await session.prompt_async()
        
        assert result == "Test Mission\n", "Double enter should submit and return the text"
