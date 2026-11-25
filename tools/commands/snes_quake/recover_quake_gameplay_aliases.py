"""Recover exact gameplay billboards from a production playable package."""
import os
import sys
from pathlib import Path

workspace = os.environ.get("SNES_WORKSPACE")
tools = Path(workspace).expanduser().resolve() / "tools" if workspace else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(tools))

from snes_tooling.quake.quake_gameplay_production_aliases import main

if __name__ == "__main__":
    raise SystemExit(main())
