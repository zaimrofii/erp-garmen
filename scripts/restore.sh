#!/bin/sh
# ============================================================
# F3-B.2.3 — Restore dari backup (PostgreSQL + media).
#
# PEMAKAIAN:
#   ./scripts/restore.sh --list
#   ./scripts/restore.sh --yes <pg.dump> [media.tar.gz]
#
# Tanpa `--yes` script hanya MENAMPILKAN rencana (dry-run) — mencegah restore
# tidak sengaja ke database produksi.
#
# Contoh drill di staging:
#   BACKUP_DIR=./backups ./scripts/restore.sh --list
#   BACKUP_DIR=./backups ./scripts/restore.sh --yes ./backups/postgres/garmen_django_20261010_010000.dump
#
# Env: BACKUP_DIR, COMPOSE_FILE, DB_NAME, DB_USER, DB_HOST, DB_PORT, DB_PASSWORD,
#      MEDIA_VOLUME, MEDIA_SOURCE_DIR, BACKUP_MODE (auto|host|container).
# ============================================================
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backup}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
DB_NAME="${DB_NAME:-garmen_django}"
DB_USER="${DB_USER:-odoo}"
DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_PASSWORD="${DB_PASSWORD:-}"
MEDIA_VOLUME="${MEDIA_VOLUME:-garmen-prod_media_files}"
MEDIA_SOURCE_DIR="${MEDIA_SOURCE_DIR:-/data}"

usage() {
    echo "Pemakaian: $0 --list"
    echo "           $0 --yes <file.dump> [file_media.tar.gz]"
    exit 1
}

as_yes=0
if [ "${1:-}" = "--list" ]; then
    echo "Backup postgres di $BACKUP_DIR/postgres :"
    ls -lht "$BACKUP_DIR/postgres" 2>/dev/null || echo "  (kosong)"
    echo
    echo "Backup media di $BACKUP_DIR/media :"
    ls -lht "$BACKUP_DIR/media" 2>/dev/null || echo "  (kosong)"
    exit 0
fi

if [ "${1:-}" = "--yes" ]; then
    as_yes=1
    shift
fi

PG_SRC="${1:-}"
MEDIA_SRC="${2:-}"
[ -n "$PG_SRC" ] || usage
[ -f "$PG_SRC" ] || { echo "ERROR: dump tidak ditemukan: $PG_SRC" >&2; exit 1; }

MODE="container"
if [ "${BACKUP_MODE:-auto}" = "host" ] \
    || { [ "${BACKUP_MODE:-auto}" = "auto" ] && command -v docker >/dev/null 2>&1 && [ -f "$COMPOSE_FILE" ]; }; then
    MODE="host"
fi

cat <<EOF
=== RENCANA RESTORE ===
mode          : $MODE
postgres dump : $PG_SRC
target DB     : $DB_NAME @ $DB_HOST:$DB_PORT (user $DB_USER)
media tar     : ${MEDIA_SRC:-(tidak ada / dilewati)}
target media  : $MEDIA_VOLUME ($MEDIA_SOURCE_DIR)
PERINGATAN    : `--clean --if-exists` akan MENGHAPUS objek yang bentrok di DB target!
EOF

if [ "$as_yes" -eq 0 ]; then
    echo
    echo "Dry-run selesai. Tambahkan --yes untuk benar-benar menjalankan."
    exit 1
fi

# --- 1) Restore PostgreSQL -------------------------------------------------
echo "[restore] memulihkan database $DB_NAME ..."
if [ "$MODE" = "host" ]; then
    docker compose -f "$COMPOSE_FILE" exec -T postgres \
        pg_restore --clean --if-exists --no-owner -U "$DB_USER" -d "$DB_NAME" < "$PG_SRC"
else
    PGPASSWORD="$DB_PASSWORD" pg_restore --clean --if-exists --no-owner \
        -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" < "$PG_SRC"
fi
echo "[restore] postgres selesai"

# --- 2) Restore media ------------------------------------------------------
if [ -n "$MEDIA_SRC" ]; then
    [ -f "$MEDIA_SRC" ] || { echo "ERROR: media tidak ditemukan: $MEDIA_SRC" >&2; exit 1; }
    echo "[restore] memulihkan media dari $MEDIA_SRC ..."
    if [ "$MODE" = "host" ]; then
        docker run --rm \
            -v "$MEDIA_VOLUME":/data \
            -v "$(cd "$(dirname "$MEDIA_SRC")" && pwd)":/backup:ro \
            alpine sh -c "rm -rf /data/* && tar xzf /backup/$(basename "$MEDIA_SRC") -C /data"
    else
        rm -rf "$MEDIA_SOURCE_DIR"/*
        tar xzf "$MEDIA_SRC" -C "$MEDIA_SOURCE_DIR"
    fi
    echo "[restore] media selesai"
fi

echo "[restore] SELESAI. Verifikasi: curl -fsS http://localhost/api/health/  lalu cek data di aplikasi."
