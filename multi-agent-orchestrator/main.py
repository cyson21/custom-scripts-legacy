#!/usr/bin/env python3
"""
Sovereign Workstation Root Entry Point.
This is a lightweight wrapper that delegates execution to scripts/main.py.
"""
import os
import sys

# Ensure the project root is in sys.path so modules can be imported absolutely
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scripts.main import main

if __name__ == "__main__":
    main()
