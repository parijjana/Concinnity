#!/usr/bin/env bash
# Run by launchd: dump icebox.db into project_docs/concinnity-backup (owner, 2026-10-12); commit+push only if it changed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export CONCINNITY_BACKUP_DIR="${CONCINNITY_BACKUP_DIR:-$HOME/code/projects/project_docs/concinnity-backup}"
export PATH="/opt/homebrew/bin:/usr/bin:/bin:$PATH"
echo "--- $(date -u +%FT%TZ)"
cd "$ROOT"
git -C "$CONCINNITY_BACKUP_DIR" pull -q --rebase --autostash || echo "pull failed (continuing)"
exec python3 scripts/backup.py --commit --push
