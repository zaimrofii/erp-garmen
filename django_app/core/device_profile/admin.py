"""Registrasi admin device profile (profil perangkat + binding per work center)."""

from django.contrib import admin

from .models import DeviceBinding, DeviceProfile


@admin.register(DeviceProfile)
class DeviceProfileAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "description")
    ordering = ("code",)


@admin.register(DeviceBinding)
class DeviceBindingAdmin(admin.ModelAdmin):
    list_display = ("wc_code", "device_profile", "user", "created_at", "last_seen_at")
    list_filter = ("device_profile",)
    search_fields = ("wc_code", "cookie_token", "user__username")
    ordering = ("-created_at",)
