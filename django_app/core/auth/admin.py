"""Registrasi admin untuk app `core.auth` (role & user custom)."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Role, User


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    """CRUD role — role adalah data, jadi bisa diatur lewat admin."""

    list_display = ("code", "name", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "description")
    ordering = ("code",)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """User custom: tambah kolom & fieldset `role` ke UserAdmin bawaan."""

    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "role",
        "operator_code",
        "is_staff",
        "is_active",
    )
    list_filter = DjangoUserAdmin.list_filter + ("role",)
    search_fields = DjangoUserAdmin.search_fields + ("operator_code",)
    fieldsets = DjangoUserAdmin.fieldsets + (
        # `operator_code` (F6.1): boleh dibaca admin, tetapi kosongkan untuk
        # membiarkannya di-generate otomatis saat simpan (role OPERATOR/QC).
        ("Garmen", {"fields": ("role", "operator_code")}),
    )
