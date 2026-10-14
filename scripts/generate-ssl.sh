#!/usr/bin/env bash
# ============================================================
# F3-B.2.2 — Bootstrap TLS untuk Nginx produksi.
#
# Tujuan:
#   1. Menyediakan sertifikat agar Nginx BISA START (self-signed dulu bila perlu).
#   2. Menggantinya dengan sertifikat Let's Encrypt (Certbot) yang valid.
#
# Pemakaian:
#   ./scripts/generate-ssl.sh --self-signed-only   # lokal/uji, tanpa jaringan
#   DOMAIN=mes.klien-a.com LETSENCRYPT_EMAIL=ops@klien-a.com ./scripts/generate-ssl.sh
#
# Catatan: sertifikat hidup di ./certbot/conf (bind mount) supaya bisa
# diinspeksi/di-backup dan dipakai `nginx -t` tanpa named volume.
# ============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN="${DOMAIN:-mes.klien-a.com}"
EMAIL="${LETSENCRYPT_EMAIL:-}"
CONF_DIR="${CERTBOT_CONF_DIR:-$PROJECT_DIR/certbot/conf}"
WWW_DIR="${CERTBOT_WWW_DIR:-$PROJECT_DIR/certbot/www}"
LIVE_DIR="$CONF_DIR/live/$DOMAIN"

SELF_SIGNED_ONLY=0
if [ "${1:-}" = "--self-signed-only" ]; then
  SELF_SIGNED_ONLY=1
fi

echo "[ssl] domain=$DOMAIN conf=$CONF_DIR"
mkdir -p "$LIVE_DIR" "$WWW_DIR"

# ---------------------------------------------------------------------------
# 1) Let's Encrypt dulu (standalone: port 80 harus bebas / Nginx belum jalan).
# ---------------------------------------------------------------------------
if [ "$SELF_SIGNED_ONLY" -eq 0 ] && [ ! -f "$LIVE_DIR/fullchain.pem" ]; then
  if [ -z "$EMAIL" ]; then
    echo "[ssl] LETSENCRYPT_EMAIL kosong → lewati Certbot, pakai self-signed."
  else
    echo "[ssl] meminta sertifikat Let's Encrypt (standalone)…"
    docker run --rm \
      -p 80:80 \
      -v "$CONF_DIR:/etc/letsencrypt" \
      -v "$WWW_DIR:/var/www/certbot" \
      certbot/certbot certonly --standalone --non-interactive \
        --agree-tos --no-eff-email --keep-until-expiring \
        --email "$EMAIL" -d "$DOMAIN"
  fi
fi

# ---------------------------------------------------------------------------
# 2) Fallback self-signed (Nginx butuh file cert saat start).
# ---------------------------------------------------------------------------
if [ ! -f "$LIVE_DIR/fullchain.pem" ]; then
  echo "[ssl] membuat self-signed (bootstrap) untuk $DOMAIN…"
  openssl req -x509 -nodes -newkey rsa:2048 -days 90 \
    -keyout "$LIVE_DIR/privkey.pem" \
    -out "$LIVE_DIR/fullchain.pem" \
    -subj "/CN=$DOMAIN"
fi

echo "[ssl] sertifikat siap:"
ls -1 "$LIVE_DIR"

if [ "$SELF_SIGNED_ONLY" -eq 0 ]; then
  echo "[ssl] reload Nginx bila sedang jalan…"
  docker compose -f "$PROJECT_DIR/docker-compose.prod.yml" exec nginx nginx -s reload || true
fi

echo "[ssl] selesai. Perbarui otomatis ditangani service 'certbot' (renew 12 jam)."
