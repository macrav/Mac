#!/usr/bin/env python3
"""Conector MCP TechMaC (stdio). Lo arranca Claude según .mcp.json."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from techmac.mcp_server import main  # noqa: E402

if __name__ == "__main__":
    main()
