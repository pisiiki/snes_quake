#!/usr/bin/env python3
"""Emit independently assembled fly3x renderer copies from the owned sources."""

from __future__ import annotations

from snes_tooling import Workspace

import argparse
import json
import re
import time
from pathlib import Path

from snes_tooling.shared.generated_outputs import GeneratedOutputError, OwnedFileFamily, sync_generated_outputs


COMMON = {"libSFX.i", "MemoryMap.i", "GSU_Cache.i", "GSU_Primitives.i", "quake/WarpFocalPatch.sgs"}
ROOTS = ("quake.sgs", "quake/FramePipeline.s")
INCLUDE = re.compile(r'^\s*\.include\s+"([^"]+)"', re.MULTILINE)
SEGMENT = re.compile(r'^(\s*\.segment\s+)"([^"]+)"', re.MULTILINE)
DEFINITION = re.compile(
    r"^[ \t]*(?:\.(?:macro|define)[ \t]+([A-Za-z_][\w]*)|"
    r"([A-Za-z_][\w]*)(?::|[ \t]*(?:=(?!=)|\.set\b)))",
    re.MULTILINE,
)
TOKENS = re.compile(r'("[^"\n]*"|;[^\n]*|\b[A-Za-z_][\w]*\b)')
GENERATED_INCLUDE = 'Data/Fly3x/'


def source_graph(example: Path) -> dict[Path, str]:
    sources: dict[Path, str] = {}

    def visit(path: Path) -> None:
        path = path.resolve()
        if path in sources:
            return
        text = path.read_text(encoding="utf-8")
        sources[path] = text
        for match in INCLUDE.finditer(text):
            name = match[1]
            if name in COMMON or name.startswith(GENERATED_INCLUDE):
                continue
            candidates = (path.parent / name, example / name)
            child = next((candidate for candidate in candidates if candidate.is_file()), None)
            if child is None:
                raise ValueError(f"unresolved renderer include: {path.name}: {name}")
            visit(child)

    for name in ROOTS:
        visit(example / name)
    return sources


def generate(example: Path, *, check: bool = False) -> dict[str, object]:
    started = time.perf_counter()
    example = example.resolve()
    sources = source_graph(example)
    names = {
        match[1] or match[2]
        for source in sources.values()
        for match in DEFINITION.finditer(source)
    }
    label_arguments: dict[str, list[int]] = {"GSU_CACHE_KERNEL_BEGIN": [0]}
    for source in sources.values():
        for macro in re.finditer(
            r"^\s*\.macro\s+(\w+)([^\n]*)\n(.*?)^\s*\.endmacro",
            source,
            re.MULTILINE | re.DOTALL,
        ):
            parameters = [part.strip().split()[0] for part in macro[2].split(",") if part.strip()]
            positions = [
                index for index, parameter in enumerate(parameters)
                if re.search(rf"^\s*{re.escape(parameter)}\s*:", macro[3], re.MULTILINE)
            ]
            if positions:
                label_arguments[macro[1]] = positions
    for source in sources.values():
        for line in source.splitlines():
            invocation = re.match(r"^\s*(\w+)\s+([^;]+)", line)
            if invocation and invocation[1] in label_arguments:
                arguments = [part.strip() for part in invocation[2].split(",")]
                for index in label_arguments[invocation[1]]:
                    argument = arguments[index]
                    if not re.fullmatch(r"[A-Za-z_]\w*", argument):
                        raise ValueError(f"unsupported generated label: {line.strip()}")
                    names.add(argument)
    # These override libSFX's instruction spellings in each root. Their
    # replacement macro bodies have distinct names in the generated copy.
    names.difference_update({"lm", "sm"})
    reserved = names & {"nop", "bra", "beq", "bne", "bcc", "bcs", "bpl", "bmi", "ret", "jmp", "jal"}
    if reserved:
        raise ValueError("instruction parsed as a declaration: " + ", ".join(sorted(reserved)))
    symbols = {name: f"F3_{name}" for name in names}
    symbols["UploadPresentDirect"] = "F3_UploadPresentDirect"
    segments = {
        match[2]
        for source in sources.values()
        for match in SEGMENT.finditer(source)
        if match[2].startswith("GSU")
    }
    for segment in segments:
        for suffix in ("LOAD", "RUN", "SIZE"):
            symbols[f"__{segment}_{suffix}__"] = f"__F3_{segment}_{suffix}__"
    changed = []
    output_root = example / GENERATED_INCLUDE
    expected = set()
    outputs = {}

    for path, source in sources.items():
        relative = path.relative_to(example)
        target = output_root / (relative.as_posix() + ".inc")
        expected.add(target)
        # The original root owns the final include of its generated copy.
        source = re.sub(
            r'^\s*\.include\s+"Data/Fly3x/[^"\n]+"[^\n]*\n?',
            "",
            source,
            flags=re.MULTILINE,
        )
        if relative.as_posix() == "quake/Viewport.i":
            source, count = re.subn(r"^BSP_RENDER_SCALE\s*=\s*2\b", "BSP_RENDER_SCALE = 3", source, flags=re.MULTILINE)
            if count != 1:
                raise ValueError("viewport scale declaration changed")

        def include(match: re.Match[str]) -> str:
            name = match[1]
            if name in COMMON:
                return match[0]
            child = next(
                candidate.resolve()
                for candidate in (path.parent / name, example / name)
                if candidate.is_file()
            )
            relative_child = child.relative_to(example).as_posix()
            return f'.include "{GENERATED_INCLUDE}{relative_child}.inc"'

        source = INCLUDE.sub(include, source)
        source = SEGMENT.sub(
            lambda match: match[1] + '"' + ("F3_" if match[2] in segments else "") + match[2] + '"',
            source,
        )
        source = TOKENS.sub(lambda match: symbols.get(match[0], match[0]), source)
        source = "; Generated by quake_fly3x_codegen.py; edit the original source.\n" + source
        if len(source.splitlines()) > 2048:
            raise ValueError(f"generated source exceeds 2048 lines: {relative}")
        old = target.read_text(encoding="utf-8") if target.is_file() else None
        if old != source:
            changed.append(target.relative_to(example).as_posix())
        outputs[target.relative_to(output_root)] = source.encode("utf-8")
    stale = sorted(path for path in output_root.rglob("*.inc") if path not in expected
                   and ".generated-output-transaction" not in path.parts)
    families = []
    for path in stale:
        if not path.read_text(encoding="utf-8").startswith("; Generated by quake_fly3x_codegen.py;"):
            raise ValueError(f"unowned file in generated renderer copies: {path}")
        relative = path.relative_to(output_root)
        families.append(OwnedFileFamily(path.name[:-4], ".inc", directory=relative.parent))
        changed.append(path.relative_to(example).as_posix())
    # Validate the entire graph before publishing. Reuse the workspace's
    # transaction and recovery support so a late failure cannot leave a mix
    # of renderer generations for the next build to assemble.
    sync_generated_outputs(outputs, output_root, check=check, owned_families=families)
    return {
        "passed": True,
        "copies": len(expected),
        "symbols": len(symbols),
        "segments": sorted(segments),
        "changed": changed,
        "elapsedSeconds": round(time.perf_counter() - started, 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example", type=Path, default=Workspace.discover().root / "src/snes_quake")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        result = generate(args.example, check=args.check)
        result["changedCount"] = len(result.pop("changed"))
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, GeneratedOutputError) as error:
        print(json.dumps({"passed": False, "error": str(error), "elapsedSeconds": round(time.perf_counter() - started, 6)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
