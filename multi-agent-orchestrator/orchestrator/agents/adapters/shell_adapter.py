from __future__ import annotations

"""
Shell and CLI Execution Utilities for Agent Adapters.

This module provides the core primitives for spawning and managing asynchronous
subprocess executions. It includes support for single command execution,
pipelined commands (cmd1 | cmd2), and real-time output streaming for logging.
These utilities ensure that all CLI-based agents share a consistent
timeout, error handling, and encoding-resilient IO strategy.
"""

import asyncio
import os
import shlex
import time
from pathlib import Path
from typing import Optional, Callable, Tuple, List

from orchestrator.core.models import AgentResult


async def execute_cli_pipeline(
    commands: List[List[str]],
    input_data: Optional[str] = None,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    timeout: int = 120,
    on_log: Optional[Callable[[str], None]] = None
) -> Tuple[int, str, str]:
    """
    Asynchronous execution of a pipeline of CLI commands, e.g. cmd1 | cmd2.
    
    This is used when an agent's logic requires chaining tools where the
    output of one is the direct input of another, minimizing memory overhead
    by using OS-level pipes instead of intermediate python strings.
    """
    if not commands:
        return 0, "", ""

    processes = []

    # Create processes and link them
    for i, cmd in enumerate(commands):
        # We quote arguments for logging safety to ensure the logged command
        # is copy-pasteable even if it contains spaces or special characters.
        safe_command_str = " ".join(shlex.quote(str(arg)) for arg in cmd)
        if on_log:
            on_log(f"$ {safe_command_str}" +
                   (" | " if i < len(commands) - 1 else ""))

        # Linking stdin: 
        # - The first process gets the user provided input_data.
        # - Subsequent processes get the stdout of the previous process.
        stdin = (
            asyncio.subprocess.PIPE if i == 0 and input_data is not None
            else (processes[-1].stdout if i > 0
                  else asyncio.subprocess.DEVNULL)
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=stdin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env
        )
        processes.append(proc)

    stdout_chunks = []
    stderr_chunks = []

    async def read_stream(
        stream: asyncio.StreamReader, chunks_list: list,
        is_stderr: bool = False, prefix: str = ""
    ):
        """Reads a stream line-by-line to enable real-time UI updates."""
        if not stream:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            # We use 'replace' to ensure that binary or corrupted output from
            # a tool doesn't crash the entire orchestration loop.
            text = line.decode('utf-8', errors='replace')
            chunks_list.append(prefix + text)
            if on_log:
                on_log((prefix + text).rstrip('\n'))

    tasks = []
    # Read stdout of ONLY the last process in the pipeline.
    if processes[-1].stdout:
        tasks.append(
            asyncio.create_task(
                read_stream(processes[-1].stdout, stdout_chunks)
            )
        )

    # Read stderr of ALL processes to capture errors at any stage of the pipe.
    for i, proc in enumerate(processes):
        prefix = f"[{i}] " if len(processes) > 1 else ""
        if proc.stderr:
            tasks.append(
                asyncio.create_task(
                    read_stream(proc.stderr, stderr_chunks, True, prefix)
                )
            )

    if input_data is not None and processes[0].stdin is not None:
        processes[0].stdin.write(input_data.encode('utf-8'))
        processes[0].stdin.close()
        try:
            await processes[0].stdin.wait_closed()
        except Exception:
            # Some processes close stdin early if they finish quickly; 
            # we ignore errors here to prevent pipeline failure.
            pass

    try:
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout)
        for proc in processes:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        # Crucial: Kill all processes in the pipeline on timeout to avoid
        # zombie processes or leaked resources.
        for proc in processes:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        raise TimeoutError(
            f"Pipeline execution timed out after {timeout} seconds"
        )

    # Use the return code of the last process as the overall success indicator.
    returncode = (
        processes[-1].returncode if processes[-1].returncode is not None
        else -1
    )
    return (
        returncode,
        "".join(stdout_chunks).strip(),
        "".join(stderr_chunks).strip()
    )


async def execute_cli(
    command: List[str],
    input_data: Optional[str] = None,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    timeout: int = 120,
    on_log: Optional[Callable[[str], None]] = None
) -> Tuple[int, str, str]:
    """
    Asynchronous execution of a CLI command with real-time logging.
    
    This is the primary execution engine for most agent adapters. It manages
    the full lifecycle of the process, including input feeding, output
    streaming, and strict timeout enforcement.
    """
    # Quote for logging to ensure clarity in the orchestrator diagnostics.
    safe_command_str = " ".join(shlex.quote(str(arg)) for arg in command)
    if on_log:
        on_log(f"$ {safe_command_str}")

    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=(
            asyncio.subprocess.PIPE if input_data is not None
            else asyncio.subprocess.DEVNULL
        ),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env
    )

    stdout_chunks = []
    stderr_chunks = []

    async def read_stream(
        stream: asyncio.StreamReader,
        chunks_list: list,
        is_stderr: bool = False
    ):
        while True:
            line = await stream.readline()
            if not line:
                break
            # Handle non-UTF-8 output gracefully.
            text = line.decode('utf-8', errors='replace')
            chunks_list.append(text)
            if on_log:
                on_log(text.rstrip('\n'))

    tasks = [
        asyncio.create_task(
            read_stream(process.stdout, stdout_chunks, False)
        ),
        asyncio.create_task(
            read_stream(process.stderr, stderr_chunks, True)
        )
    ]

    if input_data is not None and process.stdin is not None:
        process.stdin.write(input_data.encode('utf-8'))
        process.stdin.close()
        try:
            await process.stdin.wait_closed()
        except Exception:
            pass

    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout)
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        raise TimeoutError(
            f"Command execution timed out after {timeout} seconds"
        )

    returncode = (
        process.returncode if process.returncode is not None else -1
    )
    return (
        returncode,
        "".join(stdout_chunks).strip(),
        "".join(stderr_chunks).strip()
    )


class ShellAgentAdapter:
    """
    A generic adapter that executes arbitrary external scripts.
    
    This allows users to extend the orchestrator with their own custom agents
    written in any language, provided they adhere to the standard stdin/stdout
    protocol.
    """

    def __init__(
        self, script_path: str, agent_name: str,
        timeout: int = 120, model: str | None = None
    ) -> None:
        self.script_path = Path(script_path)
        self.agent_name = agent_name
        self.timeout = timeout
        self.model = model
        # Pre-check execution permissions to fail fast during initialization.
        self.available = (
            self.script_path.exists() and
            os.access(self.script_path, os.X_OK)
        )

    def is_available(self) -> bool:
        """Indicates if the target script exists and is executable."""
        return self.available

    async def ask(
        self, prompt: str, on_log: Optional[Callable[[str], None]] = None
    ) -> AgentResult:
        """Executes the script for a primary completion task."""
        if not self.is_available():
            return AgentResult(
                self.agent_name, False, "",
                f"Script not found or not executable: {self.script_path}",
                -1, 0
            )
        return await self._run(prompt, on_log)

    async def review(
        self, user_prompt: str, peer_answer: str, review_prompt: str,
        on_log: Optional[Callable[[str], None]] = None
    ) -> AgentResult:
        """Executes the script for a review task."""
        if not self.is_available():
            return AgentResult(
                self.agent_name, False, "",
                f"Script not found or not executable: {self.script_path}",
                -1, 0
            )
        return await self._run(review_prompt, on_log)

    async def _run(
        self, prompt: str, on_log: Optional[Callable[[str], None]] = None
    ) -> AgentResult:
        """
        Subprocess execution logic.
        
        The script is called with its absolute path. The prompt is fed via
        stdin, and we optionally pass '--model' if a specific model was
        requested for this agent instance.
        """
        started = time.perf_counter()

        env = os.environ.copy()

        script_arg = str(self.script_path.resolve())
        command = [script_arg]
        if self.model:
            command.extend(["--model", self.model])

        try:
            returncode, stdout, stderr = await execute_cli(
                command=command,
                input_data=prompt,
                cwd=str(Path(os.getcwd()).resolve()),
                env=env,
                timeout=self.timeout,
                on_log=on_log
            )

            ok = (returncode == 0) and bool(stdout)

            return AgentResult(
                agent_name=self.agent_name,
                ok=ok,
                stdout=stdout,
                stderr=stderr,
                returncode=returncode,
                duration_ms=int((time.perf_counter() - started) * 1000)
            )

        except TimeoutError as e:
            return AgentResult(
                self.agent_name, False, "", str(e), -1,
                int((time.perf_counter() - started) * 1000)
            )
        except Exception as e:
            return AgentResult(
                self.agent_name, False, "", str(e), -1,
                int((time.perf_counter() - started) * 1000)
            )
