#!/usr/bin/env bash
set -euo pipefail

data_dir="${DATA_DIR:-./quiz-data}"
database_path="${QUIZ_DATABASE_PATH:-${data_dir}/db/dobrokek.sqlite3}"
backup_dir="${data_dir}/backups"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_path="${backup_dir}/dobrokek-${timestamp}.sqlite3"

mkdir -p "${backup_dir}"

python3 - "${database_path}" "${backup_path}" <<'PY'
import sqlite3
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
if not source.is_file():
    raise SystemExit(f"Database does not exist: {source}")
with sqlite3.connect(source) as source_connection, sqlite3.connect(target) as target_connection:
    source_connection.backup(target_connection)
    result = target_connection.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise SystemExit(f"Backup integrity check failed: {result}")
PY

mapfile -t obsolete < <(find "${backup_dir}" -maxdepth 1 -type f -name 'dobrokek-*.sqlite3' -printf '%T@ %p\n' | sort -rn | tail -n +8 | cut -d' ' -f2-)
for path in "${obsolete[@]}"; do
    rm -- "${path}"
done

echo "Backup created: ${backup_path}"
