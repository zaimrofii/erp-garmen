#!/bin/sh
# ============================================================
# F3-B.2.3 — Backup harian: PostgreSQL dump + media tarball + retensi.
#
# Dua cara pakai (script yang sama, mode dideteksi otomatis):
#   * HOST (cron/systemd): `./scripts/backup.sh`
#       - pakai `docker compose exec postgres pg_dump`
#       - pakai `docker run` untuk membaca volume `media_files`
#   * CONTAINER (service `backup` di docker-compose.prod.yml):
#       - `BACKUP_MODE=container` → `pg_dump -h postgres` langsung
#       - media dibaca dari bind volume yang di-mount ke /data
#
# Env yang dikenali (semua punya default):
#   BACKUP_DIR (default /backup), RETENTION_DAYS (7), COMPOSE_FILE
#   DB_NAME, DB_USER, DB_HOST, DB_PORT, DB_PASSWORD
#   MEDIA_VOLUME (default garmen-prod_media_files), MEDIA_SOURCE_DIR (/data)
#
# POSIX sh supaya jalan di host (bash) MAUPUN alpine (busybox).
# ============================================================
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backup}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
DB_NAME="${DB_NAME:-garmen_django}"
DB_USER="${DB_USER:-odoo}"
DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_PASSWORD="${DB_PASSWORD:-}"
MEDIA_VOLUME="${MEDIA_VOLUME:-garmen-prod_media_files}"
MEDIA_SOURCE_DIR="${MEDIA_SOURCE_DIR:-/data}"

DATE="$(date -u +%Y%m%d_%H%M%S)"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

log() {
    echo "[backup] $NOW $*"
}

# --- Mode ------------------------------------------------------------------
MODE="container"
if [ "${BACKUP_MODE:-auto}" = "host" ] \
    || { [ "${BACKUP_MODE:-auto}" = "auto" ] && command -v docker >/dev/null 2>&1 && [ -f "$COMPOSE_FILE" ]; }; then
    MODE="host"
fi

mkdir -p "$BACKUP_DIR/postgres" "$BACKUP_DIR/media"
log "mulai mode=$MODE dir=$BACKUP_DIR retensi=${RETENTION_DAYS}h"

# --- 1) PostgreSQL --------------------------------------------------------
PG_FILE="$BACKUP_DIR/postgres/${DB_NAME}_${DATE}.dump"
if [ "$MODE" = "host" ]; then
    docker compose -f "$COMPOSE_FILE" exec -T postgres \
        pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc > "$PG_FILE"
else
    PGPASSWORD="$DB_PASSWORD" pg_dump \
        -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -Fc > "$PG_FILE"
fi
log "postgres -> $PG_FILE"

# --- 2) Media -------------------------------------------------------------
MEDIA_FILE="$BACKUP_DIR/media/media_${DATE}.tar.gz"
if [ "$MODE" = "host" ]; then
    docker run --rm \
        -v "$MEDIA_VOLUME":/data:ro \
        -v "$BACKUP_DIR/media":/backup \
        alpine tar czf "/backup/$(basename "$MEDIA_FILE")" -C /data .
else
    tar czf "$MEDIA_FILE" -C "$MEDIA_SOURCE_DIR" .
fi
log "media    -> $MEDIA_FILE"

# --- 3) Retensi -----------------------------------------------------------
DELETED_PG="$(find "$BACKUP_DIR/postgres" -name '*.dump' -mtime "+$RETENTION_DAYS" -print -delete | wc -l)"
DELETED_MEDIA="$(find "$BACKUP_DIR/media" -name '*.tar.gz' -mtime "+$RETENTION_DAYS" -print -delete | wc -l)"
log "retensi: hapus ${DELETED_PG} dump + ${DELETED_MEDIA} media (> ${RETENTION_DAYS} hari)"

# --- Ringkasan ------------------------------------------------------------
PG_SIZE="$(du -h "$PG_FILE" | cut -f1)"
MEDIA_SIZE="$(du -h "$MEDIA_FILE" | cut -f1)"
log "selesai pg=${PG_SIZE} media=${MEDIA_SIZE}"
