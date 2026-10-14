"""Admin ``PrintJob`` — **read-only** (audit hasil cetak).

Print job dibuat oleh kode (generator + backend), bukan diketik manual di admin;
karena itu tambah/ubah/hapus dimatikan dan semua field hanya bisa dibaca.
"""

from django.contrib import admin

from .models import PrintJob


@admin.register(PrintJob)
class PrintJobAdmin(admin.ModelAdmin):
    """Tampilan audit PrintJob (read-only)."""

    list_display = (
        "id",
        "resource",
        "resource_id",
        "backend",
        "status",
        "bytes_sent",
        "ref",
        "created_at",
    )
    list_filter = ("resource", "status", "backend")
    search_fields = ("resource_id", "ref", "last_error")
    readonly_fields = (
        "resource",
        "resource_id",
        "backend",
        "status",
        "bytes_sent",
        "last_error",
        "ref",
        "created_at",
        "updated_at",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request) -> bool:
        """PrintJob hanya dibuat oleh kode, bukan dari admin."""
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        """Read-only: tidak ada perubahan lewat admin."""
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        """Audit trail tidak boleh dihapus dari admin."""
        return False
