"""Generate the palette-preserving runtime asset view and assembled renderer copies."""
import argparse
import json
from pathlib import Path
import time

from snes_tooling import Workspace
from snes_tooling.quake import quake_fly3x_codegen, quake_warp_assets, quake_warp_focal_codegen
from snes_tooling.quake.quake_release_layout import resolve_input


def generate(example, *, check=False, config=None, background_config=None):
    """Generate the existing runtime assets with workspace or release inputs."""
    started = time.perf_counter()
    example = example.resolve()
    root = example.parents[1]
    background_config = background_config or resolve_input(root, Path('config/warp-background.json'))
    assets = quake_warp_assets.generate(example, background_config, check=check)
    focal = quake_warp_focal_codegen.generate(example, check=check, config=config)
    # Alternate source-focal builds still validate the archive's own bindings.
    from snes_tooling.quake.quake_alias_visibility_projection import require_bindings
    visibility = json.loads((example/'Data/QuakeBSPAliasVisibility.json').read_text())
    archive = visibility['archive']
    require_bindings(archive, example/'Data', archive['bindings']['projections'][2]['focal'])
    copies = quake_fly3x_codegen.generate(example, check=check)
    return {'passed': True, 'assets': assets, 'focal': focal, 'rendererCopiesChanged': len(copies['changed']),
            'elapsedSeconds': round(time.perf_counter()-started, 3)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--example', type=Path, default=Workspace.discover().root/'src/snes_quake')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--config', type=Path, help='ROM configuration; default: asset-bound workspace config')
    args = parser.parse_args(argv)
    started = time.perf_counter()
    try:
        result = generate(args.example, check=args.check, config=args.config)
    except Exception as error:
        result = {'passed': False, 'error': str(error)}
    result['elapsedSeconds'] = round(time.perf_counter()-started, 3)
    print(json.dumps(result))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
