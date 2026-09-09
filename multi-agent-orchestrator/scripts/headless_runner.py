#!/usr/bin/env python3
"""
Headless Runner for Sovereign Workstation Missions.

This script provides a non-interactive entry point for running orchestration
missions directly from the command line, bypassing the Textual TUI. It is
intended for testing, automation, and integration purposes.
"""
import os
import sys
import asyncio
import argparse
from pathlib import Path

# Ensure the project root is in the Python path for absolute imports.
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from orchestrator.tui.controller import TUIController
from orchestrator.core.models import DeploymentUnit, ExecutionMode
from orchestrator.agents.swarm import run_swarm_logic
from orchestrator.core.logger import get_logger, setup_logging
import logging

# Explicitly configure logging for headless script
setup_logging()
logging.getLogger().setLevel(logging.DEBUG)

logger = get_logger("headless_runner")


async def run_mission(args):
    """
    Sets up and executes a single mission based on parsed CLI arguments.
    """
    logger.info(f"--- Starting Headless Mission: {args.mission} ---")
    try:
        # The TUIController is still needed to manage state and settings.
        logger.debug("Initializing TUIController...")
        controller = TUIController()
        controller.is_interactive = False
        logger.debug("Running preflight checks...")
        controller.run_preflight()
        logger.debug("Discovering resources...")
        controller.discover_resources()
        logger.debug("Controller setup complete.")

        # Parse deployment units from arguments.
        unit_personas = [u.strip() for u in args.units.split(',')]
        unit_engines = [e.strip() for e in args.engines.split(',')]
        
        deployment_units = []
        for i, persona in enumerate(unit_personas):
            engine = unit_engines[i] if i < len(unit_engines) else unit_engines[-1]
            deployment_units.append(DeploymentUnit(persona=persona, engine=engine))

        logger.info(f"Deployment Units: {deployment_units}")
        
        execution_mode = ExecutionMode(args.mode)
        logger.info(f"Execution Mode: {execution_mode}")

        # Execute the core swarm logic.
        logger.debug("Executing run_swarm_logic...")
        await run_swarm_logic(
            controller=controller,
            user_prompt=args.mission,
            deployment_units=deployment_units,
            judge_agent="judge",
            auditor_agent="auditor",
            execution_mode=execution_mode,
            history_context=""  # No history context for simple headless runs
        )
        logger.info("run_swarm_logic completed.")

    except Exception as e:
        logger.exception(f"CRITICAL: un_mission failed with an unhandled exception: {e}")
    finally:
        logger.info(f"--- Headless Mission Finished ---")


def main():
    """
    Parses arguments and starts the asyncio event loop.
    """
    parser = argparse.ArgumentParser(
        description="Run a non-interactive Sovereign Workstation mission."
    )
    parser.add_argument(
        "-m", "--mission",
        required=True,
        help="The user prompt or mission description."
    )
    parser.add_argument(
        "-u", "--units",
        required=True,
        help="Comma-separated list of personas for the deployment units (e.g., 'engineer,architect')."
    )
    parser.add_argument(
        "-e", "--engines",
        default="gemini",
        help="Comma-separated list of engines corresponding to the units (e.g., 'gemini,claude')."
    )
    parser.add_argument(
        "--mode",
        choices=[e.value for e in ExecutionMode],
        default=ExecutionMode.PARALLEL.value,
        help="The execution mode for the swarm."
    )

    args = parser.parse_args()
    
    try:
        asyncio.run(run_mission(args))
    except KeyboardInterrupt:
        logger.info("Headless run cancelled by user.")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"An unhandled error occurred during the headless run: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
