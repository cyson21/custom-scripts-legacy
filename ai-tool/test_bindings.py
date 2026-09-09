from textual.app import App, ComposeResult
from textual.widgets import Tree
from textual.binding import Binding

class MyApp(App):
    BINDINGS = [
        Binding("right", "expand", "Expand", show=False),
        Binding("left", "collapse", "Collapse", show=False),
    ]

    def compose(self) -> ComposeResult:
        tree = Tree("Root")
        tree.root.add("Child 1").add("Grandchild 1")
        tree.root.expand_all()
        yield tree

    def action_expand(self):
        print("ACTION EXPAND CALLED")
        tree = self.query_one(Tree)
        if tree.cursor_node:
            tree.cursor_node.expand()

    def action_collapse(self):
        print("ACTION COLLAPSE CALLED")
        tree = self.query_one(Tree)
        if tree.cursor_node:
            tree.cursor_node.collapse()

if __name__ == "__main__":
    app = MyApp()
    print("Running app...")
