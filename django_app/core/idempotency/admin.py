"""Registrasi admin idempotency record (read-only: untuk audit & debug)."""

from django.contrib import admin

from .models import IdempotencyRecord


@admin.register(IdempotencyRecord)
class IdempotencyRecordAdmin(admin.ModelAdmin):
    list_display = (
        "key",
        "resource",
        "resource_id",
        "action",
        "response_status",
        "created_at",
        "expires_at",
    )
    list_filter = ("resource", "action", "response_status")
    search_fields = ("key", "resource_id", "request_hash")
    ordering = ("-created_at",)
    readonly_fields = (
        "key",
        "resource",
        "resource_id",
        "action",
        "request_hash",
        "response_status",
        "response_body",
        "created_at",
        "expires_at",
    )

    def has_add_permission(self, request) -> bool:
        """Record dibuat service, bukan manual dari admin."""
        return False
