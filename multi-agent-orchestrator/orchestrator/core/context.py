"""
Architectural Role: Orchestration Runtime Context.
This module defines the 'living state' of a swarm mission. It acts as a shared 
blackboard where agents can read the current mission status, access tool results, 
and coordinate through hooks and locks.
"""
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from orchestrator.core.models import ConsensusResult, TurnResult
from orchestrator.core.hooks import HookManager

@dataclass
class OrchestrationContext:
    """
    Function: Shared state object for a single swarm execution.
    Why: By centralizing mission state in a context object, we can ensure that 
    parallel agents stay synchronized and that all modifications (diffs) are 
    tracked in a single, auditable memory structure.
    """
    artifact_dir: Path
    user_prompt: str = ""
    max_rounds: int = 2
    turns: list[TurnResult] = field(default_factory=list)
    consensus: ConsensusResult | None = None
    hooks: HookManager = field(default_factory=HookManager)
    
    # Why: diff_memory and execution_trace provide the 'long-term memory' 
    # of the session, enabling post-mortem reports and iterative refinements.
    diff_memory: list[dict] = field(default_factory=list)
    execution_trace: list[dict] = field(default_factory=list)
    
    # Why: sandbox_manager is held here to provide agents with a safe 
    # execution environment without tightly coupling the sandbox to the agents.
    sandbox_manager: Optional[object] = None
    
    # Why: The lock ensures that concurrent updates to shared resources 
    # (like file edits or state transitions) remain atomic and race-free.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
