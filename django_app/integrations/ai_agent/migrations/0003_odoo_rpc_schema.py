"""Update schema `mcp-odoo-rpc` (Sprint H T1.2) — method list nyata."""

from __future__ import annotations

from django.db import migrations

NEW_SCHEMA = {
    "get_stock": {"product_odoo_id": "int", "location_id": "int?"},
    "get_invoice": {"invoice_odoo_id": "int"},
    "get_purchase_order": {"purchase_order_odoo_id": "int"},
    "get_sale_order": {"sale_order_odoo_id": "int"},
    "get_product_info": {"product_odoo_id": "int"},
    "get_partner_info": {"partner_odoo_id": "int"},
    "list_recent_moves": {"limit": "int?"},
}
OLD_SCHEMA = {"read": {"model": "str", "domain": "list", "fields": "list[str]"}}


def update_schema(apps, schema_editor):
    Tool = apps.get_model("ai_agent", "AIToolRegistry")
    Tool.objects.filter(name="mcp-odoo-rpc").update(schema=NEW_SCHEMA)


def restore_schema(apps, schema_editor):
    Tool = apps.get_model("ai_agent", "AIToolRegistry")
    Tool.objects.filter(name="mcp-odoo-rpc").update(schema=OLD_SCHEMA)


class Migration(migrations.Migration):
    dependencies = [("ai_agent", "0002_seed_tools")]

    operations = [migrations.RunPython(update_schema, restore_schema)]
