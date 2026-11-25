"""Compatibility entry point for immutable playable gameplay inputs."""

import os
import sys
from pathlib import Path

# Shared editable installs can point at a different checkout.
workspace = os.environ.get("SNES_WORKSPACE")
tools = Path(workspace).expanduser().resolve() / "tools" if workspace else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(tools))

from snes_tooling.quake.export_quake_gameplay_assets import main

if __name__ == "__main__":
    raise SystemExit(main())
