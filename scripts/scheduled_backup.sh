#!/usr/bin/env bash
# Run by launchd: dump icebox.db into the private backup repo; commit+push only if it changed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export CONCINNITY_BACKUP_DIR="${CONCINNITY_BACKUP_DIR:-$HOME/code/projects/concinnity-backup}"
export PATH="/opt/homebrew/bin:/usr/bin:/bin:$PATH"
echo "--- $(date -u +%FT%TZ)"
cd "$ROOT"
git -C "$CONCINNITY_BACKUP_DIR" pull -q --rebase || echo "pull failed (continuing)"
exec python3 scripts/backup.py --commit --push
