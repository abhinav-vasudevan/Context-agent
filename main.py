"""
Context Agent — Main Entry Point

Starts the FastAPI backend server.
For the CLI interface, use: python cli.py
"""

import sys
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent))

from backend.server import main

if __name__ == "__main__":
    main()
