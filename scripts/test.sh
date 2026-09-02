#!/usr/bin/env sh
# POSIX twin of test.ps1.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
UV_CACHE_DIR="$ROOT/.uv-cache"
export UV_CACHE_DIR
mkdir -p "$UV_CACHE_DIR"
exec uv run python -m unittest discover -s tests -p "test*.py"
