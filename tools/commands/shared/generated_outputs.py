"""Compatibility alias for :mod:`snes_tooling.shared.generated_outputs`."""

from __future__ import annotations

import importlib
import sys


_IMPLEMENTATION = importlib.import_module("snes_tooling.shared.generated_outputs")
if __name__ == "__main__" and hasattr(_IMPLEMENTATION, "main"):
    raise SystemExit(_IMPLEMENTATION.main())
sys.modules[__name__] = _IMPLEMENTATION
