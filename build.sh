#!/usr/bin/env sh
set -eu

usage() {
    echo "usage: sh ./build.sh [--check] [--assets-only] [--qualified-assets] [--python COMMAND]" >&2
}

check=false
assets_only=false
qualified_assets=false
python="${PYTHON:-python3}"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --check) check=true; shift ;;
        --assets-only) assets_only=true; shift ;;
        --qualified-assets) qualified_assets=true; shift ;;
        --python) [ "$#" -ge 2 ] || { usage; exit 2; }; python=$2; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage; exit 2 ;;
    esac
done

root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
lib_sfx="$root/third_party/libSFX"
cc65="$lib_sfx/tools/cc65"
release_tool="$root/tools/commands/snes_quake/build_quake_release.py"

for command in git make cmake ninja "$python"; do
    command -v "$command" >/dev/null 2>&1 || {
        echo "error: required command not found: $command" >&2
        exit 2
    }
done
bsdtar=$(command -v bsdtar || true)
if [ -z "$bsdtar" ]; then
    echo "error: bsdtar is required; on Ubuntu install libarchive-tools" >&2
    exit 2
fi

if [ -e "$root/.git" ]; then
    git -C "$root" submodule update --init third_party/libSFX third_party/ericw-tools third_party/quake-map-source third_party/vcpkg
fi
git -C "$lib_sfx" submodule update --init tools/cc65

"$python" "$release_tool" --release-root "$root" --preflight

ca65="$cc65/bin/ca65"
ld65="$cc65/bin/ld65"
if [ "$check" = false ] && { [ ! -x "$ca65" ] || [ ! -x "$ld65" ]; }; then
    make -C "$cc65" bin -j"${JOBS:-4}"
fi
if [ ! -x "$ca65" ] || [ ! -x "$ld65" ]; then
    echo "error: pinned cc65 build did not provide ca65 and ld65" >&2
    exit 2
fi

set -- "$release_tool" --release-root "$root" --tar "$bsdtar"
[ "$check" = false ] || set -- "$@" --check
[ "$assets_only" = false ] || set -- "$@" --assets-only
[ "$qualified_assets" = false ] || set -- "$@" --qualified-assets
"$python" "$@"
