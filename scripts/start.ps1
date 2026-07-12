$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$env:UV_CACHE_DIR = Join-Path $Root ".uv-cache"
$env:UV_PYTHON = "python3.13.exe"
New-Item -ItemType Directory -Force -Path $env:UV_CACHE_DIR | Out-Null
uv run python -m global_icebox
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
