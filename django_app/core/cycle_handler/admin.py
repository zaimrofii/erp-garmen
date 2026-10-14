"""Registrasi admin cycle handler (definisi siklus + step + instance).

Definisi rework = konfigurasi, jadi harus bisa diatur lewat admin tanpa deploy
ulang (prinsip blueprint: "semua aturan = konfigurasi, bukan kode").
"""

from django.contrib import admin

from .models import CycleDefinition, CycleInstance, CycleStep


class CycleStepInline(admin.TabularInline):
    """Step siklus di-edit menyatu dengan definisinya."""

    model = CycleStep
    extra = 1
    ordering = ("order",)


@admin.register(CycleDefinition)
class CycleDefinitionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "max_iterations", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "description")
    ordering = ("code",)
    inlines = (CycleStepInline,)


@admin.register(CycleInstance)
class CycleInstanceAdmin(admin.ModelAdmin):
    list_display = (
        "definition",
        "ref_type",
        "ref_id",
        "current_step",
        "iteration_count",
        "status",
        "started_at",
    )
    list_filter = ("status", "definition", "ref_type")
    search_fields = ("ref_id", "ref_type")
    readonly_fields = ("started_at", "updated_at")
