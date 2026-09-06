"""Compatibility alias for :mod:`snes_tooling.shared.validate_gsu_cache_kernels`."""

from __future__ import annotations

import importlib
import sys


if __name__ == "__main__":
    import subprocess
    from pathlib import Path

    _TOOLING_ROOT = Path(__file__).resolve().parents[2]
    _SIBLING_PACKAGE = _TOOLING_ROOT / "snes_tooling"
    if _SIBLING_PACKAGE.is_dir():
        sys.path.insert(0, str(_TOOLING_ROOT))
        _IMPLEMENTATION = importlib.import_module(
            f"snes_tooling.shared.{Path(__file__).stem}"
        )
        raise SystemExit(_IMPLEMENTATION.main())
    _WORKSPACE = Path(__file__).resolve().parents[3]
    _RESULT = subprocess.run(
        [
            sys.executable,
            str(_WORKSPACE / "tools" / "snes_tooling_compat.py"),
            "validate-gsu-cache-kernels",
            sys.argv[0],
            *sys.argv[1:],
        ],
        check=False,
    )
    raise SystemExit(_RESULT.returncode)

_IMPLEMENTATION = importlib.import_module(
    "snes_tooling.shared.validate_gsu_cache_kernels"
)
sys.modules[__name__] = _IMPLEMENTATION
