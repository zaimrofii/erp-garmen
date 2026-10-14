"""Event generator **rule-based** (dadu probabilitas, bukan LLM) — fase M1.

``EventGenerator`` memutuskan event dunia (downtime, defect, urgent, cancel,
bundle_assigned) dari blok ``anomaly`` skenario. Ia **tidak** memakai LLM: LLM
hanya dipakai agent (operator/QC) untuk keputusan ambigu.

Catatan desain:

* ``rng`` bisa disuntik (``random.Random``) untuk **reproducibility**; kalau
  tidak diberi, seed diturunkan dari nama skenario sehingga run yang sama
  menghasilkan urutan dadu yang sama (replay).
* :meth:`next_event` mengembalikan **satu** event (yang pertama lolos) atau
  ``None``; :meth:`events_at` mengembalikan **semua** event yang lolos pada
  tick yang sama — karena beberapa anomali boleh muncul bersamaan.
* ``ORDER_IN`` dibuat **sekali di awal run** lewat :meth:`initial_events`,
  bukan di-roll per tick.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

from ..config import Scenario

__all__ = ("Event", "EventGenerator", "EventType")

#: Jenis event yang dikenal dunia simulasi.
EventType = Literal[
    "ORDER_IN", "DOWNTIME", "URGENT", "DEFECT", "CANCEL", "BUNDLE_ASSIGNED"
]

#: Event penugasan bundle ke operator (memicu aksi operator).
EVENT_BUNDLE_ASSIGNED = "BUNDLE_ASSIGNED"

#: Urutan pengecekan anomali per tick (prioritas tampil untuk ``next_event``).
_ANOMALY_ORDER: tuple[str, ...] = (
    "DOWNTIME", "DEFECT", EVENT_BUNDLE_ASSIGNED, "URGENT", "CANCEL"
)


@dataclass
class Event:
    """Satu kejadian dunia pada satu waktu sim."""

    id: str
    type: EventType
    timestamp_sim: datetime
    payload: dict


class EventGenerator:
    """Roll anomali per tick dari probabilitas skenario (injectable RNG)."""

    def __init__(
        self,
        scenario: Scenario,
        rng: Optional[random.Random] = None,
        available_bundles: Optional[list[dict]] = None,
    ) -> None:
        self.scenario = scenario
        # Seed dari nama skenario → replay reproducible (kalau rng tidak disuntik).
        self.rng = rng if rng is not None else random.Random(scenario.scenario)
        #: Bundle nyata dari MES (diisi orchestrator via bootstrap), dipakai untuk
        #: memilih ``bundle_id`` pada event DEFECT. Kosong → DEFECT tidak di-generate.
        self.available_bundles: list[dict] = list(available_bundles or [])

    # --------------------------------------------------------------- probabilitas
    def _prob(self, event_type: str) -> float:
        """Probabilitas satu jenis anomali dari blok ``anomaly``."""

        anomaly = self.scenario.anomaly
        return {
            "DOWNTIME": anomaly.downtime_prob,
            "DEFECT": anomaly.defect_prob,
            EVENT_BUNDLE_ASSIGNED: anomaly.bundle_assigned_prob,
            "URGENT": anomaly.urgent_order_prob,
            "CANCEL": anomaly.cancel_order_prob,
        }[event_type]

    # --------------------------------------------------------------- konstruksi
    @staticmethod
    def _make(event_type: EventType, ts_sim: datetime, payload: dict) -> Event:
        return Event(
            id=str(uuid.uuid4()),
            type=event_type,
            timestamp_sim=ts_sim,
            payload=payload,
        )

    def _payload_for(self, event_type: str) -> dict:
        """Payload contoh untuk anomali (dipilih lewat rng untuk variasi).

        ``DEFECT`` menyertakan ``bundle_id`` dari ``available_bundles`` (bundle
        NYATA di MES) supaya aksi QC bisa menargetkan bundle yang valid.
        """

        if event_type == "DOWNTIME":
            return {"wc_id": self.rng.randint(1, 3), "reason": "machine_stop"}
        if event_type == "DEFECT":
            bundle = self.rng.choice(self.available_bundles)
            return {
                "bundle_id": bundle.get("id"),
                "qty": self.rng.randint(1, 5),
                "reason": self.rng.choice(("stitch", "fabric", "measurement")),
            }
        if event_type == EVENT_BUNDLE_ASSIGNED:
            bundle = self.rng.choice(self.available_bundles)
            return {
                "bundle_id": bundle.get("id"),
                "wc_id": "SEWING-1",
                "operator_id": None,
            }
        if event_type == "URGENT":
            return {"order_ref": "SO-FASTTRACK", "priority": "FAST_TRACK"}
        if event_type == "CANCEL":
            return {"reason": "cancelled_by_customer"}
        return {}

    def _assigned_events(self, ts_sim: datetime) -> list[Event]:
        """N event ``BUNDLE_ASSIGNED`` untuk bundle **BERBEDA** pada satu tick.

        FASE 3.3 (overlap antar-bundle): ``N`` di-roll ``1..bundle_assigned_max_per_tick``
        lalu di-clamp ke jumlah bundle tersedia (tanpa pengulangan — tiap event
        membawa ``bundle_id`` yang unik dalam tick yang sama). Payload sama dengan
        :meth:`_payload_for` (``wc_id``/``operator_id``).
        """

        max_n = max(int(self.scenario.anomaly.bundle_assigned_max_per_tick), 1)
        n = min(self.rng.randint(1, max_n), len(self.available_bundles))
        if n <= 0:
            return []

        # `sample` → bundle berbeda (tanpa duplikat) dalam satu tick.
        chosen = self.rng.sample(self.available_bundles, n)
        return [
            self._make(
                EVENT_BUNDLE_ASSIGNED,
                ts_sim,
                {
                    "bundle_id": bundle.get("id"),
                    "wc_id": "SEWING-1",
                    "operator_id": None,
                },
            )
            for bundle in chosen
        ]

    # ------------------------------------------------------------------ publik
    def initial_events(self, ts_sim: datetime) -> list[Event]:
        """Event awal run — ``ORDER_IN`` (dipanggil **sekali**, bukan per tick)."""

        payload = {
            "order_ref": f"SO-{self.scenario.scenario.upper()}-001",
            "style": "BASIC-TEE",
            "qty": 120,
            "lines": self.scenario.factory.lines,
        }
        return [self._make("ORDER_IN", ts_sim, payload)]

    def order_in_at(self, ts_sim: datetime) -> Optional[Event]:
        """Event ``ORDER_IN`` kalau ``ts_sim`` jatuh pada salah satu ``order_in_hours``.

        FASE 3.4 — order baru datang kapan saja (mis. 08:00/11:00/14:00), bukan
        hanya sekali di awal shift. ``None`` kalau jam tidak cocok (atau daftar
        jam kosong → perilaku lama: hanya ``initial_events``).
        """

        hours = self.scenario.anomaly.order_in_hours or []
        if ts_sim.strftime("%H:%M") not in hours:
            return None
        payload = {
            "order_ref": f"SO-{ts_sim:%Y%m%d}-{self.rng.randint(1000, 9999)}",
            "style": "BASIC-TEE",
            "qty": self.rng.randint(50, 200),
            "lines": 1,
        }
        return self._make("ORDER_IN", ts_sim, payload)

    def events_at(self, ts_sim: datetime) -> list[Event]:
        """Semua anomali yang lolos pada ``ts_sim`` (urutan: DOWNTIME→CANCEL).

        Beberapa anomali boleh muncul di tick yang sama → bisa >1 event, bisa
        kosong (``[]``).
        """

        fired: list[Event] = []
        # FASE 3.4 — order baru pada jam terjadwal (checkout 08:00/11:00/14:00).
        order_in = self.order_in_at(ts_sim)
        if order_in is not None:
            fired.append(order_in)
        for event_type in _ANOMALY_ORDER:
            # DEFECT & BUNDLE_ASSIGNED menargetkan bundle NYATA (bundle_id) →
            # tanpa bundle, skip.
            if (
                event_type in ("DEFECT", EVENT_BUNDLE_ASSIGNED)
                and not self.available_bundles
            ):
                continue
            if self.rng.random() >= self._prob(event_type):
                continue
            if event_type == EVENT_BUNDLE_ASSIGNED:
                # FASE 3.3: N bundle BERBEDA per tick (overlap antar-bundle).
                fired.extend(self._assigned_events(ts_sim))
            else:
                fired.append(self._make(event_type, ts_sim, self._payload_for(event_type)))
        return fired

    def next_event(self, ts_sim: datetime) -> Optional[Event]:
        """Event pertama yang lolos pada ``ts_sim`` (atau ``None`` bila tidak ada).

        Untuk mengambil **semua** event pada tick yang sama, pakai
        :meth:`events_at`.
        """

        fired = self.events_at(ts_sim)
        return fired[0] if fired else None
