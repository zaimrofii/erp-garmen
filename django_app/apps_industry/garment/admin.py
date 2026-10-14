"""Registrasi admin model inti garmen (Sprint 2.1).

Minimal saja: list_display sederhana + filter/search yang jelas berguna supaya
data master produksi (work center, routing, line, bundle) bisa diisi/inspeksi
tanpa shell. Aturan bisnis tetap di service layer (Sprint 2.2), bukan di admin.
"""

from django.contrib import admin

from .models import (
    Bundle,
    BundleEvent,
    GarmentDeviceProfile,
    Order,
    OrderLine,
    ProcessRouting,
    ProductionLine,
    RoutingStep,
    ScrapAccumulator,
    WorkCenter,
    WorkOrder,
)


class OrderLineInline(admin.TabularInline):
    model = OrderLine
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "customer",
        "order_type",
        "state",
        "priority",
        "deadline",
        "updated_at",
    )
    list_filter = ("state", "order_type")
    search_fields = ("code", "customer__name")
    inlines = (OrderLineInline,)


@admin.register(OrderLine)
class OrderLineAdmin(admin.ModelAdmin):
    list_display = ("order", "product", "tag", "qty", "ticket_code")
    list_filter = ("tag",)
    search_fields = ("order__code", "product__code", "ticket_code")


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = ("code", "order_line", "state", "qty_planned", "qty_done")
    list_filter = ("state",)
    search_fields = ("code", "order_line__order__code")


@admin.register(WorkCenter)
class WorkCenterAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


class RoutingStepInline(admin.TabularInline):
    model = RoutingStep
    extra = 0
    fields = ("order", "code", "label", "is_initial", "is_terminal", "work_center")
    show_change_link = True
    ordering = ("order",)


@admin.register(ProcessRouting)
class ProcessRoutingAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    inlines = (RoutingStepInline,)


@admin.register(RoutingStep)
class RoutingStepAdmin(admin.ModelAdmin):
    list_display = (
        "routing",
        "order",
        "code",
        "label",
        "is_initial",
        "is_terminal",
        "work_center",
    )
    list_filter = ("routing", "is_initial", "is_terminal")
    search_fields = ("code", "label", "routing__code")
    filter_horizontal = ("allowed_next_steps",)


@admin.register(ProductionLine)
class ProductionLineAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    filter_horizontal = ("work_centers",)


class BundleEventInline(admin.TabularInline):
    """Jejak audit bundle: tampil read-only (append-only, tidak diubah dari admin)."""

    model = BundleEvent
    extra = 0
    can_delete = False
    fields = ("ts", "event_type", "actor", "text")
    readonly_fields = ("ts", "event_type", "actor", "text")
    ordering = ("-ts",)


@admin.register(Bundle)
class BundleAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "work_order",
        "size",
        "sku_variant",
        "qty",
        "qty_done",
        "state",
        "current_work_center",
        "version",
    )
    list_filter = ("state", "size")
    search_fields = ("code", "sku_variant", "work_order__code")
    readonly_fields = ("version", "created_at", "updated_at")
    inlines = (BundleEventInline,)


@admin.register(BundleEvent)
class BundleEventAdmin(admin.ModelAdmin):
    list_display = ("ts", "bundle", "event_type", "actor")
    list_filter = ("event_type",)
    search_fields = ("bundle__code", "event_type", "text")


@admin.register(ScrapAccumulator)
class ScrapAccumulatorAdmin(admin.ModelAdmin):
    list_display = (
        "work_center",
        "bundle",
        "qty",
        "rework_qty",
        "end_loss_qty",
        "reason",
        "updated_at",
    )
    list_filter = ("work_center",)
    search_fields = ("work_center__code", "bundle__code", "reason")


@admin.register(GarmentDeviceProfile)
class GarmentDeviceProfileAdmin(admin.ModelAdmin):
    list_display = ("device_profile", "work_center", "updated_at")
    list_filter = ("work_center",)
    search_fields = ("device_profile__code", "notes")
