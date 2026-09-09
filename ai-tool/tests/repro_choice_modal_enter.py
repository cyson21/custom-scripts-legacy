
import pytest
from textual.app import App
from aitool.ui.modals import ChoiceModal
from textual.widgets import Button

class ChoiceModalTestApp(App):
    def __init__(self):
        super().__init__()
        self.dismiss_value = None

    def on_mount(self):
        choices = [("Option 1", "opt1"), ("Option 2", "opt2")]
        self.push_screen(ChoiceModal("Test Choice", choices), self.handle_choice)

    def handle_choice(self, value):
        self.dismiss_value = value

@pytest.mark.asyncio
async def test_choice_modal_enter_initial_focus():
    app = ChoiceModalTestApp()
    async with app.run_test() as pilot:
        assert isinstance(app.screen, ChoiceModal)
        
        # Initial focus should be on c0 (if focused by Textual) or we might need to focus it.
        # But even if it's not focused, we want it to work if it IS focused.
        
        if not isinstance(app.focused, Button):
            await pilot.press("down")
        
        await pilot.press("enter")
        await pilot.pause(0.2)
        
        assert app.dismiss_value == "opt1"
