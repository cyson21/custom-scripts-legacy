import ast
import os
from pathlib import Path
from typing import List, Dict, Any, Set, Optional, Callable


class CodeIndexer:
    """
    Indexes project symbols (classes, functions) to provide context to agents.
    """

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.index: Dict[str, Any] = {}
        # Aggressive exclusion list to prevent hanging in large directories
        self.exclude_dirs = [
            ".git", "__pycache__", "venv", ".venv", "artifacts",
            ".pytest_cache", ".sandboxes", "node_modules", "target", "build",
            "dist", ".nvm", ".npm", ".rustup", ".cargo", "Library",
            "Applications", "Pictures", "Music", "Movies", "Downloads",
            "Desktop", ".cache", ".local", ".config", ".vscode", ".idea",
            ".DS_Store"
        ]

    def scan(self, exclude_dirs: List[str] = None,
             on_progress: Optional[Callable[[str], None]] = None):
        if exclude_dirs:
            self.exclude_dirs.extend(exclude_dirs)
            self.exclude_dirs = sorted(list(set(self.exclude_dirs)))

        file_count = 0
        for root, dirs, files in os.walk(self.root_dir):
            # Prune directories in-place for os.walk efficiency
            dirs[:] = [
                d for d in dirs
                if d not in self.exclude_dirs and not d.startswith('.')
            ]

            for file in files:
                if file.endswith(".py"):
                    file_path = Path(root) / file
                    try:
                        relative_path = file_path.relative_to(self.root_dir)
                        if on_progress and file_count % 100 == 0:
                            on_progress(
                                f"Indexing ({file_count} files): "
                                f"{relative_path}"
                            )
                        self._index_file(file_path, str(relative_path))
                        file_count += 1
                    except (ValueError, OSError):
                        continue

    def _index_file(self, file_path: Path, rel_path: str):
        try:
            # Skip large files (> 1MB) to prevent memory issues
            if file_path.stat().st_size > 1024 * 1024:
                return

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            tree = ast.parse(content)

            symbols = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    symbols.append({
                        "type": "class",
                        "name": node.name,
                        "line": node.lineno
                    })
                elif isinstance(node, ast.FunctionDef):
                    symbols.append({
                        "type": "function",
                        "name": node.name,
                        "line": node.lineno
                    })
                elif isinstance(node, ast.AsyncFunctionDef):
                    symbols.append({
                        "type": "async_function",
                        "name": node.name,
                        "line": node.lineno
                    })

            if symbols:
                self.index[rel_path] = symbols
        except Exception:
            # Skip files that can't be parsed
            pass

    def get_summary(self) -> str:
        """Returns a string representation of the index for LLM context."""
        lines = ["# Project Symbol Index"]
        for file, symbols in sorted(self.index.items()):
            lines.append(f"## {file}")
            for sym in symbols:
                lines.append(
                    f"- [{sym['type']}] {sym['name']} (line {sym['line']})"
                )
        return "\n".join(lines)

    def _get_defined_symbols(self, file_path: Path) -> Set[str]:
        """
        Parses a Python file and returns a set of defined class and
        function names.
        """
        symbols = set()
        try:
            if (not file_path.exists() or
                    file_path.stat().st_size > 1024 * 1024):
                return symbols
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(
                    node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    symbols.add(node.name)
        except Exception:
            pass  # Ignore files that can't be parsed
        return symbols

    def _file_path_to_module_name(self, file_path: str) -> str:
        """Converts a file path to a Python module name."""
        return file_path.replace(os.sep, ".").removesuffix(".py")

    def _resolve_import(self, node: ast.ImportFrom,
                        current_file: Path) -> Optional[str]:
        """Resolves an ImportFrom node to a module name."""
        if node.level > 0:  # Relative import
            level = node.level
            base_path = current_file.parent
            for _ in range(level - 1):
                base_path = base_path.parent

            module_path_parts = node.module.split('.') if node.module else []

            final_path = base_path
            for part in module_path_parts:
                final_path = final_path / part

            try:
                if not final_path.is_absolute():
                    # This can happen with malformed paths
                    return None

                relative_to_root = final_path.relative_to(self.root_dir)
                module_name = self._file_path_to_module_name(
                    str(relative_to_root)
                )

                # Check if it resolves to a package or a module
                potential_file = self.root_dir / (
                    module_name.replace('.', os.sep) + '.py'
                )
                potential_package = self.root_dir / (
                    module_name.replace('.', os.sep)
                ) / '__init__.py'

                if potential_file.exists():
                    return module_name
                elif potential_package.exists():
                    return module_name
                return None
            except ValueError:
                return None  # Path is not within the root directory

        elif node.module:  # Absolute import
            return node.module

        return None

    def get_impact_analysis(
        self, modified_files: List[str]
    ) -> Dict[str, List[str]]:
        """
        Analyzes the codebase to find which files import symbols from
        the modified files.
        """
        impact_analysis = {file: [] for file in modified_files}

        module_to_file_map = {
            self._file_path_to_module_name(f): f for f in modified_files
        }
        modified_modules = {
            name: self._get_defined_symbols(self.root_dir / path)
            for name, path in module_to_file_map.items()
        }
        # Filter out modules with no symbols
        modified_modules = {k: v for k, v in modified_modules.items() if v}
        modified_module_names = set(modified_modules.keys())

        all_py_files = []
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if d not in self.exclude_dirs]
            for file in files:
                if file.endswith(".py"):
                    file_path = Path(root) / file
                    relative_path = str(file_path.relative_to(self.root_dir))
                    if relative_path not in modified_files:
                        all_py_files.append(file_path)

        for file_to_check in all_py_files:
            try:
                with open(file_to_check, "r", encoding="utf-8") as f:
                    content = f.read()
                tree = ast.parse(content)
                importer_rel_path = str(
                    file_to_check.relative_to(self.root_dir))

                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        imported_module = self._resolve_import(
                            node, file_to_check)
                        if (imported_module and
                                imported_module in modified_module_names):
                            imported_names = {
                                alias.name for alias in node.names}

                            if ("*" in imported_names or
                                    not imported_names.isdisjoint(
                                        modified_modules[imported_module])):
                                mod_file_path = \
                                    module_to_file_map[imported_module]
                                if (importer_rel_path not in
                                        impact_analysis[mod_file_path]):
                                    impact_analysis[mod_file_path].append(
                                        importer_rel_path
                                    )

                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            imported_module = alias.name
                            # Check for both direct and sub-module imports
                            for mod_name in modified_module_names:
                                if (mod_name == imported_module or
                                        mod_name.startswith(
                                            imported_module + '.')):
                                    mod_file_path = \
                                        module_to_file_map[mod_name]
                                    if (importer_rel_path not in
                                            impact_analysis[mod_file_path]):
                                        impact_analysis[mod_file_path].append(
                                            importer_rel_path
                                        )
            except Exception:
                continue  # Ignore files that can't be parsed

        return impact_analysis


if __name__ == "__main__":
    indexer = CodeIndexer(Path.cwd())
    indexer.scan()
    print(indexer.get_summary())

    # --- DEMO of impact analysis ---
    # This is a placeholder for actual modified files from git
    sample_modified_files = ["orchestrator/models.py"]

    # Check if the file exists before running the analysis
    if not (Path.cwd() / sample_modified_files[0]).exists():
        print(
            f"\nSkipping impact analysis demo: "
            f"'{sample_modified_files[0]}' not found."
        )
    else:
        print("\n\n--- Dependency Impact Analysis ---")
        impact = indexer.get_impact_analysis(sample_modified_files)
        for file, dependencies in impact.items():
            if dependencies:
                print(f"File '{file}' impacts:")
                for dep in sorted(dependencies):
                    print(f"  - {dep}")
            else:
                print(f"File '{file}' has no detected dependencies.")
