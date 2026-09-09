import os
import platform
import subprocess
from pathlib import Path
import shutil

def get_windows_home_in_wsl() -> Path | None:
    try:
        # Get Windows USERPROFILE path via powershell
        result = subprocess.run(["cmd.exe", "/c", "echo %USERPROFILE%"], capture_output=True, text=True)
        win_path = result.stdout.strip()
        if win_path:
            # Convert C:\Users\xxx to /mnt/c/Users/xxx
            drive, path = win_path.split(':\\')
            path = path.replace('\\', '/')
            return Path(f"/mnt/{drive.lower()}/{path}")
    except:
        pass
    
    # Heuristic based on WSL username
    user = os.environ.get('USER')
    if user:
        guess = Path(f"/mnt/c/Users/{user}")
        if guess.exists(): return guess
        # Try finding a directory that matches "Son chan yang" or similar
        users_dir = Path("/mnt/c/Users")
        if users_dir.exists():
            for d in users_dir.iterdir():
                if d.is_dir() and "son" in d.name.lower():
                    return d
    return None

def get_gemini_cli_path() -> Path | None:
    # 1. Try to find via 'npm root -g'
    try:
        result = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, shell=(os.name == 'nt'))
        if result.returncode == 0:
            npm_root = Path(result.stdout.strip())
            gemini_js = npm_root / "@google" / "gemini-cli" / "dist" / "index.js"
            if gemini_js.exists():
                return gemini_js
    except Exception:
        pass

    # 2. Try common locations
    homes = [Path.home()]
    if "microsoft" in platform.uname().release.lower() or "wsl" in platform.uname().release.lower():
        win_home = get_windows_home_in_wsl()
        if win_home: homes.append(win_home)

    for home in homes:
        common_paths = [
            home / "AppData/Roaming/npm/node_modules/@google/gemini-cli/dist/index.js",
            home / ".nvm/versions/node/v*/lib/node_modules/@google/gemini-cli/dist/index.js",
            Path("/usr/local/lib/node_modules/@google/gemini-cli/dist/index.js")
        ]
        for p in common_paths:
            if "*" in str(p):
                import glob
                matches = list(Path(p).parent.glob(Path(p).name))
                if matches: return Path(matches[0])
            elif p.exists():
                return p

    return None

def get_codex_cli_path() -> Path | None:
    # 1. Check if 'codex' is in PATH
    codex_which = shutil.which("codex")
    if codex_which:
        return Path(codex_which)

    system = platform.system().lower()
    machine = platform.machine().lower()

    homes = [Path.home()]
    is_wsl = "linux" in system and ("microsoft" in platform.uname().release.lower() or "wsl" in platform.uname().release.lower())
    if is_wsl:
        win_home = get_windows_home_in_wsl()
        if win_home: homes.append(win_home)

    for home in homes:
        codex_home = home / ".codex" / "bin"
        if not codex_home.exists():
            continue

        if is_wsl:
            target = codex_home / "wsl" / "codex"
            if target.exists(): return target
            
        if "linux" in system:
            if "aarch64" in machine or "arm" in machine:
                target = codex_home / "linux-arm64" / "codex"
            else:
                target = codex_home / "linux-x64" / "codex"
        elif "darwin" in system:
            if "arm" in machine or "aarch64" in machine:
                target = codex_home / "darwin-arm64" / "codex"
            else:
                target = codex_home / "darwin-x64" / "codex"
        elif "windows" in system:
            target = codex_home / "windows-x64" / "codex.exe"
        else:
            target = None

        if target and target.exists():
            return target

        for f in codex_home.rglob("codex*"):
            if f.is_file() and os.access(f, os.X_OK):
                return f

    return None

def get_sg_cli_path() -> Path | None:
    """
    Finds the path to the ast-grep (sg) CLI.
    """
    sg_which = shutil.which("sg")
    if sg_which:
        return Path(sg_which)
    return None
