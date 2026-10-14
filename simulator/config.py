"""Skema konfigurasi skenario simulator (Pydantic v2) — fase M1.

Satu-satunya pintu masuk konfigurasi simulator: file YAML (lihat
``scenarios/*.yaml``) diparse menjadi objek :class:`Scenario` yang dipakai
oleh ``world`` (clock + event generator) maupun agent (M4).

Kontrak:

* Semua model mewarisi ``pydantic.BaseModel`` (v2) dengan constraint eksplisit
  (``ge``/``le`` untuk probabilitas & suhu, ``gt`` untuk nilai yang harus
  positif) supaya salah konfigurasi ketahuan di sini, bukan di tengah run.
* :func:`load` **fail-closed**: file hilang / YAML rusak / skema tidak valid
  → ``ValueError`` (bukan ``FileNotFoundError`` / ``ValidationError`` mentah)
  supaya pemanggil hanya perlu menangani satu jenis error.

Django TIDAK diimpor di sini — simulator adalah klien API biasa dan tidak
boleh mengontaminasi runtime production.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Union

import yaml
from pydantic import BaseModel, Field, ValidationError

# --------------------------------------------------------------------------- env
# FASE 3.1.1: muat ``.env`` / ``.env.local`` SEBELUM ``os.environ`` dibaca di
# :func:`load`. Env yang SUDAH ada di OS tetap menang (``override=False``); file
# hanya mengisi variabel yang belum diset. Dipakai untuk ``DJANGO_SIM_COOKIE`` /
# ``DJANGO_SIM_TOKEN`` / ``DJANGO_SIM_USERNAME`` / ``DJANGO_SIM_PASSWORD`` supaya
# tak perlu ``export`` manual (mis. saat menjalankan simulator di dalam container).
try:  # python-dotenv ada di requirements Django; fallback parser minimal di bawah
    from dotenv import load_dotenv

    _DOTENV_AVAILABLE = True
except ImportError:  # pragma: no cover - hanya kalau dependency tak terpasang
    load_dotenv = None  # type: ignore[assignment]
    _DOTENV_AVAILABLE = False

#: Urutan baca: ``.env.local`` menang atas ``.env`` (yang dibaca pertama menang,
#: karena keduanya TIDAK menimpa env OS / nilai yang sudah terisi).
_ENV_FILES: tuple[str, ...] = (".env.local", ".env")


def _parse_env_file(path: Path) -> None:
    """Parser ``.env`` minimal (fallback tanpa python-dotenv): ``KEY=VALUE``.

    Baris kosong / komentar (``#``) dilewati; kutip di sekitar nilai dipangkas.
    Nilai TIDAK menimpa env OS yang sudah ada (``setdefault``).
    """

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _load_env_files() -> None:
    """Muat ``.env`` / ``.env.local`` (kalau ada) dari direktori paket simulator."""

    here = Path(__file__).resolve().parent
    for name in _ENV_FILES:
        path = here / name
        if not path.is_file():
            continue
        if _DOTENV_AVAILABLE:
            load_dotenv(path, override=False)
        else:
            _parse_env_file(path)


# Dipanggil SEKALI saat import modul — sebelum ``load()`` membaca ``os.environ``.
_load_env_files()

__all__ = (
    "ActionTiming",
    "Anomaly",
    "Clock",
    "Django",
    "DjangoAuth",
    "Factory",
    "Fatigue",
    "LLM",
    "Recording",
    "Scenario",
    "load",
)

PathLike = Union[str, Path]


class Factory(BaseModel):
    """Jumlah fasilitas/staf lantai produksi untuk satu skenario."""

    lines: int = Field(ge=1, description="Jumlah lini produksi.")
    operators_per_line: int = Field(ge=0, description="Operator per lini.")
    qc_per_line: int = Field(ge=0, description="QC per lini.")
    cutting: int = Field(ge=0, description="Stasiun cutting.")
    inventory: int = Field(ge=0, description="Staf inventory.")
    supervisor: int = Field(ge=0, description="Supervisor.")
    ppic: int = Field(ge=0, description="Staf PPIC.")


class Clock(BaseModel):
    """Pengaturan jam kerja & kecepatan kompresi waktu."""

    duration: str = Field(description='Rentang jam kerja, mis. "07:00-17:00".')
    speed: int = Field(gt=0, description="Faktor kompresi (60 = 60x).")


class LLM(BaseModel):
    """Endpoint/model LLM dan peran yang boleh memakainya."""

    provider: str = Field(description='Penyedia, mis. "ollama".')
    model: str = Field(description='Nama model, mis. "qwen2.5:7b".')
    base_url: str = Field(description='Base URL, mis. "http://ollama:11434".')
    temperature: float = Field(ge=0.0, le=2.0)
    roles_using_llm: list[str] = Field(default_factory=list)


class Anomaly(BaseModel):
    """Probabilitas anomali rule-based (bukan LLM) per tick."""

    downtime_prob: float = Field(ge=0.0, le=1.0)
    defect_prob: float = Field(ge=0.0, le=1.0)
    urgent_order_prob: float = Field(ge=0.0, le=1.0)
    cancel_order_prob: float = Field(ge=0.0, le=1.0)
    #: Probabilitas event BUNDLE_ASSIGNED (menugaskan bundle ke operator) per tick.
    bundle_assigned_prob: float = Field(default=0.30, ge=0.0, le=1.0)
    #: Jumlah MAKSIMUM event BUNDLE_ASSIGNED per tick (FASE 3.3: overlap antar-
    #: bundle). ``1`` = perilaku lama (sequential); ``>1`` = beberapa bundle
    #: BERBEDA aktif bersamaan dalam satu tick (Django sudah mendukung — state
    #: per bundle, tanpa lock global).
    bundle_assigned_max_per_tick: int = Field(default=1, ge=1)
    #: FASE 3.4 — jam (sim) saat "order baru masuk" (``"HH:MM"``). Tiap tick yang
    #: jamnya cocok memunculkan satu event ``ORDER_IN`` (order datang kapan saja).
    #: Kosong = perilaku lama (ORDER_IN hanya sekali lewat ``initial_events``).
    order_in_hours: list[str] = Field(
        default_factory=lambda: ["08:00", "11:00", "14:00"]
    )


class Fatigue(BaseModel):
    """Kurva kelelahan hardcoded (memperlambat aksi, bukan LLM)."""

    slowdown_hours: list[str] = Field(default_factory=list)
    slowdown_factor: float = Field(gt=0.0, le=1.0)


class DjangoAuth(BaseModel):
    """Kredensial opsional untuk memanggil API Django (mis. saat di container).

    ``cookie`` = nilai header ``Cookie`` (mis. ``sessionid=...; device_token=...``);
    ``token`` = bearer token untuk header ``Authorization``. Kosong = tanpa auth.
    """

    cookie: str = ""
    token: str = ""


class Django(BaseModel):
    """Alamat REST API Django yang dipanggil simulator."""

    base_url: str = Field(description='Mis. "http://django:8000".')
    api_prefix: str = Field(description='Mis. "/api/v1".')
    auth: DjangoAuth = Field(default_factory=DjangoAuth)


class Recording(BaseModel):
    """Pengaturan rekaman run untuk replay/regression."""

    output: str = Field(description='Template path, mis. "runs/{scenario}_{timestamp}.jsonl".')
    telemetry: bool = False


class ActionTiming(BaseModel):
    """Jeda realistis antar aksi agent (FASE 2.7): delay acak + prob idle."""

    min_delay_sec: float = 0.5
    max_delay_sec: float = 3.0
    idle_prob: float = Field(default=0.2, ge=0.0, le=1.0)


class Scenario(BaseModel):
    """Akar skenario: identitas + seluruh blok konfigurasi."""

    scenario: str
    description: str = ""
    factory: Factory
    clock: Clock
    llm: LLM
    anomaly: Anomaly
    fatigue: Fatigue
    django: Django
    recording: Recording
    #: Whitelist endpoint per peran: {role: ["METHOD path", ...]}. Aditif sejak M4
    #: (sebelumnya YAML ``tool_set`` diabaikan Pydantic; kini masuk ke Scenario).
    tool_set: dict[str, list[str]] = Field(default_factory=dict)
    #: Jeda realistis antar aksi (FASE 2.7). Aditif — skenario lama pakai default.
    timing: ActionTiming = Field(default_factory=ActionTiming)
    #: Multi-hari (FASE 3.1): jumlah hari + tanggal mulai ("YYYY-MM-DD"; kosong = hari ini).
    days: int = Field(default=1, ge=1)
    start_date: str = ""


def load(path: PathLike) -> Scenario:
    """Baca file YAML skenario → :class:`Scenario`.

    Raise ``ValueError`` kalau file tidak ada, YAML tidak bisa diparse, isi
    bukan mapping, atau skema tidak lolos validasi Pydantic.
    """

    file_path = Path(path)
    if not file_path.is_file():
        raise ValueError(f"File skenario tidak ditemukan: {file_path}")

    try:
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # YAML rusak / indentasi salah, dsb.
        raise ValueError(f"Gagal parse YAML skenario {file_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(
            f"Isi skenario harus berupa mapping YAML, dapat {type(raw).__name__}: {file_path}"
        )

    try:
        scenario = Scenario.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"Skema skenario tidak valid ({file_path}): {exc}") from exc

    # Auth dari ENV (FASE 3.1): JANGAN hardcode cookie di YAML. Override hanya
    # kalau YAML kosong (nilai eksplisit di YAML tetap menang).
    if not scenario.django.auth.cookie and os.environ.get("DJANGO_SIM_COOKIE"):
        scenario.django.auth.cookie = os.environ["DJANGO_SIM_COOKIE"]
    if not scenario.django.auth.token and os.environ.get("DJANGO_SIM_TOKEN"):
        scenario.django.auth.token = os.environ["DJANGO_SIM_TOKEN"]
    return scenario
