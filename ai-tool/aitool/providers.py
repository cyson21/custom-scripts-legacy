"""
Architectural Role: Provider implementations for Claude and Gemini CLI tools.
This module encapsulates the specific CLI commands, file paths, and metadata
parsing logic for each AI provider, exposing a uniform BaseProvider API.
"""
import os
import json
import glob
import shutil
import shlex
import subprocess
import traceback
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Tuple, Any
from aitool.config import logger, CLAUDE_PROJECTS_DIR, META_FILE, LEGACY_META_FILE, _UUID_RE
from aitool.models import BaseSession, ClaudeSession, GeminiSession

class BaseProvider(ABC):
    name: str
    short_name: str
    color: str

    @abstractmethod
    def load_sessions(self, show_archived: bool) -> List[BaseSession]: ...

    @abstractmethod
    def archive_session(self, s: BaseSession) -> None: ...

    @abstractmethod
    def restore_session(self, s: BaseSession) -> None: ...

    @abstractmethod
    def delete_session(self, s: BaseSession) -> None: ...

    @abstractmethod
    def rename_session(self, s: BaseSession, new_title: str) -> None: ...

    @abstractmethod
    def get_resume_command(self, s: BaseSession) -> str: ...

    @abstractmethod
    def get_new_session_command(self, cwd: str) -> str: ...

    @abstractmethod
    def run_ai_summary(self, prompt: str) -> str: ...

    @abstractmethod
    def save_ai_summary(self, s: BaseSession, title: str) -> None: ...

    @abstractmethod
    def get_workspaces(self, exclude_cwd: str) -> List[Tuple[str, Any]]: ...

    @abstractmethod
    def move_copy_session(self, s: BaseSession,
                          dest_cwd: str, move: bool) -> None: ...

    @abstractmethod
    def is_available(self) -> bool:
        """
        Why: We use shutil.which for rapid availability checks instead of
        attempting to execute the binary and waiting for a subprocess timeout.
        This ensures the UI remains snappy during initial provider discovery.
        """
        ...

    @abstractmethod
    def get_version(self) -> str: ...


class ClaudeProvider(BaseProvider):
    name = "Claude Code"
    short_name = "claude"
    color = "yellow"

    def _load_meta(self) -> dict:
        # 신규 경로 없으면 레거시 경로 폴백 후 신규 경로에 복사 저장 (레거시 파일 삭제 안 함)
        if META_FILE.exists():
            try:
                with open(META_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        if LEGACY_META_FILE.exists():
            try:
                with open(LEGACY_META_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._save_meta(data)
                return data
            except Exception:
                pass
        return {}

    def _save_meta(self, meta: dict):
        try:
            META_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(META_FILE, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("메타 저장 실패: %s\n%s", e, traceback.format_exc())

    def load_sessions(self, show_archived: bool) -> List[BaseSession]:
        if not CLAUDE_PROJECTS_DIR.exists():
            return []
        sessions: List[BaseSession] = []
        meta = self._load_meta()

        for proj_dir in CLAUDE_PROJECTS_DIR.iterdir():
            if not proj_dir.is_dir():
                continue
            if show_archived:
                target_dir = proj_dir / "archived"
                if target_dir.is_dir():
                    for f in target_dir.glob("*.jsonl"):
                        s = ClaudeSession(f, is_archived=True)
                        if len(s.messages) <= 1:
                            continue
                        if s.session_id in meta:
                            s.summary = meta[s.session_id]
                        sessions.append(s)
            else:
                for f in proj_dir.glob("*.jsonl"):
                    s = ClaudeSession(f, is_archived=False)
                    if len(s.messages) <= 1:
                        continue
                    if s.session_id in meta:
                        s.summary = meta[s.session_id]
                    sessions.append(s)

        sessions.sort(key=lambda x: x.date_str, reverse=True)
        return sessions

    def archive_session(self, s: BaseSession) -> None:
        archive_dir = s.file_path.parent / "archived"
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s.file_path), str(archive_dir / s.file_path.name))

    def restore_session(self, s: BaseSession) -> None:
        active_dir = s.file_path.parent.parent
        shutil.move(str(s.file_path), str(active_dir / s.file_path.name))

    def delete_session(self, s: BaseSession) -> None:
        s.file_path.unlink()

    def find_empty_sessions(self) -> List[Path]:
        """UUID 파일명이고 messages <= 1 인 세션 파일 목록을 반환한다."""
        if not CLAUDE_PROJECTS_DIR.exists():
            return []
        result: List[Path] = []
        for proj_dir in CLAUDE_PROJECTS_DIR.iterdir():
            if not proj_dir.is_dir():
                continue
            # 일반 세션 + archived 세션 모두 탐색
            for search_dir in [proj_dir, proj_dir / "archived"]:
                if not search_dir.is_dir():
                    continue
                for f in search_dir.glob("*.jsonl"):
                    if not _UUID_RE.match(f.stem):
                        continue  # last-prompt, file-history-snapshot 등 시스템 파일 제외
                    s = ClaudeSession(f, is_archived=False)
                    if len(s.messages) <= 1:
                        result.append(f)
        return result

    def rename_session(self, s: BaseSession, new_title: str) -> None:
        meta = self._load_meta()
        meta[s.session_id] = new_title
        self._save_meta(meta)

    def save_ai_summary(self, s: BaseSession, title: str) -> None:
        self.rename_session(s, title)

    def get_resume_command(self, s: BaseSession) -> str:
        if os.name == "nt":
            return f'cd /d "{s.cwd}" && claude --resume "{s.session_id}"'
        safe_cwd = shlex.quote(s.cwd)
        safe_id = shlex.quote(s.session_id)
        return f'cd {safe_cwd} && claude --resume {safe_id}'

    def get_new_session_command(self, cwd: str) -> str:
        if os.name == "nt":
            return f'cd /d "{cwd}" && claude'
        safe_cwd = shlex.quote(cwd)
        return f'cd {safe_cwd} && claude'

    def run_ai_summary(self, prompt: str) -> str:
        # 지시사항을 맨 앞에 배치하고 길이를 제한하여 모델의 엉뚱한 답변 방지
        instruct = "아주 짧은 채팅방 제목(6단어 이하, 한국어로)으로 요약해줘. 제목만 출력: "
        prompt = instruct + prompt[:1500]

        env = {**os.environ}
        env.update({
            "CI": "true",
            "TERM": "dumb",
            "NO_COLOR": "1",
            "GIT_TERMINAL_PROMPT": "0",
        })

        if os.name == "nt":
            env["_CLAUDE_PROMPT"] = prompt
            cmd = [
                "powershell", "-NoProfile", "-Command",
                'claude -p "$env:_CLAUDE_PROMPT" --output-format text --no-session-persistence --tools "" --dangerously-skip-permissions',
            ]
            result = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )
        else:
            claude_bin = shutil.which("claude")
            if not claude_bin:
                local_bin = Path.home() / ".local/bin/claude"
                if local_bin.exists():
                    claude_bin = str(local_bin)
                else:
                    nvm_bins = Path.home().glob(".nvm/versions/node/*/bin/claude")
                    candidate = next(nvm_bins, None)
                    claude_bin = str(candidate) if candidate else "claude"

            # 인자 방식으로 복구 (stdin 방식에서 컨텍스트 무시 문제 발생)
            cmd = [claude_bin, "-p", prompt, "--output-format", "text", "--no-session-persistence", "--tools", "", "--dangerously-skip-permissions"]
            result = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=60,
                start_new_session=True,
                env=env,
            )

        if result.returncode != 0:
            logger.error("Claude AI 요약 실패 (exit code %d). stdout: %s, stderr: %s", result.returncode, result.stdout.strip(), result.stderr.strip())
            return ""

        output = result.stdout.strip()
        if output:
            # 여러 줄 응답 시 첫 번째 의미 있는 줄만 추출
            lines = [line.strip() for line in output.split("\n") if line.strip()]
            if lines:
                # 사족 제거 (예: "대화 내용을 분석한 결과:", "제안 제목:", "제목:")
                first_line = lines[0]
                remove_prefixes = ["대화 내용을 분석한 결과:", "제안 제목:", "제목:", "**제안 제목:**", "**제목:**"]
                for p_fix in remove_prefixes:
                    if first_line.startswith(p_fix):
                        first_line = first_line[len(p_fix):].strip()
                        break

                # 만약 첫 줄이 비어버리면 다음 줄 시도 (또는 "제안 제목:" 바로 뒤에 있는 경우)
                if (not first_line or len(first_line) < 2) and len(lines) > 1:
                    first_line = lines[1]
                    for p_fix in remove_prefixes:
                        if first_line.startswith(p_fix):
                            first_line = first_line[len(p_fix):].strip()
                            break
                
                # 특수문자 제거: 따옴표, 마크다운 별표 등
                first_line = first_line.strip().strip('"').strip("'").strip("*").strip()
                output = first_line[:100]  # 너무 길면 자름

        if not output:
            logger.error(
                "Claude AI 요약 실패 - stdout 비어있음. stderr: %s", result.stderr[:500])
        return output

    def get_workspaces(self, exclude_cwd: str) -> List[Tuple[str, Any]]:
        ws_map: dict = {}
        if not CLAUDE_PROJECTS_DIR.exists():
            return []
        for proj_dir in CLAUDE_PROJECTS_DIR.iterdir():
            if not proj_dir.is_dir():
                continue
            for f in proj_dir.glob("*.jsonl"):
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        for raw in fp:
                            raw = raw.strip()
                            if not raw:
                                continue
                            obj = json.loads(raw)
                            cwd = obj.get("cwd", "")
                            if cwd and cwd != exclude_cwd:
                                ws_map[cwd] = proj_dir
                            if cwd:
                                break
                except Exception:
                    pass
                break
        return [(cwd, proj_dir) for cwd, proj_dir in sorted(ws_map.items())]

    def move_copy_session(self, s: BaseSession, dest_cwd: str, move: bool) -> None:
        dest_proj_dir: Optional[Path] = None
        if CLAUDE_PROJECTS_DIR.exists():
            for proj_dir in CLAUDE_PROJECTS_DIR.iterdir():
                if not proj_dir.is_dir():
                    continue
                for f in proj_dir.glob("*.jsonl"):
                    try:
                        with open(f, "r", encoding="utf-8") as fp:
                            for raw in fp:
                                raw = raw.strip()
                                if not raw:
                                    continue
                                obj = json.loads(raw)
                                if obj.get("cwd", "") == dest_cwd:
                                    dest_proj_dir = proj_dir
                                break
                    except Exception:
                        pass
                    if dest_proj_dir:
                        break
                if dest_proj_dir:
                    break

        if not dest_proj_dir:
            if not Path(dest_cwd).is_dir():
                raise FileNotFoundError(f"존재하지 않는 경로: {dest_cwd}")
            # Claude 인코딩: '/' → '-', '.' → '-', 선두 '-' 추가
            encoded = dest_cwd.replace(
                "/", "-").replace(".", "-").replace("\\", "-")
            if not encoded.startswith("-"):
                encoded = "-" + encoded
            dest_proj_dir = CLAUDE_PROJECTS_DIR / encoded
            dest_proj_dir.mkdir(parents=True, exist_ok=True)

        if s.is_archived:
            target_dir = dest_proj_dir / "archived"
        else:
            target_dir = dest_proj_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        dest_file = target_dir / s.file_path.name

        # Rewrite jsonl to update cwd
        updated_lines = []
        try:
            with open(s.file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if "cwd" in obj:
                            obj["cwd"] = dest_cwd
                        updated_lines.append(json.dumps(obj, ensure_ascii=False))
                    except Exception:
                        updated_lines.append(line)
        except Exception as e:
            logger.error(f"Failed to read {s.file_path} during move/copy: {e}")
            raise

        with open(dest_file, "w", encoding="utf-8") as f:
            for line in updated_lines:
                f.write(line + "\n")

        if move and s.file_path != dest_file:
            os.remove(s.file_path)

    def is_available(self) -> bool:
        """
        Why: We use shutil.which for rapid availability checks instead of
        attempting to execute the binary and waiting for a subprocess timeout.
        This ensures the UI remains snappy during initial provider discovery.
        """
        if shutil.which("claude"):
            return True
        return CLAUDE_PROJECTS_DIR.exists()

    def get_version(self) -> str:
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                ver = (result.stdout.strip() or result.stderr.strip())
                return ver[:30] if ver else "사용 가능"
            return "사용 불가"
        except Exception:
            return "사용 불가"


class GeminiProvider(BaseProvider):
    name = "Gemini CLI"
    short_name = "gemini"
    color = "cyan"

    def _get_base_dir(self) -> str:
        gemini_home = os.environ.get(
            "GEMINI_CLI_HOME", str(Path.home() / ".gemini"))
        return os.environ.get("GEMINI_TMP_DIR", os.path.join(gemini_home, "tmp"))

    def load_sessions(self, show_archived: bool) -> List[BaseSession]:
        base_dir = self._get_base_dir()
        subdir = "archived" if show_archived else "chats"
        pattern = os.path.join(base_dir, "*", subdir, "*.json")
        files = glob.glob(pattern)

        sessions: List[BaseSession] = []
        for file in files:
            hash_dir = os.path.dirname(os.path.dirname(file))
            root_file = os.path.join(hash_dir, ".project_root")
            project_path = "Unknown"
            if os.path.exists(root_file):
                try:
                    with open(root_file, "r") as f:
                        project_path = f.read().strip()
                except Exception:
                    pass

            s = GeminiSession(Path(file), project_path, show_archived)
            if not s.session_id or len(s.messages) <= 1:
                continue
            sessions.append(s)

        sessions.sort(key=lambda x: x.date_str, reverse=True)
        return sessions

    def archive_session(self, s: BaseSession) -> None:
        archive_dir = s.file_path.parent.parent / "archived"
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s.file_path), str(archive_dir / s.file_path.name))

    def restore_session(self, s: BaseSession) -> None:
        chats_dir = s.file_path.parent.parent / "chats"
        chats_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s.file_path), str(chats_dir / s.file_path.name))

    def delete_session(self, s: BaseSession) -> None:
        s.file_path.unlink()

    def rename_session(self, s: BaseSession, new_title: str) -> None:
        if not isinstance(s, GeminiSession):
            raise TypeError(
                f"GeminiProvider.rename_session expects GeminiSession, got {type(s).__name__}")
        s.data["summary"] = new_title
        with open(s.file_path, "w", encoding="utf-8") as f:
            json.dump(s.data, f, ensure_ascii=False, indent=2)

    def save_ai_summary(self, s: BaseSession, title: str) -> None:
        self.rename_session(s, title)

    def get_resume_command(self, s: BaseSession) -> str:
        if os.name == "nt":
            return f'cd /d "{s.cwd}" && gemini --resume "{s.session_id}"'
        safe_cwd = shlex.quote(s.cwd)
        safe_id = shlex.quote(s.session_id)
        return f'cd {safe_cwd} && gemini --resume {safe_id}'

    def get_new_session_command(self, cwd: str) -> str:
        if os.name == "nt":
            return f'cd /d "{cwd}" && gemini'
        safe_cwd = shlex.quote(cwd)
        return f'cd {safe_cwd} && gemini'

    def run_ai_summary(self, prompt: str) -> str:
        # 지시사항을 맨 앞에 배치하고 길이를 제한하여 모델의 엉뚱한 답변 방지
        instruct = "아주 짧은 채팅방 제목(6단어 이하, 한국어로)으로 요약해줘. 제목만 출력: "
        prompt = instruct + prompt[:1500]
        
        env = {**os.environ}
        env.update({
            "CI": "true",
            "TERM": "dumb",
            "NO_COLOR": "1",
            "GIT_TERMINAL_PROMPT": "0",
        })
        if os.name == "nt":
            env["_GEMINI_PROMPT"] = prompt
            cmd = [
                "powershell", "-NoProfile", "-Command",
                'gemini -p "$env:_GEMINI_PROMPT" -m "gemini-2.5-flash-lite" -o text --yolo',
            ]
            result = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )
        else:
            gemini_bin = shutil.which("gemini")
            if not gemini_bin:
                local_bin = Path.home() / ".local/bin/gemini"
                if local_bin.exists():
                    gemini_bin = str(local_bin)
                else:
                    nvm_bins = Path.home().glob(".nvm/versions/node/*/bin/gemini")
                    candidate = next(nvm_bins, None)
                    gemini_bin = str(candidate) if candidate else "gemini"

            # Gemini CLI는 --tools 옵션을 지원하지 않으므로 제거
            cmd = [gemini_bin, "-p", prompt, "-m", "gemini-2.5-flash-lite", "-o", "text", "--yolo"]
            result = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=60,
                start_new_session=True,
                env=env,
            )

        if result.returncode != 0:
            logger.error("Gemini AI 요약 실패 (exit code %d). stdout: %s, stderr: %s", result.returncode, result.stdout.strip(), result.stderr.strip())
            return ""

        output = result.stdout.strip()
        if output:
            # 여러 줄 응답 시 첫 번째 의미 있는 줄만 추출
            lines = [line.strip() for line in output.split("\n") if line.strip()]
            if lines:
                # 사족 제거 (예: "대화 내용을 분석한 결과:", "제안 제목:", "제목:")
                first_line = lines[0]
                remove_prefixes = ["대화 내용을 분석한 결과:", "제안 제목:", "제목:", "**제안 제목:**", "**제목:**"]
                for p_fix in remove_prefixes:
                    if first_line.startswith(p_fix):
                        first_line = first_line[len(p_fix):].strip()
                        break

                # 만약 첫 줄이 비어버리면 다음 줄 시도 (또는 "제안 제목:" 바로 뒤에 있는 경우)
                if (not first_line or len(first_line) < 2) and len(lines) > 1:
                    first_line = lines[1]
                    for p_fix in remove_prefixes:
                        if first_line.startswith(p_fix):
                            first_line = first_line[len(p_fix):].strip()
                            break
                
                # 특수문자 제거: 따옴표, 마크다운 별표 등
                first_line = first_line.strip().strip('"').strip("'").strip("*").strip()
                output = first_line[:100]  # 너무 길면 자름

        if not output:
            logger.error(
                "Gemini AI 요약 실패 - stdout 비어있음. stderr: %s", result.stderr[:500])
        return output

    def get_workspaces(self, exclude_cwd: str) -> List[Tuple[str, Any]]:
        base_dir = self._get_base_dir()
        workspaces: List[str] = []
        for root_file in glob.glob(os.path.join(base_dir, "*", ".project_root")):
            try:
                with open(root_file, "r") as f:
                    path = f.read().strip()
                if path and path != exclude_cwd:
                    workspaces.append(path)
            except Exception:
                pass
        return [(w, w) for w in sorted(set(workspaces))]

    def move_copy_session(self, s: BaseSession, dest_cwd: str, move: bool) -> None:
        base_dir = self._get_base_dir()
        dest_tmp: Optional[str] = None
        for root_file in glob.glob(os.path.join(base_dir, "*", ".project_root")):
            try:
                with open(root_file, "r") as f:
                    if f.read().strip() == dest_cwd:
                        dest_tmp = os.path.dirname(root_file)
                        break
            except Exception:
                pass

        if not dest_tmp:
            if not Path(dest_cwd).is_dir():
                raise FileNotFoundError(f"존재하지 않는 경로: {dest_cwd}")
            base_name = Path(dest_cwd).name
            dest_tmp = os.path.join(base_dir, base_name)
            counter = 1
            while os.path.exists(dest_tmp):
                dest_tmp = os.path.join(base_dir, f"{base_name}-{counter}")
                counter += 1
            os.makedirs(os.path.join(dest_tmp, "chats"), exist_ok=True)
            with open(os.path.join(dest_tmp, ".project_root"), "w") as f:
                f.write(dest_cwd)

        dest_chats = Path(dest_tmp) / "chats"
        dest_chats.mkdir(parents=True, exist_ok=True)
        dest_file = dest_chats / s.file_path.name

        if move:
            shutil.move(str(s.file_path), str(dest_file))
        else:
            shutil.copy2(str(s.file_path), str(dest_file))

    def is_available(self) -> bool:
        """
        Why: Fast availability determination using shutil.which and
        directory existence checks to avoid slow CLI calls during startup.
        """
        if shutil.which("gemini"):
            return True
        # gemini는 zsh 함수로 정의되기도 하므로, 빠른 판별을 위해 base_dir 존재 여부를 체크
        return Path(self._get_base_dir()).exists()

    def get_version(self) -> str:
        # 먼저 바이너리 직접 실행 시도 (빠름)
        try:
            result = subprocess.run(
                ["gemini", "--version"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                ver = (result.stdout.strip() or result.stderr.strip())
                return ver[:30] if ver else "사용 가능"
        except Exception:
            pass
        # 직접 실행 실패 시 zsh 함수로 정의된 경우 폴백 (zsh -ic: .zshrc 소싱)
        try:
            result = subprocess.run(
                ["zsh", "-ic", "gemini --version"],
                stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=10,
                start_new_session=True,
            )
            if result.returncode == 0:
                ver = (result.stdout.strip() or result.stderr.strip())
                return ver[:30] if ver else "사용 가능"
            return "사용 불가"
        except Exception:
            return "사용 불가"
