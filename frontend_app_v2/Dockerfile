# syntax=docker/dockerfile:1
# ============================================================
# F3-B.2.2 — Build FRONTEND (bun) untuk di-serve Nginx.
#
# MENGAPA IMAGE TERPISAH (bukan stage di django_app/Dockerfile.prod):
#   1. `frontend_app_v2/` adalah SAUDARA dari build context `./django_app`,
#      jadi `COPY ../frontend_app_v2` TIDAK mungkin dari Dockerfile.prod.
#   2. Service `nginx` memount named volume `frontend_dist`. Isi direktori
#      image akan TERTUTUP oleh volume kosong, jadi `dist/` harus "dituang"
#      ke volume itu oleh service one-shot `frontend_builder` (lihat compose).
#   Tetap "Opsi A" secara prinsip: satu perintah `docker compose build`
#   membangun backend + frontend (lihat prinsip: build frontend di tahap terpisah).
#
# Dipakai oleh service `frontend_builder` (compose prod) -> menulis ke
# volume `frontend_dist` yang di-mount Nginx di /var/www/frontend.
# ============================================================

FROM oven/bun:1-alpine AS build

WORKDIR /app

# Layer dependency dulu supaya cache efektif saat hanya source yang berubah.
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY . .

# URL produksi (same-origin di belakang Nginx). Bisa di-override via build args.
ARG VITE_API_BASE_URL=https://mes.klien-a.com/api/v1
ARG VITE_WS_URL=wss://mes.klien-a.com/ws
ARG VITE_WS_ENABLED=true

# Vite hanya membaca variabel dari file `.env*` (bukan env shell) → tulis dulu.
RUN printf 'VITE_API_BASE_URL=%s\nVITE_WS_URL=%s\nVITE_WS_ENABLED=%s\n' \
        "$VITE_API_BASE_URL" "$VITE_WS_URL" "$VITE_WS_ENABLED" > .env.production \
    && bun run build

# ---------------------------------------------------------------------------
# Stage akhir kecil: menyimpan hasil `dist/` saja.
# `CMD` menyalin hasil ke volume `frontend_dist` (dipanggil service one-shot).
# ---------------------------------------------------------------------------
FROM alpine:3.20

COPY --from=build /app/dist /dist

CMD ["sh", "-c", "mkdir -p /var/www/frontend && cp -r /dist/. /var/www/frontend/ && echo 'frontend dist -> /var/www/frontend'"]
