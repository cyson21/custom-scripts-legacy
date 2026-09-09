import ast
import os
from pathlib import Path
from typing import Dict, Set, List


class DependencyAnalyzer:
    """
    Analyzes project dependencies to determine the impact of changes.
    Useful for 'Dependency Impact Analysis'.
    """

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.graph: Dict[str, Set[str]] = {}  # file -> files that import it

    def build_graph(self):
        """Builds a dependency graph by scanning all python files."""
        self.graph = {}
        for root, _, files in os.walk(self.root_dir):
            for file in files:
                if file.endswith(".py"):
                    file_path = Path(root) / file
                    self._process_file(file_path)

    def _process_file(self, file_path: Path):
        try:
            content = file_path.read_text()
            tree = ast.parse(content)

            relative_path = str(file_path.relative_to(self.root_dir))

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for n in node.names:
                        self._add_to_graph(n.name, relative_path)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        self._add_to_graph(node.module, relative_path)
        except Exception:
            pass

    def _add_to_graph(self, module_name: str, importer_path: str):
        # Convert module name to possible file path
        module_parts = module_name.split('.')
        possible_path = "/".join(module_parts) + ".py"

        if possible_path not in self.graph:
            self.graph[possible_path] = set()
        self.graph[possible_path].add(importer_path)

    def get_impacted_files(self, changed_file: str) -> List[str]:
        """
        Returns a list of files that might be impacted by a change
        to changed_file.
        """
        relative_path = changed_file
        if os.path.isabs(changed_file):
            try:
                relative_path = str(
                    Path(changed_file).relative_to(self.root_dir))
            except Exception:
                pass

        impacted = self.graph.get(relative_path, set())
        # Recursive impact could be added here
        return sorted(list(impacted))
