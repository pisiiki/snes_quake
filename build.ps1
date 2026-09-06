[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$AssetsOnly,
    [switch]$QualifiedAssets,
    [string]$Python = "python",
    [string]$Bash = $env:MSYS2_BASH
)

$ErrorActionPreference = "Stop"
$onWindows = [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
if (-not $onWindows) { throw "this release currently builds on Windows 10/11 only" }
$libSfx = Join-Path $PSScriptRoot "third_party/libSFX"
if (Test-Path (Join-Path $PSScriptRoot ".git")) {
    & git -C $PSScriptRoot submodule update --init third_party/libSFX third_party/ericw-tools third_party/quake-map-source third_party/vcpkg
    if ($LASTEXITCODE -ne 0) { throw "could not initialize release submodules" }
}
& git -C $libSfx submodule update --init tools/cc65
if ($LASTEXITCODE -ne 0) { throw "could not initialize the pinned cc65 source" }

$releaseTool = Join-Path $PSScriptRoot "tools/commands/snes_quake/build_quake_release.py"
& $Python $releaseTool --release-root $PSScriptRoot --preflight
if ($LASTEXITCODE -ne 0) { throw "SNES Quake release preflight failed" }

$ca65 = Join-Path $libSfx "tools/cc65/bin/ca65.exe"
$ld65 = Join-Path $libSfx "tools/cc65/bin/ld65.exe"
if (-not $Check -and (-not (Test-Path $ca65) -or -not (Test-Path $ld65))) {
    if (-not $Bash) {
        $bashCommand = Get-Command bash.exe -ErrorAction SilentlyContinue
        if ($bashCommand) { $Bash = $bashCommand.Source }
    }
    if (-not $Bash -or -not (Test-Path $Bash)) {
        throw "MSYS2 bash was not found; install MSYS2 and add bash.exe to PATH or set MSYS2_BASH"
    }
    & $Bash -lc 'command -v cygpath >/dev/null && command -v make >/dev/null'
    if ($LASTEXITCODE -ne 0) {
        throw "selected bash lacks MSYS2 cygpath/make; set MSYS2_BASH to the MSYS2 bash.exe"
    }
    $env:QUAKE_RELEASE_LIBSFX = $libSfx
    try {
        $unixLibSfx = (& $Bash -lc 'cygpath -u "$QUAKE_RELEASE_LIBSFX"').Trim()
        if ($LASTEXITCODE -ne 0 -or -not $unixLibSfx) {
            throw "could not convert the libSFX path for MSYS2"
        }
        $env:QUAKE_RELEASE_LIBSFX_UNIX = $unixLibSfx
        & $Bash -lc 'export PATH=/ucrt64/bin:/usr/bin:$PATH; make -C "$QUAKE_RELEASE_LIBSFX_UNIX/tools/cc65" bin -j4'
    } finally {
        Remove-Item Env:QUAKE_RELEASE_LIBSFX -ErrorAction SilentlyContinue
        Remove-Item Env:QUAKE_RELEASE_LIBSFX_UNIX -ErrorAction SilentlyContinue
    }
    if ($LASTEXITCODE -ne 0) { throw "could not build the pinned cc65 toolchain" }
}
if (-not (Test-Path $ca65) -or -not (Test-Path $ld65)) {
    throw "pinned cc65 build did not provide ca65.exe and ld65.exe"
}

$arguments = @($releaseTool, "--release-root", $PSScriptRoot)
if ($Check) { $arguments += "--check" }
if ($AssetsOnly) { $arguments += "--assets-only" }
if ($QualifiedAssets) { $arguments += "--qualified-assets" }
& $Python @arguments
if ($LASTEXITCODE -ne 0) { throw "SNES Quake release build failed" }
