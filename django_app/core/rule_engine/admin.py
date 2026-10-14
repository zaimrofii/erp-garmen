"""Registrasi admin rule engine (kondisi & aksi sebagai inline)."""

from django.contrib import admin

from .models import Rule, RuleAction, RuleCondition


class RuleConditionInline(admin.TabularInline):
    """Kondisi di-edit menyatu dengan rule-nya."""

    model = RuleCondition
    extra = 1
    ordering = ("order",)


class RuleActionInline(admin.TabularInline):
    """Aksi di-edit menyatu dengan rule-nya."""

    model = RuleAction
    extra = 1


@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "priority", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "description")
    ordering = ("priority", "code")
    inlines = (RuleConditionInline, RuleActionInline)
