"""Budget final sprite shader code while source variants retain resident pixels."""
from hashlib import sha256
import json
from pathlib import Path

from snes_tooling.quake.quake_alias_format import HEADER, MAGIC, VERSION, SPRITE_DIRECTORY

BEGIN = "; BEGIN playable sprite shader budget"
END = "; END playable sprite shader budget"
INCLUDE = "Data/PlayableSpriteBudget.i"


def prepare_source_budget(example, *, source_shader=None, shader_preamble=b""):
    example = Path(example)
    data = example / "Data"
    metadata = json.loads((data / "QuakeBSPAliasAssets.json").read_bytes())
    payload = (data / "QuakeBSPAliasRuntime0.bin").read_bytes()
    if len(payload) != 32768:
        raise ValueError("sprite shader source budget requires the original complete QBA control bank")
    header = HEADER.unpack_from(payload)
    count = metadata["format"]["chunkCount"]
    if (header[:3] != (MAGIC, VERSION, HEADER.size) or header[8] != count
            or type(count) is not int or not 0 < count < 128
            or header[10] < HEADER.size
            or header[10] + header[4] * SPRITE_DIRECTORY.size > len(payload)):
        raise ValueError("sprite shader source budget requires the original complete QBA control bank")
    for index in range(header[4]):
        sprite = SPRITE_DIRECTORY.unpack_from(payload, header[10] + index * SPRITE_DIRECTORY.size)
        if sprite[0] >= 0x70:
            raise ValueError("sprite shader source budget requires original resident pixel pointers")
    budget = ("; GSU-only source budget; all source sprite pixels remain resident.\n"
              ".ifndef __PLAYABLE_SPRITE_BUDGET_I__\n__PLAYABLE_SPRITE_BUDGET_I__ = 1\n"
              + ("PLAYABLE_SPRITE_STREAM = 1\n" if count > 1 else "")
              +
              f"SPRITE_STREAM_BANK_COUNT = {count}\n"
              "SPRITE_STREAM_BANK_RECORD_BYTES = 4\n.endif\n").encode("ascii")
    shader = example / "quake.sgs"
    original = shader_preamble + (source_shader or shader).read_bytes()
    newline = "\r\n" if b"\r\n" in original and b"\n" not in original.replace(b"\r\n", b"") else "\n"
    text = original.decode("utf-8")
    if text.startswith(BEGIN):
        finish = text.find(END)
        if finish < 0:
            raise ValueError("incomplete managed sprite shader source budget prefix")
        finish += len(END)
        if not text[finish:].startswith(newline):
            raise ValueError("sprite shader budget end marker requires its newline")
        text = text[finish + len(newline):]
    elif BEGIN in text or END in text:
        raise ValueError("sprite shader budget prefix must be at the source entry")
    prefix = newline.join((BEGIN, ".ifndef SPRITE_STREAM_BANK_COUNT", f'.include "{INCLUDE}"',
                           ".endif", END, ""))
    current = (prefix + text).encode("utf-8")
    for path, blob in ((example / INCLUDE, budget), (shader, current)):
        if not path.is_file() or path.read_bytes() != blob:
            path.write_bytes(blob)
    return dict(gsuOnly=True, residentSourcePixels=True, bankCount=count, streamingCode=count > 1,
                shaderSha256=sha256(current).hexdigest(), includeSha256=sha256(budget).hexdigest())
