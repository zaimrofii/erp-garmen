"""Service layer app `apps_industry.garment` (Sprint 2.2).

Service = tempat aturan bisnis garmen. Model tetap tipis (data) dan engine
generik ada di `core/*`; service inilah yang merangkai keduanya:

  * `bundle_engine.BundleEngine`               — order line -> bundle (matriks size)
  * `overlap_release.OverlapRelease`           — baca DAG routing (step berikutnya)
  * `rework_loop.ReworkLoopHandler`            — siklus QC rework (core.cycle_handler)
  * `tag_router.TagRouter`                     — tag -> routing + kupon (core.rule_engine)
  * `capability_allocator.CapabilityAllocator` — line produksi yang mampu
  * `wc_queue.WCQueue`                         — queue virtual per work center
  * `two_stage_aggregator.TwoStageAggregator`  — payload stok dua tahap (WIP/FG)
  * `scrap_accumulator.ScrapAccumulatorService`— akumulasi scrap/rework/end-loss
  * `priority_scheduler.PriorityScheduler`     — skor prioritas + bundle berikutnya
  * `bottleneck_detector.BottleneckDetector`   — deteksi work center bottleneck

Semua service bersifat class-based dan stateless (tidak ada global state), serta
sinkron murni: belum ada pemanggilan event bus (itu Fase 3 saat endpoint jalan).
"""

from __future__ import annotations

from .exceptions import (
    BottleneckDetectorError,
    BundleEngineError,
    CapabilityAllocatorError,
    OverlapReleaseError,
    PrioritySchedulerError,
    ReworkLoopError,
    ScrapAccumulatorError,
    ServiceError,
    TagRouterError,
    TwoStageAggregatorError,
    WCQueueError,
)
from .bundle_engine import BundleEngine
from .capability_allocator import CapabilityAllocator
from .overlap_release import OverlapRelease
from .rework_loop import ReworkLoopHandler
from .tag_router import RoutingPlan, TagRouter
from .wc_queue import WCQueue
from .bottleneck_detector import BottleneckDetector, BottleneckReport
from .priority_scheduler import PriorityScheduler
from .scrap_accumulator import ScrapAccumulatorService
from .two_stage_aggregator import AggregatedMove, TwoStageAggregator

__all__ = [
    "AggregatedMove",
    "BottleneckDetector",
    "BottleneckDetectorError",
    "BottleneckReport",
    "BundleEngine",
    "BundleEngineError",
    "CapabilityAllocator",
    "CapabilityAllocatorError",
    "OverlapRelease",
    "OverlapReleaseError",
    "PriorityScheduler",
    "PrioritySchedulerError",
    "ReworkLoopError",
    "ReworkLoopHandler",
    "RoutingPlan",
    "ScrapAccumulatorError",
    "ScrapAccumulatorService",
    "ServiceError",
    "TagRouter",
    "TagRouterError",
    "TwoStageAggregator",
    "TwoStageAggregatorError",
    "WCQueue",
    "WCQueueError",
]

