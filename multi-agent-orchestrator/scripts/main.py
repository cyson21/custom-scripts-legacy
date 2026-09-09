#!/usr/bin/env python3
"""
Sovereign Workstation Entry Point.

This module serves as the primary bootstrap for the Sovereign Workstation CLI.
It handles environment initialization, project root path resolution for local
module imports, and the high-level application lifecycle.
"""
import os
import sys
import argparse
from orchestrator.core.logger import get_logger

logger = get_logger("root")


def main():
    """
    Initializes and runs the Sovereign Workstation CLI application.
    
    This function handles the critical setup of ensuring the project root is in 
    the Python path, which allows for consistent absolute imports across the 
    entire multi-agent orchestrator package regardless of how it's invoked.
    """
    parser = argparse.ArgumentParser(description="Sovereign Workstation Multi-Agent Orchestrator CLI")
    # Allowing it to parse and print help instead of dropping into interactive mode immediately if just requesting help
    parser.parse_args()

    # Why: We moved main.py to scripts/, so project root is now the parent directory.
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(scripts_dir)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    logger.info("--- Sovereign Workstation Started ---")

    try:
        from orchestrator.cli.app import run as run_cli
        run_cli()
    except ImportError as e:
        logger.error(f"Error: Unable to import CLI application. Details: {e}")
        print(
            "Error: Unable to import CLI application. "
            "Please check dependencies.",
            file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logger.exception("Uncaught crash in main loop")
        import traceback
        traceback.print_exc()
        print(
            "An unexpected error occurred. See orchestrator.log for details.",
            file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
