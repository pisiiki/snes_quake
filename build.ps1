[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$AssetsOnly,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$onWindows = [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
if (-not $onWindows) { throw "this release currently builds on Windows 10/11 only" }
$libSfx = Join-Path $PSScriptRoot "libSFX"
if (Test-Path (Join-Path $PSScriptRoot ".git")) {
    & git -C $PSScriptRoot submodule update --init libSFX
    if ($LASTEXITCODE -ne 0) { throw "could not initialize release submodules" }
}
& git -C $libSfx submodule update --init tools/cc65
if ($LASTEXITCODE -ne 0) { throw "could not initialize the pinned cc65 source" }

$releaseTool = Join-Path $PSScriptRoot "src/snes_quake/tools/build_quake_release.py"
& $Python $releaseTool --release-root $PSScriptRoot --preflight
if ($LASTEXITCODE -ne 0) { throw "SNES Quake release preflight failed" }

$ca65 = Join-Path $libSfx "tools/cc65/bin/ca65.exe"
$ld65 = Join-Path $libSfx "tools/cc65/bin/ld65.exe"
if (-not $Check -and (-not (Test-Path $ca65) -or -not (Test-Path $ld65))) {
    $bash = "C:/msys64/usr/bin/bash.exe"
    if (-not (Test-Path $bash)) {
        throw "MSYS2 bash not found at C:/msys64/usr/bin/bash.exe"
    }
    $env:QUAKE_RELEASE_LIBSFX = $libSfx
    try {
        $unixLibSfx = (& $bash -lc 'cygpath -u "$QUAKE_RELEASE_LIBSFX"').Trim()
        if ($LASTEXITCODE -ne 0 -or -not $unixLibSfx) {
            throw "could not convert the libSFX path for MSYS2"
        }
        $env:QUAKE_RELEASE_LIBSFX_UNIX = $unixLibSfx
        & $bash -lc 'export PATH=/ucrt64/bin:/usr/bin:$PATH; make -C "$QUAKE_RELEASE_LIBSFX_UNIX/tools/cc65" bin -j4'
    } finally {
        Remove-Item Env:QUAKE_RELEASE_LIBSFX -ErrorAction SilentlyContinue
        Remove-Item Env:QUAKE_RELEASE_LIBSFX_UNIX -ErrorAction SilentlyContinue
    }
    if ($LASTEXITCODE -ne 0) { throw "could not build the pinned cc65 toolchain" }
}
if (-not (Test-Path $ca65) -or -not (Test-Path $ld65)) {
    throw "pinned cc65 build did not provide ca65.exe and ld65.exe"
}

$arguments = @(
    $releaseTool,
    "--release-root", $PSScriptRoot
)
if ($Check) { $arguments += "--check" }
if ($AssetsOnly) { $arguments += "--assets-only" }
& $Python @arguments
if ($LASTEXITCODE -ne 0) { throw "SNES Quake release build failed" }
