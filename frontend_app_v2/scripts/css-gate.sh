#!/usr/bin/env bash
# GATE no-visual-regression CSS (Tailwind) — mengukur ULANG, bukan menyalin nilai.
#
# Kenapa ada: gate lama (`md5_tailwind_css` di docs/current-project.json) ternyata
# DISALIN identik dari Fase 2 sampai H2.2 (23 kemunculan) padahal kelas baru memang
# ditambahkan H1.5/H1.6/H1.8/H2.1/H2.2 ⇒ nilai itu "hantu" (lihat docs/current-project.json
# blok `css_gate` + `decisions_retroaktif`).
#
# Cara pakai:
#   bun --bun run css:gate             → ukur + bandingkan baseline (PASS/FAIL)
#   bun --bun run css:gate --update    → ukur + TULIS ULANG baseline (sadar/disengaja)
#
# Keluaran : PASS/FAIL + md5 + jumlah rule + petunjuk bila berubah; `--update` mencetak
#            diff (md5 & rule lama→baru), timestamp UTC, dan direktori pemanggil + WARNING.
# Baseline : scripts/css-gate.baseline (hash + jumlah rule + jejak update; TIDAK memuat
#            nama kelas Tailwind supaya file ini tidak ikut memicu rule baru — Tailwind v4
#            memindai SELURUH project root termasuk tests/**).
set -euo pipefail

CALLER_DIR="$PWD"
cd "$(dirname "$0")/.." || exit 1

BASELINE="scripts/css-gate.baseline"
UPDATE=0
for arg in "$@"; do
  case "$arg" in
    --update|-u) UPDATE=1 ;;
    *) echo "FAIL: argumen tak dikenal: $arg (gunakan --update untuk memperbarui baseline)" >&2; exit 2 ;;
  esac
done

if [ ! -f "$BASELINE" ]; then
  echo "FAIL: baseline $BASELINE tidak ada." >&2
  exit 2
fi

BUN_BIN=$(command -v bun || echo "$HOME/.bun/bin/bun")
LOG=$(mktemp)
"$BUN_BIN" --bun run build > "$LOG" 2>&1 || { echo "FAIL: build gagal — lihat $LOG"; tail -20 "$LOG"; exit 2; }

CSS=$(ls dist/assets/*.css | head -1)
MD5=$(md5sum "$CSS" | cut -d' ' -f1)
RULES=$(tr '}' '\n' < "$CSS" | grep -c '{')
SIZE=$(wc -c < "$CSS" | tr -d ' ')
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)

EXPECT_MD5=$(grep '^md5=' "$BASELINE" | head -1 | cut -d= -f2 | tr -d '\r')
EXPECT_RULES=$(grep '^rules=' "$BASELINE" | head -1 | cut -d= -f2 | tr -d '\r')

echo "css      : $CSS ($SIZE byte)"
echo "md5      : $MD5   (baseline: $EXPECT_MD5)"
echo "rules    : $RULES   (baseline: $EXPECT_RULES)"

if [ "$MD5" = "$EXPECT_MD5" ]; then
  if [ "$UPDATE" = "1" ]; then
    echo "UPDATE: baseline sudah identik (no diff) — tidak ada yang ditulis."
    echo "        waktu=$NOW dipanggil dari=$CALLER_DIR"
  fi
  echo "PASS: CSS identik dengan baseline (tidak ada perubahan utilitas)."
  exit 0
fi

DELTA=$((RULES - EXPECT_RULES))

if [ "$UPDATE" = "1" ]; then
  TMP=$(mktemp)
  grep -v -e '^md5=' -e '^rules=' -e '^# updated_' "$BASELINE" > "$TMP"
  {
    cat "$TMP"
    echo "# updated_at=$NOW"
    echo "# updated_from=$CALLER_DIR"
    echo "md5=$MD5"
    echo "rules=$RULES"
  } > "$BASELINE"
  rm -f "$TMP"
  echo "UPDATE: baseline diperbarui"
  echo "        md5   : $EXPECT_MD5 -> $MD5"
  echo "        rules : $EXPECT_RULES -> $RULES (delta $DELTA)"
  echo "        waktu : $NOW"
  echo "        dipanggil dari: $CALLER_DIR"
  echo "WARNING: baseline updated — pastikan perubahan CSS intentional"
  exit 0
fi

echo "FAIL: md5 CSS BERUBAH."
if [ "$RULES" != "$EXPECT_RULES" ]; then
  echo "       jumlah rule ikut berubah ($EXPECT_RULES -> $RULES, delta $DELTA) ⇒ kemungkinan" \
       "ada kelas Tailwind BARU/KELAS HILANG di src/** atau tests/** (atau docs/*.json yang" \
       "juga dipindai)."
  echo "       Petunjuk: simpan salinan CSS sebelum perubahan / bandingkan daftar rule."
else
  echo "       jumlah rule SAMA ⇒ perubahan nilai/urutan (mis. token theme atau isi rule) —" \
       "periksa src/index.css / token warna."
fi
echo "       Kalau perubahan DISENGAJA: 'bun --bun run css:gate --update' (mencatat" \
     "timestamp + direktori pemanggil) lalu catat di docs/current-project.json."
exit 1
