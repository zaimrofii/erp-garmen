"""4 model AI Agent (D.1).

Kontrak: docs/ai/MCP-REGISTRY.md §6 (AIToolRegistry) dan
docs/ai/CHAT-CONTRACT.md §9 (decision log, HITL queue, semantic cache).
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class AIToolRegistry(models.Model):
    """Registry tool MCP — SATU sumber kebenaran (read-only di fase ini)."""

    name = models.SlugField("nama", max_length=64, unique=True)
    mcp_endpoint_url = models.CharField("endpoint MCP", max_length=200)
    schema = models.JSONField("schema", default=dict, blank=True)
    read_only = models.BooleanField("read-only", default=True)
    allowed_roles = models.JSONField("role diizinkan", default=list, blank=True)
    rate_limit_per_minute = models.PositiveIntegerField("rate limit/menit", default=60)
    circuit_breaker_threshold = models.PositiveIntegerField(
        "ambang circuit breaker", default=5
    )
    active = models.BooleanField("aktif", default=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        db_table = "ai_agent_aitoolregistry"
        verbose_name = "AI Tool Registry"
        verbose_name_plural = "AI Tool Registry"
        ordering = ["name"]

    def _validate(self) -> None:
        if not self.read_only:
            raise ValidationError(
                "read_only=False tidak didukung di Sprint D (write = fase terpisah)."
            )
        if self.pk:
            previous = (
                AIToolRegistry.objects.filter(pk=self.pk)
                .values_list("name", flat=True)
                .first()
            )
            if previous is not None and previous != self.name:
                raise ValidationError("name tool tidak boleh diubah setelah dibuat.")

    def clean(self) -> None:
        super().clean()
        self._validate()

    def save(self, *args, **kwargs):
        self._validate()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} (active={self.active})"


class AIDecisionLog(models.Model):
    """Log satu keputusan AI (dipakai observability + audit HITL)."""

    timestamp = models.DateTimeField("waktu", auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    channel = models.CharField("kanal", max_length=20, default="DESKTOP")
    query_text = models.TextField("pertanyaan")
    query_embedding_id = models.CharField(
        "embedding id", max_length=100, blank=True, default="", db_index=True
    )
    decision_gate_result = models.CharField("hasil decision gate", max_length=20)
    intent = models.CharField("intent", max_length=100, blank=True, default="")
    confidence_score = models.FloatField("confidence", null=True, blank=True)
    impact_score = models.CharField("impact", max_length=20, blank=True, default="")
    tools_called = models.JSONField("tool dipanggil", default=list, blank=True)
    context_tokens_in = models.PositiveIntegerField(default=0)
    context_tokens_out = models.PositiveIntegerField(default=0)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_cost_usd = models.DecimalField(
        "biaya (USD)", max_digits=10, decimal_places=6, default=0
    )
    cache_hit = models.BooleanField("cache hit", default=False)
    hit_similarity_score = models.FloatField("similarity", null=True, blank=True)
    hitl_required = models.BooleanField("butuh HITL", default=False)
    hitl_decision = models.CharField("keputusan HITL", max_length=20, blank=True, default="")
    hitl_approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    hitl_latency_seconds = models.PositiveIntegerField(null=True, blank=True)
    response_text = models.TextField("jawaban", blank=True, default="")
    model_used = models.CharField("model", max_length=50, blank=True, default="")
    latency_ms = models.PositiveIntegerField("latency (ms)", default=0)

    class Meta:
        db_table = "ai_agent_aidecisionlog"
        verbose_name = "AI Decision Log"
        verbose_name_plural = "AI Decision Logs"
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        return f"AIDecisionLog#{self.pk} {self.decision_gate_result}"


class AIHitlQueue(models.Model):
    """Antrean persetujuan manusia (Sprint F mengeksekusi decision)."""

    decision_log = models.ForeignKey(
        AIDecisionLog, on_delete=models.CASCADE, related_name="hitl_requests"
    )
    risk_level = models.CharField("risk", max_length=10)
    proposed_action = models.JSONField("aksi diusulkan", default=dict, blank=True)
    required_approver_role = models.CharField("role approver", max_length=20)
    channel = models.CharField("kanal", max_length=20)
    status = models.CharField("status", max_length=20, default="PENDING", db_index=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default="")
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_agent_aihitlqueue"
        verbose_name = "AI HITL Queue"
        verbose_name_plural = "AI HITL Queue"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"AIHitlQueue#{self.pk} {self.status}"


class AISemanticCache(models.Model):
    """Mirror ORM cache semantik (Redis = sumber utama)."""

    query_embedding_id = models.CharField(
        "embedding id", max_length=100, blank=True, default="", db_index=True
    )
    query_normalized_text = models.TextField("query normal", db_index=True)
    response_text = models.TextField("jawaban")
    tool_calls_signature = models.CharField(max_length=64, blank=True, default="")
    hit_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    invalidation_trigger = models.CharField(max_length=50, blank=True, default="")

    class Meta:
        db_table = "ai_agent_aisemanticcache"
        verbose_name = "AI Semantic Cache"
        verbose_name_plural = "AI Semantic Cache"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"AISemanticCache#{self.pk} hits={self.hit_count}"


__all__ = ("AIDecisionLog", "AIHitlQueue", "AISemanticCache", "AIToolRegistry")

