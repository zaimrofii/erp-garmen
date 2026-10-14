#!/usr/bin/env python
"""Load test sederhana: ±100 request/detik ke endpoint **read-only**.

Default target ``GET /api/health/`` — aman (tidak menyentuh data, dikecualikan
dari rate limit) dan tidak pernah mengirim aksi tulis.

Cara jalan (container sudah punya httpx):

    docker exec garmen_django python scripts/load_test.py
    # Fase G — beban anon (IP disebar lewat X-Forwarded-For) & sebagai perangkat:
    docker exec garmen_django python scripts/load_test.py --path /api/v1/devices/me
    docker exec garmen_django python scripts/load_test.py --path /api/v1/devices/me \\
        --cookie "device_token=<token binding ber-user>"
    # Fase G — bukti rate limit anon vs user (tanpa penyebaran IP):
    docker exec garmen_django python scripts/load_test.py --throttle-probe --path /api/v1/devices/me

Atau dari host (fallback ``urllib`` kalau httpx belum terpasang):

    python3 scripts/load_test.py --base-url http://localhost:8000

Output: total request, sukses (200), gagal (+status), latency p50/p95/p99, RPS
aktual, dan **error rate** (gagal bila > ``--max-error-rate``, default 1%).

Catatan throttle: rate limit DRF (anon 60/min, user 300/min) dihitung **per IP**
untuk anonim. Untuk mengukur kapasitas server (bukan kuota), beban default
menyebar IP lewat header ``X-Forwarded-For`` (``--xff-rotate``, default ON) —
tanpa itu, request ke-61 anon akan 429. ``--throttle-probe`` justru mematikan
penyebaran itu supaya batas 60/min benar-benar terlihat.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

try:  # httpx = pool koneksi, lebih representatif
    import httpx
except ImportError:  # pragma: no cover - fallback untuk host tanpa httpx
    httpx = None
    import urllib.error
    import urllib.request

__all__ = ("percentile", "run", "throttle_probe")

DEFAULT_RPS = 100
DEFAULT_DURATION = 10.0
DEFAULT_WORKERS = 50
REQUEST_TIMEOUT = 5.0
DEFAULT_MAX_ERROR_RATE = 1.0

#: Fungsi pembuat header per request (index request dipakai untuk menyebar IP).
HeadersFactory = Callable[[int], dict[str, str]]


def percentile(values: list[float], pct: float) -> float:
    """Persentil (interpolasi linear) dari daftar latency yang sudah diurutkan."""
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    posisi = (len(values) - 1) * (pct / 100)
    bawah = int(posisi)
    atas = min(bawah + 1, len(values) - 1)
    return values[bawah] + (values[atas] - values[bawah]) * (posisi - bawah)


def one_request(
    client, url: str, headers: dict[str, str] | None = None
) -> tuple[int, float]:
    """Kirim satu request; kembalikan ``(status, latency_ms)`` (0 = gagal kirim)."""
    start = time.perf_counter()
    try:
        if client is not None:
            response = client.get(url, timeout=REQUEST_TIMEOUT, headers=headers or {})
            status = response.status_code
        else:  # pragma: no cover - jalur host tanpa httpx
            request = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                status = response.status
    except Exception:  # noqa: BLE001 - load test: kegagalan apa pun dihitung gagal
        status = 0
    return status, (time.perf_counter() - start) * 1000


def run(
    url: str,
    rps: int,
    duration: float,
    workers: int,
    headers_for: HeadersFactory | None = None,
    max_error_rate: float = DEFAULT_MAX_ERROR_RATE,
) -> int:
    """Jalankan beban ±``rps`` request/detik selama ``duration`` detik."""
    total = int(rps * duration)
    print(f"target     : {url}")
    print(
        f"rencana    : {total} request ({rps} RPS x {duration:g} detik, "
        f"{workers} worker)"
    )

    client = httpx.Client() if httpx is not None else None
    try:
        mulai = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for index in range(total):
                headers = headers_for(index) if headers_for is not None else None
                futures.append(pool.submit(one_request, client, url, headers))
                # Sebar request merata: request ke-i dijadwalkan pada i/rps detik.
                sisa = (mulai + (index + 1) / rps) - time.perf_counter()
                if sisa > 0:
                    time.sleep(sisa)
            hasil = [future.result() for future in futures]
        durasi = time.perf_counter() - mulai
    finally:
        if client is not None:
            client.close()

    statuses = [status for status, _ in hasil]
    latencies = sorted(latency for _, latency in hasil)
    sukses = sum(1 for status in statuses if status == 200)
    gagal = total - sukses
    status_gagal = sorted({status for status in statuses if status != 200})
    error_rate = (gagal / total * 100) if total else 0.0

    print(f"total      : {total} request dalam {durasi:.2f} detik")
    print(f"sukses     : {sukses} (HTTP 200)")
    print(f"gagal      : {gagal}" + (f" | status: {status_gagal}" if gagal else ""))
    print(f"error rate : {error_rate:.2f}% (batas {max_error_rate:g}%)")
    print(f"rps aktual : {total / durasi:.1f} RPS")
    if latencies:
        print(
            f"latency    : p50 {percentile(latencies, 50):.1f} ms | "
            f"p95 {percentile(latencies, 95):.1f} ms | "
            f"p99 {percentile(latencies, 99):.1f} ms"
        )
        print(
            f"latency    : rata-rata {statistics.fmean(latencies):.1f} ms | "
            f"max {latencies[-1]:.1f} ms | min {latencies[0]:.1f} ms"
        )
    return 0 if error_rate <= max_error_rate else 1


def throttle_probe(
    url: str,
    headers: dict[str, str] | None = None,
    cookie: str | None = None,
    limit: int = 90,
) -> int:
    """Bukti rate limit (Fase G): anon 60/min vs user 300/min.

    Kirim request **berurutan tanpa menyebar IP** sampai 429 muncul, lalu kirim
    satu request memakai cookie device binding **ber-user**: kalau request itu
    tetap 200 sementara anon sudah 429, berarti anggaran anon & user benar-benar
    terpisah (UserRateThrottle memakai `request.user`).
    """
    client = httpx.Client() if httpx is not None else None
    try:
        sukses_anon = 0
        status_anon_pertama_429 = None
        for index in range(limit):
            status, _ = one_request(client, url, headers)
            if status == 200:
                sukses_anon += 1
                continue
            status_anon_pertama_429 = (index + 1, status)
            break

        print(f"anon       : {sukses_anon} request 200 sebelum 429")
        if status_anon_pertama_429 is None:
            print("anon       : tidak mencapai 429 dalam batas probe (kuota belum habis)")
            return 1

        nomor, status = status_anon_pertama_429
        print(f"anon       : request ke-{nomor} → HTTP {status} (kuota anon habis)")

        if cookie is None:
            print("user       : dilewati (tanpa --cookie)")
            return 0

        headers_user = dict(headers or {})
        headers_user["Cookie"] = cookie
        status_user, _ = one_request(client, url, headers_user)
        print(f"user(dev)  : HTTP {status_user} (anggaran terpisah)")
        return 0 if status_user == 200 else 1
    finally:
        if client is not None:
            client.close()


def make_headers_factory(args) -> HeadersFactory | None:
    """Bangun fungsi header per request (cookie + `--header` + penyebaran IP)."""
    extra: dict[str, str] = {}
    for item in args.header or []:
        name, _, value = item.partition(":")
        if name.strip():
            extra[name.strip()] = value.strip()

    if args.cookie:
        extra["Cookie"] = args.cookie

    cookies = read_cookie_file(args.cookie_file)
    rotate = args.xff_rotate
    if not extra and not rotate and not cookies:
        return None

    def headers_for(index: int) -> dict[str, str]:
        headers = dict(extra)
        if rotate:
            # IP berbeda per request → throttle anon (per-IP) tidak membatasi beban.
            headers["X-Forwarded-For"] = (
                f"10.{index // 65536 % 256}.{index // 256 % 256}.{index % 256 + 1}"
            )
        if cookies:
            # Kuota user dihitung PER USER (300/min), jadi beban authenticated
            # disebar merata ke beberapa device binding ber-user berbeda.
            headers["Cookie"] = cookies[index % len(cookies)]
        return headers

    return headers_for


def read_cookie_file(path: str | None) -> list[str]:
    """Baca daftar cookie (satu per baris) untuk rotasi user pada beban authenticated."""
    if not path:
        return []

    try:
        with open(path, encoding="utf-8") as handle:
            return [
                line.strip()
                for line in handle
                if line.strip() and not line.startswith("#")
            ]
    except OSError as exc:
        print(f"peringatan    : tidak bisa membaca {path}: {exc}")
        return []


def main() -> int:
    """Entry point CLI."""
    parser = argparse.ArgumentParser(
        description="Load test sederhana ke endpoint READ-ONLY (jangan ke endpoint tulis)."
    )
    parser.add_argument(
        "--base-url", default="http://localhost:8000", help="base URL service"
    )
    parser.add_argument("--path", default="/api/health/", help="path endpoint read-only")
    parser.add_argument("--rps", type=int, default=DEFAULT_RPS, help="request per detik")
    parser.add_argument(
        "--duration", type=float, default=DEFAULT_DURATION, help="durasi (detik)"
    )
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS, help="jumlah thread worker"
    )
    parser.add_argument(
        "--header",
        action="append",
        metavar="NAMA:NILAI",
        help="header tambahan (boleh diulang), mis. 'Authorization: Bearer x'",
    )
    parser.add_argument("--cookie", help="nilai header Cookie, mis. 'device_token=…'")
    parser.add_argument(
        "--cookie-file",
        help="file berisi satu cookie per baris (di-rotasi per request → banyak user)",
    )
    parser.add_argument(
        "--no-xff-rotate",
        dest="xff_rotate",
        action="store_false",
        help="jangan sebar IP lewat X-Forwarded-For (biarkan rate limit berlaku)",
    )
    parser.add_argument(
        "--max-error-rate",
        type=float,
        default=DEFAULT_MAX_ERROR_RATE,
        help="batas error rate (%%) — keluar 1 kalau terlampaui (default 1)",
    )
    parser.add_argument(
        "--throttle-probe",
        action="store_true",
        help="mode bukti rate limit: anon sampai 429, lalu cek cookie user tetap 200",
    )
    parser.add_argument(
        "--probe-limit", type=int, default=90, help="batas request pada --throttle-probe"
    )
    args = parser.parse_args()

    url = args.base_url.rstrip("/") + args.path

    if args.throttle_probe:
        # Probe sengaja TIDAK menyebar IP & tidak mengirim cookie user.
        return throttle_probe(url, cookie=args.cookie, limit=args.probe_limit)

    return run(
        url,
        args.rps,
        args.duration,
        args.workers,
        headers_for=make_headers_factory(args),
        max_error_rate=args.max_error_rate,
    )


if __name__ == "__main__":
    sys.exit(main())
