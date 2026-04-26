#!/usr/bin/env bash
# Restore an encrypted Lightsei DB backup into a Postgres target.
#
# Usage:
#   BACKUP_PASSPHRASE='...' scripts/restore.sh <backup.sql.gz.enc> <target-db-url>
#
# Example (local docker scratch DB):
#   docker run -d --rm --name pg-restore-test \
#     -e POSTGRES_PASSWORD=test -e POSTGRES_DB=postgres \
#     -p 5434:5432 postgres:18-alpine
#   BACKUP_PASSPHRASE=$(cat ~/lightsei-backup-passphrase.txt) \
#     scripts/restore.sh ./lightsei-20260426_220625.sql.gz.enc \
#       postgresql://postgres:test@host.docker.internal:5434/postgres
#
# The script does NOT touch the prod DB. Point it at a scratch Postgres,
# verify the data, then if you're rebuilding production you'd swap.

set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <backup.sql.gz.enc> <target-db-url>" >&2
  exit 2
fi

INPUT="$(realpath "$1")"
TARGET_URL="$2"

if [ -z "${BACKUP_PASSPHRASE:-}" ]; then
  echo "set BACKUP_PASSPHRASE in env" >&2
  exit 2
fi

if [ ! -f "$INPUT" ]; then
  echo "no such file: $INPUT" >&2
  exit 2
fi

# Pick a psql runner: native if present, otherwise docker
if command -v psql > /dev/null 2>&1; then
  PSQL=(psql)
elif command -v docker > /dev/null 2>&1; then
  echo "psql not found locally; using docker postgres:18-alpine"
  PSQL=(docker run --rm -i --network host postgres:18-alpine psql)
else
  echo "need either psql or docker installed" >&2
  exit 2
fi

echo "decrypting + restoring $(basename "$INPUT") into $TARGET_URL..."
openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in "$INPUT" \
  | gunzip \
  | "${PSQL[@]}" "$TARGET_URL"

echo
echo "restore complete. Smoke checks:"
for q in \
  "SELECT version_num FROM alembic_version" \
  "SELECT count(*) AS workspaces FROM workspaces" \
  "SELECT count(*) AS users FROM users" \
  "SELECT count(*) AS api_keys FROM api_keys" \
  "SELECT count(*) AS runs FROM runs" \
  "SELECT count(*) AS thread_messages FROM thread_messages"
do
  "${PSQL[@]}" "$TARGET_URL" -c "$q" 2>&1 || true
done
