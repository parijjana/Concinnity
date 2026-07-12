$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$env:UV_CACHE_DIR = Join-Path $Root ".uv-cache"
$env:UV_PYTHON = "python3.13.exe"
New-Item -ItemType Directory -Force -Path $env:UV_CACHE_DIR | Out-Null

$Port = if ($env:GLOBAL_ICEBOX_UI_PORT) { $env:GLOBAL_ICEBOX_UI_PORT } else { "8765" }
$OpenArgs = @()
if ($env:GLOBAL_ICEBOX_UI_OPEN_BROWSER -eq "1") {
    $OpenArgs += "--open-browser"
}

Write-Host "Launching Concinnity H2H UI at http://127.0.0.1:$Port"
uv run python -m global_icebox.ui --host 127.0.0.1 --port $Port @OpenArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
