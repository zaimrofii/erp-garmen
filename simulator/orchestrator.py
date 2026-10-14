"""Entry point simulator + CLI Typer — fase M4 (MVP, terakhir).

Merangkai semua modul menjadi satu run:

    Scenario (YAML) → MESClient + Recorder → build_agents
        → SimulationClock (tick) × EventGenerator (anomali rule-based)
        → dispatch ke agent (asyncio.gather) → telemetry JSONL
        → compute_kpi → tulis *_kpi.json

Dijalankan::

    python -m simulator.orchestrator -s mini_1line

Catatan desain (MVP, bukan produksi):

* delay per tick = ``clock.real_sleep_per_tick`` (60/speed) dilipat fatigue →
  ``speed 60 → 1 detik per menit sim``; ``speed 600 → 0.1 detik``.
  (Spesifikasi menyebut ``fatigue_delay``/``1.0/speed``; M1 sudah punya
  ``apply_fatigue`` + ``real_sleep_per_tick`` dan M1 tidak diubah, jadi dipakai
  keduanya — hasilnya konsisten dengan komentar "speed 60 → 1s/menit sim".)
* ``supervisor`` masih scripted (LLM supervisor ditunda ke scale); mapping event
  belum menargetkannya sehingga ia idle — itu disengaja untuk MVP.
* Tidak ada state yang dipersist: hanya file jejak per run. Django tidak diubah.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import typer

from .agents.base import BaseAgent
from .agents.operator import OperatorAgent
from .agents.qc import QCAgent
from .agents.scripted import ScriptedAgent
from .client.http import MESClient, refresh_session_cookie
from .config import Scenario, load
from .llm.client import OllamaClient
from .telemetry.kpi import compute_kpi
from .telemetry.recorder import Recorder
from .world.clock import SimulationClock
from .world.events import Event, EventGenerator

logger = logging.getLogger(__name__)

app = typer.Typer(add_completion=False, help="Simulator garmen (MES) — MVP.")

#: Round-robin pemilihan PPIC (state in-memory per proses, bukan persisted).
_PPIC_RR = itertools.count()

#: FASE 3.3 — round-robin operator: bundle berbeda (dalam tick yang sama) diberi
#: operator berbeda supaya overlap antar-bundle benar-benar paralel.
_OPERATOR_RR = itertools.count()

#: Operator yang sedang mengerjakan bundle (in-flight). Diisi/dikosongkan oleh
#: :func:`_dispatch` mengelilingi ``await`` supaya tick paralel berikutnya tidak
#: menugaskan operator yang sama ke bundle lain.
_BUSY_OPERATOR_IDS: set = set()


class BundleRegistry:
    """Registry bundle SHARED antar agent (in-memory, satu instance per run).

    Semua agent memegang **reference** yang sama → update state/version di satu
    agent langsung terlihat agent lain (mencegah data stale → 400 transisi).
    """

    def __init__(self, bundles: list[dict]) -> None:
        self._data: dict = {b["id"]: dict(b) for b in bundles}

    def get(self, bundle_id):
        """Bundle by id (atau ``None``)."""
        return self._data.get(bundle_id)

    def all(self) -> list[dict]:
        """Semua bundle (list nilai registry)."""
        return list(self._data.values())

    def update(self, bundle_id, **kwargs) -> None:
        """Update field bundle in-place (bundle tak ada → diabaikan)."""
        if bundle_id in self._data:
            self._data[bundle_id].update(kwargs)


def build_agents(scenario: Scenario, client: MESClient, recorder: Recorder) -> list[BaseAgent]:
    """Rakit agent sesuai ``scenario.factory``.

    Operator & QC memakai LLM (satu :class:`OllamaClient` dibagi); cutting,
    inventory, supervisor, dan ppic scripted. ``tool_set`` diambil dari
    ``scenario.tool_set[role]`` (fallback ``[]`` → agent scripted **idle**,
    ``act`` mengembalikan ``None``).
    """

    factory = scenario.factory
    tool_set = scenario.tool_set or {}
    llm_client = OllamaClient(
        base_url=scenario.llm.base_url,
        model=scenario.llm.model,
        temperature=scenario.llm.temperature,
    )
    agents: list[BaseAgent] = []

    for line in range(1, factory.lines + 1):
        for i in range(1, factory.operators_per_line + 1):
            agent = OperatorAgent(
                f"op-{line}-{i}", client, recorder,
                tool_set.get("operator", []), llm_client=llm_client,
            )
            agent.line_id = line
            agents.append(agent)
        for i in range(1, factory.qc_per_line + 1):
            agent = QCAgent(
                f"qc-{line}-{i}", client, recorder,
                tool_set.get("qc", []), llm_client=llm_client,
            )
            agent.line_id = line
            agents.append(agent)

    for role, count in (
        ("cutting", factory.cutting),
        ("inventory", factory.inventory),
        ("supervisor", factory.supervisor),  # scripted dulu; LLM ditunda ke scale
        ("ppic", factory.ppic),
    ):
        for i in range(1, count + 1):
            agents.append(
                ScriptedAgent(f"{role}-{i}", role, client, recorder, tool_set.get(role, []))
            )
    return agents


def pick_agents_for_event(event: Event, agents: list[BaseAgent]) -> list[BaseAgent]:
    """Pilih agent relevan untuk sebuah event (mapping sederhana event.type → role)."""

    etype = getattr(event, "type", None)
    payload = getattr(event, "payload", None) or {}

    if etype == "ORDER_IN":
        # FASE 3.4 — ORDER_IN memicu pembuatan WorkOrder + Bundle oleh `cutting`
        # (order baru → WO → bundle → lini produksi). PPIC tidak lagi ikut di sini;
        # ia tetap menangani URGENT.
        return [a for a in agents if a.role == "cutting"]

    if etype == "DOWNTIME":
        line = payload.get("line")
        return [a for a in agents
                if a.role == "operator" and (line is None or a.line_id == line)]

    if etype == "DEFECT":
        line = payload.get("line")
        qcs = [a for a in agents if a.role == "qc" and a.line_id == line]
        if not qcs:
            qcs = [a for a in agents if a.role == "qc"]
        return qcs[:1]

    if etype == "BUNDLE_ASSIGNED":
        # Operator line terkait; kalau tak match line → semua operator.
        line = payload.get("line")
        ops = [a for a in agents
               if a.role == "operator" and (line is None or a.line_id == line)]
        if not ops:
            ops = [a for a in agents if a.role == "operator"]
        if not ops:
            return []
        # FASE 3.3 — round-robin + lewati operator yang sedang sibuk (in-flight):
        # bundle berbeda pada tick yang sama dilayani operator berbeda.
        free = [a for a in ops if a.id not in _BUSY_OPERATOR_IDS]
        if not free:
            return []  # semua operator sedang mengerjakan bundle lain
        return [free[next(_OPERATOR_RR) % len(free)]]

    if etype == "URGENT":
        ppics = [a for a in agents if a.role == "ppic"]
        if ppics:
            return [ppics[next(_PPIC_RR) % len(ppics)]]
        return []

    return []


async def _act_safe(agent: BaseAgent, event: Event) -> bool:
    """Jalankan ``act`` satu agent; kegagalan dicatat & TIDAK menghentikan dunia."""

    try:
        result = await agent.act(event)
    except Exception as exc:  # noqa: BLE001 - satu agent gagal != run gagal
        logger.warning(
            "agent %s gagal act(%s): %s",
            getattr(agent, "id", "?"), getattr(event, "type", "?"), exc,
        )
        return False
    return result is not None


async def _dispatch(
    event: Event, agents: list[BaseAgent], busy_bundle_ids: set
) -> int:
    """Kirim event ke semua agent relevan secara paralel; kembalikan #aksi sukses.

    **In-flight guard** (FASE 2.4): event ber-``bundle_id`` yang sedang di-action
    (ada di ``busy_bundle_ids``) di-skip supaya N event/agent tidak menembak bundle
    yang sama bersamaan (race → 1 sukses, sisanya error). Set ditambah **sebelum**
    ``await`` dan selalu di-``discard`` di ``finally``.
    """

    bundle_id = (getattr(event, "payload", None) or {}).get("bundle_id")
    guarded = bundle_id not in (None, "")
    if guarded:
        if bundle_id in busy_bundle_ids:
            logger.info("skip event: bundle %s sedang di-action (in-flight).", bundle_id)
            return 0
        busy_bundle_ids.add(bundle_id)
    try:
        relevant = pick_agents_for_event(event, agents)
        if not relevant:
            return 0
        # FASE 3.3 — tandai operator in-flight SEBELUM await supaya `_dispatch`
        # lain (tick yang sama, bundle berbeda) memilih operator lain.
        newly_busy = [
            a.id
            for a in relevant
            if a.role == "operator" and a.id not in _BUSY_OPERATOR_IDS
        ]
        _BUSY_OPERATOR_IDS.update(newly_busy)
        try:
            results = await asyncio.gather(*[_act_safe(a, event) for a in relevant])
            return sum(1 for ok in results if ok)
        finally:
            _BUSY_OPERATOR_IDS.difference_update(newly_busy)
    finally:
        if guarded:
            busy_bundle_ids.discard(bundle_id)


#: State bundle yang boleh menerima aksi (selain ini = terminal → transisi invalid).
ACTIONABLE_STATES = ("DRAFT", "CUTTING", "SEWING", "QC", "FINISHING")


async def _bootstrap(client: MESClient) -> BundleRegistry:
    """Ambil daftar bundle ACTIONABLE dari MES → :class:`BundleRegistry`.

    ``GET /garmen/bundles/`` → ``rows``; hanya bundle ber-state ``ACTIONABLE_STATES``
    (bukan DONE/CANCELLED) yang dipakai — bundle terminal tak bisa di-action
    (Django membalas 400 transisi invalid). Kosong → pesan + registry kosong.
    """

    try:
        response = await client.get("/garmen/bundles/")
    except Exception as exc:  # noqa: BLE001 - bootstrap tak boleh mematikan run
        logger.warning("bootstrap: GET bundles gagal (%s).", exc)
        return BundleRegistry([])
    if response.status_code != 200:
        logger.warning("bootstrap: GET bundles -> %s.", response.status_code)
        return BundleRegistry([])

    try:
        rows = response.json().get("rows") or []
    except Exception:  # noqa: BLE001 - respons tak terduga
        logger.warning("bootstrap: respons bundles tak terduga.")
        return BundleRegistry([])

    all_bundles = [
        {
            "id": row.get("id"),
            "version": row.get("version"),
            "state": row.get("state"),
            "allowed_actions": row.get("allowed_actions") or [],
            # FASE 3.3 — display/KPI saja (Django TIDAK memindahkan WC saat aksi;
            # field ini hanya ikut dilaporkan, bukan dasar logika).
            "current_work_center_code": row.get("current_work_center_code"),
        }
        for row in rows
        if isinstance(row, dict) and row.get("id") is not None
    ]
    bundles = [b for b in all_bundles if b["state"] in ACTIONABLE_STATES]

    if not bundles:
        print("WARNING: tidak ada bundle actionable. Semua bundle DONE/CANCELLED.")
        print("Simulator akan idle. Reset bundle ke DRAFT via Django shell dulu.")
        return BundleRegistry([])

    print(f"Bootstrap: {len(bundles)} bundle actionable dari {len(all_bundles)}.")
    return BundleRegistry(bundles)


#: Endpoint probe auth (FASE 3.1.1). ``/garmen/bundles/`` = ``AllowAny`` → selalu
#: 200 walau cookie kedaluwarsa (tidak bisa mendeteksi), jadi probe memakai
#: endpoint ``IsAuthenticated`` (GET, tanpa efek samping) ini supaya 401/403
#: benar-benar menandakan cookie tak valid.
_AUTH_PROBE_PATH = "/audit/products-missing-odoo-id/"


async def _ensure_auth(scenario: Scenario, client: MESClient) -> bool:
    """Pastikan cookie klien masih valid; refresh via login admin bila 401/403.

    FASE 3.1.1 (multi-hari): ``sessionid`` bisa kedaluwarsa. Kalau probe 401/403
    DAN ``DJANGO_SIM_USERNAME``/``DJANGO_SIM_PASSWORD`` tersedia → login ulang ke
    ``/admin/login/`` dan ganti cookie klien.

    Return ``True`` = lanjut; ``False`` = refresh gagal (pemanggil SKIP hari itu).
    """

    try:
        probe = await client.get(_AUTH_PROBE_PATH)
    except Exception as exc:  # noqa: BLE001 - probe tak boleh mematikan run
        logger.warning("auth probe gagal (%s) — lanjut tanpa penyegaran.", exc)
        return True
    if probe.status_code not in (401, 403):
        return True

    logger.warning(
        "auth probe -> %s (cookie tak valid); mencoba refresh sesi.",
        probe.status_code,
    )
    username = os.environ.get("DJANGO_SIM_USERNAME", "")
    password = os.environ.get("DJANGO_SIM_PASSWORD", "")
    new_cookie = await refresh_session_cookie(
        scenario.django.base_url, username, password
    )
    if not new_cookie:
        logger.warning(
            "refresh cookie gagal (kredensial kosong / login ditolak) — SKIP hari."
        )
        return False
    client.set_auth_cookie(new_cookie)
    scenario.django.auth.cookie = new_cookie
    logger.info("cookie sesi diperbarui via login admin.")
    return True


async def _run_one_shift(scenario: Scenario, day_number: int, day_date: date) -> dict:
    """Jalankan SATU hari (shift) — client/recorder/agent FRESH; Django = truth.

    FASE 3.1: tiap hari mem-bootstrap ULANG (resume bundle non-terminal dari hari
    sebelumnya), me-reseed ``EventGenerator`` (pola event beda per hari), dan
    memakai ``day_date`` sebagai basis timestamp clock.
    """

    auth_headers: dict = {}
    if scenario.django.auth.cookie:
        auth_headers["Cookie"] = scenario.django.auth.cookie
    if scenario.django.auth.token:
        auth_headers["Authorization"] = f"Bearer {scenario.django.auth.token}"
    client = MESClient(
        scenario.django.base_url, scenario.django.api_prefix, auth_headers=auth_headers
    )

    # Path recorder per hari: sisipkan "_day{N}" ke pattern skenario.
    output_pattern = scenario.recording.output.replace(
        "{scenario}", f"{scenario.scenario}_day{day_number}"
    )
    recorder = Recorder(scenario.scenario, output_pattern)
    llm_client = None
    try:
        agents = build_agents(scenario, client, recorder)
        # llm_client dibagi operator/qc — ambil satu untuk ditutup nanti.
        llm_client = next(
            (a.llm_client for a in agents if getattr(a, "llm_client", None)), None
        )

        # FASE 3.1.1: pastikan cookie valid SEBELUM bootstrap (endpoint sync WIP
        # = IsAuthenticated; bootstrap bundle sendiri AllowAny).
        if not await _ensure_auth(scenario, client):
            print(f"SKIP DAY {day_number}: auth tidak valid & refresh gagal.")
            return {
                "day": day_number,
                "date": day_date.isoformat(),
                "total_actions": 0,
                "note": "auth unavailable",
            }

        # Bootstrap FRESH tiap hari → resume bundle non-terminal dari hari lalu.
        registry = await _bootstrap(client)
        if not registry.all():
            print(f"SKIP DAY {day_number}: tidak ada bundle actionable.")
            return {"day": day_number, "date": day_date.isoformat(),
                    "total_actions": 0, "note": "no actionable bundles"}
        # Semua agent pegang REFERENCE registry yang sama (anti-stale).
        for agent in agents:
            agent.bundle_registry = registry
            agent.timing = scenario.timing

        start, end = scenario.clock.duration.split("-")
        clock = SimulationClock(
            start=start.strip(),
            end=end.strip(),
            speed=scenario.clock.speed,
            fatigue_hours=scenario.fatigue.slowdown_hours,
            slowdown_factor=scenario.fatigue.slowdown_factor,
        )
        # Label hari (G3) TANPA mengubah world/clock.py: set base_date dari luar.
        clock.base_date = day_date

        # Reseed per hari (G2): pola event BEDA antar hari.
        event_gen = EventGenerator(
            scenario,
            rng=random.Random(f"{scenario.scenario}-{day_number}"),
            available_bundles=registry.all(),
        )
        start_ts = datetime.combine(clock.base_date, clock.start_time)

        actions = 0
        busy_bundle_ids: set = set()  # in-flight guard (FASE 2.4)
        # Event awal (ORDER_IN) — sekali di awal shift, bukan per tick.
        initial = event_gen.initial_events(start_ts)
        if initial:
            actions += sum(await asyncio.gather(
                *[_dispatch(e, agents, busy_bundle_ids) for e in initial]
            ))
        for ts in clock.tick():
            events = event_gen.events_at(ts)
            if events:
                actions += sum(await asyncio.gather(
                    *[_dispatch(e, agents, busy_bundle_ids) for e in events]
                ))
            if ts.minute == 0:  # progress tiap 60 menit sim
                print(f"[day {day_number}] {ts.strftime('%H:%M')} — {actions} actions",
                      file=sys.stderr)
            await asyncio.sleep(clock.apply_fatigue(ts, clock.real_sleep_per_tick))
    finally:
        recorder.close()
        await client.close()
        if llm_client is not None:
            await llm_client.close()

    kpi = compute_kpi(recorder.path)
    kpi_path = Path(recorder.path).with_name(Path(recorder.path).stem + "_kpi.json")
    kpi_path.write_text(json.dumps(kpi, indent=2, ensure_ascii=False), encoding="utf-8")
    kpi["day"] = day_number
    kpi["date"] = day_date.isoformat()
    return kpi


async def run_scenario(scenario_path: str, days=None) -> dict:
    """Jalankan skenario MULTI-HARI (FASE 3.1): loop ``scenario.days`` shift.

    Django tetap source of truth; TIDAK ada state simulator yang dipersist. Tulis
    KPI per hari + agregat ``<dir_recording>/<scenario>_kpi_all.json``. ``days``
    (opsional) menimpa ``scenario.days``.
    """

    scenario = load(scenario_path)
    if days is not None:
        scenario.days = max(int(days), 1)

    start_date = (
        date.fromisoformat(scenario.start_date) if scenario.start_date else date.today()
    )

    daily_kpis: list[dict] = []
    for day in range(scenario.days):
        day_date = start_date + timedelta(days=day)
        daily_kpis.append(await _run_one_shift(scenario, day, day_date))

    aggregate = {
        "scenario": scenario.scenario,
        "days": scenario.days,
        "start_date": start_date.isoformat(),
        "total_actions": sum(k.get("total_actions", 0) for k in daily_kpis),
        "per_day": daily_kpis,
    }
    agg_path = (
        Path(scenario.recording.output).parent / f"{scenario.scenario}_kpi_all.json"
    )
    agg_path.parent.mkdir(parents=True, exist_ok=True)
    agg_path.write_text(
        json.dumps(aggregate, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("KPI agregat multi-hari ditulis ke %s", agg_path)
    return aggregate


@app.command()
def main(
    scenario: str = typer.Option("mini_1line", "--scenario", "-s"),
    scenario_dir: str = typer.Option("simulator/scenarios", "--dir", "-d"),
    days: int = typer.Option(None, "--days", "-n", help="Override scenario.days"),
) -> None:
    """Jalankan skenario simulator (multi-hari)."""
    path = Path(scenario_dir) / f"{scenario}.yaml"
    kpi = asyncio.run(run_scenario(str(path), days=days))
    typer.echo(json.dumps(kpi, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    app()