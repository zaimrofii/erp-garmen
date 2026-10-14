"""Admin ``AuditLog`` — **read-only** (audit trail tidak boleh diubah/dihapus).

Baris audit dibuat oleh kode (``AuditLogger``), bukan diketik di admin; karena
itu tambah/ubah/hapus dimatikan dan seluruh field hanya bisa dibaca.
"""

from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Tampilan audit (read-only) untuk investigasi selisih produksi."""

    list_display = (
        "id",
        "timestamp",
        "user",
        "action",
        "resource",
        "resource_id",
        "result",
        "request_id",
        "ip_address",
    )
    list_filter = ("result", "action", "resource")
    search_fields = ("resource_id", "request_id", "action", "user_agent")
    date_hierarchy = "timestamp"
    list_select_related = ("user",)
    #: Semua field hanya-baca (dihitung dari model supaya tidak pernah ketinggalan).
    readonly_fields = tuple(field.name for field in AuditLog._meta.fields)

    def has_add_permission(self, request) -> bool:
        """AuditLog hanya dibuat aplikasi, bukan dari admin."""
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        """Read-only: audit tidak boleh diubah."""
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        """Audit trail tidak boleh dihapus dari admin."""
        return False
