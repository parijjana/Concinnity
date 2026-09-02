#!/usr/bin/env sh
# POSIX twin of start.ps1. Same contract: run from the repo root, keep uv's cache inside the
# repo, launch the stdio server. Deliberately does NOT pin UV_PYTHON — start.ps1 sets
# "python3.13.exe", which is a Windows filename and resolves to nothing here; pyproject's
# requires-python >=3.11 already constrains it, and uv provisions the interpreter itself.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
UV_CACHE_DIR="$ROOT/.uv-cache"
export UV_CACHE_DIR
mkdir -p "$UV_CACHE_DIR"
exec uv run python -m global_icebox
