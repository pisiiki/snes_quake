# License scope and third-party notices

## Project-license scope

The MIT License in `LICENSE` applies only to the independently authored source
code, build and validation tooling, and original prose documentation in this
repository.

It does not relicense Quake, the contents of `third_party/quake106/`, extracted or generated
Quake game data, Quake-derived images or video, trademarks, the assembled ROM
as a whole, or third-party dependencies. The MIT License continues to apply to
the project's original code embodied in the ROM, while every third-party
component and asset remains subject to its own terms.

This is an unofficial project and is not affiliated with or endorsed by id
Software.

## Quake shareware 1.06

`third_party/quake106/quake106.zip` is the complete, unmodified shareware distribution
(9094045 bytes; SHA-256 `ec6c9d34b1ae0252ac0066045b6611a7919c2a0d78a3a66d9387a8f597553239`). Its original
`SLICNSE.TXT` and `README.TXT` are extracted beside it for convenient review.
Quake game data remains copyrighted by id Software; those terms are not
replaced by the source-code licenses in this repository.
The linked replay video is rendered from those shareware game-data assets and
is distributed subject to the same third-party terms.

## libSFX

`third_party/libSFX` is a Git submodule from `https://github.com/Optiroc/libSFX.git`, pinned to
`61b3ea97e398333c1b7a6f62a53f1112fdfb6070`. Its own license and recursively pinned build dependencies
remain in their upstream repositories. Only its cc65 submodule is initialized;
that source is pinned to `cc3c40c54e51b2d9a22b63c85c418a2b11763377` from `https://github.com/cc65/cc65.git`.

`src/snes_quake/Map.cfg` and `src/snes_quake/libSFX.cfg` are adapted from
libSFX configuration templates. Copyright (c) 2015-2017 David Lindecrantz;
used under the MIT License in `third_party/libSFX/LICENSE`.

## cc65

cc65 is used as build tooling through libSFX's pinned submodule and remains
under its upstream zlib License, available in `third_party/libSFX/tools/cc65/LICENSE` after
the recursive dependency is initialized.

## Modern BSP inputs

`third_party/quake-map-source` contains the official map-source archive used by
the configured build. `third_party/ericw-tools` supplies QBSP, VIS, LIGHT, and
BSP inspection tooling. `third_party/vcpkg` supplies their pinned native build
dependencies. Each is a Git submodule whose repository URL and full commit are
declared in `config/rom-config.json`; the release preflight rejects any
checkout that differs from that config. Their own licenses and the Quake map
source terms remain authoritative and are not replaced by this project's MIT
License.

NumPy 2.3.5 and Pillow
12.0.0 are build-time Python dependencies,
installed separately from the hashes in `tools/requirements-build.txt`. They remain
under their upstream BSD-3-Clause and MIT-CMU licenses respectively and are not
copied into this repository.
