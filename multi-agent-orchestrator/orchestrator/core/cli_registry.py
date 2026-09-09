import shutil
import os
import subprocess
import asyncio
from pathlib import Path
from typing import Dict, Optional, Any


class CLIRegistry:
    """
    Discovers local CLI binaries and caches their absolute paths.
    Provides lookup functionality to avoid repeated disk I/O.
    """

    def __init__(self):
        self._cache: Dict[str, Path] = {}
        self._capabilities: Dict[str, Dict[str, Any]] = {}

    def lookup(self, name: str) -> Optional[Path]:
        if name in self._cache:
            return self._cache[name]

        path = self._discover(name)
        if path:
            self._cache[name] = path
        return path

    def _discover(self, name: str) -> Optional[Path]:
        # 1. Try shutil.which
        which_path = shutil.which(name)
        if which_path:
            return Path(which_path).resolve()

        # 2. Try npm bin -g for npm packages
        try:
            result_bin = subprocess.run(
                ["npm", "bin", "-g"],
                capture_output=True,
                text=True,
                shell=(os.name == 'nt'),
                stdin=subprocess.DEVNULL,
                timeout=10
            )
            if result_bin.returncode == 0:
                npm_bin = Path(result_bin.stdout.strip())
                bin_path = npm_bin / name
                if bin_path.exists():
                    return bin_path.resolve()
                if os.name == 'nt':
                    bin_path_exe = npm_bin / f"{name}.cmd"
                    if bin_path_exe.exists():
                        return bin_path_exe.resolve()
        except Exception:
            pass

        # 3. Try brew --prefix for Homebrew
        try:
            result = subprocess.run(
                ["brew", "--prefix"],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=10
            )
            if result.returncode == 0:
                brew_prefix = Path(result.stdout.strip())
                bin_path = brew_prefix / "bin" / name
                if bin_path.exists():
                    return bin_path.resolve()
        except Exception:
            pass

        # 4. Check common paths
        common_paths = [
            Path.home() / ".local" / "bin" / name,
            Path("/usr/local/bin") / name,
            Path("/opt/homebrew/bin") / name,
        ]

        # NVM Support: Search in NVM current/versions directories
        nvm_dir = os.environ.get('NVM_DIR') or str(Path.home() / ".nvm")
        if Path(nvm_dir).exists():
            # Try to find the latest node version's bin directory
            versions_dir = Path(nvm_dir) / "versions" / "node"
            if versions_dir.exists():
                for v_dir in sorted(versions_dir.iterdir(), reverse=True):
                    bin_path = v_dir / "bin" / name
                    if bin_path.exists():
                        return bin_path.resolve()

        if os.name == 'nt':
            common_paths.extend([
                Path.home() / "AppData" / "Local" / "Microsoft" /
                "WindowsApps" / f"{name}.exe"
            ])

        for path in common_paths:
            if path.exists():
                return path.resolve()

        return None

    async def get_capabilities(self, name: str) -> Dict[str, Any]:
        if name in self._capabilities:
            return self._capabilities[name]

        path = self.lookup(name)
        if not path:
            self._capabilities[name] = {"installed": False, "models": []}
            return self._capabilities[name]

        try:
            proc = await asyncio.create_subprocess_exec(
                str(path), "--help",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=5.0
            )
            output = stdout.decode('utf-8', errors='replace') + \
                stderr.decode('utf-8', errors='replace')
            self._capabilities[name] = {"installed": True, "help_text": output}
            return self._capabilities[name]
        except Exception as e:
            self._capabilities[name] = {
                "installed": True, "help_text": "", "error": str(e)}
            return self._capabilities[name]

    async def get_available_models(self, name: str) -> list[str]:
        if name == "gemini":
            return [
                "gemini-3.1-pro", "gemini-3.1-flash-lite",
                "gemini-3-deep-think"
            ]

        elif name == "codex":
            return ["codex-5.3", "codex-5.4", "gpt-5.4", "o3-pro"]

        elif name == "claude":
            return [
                "claude-4.6-sonnet", "claude-4.6-opus", "claude-4.5-haiku"
            ]

        return []


# Global registry instance
registry = CLIRegistry()
