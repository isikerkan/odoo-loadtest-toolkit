#!/bin/bash
# Clone an Odoo database for load testing: ./scripts/clone_db.sh <source> <clone>
# Terminates connections to both databases so CREATE DATABASE ... TEMPLATE works,
# then neutralizes outgoing mail servers on the clone so load runs cannot send mail.
set -euo pipefail

SOURCE="${1:?source db required}"
CLONE="${2:?clone db required}"

psql postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                  WHERE datname IN ('$SOURCE', '$CLONE') AND pid <> pg_backend_pid();" >/dev/null
dropdb --if-exists "$CLONE"
createdb -T "$SOURCE" "$CLONE"
psql "$CLONE" -c "UPDATE ir_mail_server SET active = false;" >/dev/null 2>&1 || true
echo "cloned $SOURCE -> $CLONE"
