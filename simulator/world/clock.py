"""Clock simulasi — kompresi waktu (mis. 07:00→17:00 pada 60x) — fase M1.

Desain sengaja **sinkron**: tidak ada ``asyncio`` di sini. Generator
:meth:`SimulationClock.tick` murni (tanpa ``sleep``) supaya bisa dikonsumsi
orchestrator/agent dengan strategi pacing masing-masing. Untuk pemakaian
sederhana, ``__main__`` memakai ``time.sleep`` biasa.

Istilah:

* **tick** = 1 menit waktu *sim*. Untuk shift 10 jam → 600 tick.
* ``duration_real_seconds`` = total detik sim ÷ ``speed`` (lama run dinding).
* ``real_sleep_per_tick`` = 60 ÷ ``speed`` detik (tempo 1 tick).

Kurva kelelahan di-hardcode sebagai data (jam + faktor), bukan diputuskan LLM:
:meth:`is_fatigue_hour` mendeteksi jam lelah, :meth:`apply_fatigue` memperlambat
delay pada jam tersebut (``delay / slowdown_factor``).
"""

from __future__ import annotations

import os
import time as _time
from datetime import date, datetime, time, timedelta
from typing import Iterator, Optional, Sequence

__all__ = ("SimulationClock",)


def _parse_hhmm(value: str) -> time:
    """Parse ``"HH:MM"`` → :class:`datetime.time` (raise ``ValueError`` bila salah)."""

    try:
        hh, mm = str(value).split(":")
        return time(int(hh), int(mm))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Format jam harus 'HH:MM', dapat: {value!r}") from exc


class SimulationClock:
    """Jam kerja terkompresi dengan generator tick per menit sim."""

    def __init__(
        self,
        start: str = "07:00",
        end: str = "17:00",
        speed: int = 60,
        fatigue_hours: Optional[Sequence[str]] = None,
        slowdown_factor: float = 1.0,
    ) -> None:
        if speed <= 0:
            raise ValueError(f"speed harus > 0, dapat: {speed}")

        self.start_time = _parse_hhmm(start)
        self.end_time = _parse_hhmm(end)
        self.speed = int(speed)
        if self.end_time <= self.start_time:
            raise ValueError(
                f"end ({end}) harus setelah start ({start}) dalam satu hari."
            )

        #: Jam-jam lelah sebagai himpunan "HH:MM" (mis. {"11:00", "15:00"}).
        self.fatigue_hours = frozenset(str(h) for h in (fatigue_hours or ()))
        self.slowdown_factor = float(slowdown_factor)

        #: Tanggal dasar timestamp sim (deterministik dalam satu hari).
        self.base_date = date.today()

    # ------------------------------------------------------------------ ukuran
    @property
    def duration_sim_minutes(self) -> int:
        """Total menit waktu sim (mis. 07:00→17:00 = 600)."""

        start_dt = datetime.combine(self.base_date, self.start_time)
        end_dt = datetime.combine(self.base_date, self.end_time)
        return int((end_dt - start_dt).total_seconds() // 60)

    @property
    def duration_real_seconds(self) -> float:
        """Lama run dinding: total detik sim ÷ speed."""

        return self.duration_sim_minutes * 60 / self.speed

    @property
    def real_sleep_per_tick(self) -> float:
        """Jeda dinding per tick (1 menit sim): 60 ÷ speed detik."""

        return 60 / self.speed

    # -------------------------------------------------------------------- tick
    def tick(self) -> Iterator[datetime]:
        """Yield timestamp sim tiap 1 menit, dari ``start`` **sampai sebelum** ``end``.

        Untuk 07:00→17:00 menghasilkan 600 nilai (07:00, 07:01, …, 16:59);
        batas ``end`` (17:00) adalah akhir shift, bukan durasi, sehingga tidak
        ikut di-yield. Generator ini tidak melakukan ``sleep``.
        """

        cursor = datetime.combine(self.base_date, self.start_time)
        end_dt = datetime.combine(self.base_date, self.end_time)
        while cursor < end_dt:
            yield cursor
            cursor += timedelta(minutes=1)

    # ---------------------------------------------------------------- fatigue
    def is_fatigue_hour(self, ts: datetime) -> bool:
        """``True`` kalau jam dari ``ts`` ada di ``fatigue_hours``."""

        return ts.strftime("%H:%M") in self.fatigue_hours

    def apply_fatigue(self, ts: datetime, delay: float) -> float:
        """Perlambat ``delay`` pada jam lelah: ``delay / slowdown_factor``.

        Di luar jam lelah mengembalikan ``delay`` apa adanya.
        """

        if self.is_fatigue_hour(ts):
            return delay / self.slowdown_factor
        return delay


def _print_tick(clock: SimulationClock, ts: datetime) -> None:
    """Cetak satu baris timestamp + tag ``[FATIGUE]`` bila perlu."""

    tag = "  [FATIGUE]" if clock.is_fatigue_hour(ts) else ""
    print(f"{ts.strftime('%H:%M')}{tag}")


def _demo() -> None:
    """Demo: cetak timestamp tiap 60 menit sim dari 07:00 s/d 17:00.

    Default **instan** (pacing via ``time.sleep`` dimatikan) supaya bisa
    diinspeksi cepat. Set env ``SIM_CLOCK_PACE=1`` untuk tempo dinding nyata
    (``real_sleep_per_tick`` detik per baris).
    """

    clock = SimulationClock(
        start="07:00",
        end="17:00",
        speed=60,
        fatigue_hours=("11:00", "15:00"),
        slowdown_factor=0.7,
    )
    pace = os.environ.get("SIM_CLOCK_PACE") == "1"

    print(
        f"# {clock.duration_sim_minutes} menit sim | "
        f"{clock.duration_real_seconds:.0f}s real | "
        f"{clock.real_sleep_per_tick:.2f}s/tick"
    )

    end_dt = datetime.combine(clock.base_date, clock.end_time)
    for ts in clock.tick():
        if ts.minute != 0:  # hanya tiap 60 menit sim
            continue
        _print_tick(clock, ts)
        if pace:
            _time.sleep(clock.real_sleep_per_tick)

    # Baris penutup 17:00 (batas shift — di luar 600 tick utama).
    _print_tick(clock, end_dt)


if __name__ == "__main__":
    _demo()
