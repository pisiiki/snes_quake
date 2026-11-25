# License scope and third-party notices

## Project-license scope

The [project MIT License](../LICENSE) applies to the independently authored
source code, build and validation tooling, and original prose documentation.
This includes the project's original code embodied in the cartridge. Quake
content, screenshots, videos, trademarks, and third-party dependencies retain
their respective terms. The assembled cartridge combines components under
those separate terms. This is an unofficial Quake project.

## Quake shareware 1.06

The bundled `third_party/quake106/quake106.zip` is the complete, unmodified
Quake 1.06 shareware distribution. It is 9,094,045
bytes and has SHA-256
`ec6c9d34b1ae0252ac0066045b6611a7919c2a0d78a3a66d9387a8f597553239`.
The original `SLICNSE.TXT` and `README.TXT` are inside the archive.

The original Quake game data is copyrighted by id Software. The shareware
terms apply to that data. The release screenshots, videos, and generated
runtime data use the original Quake content.

## libSFX and cc65

The standalone build fetches [libSFX](https://github.com/Optiroc/libSFX/tree/61b3ea97e398333c1b7a6f62a53f1112fdfb6070)
at `61b3ea97e398333c1b7a6f62a53f1112fdfb6070`. Its
[cc65 build dependency](https://github.com/cc65/cc65/tree/cc3c40c54e51b2d9a22b63c85c418a2b11763377)
is pinned to `cc3c40c54e51b2d9a22b63c85c418a2b11763377` and uses the
[upstream zlib license](https://github.com/cc65/cc65/blob/cc3c40c54e51b2d9a22b63c85c418a2b11763377/LICENSE).

[`Map.cfg`](../src/snes_quake/Map.cfg) and
[`libSFX.cfg`](../src/snes_quake/libSFX.cfg) adapt libSFX configuration
templates. The [upstream MIT notice](https://github.com/Optiroc/libSFX/blob/61b3ea97e398333c1b7a6f62a53f1112fdfb6070/LICENSE)
is reproduced below.

```text
The MIT License (MIT)

Copyright (c) 2015-2017 David Lindecrantz

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Python build dependencies

The standalone `requirements.txt` pins build-time
[NumPy 2.3.5](https://pypi.org/project/numpy/2.3.5/) and
[Pillow 12.0.0](https://pypi.org/project/pillow/12.0.0/) by hash. They retain
their upstream BSD-3-Clause and MIT-CMU licenses respectively.
