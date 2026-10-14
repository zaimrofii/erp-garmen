"""Seed state machine garmen (Sprint 3.1).

Prinsip blueprint: **semua aturan = konfigurasi, bukan kode**. Karena itu alur
bundle & work order disimpan sebagai data di `core.state_machine`, bukan enum di
Python. Migration ini idempotent (`get_or_create`) supaya aman dijalankan
berulang dan tidak menimpa perubahan admin.

Catatan: `BUNDLE_SCRAP` = "any state -> DONE" diterjemahkan sebagai satu transisi
per state non-terminal (constraint unik Transition: machine + from_state +
action_id).
"""

from django.db import migrations

BUNDLE_MACHINE = {
    "code": "garment.bundle",
    "name": "Garment Bundle",
    "description": "Alur bundle garmen: DRAFT -> CUTTING -> SEWING -> QC -> DONE.",
    "states": (
        {"code": "DRAFT", "label": "Draft", "is_initial": True, "order": 10},
        {"code": "CUTTING", "label": "Cutting", "order": 20},
        {"code": "SEWING", "label": "Sewing", "order": 30},
        {"code": "QC", "label": "QC", "order": 40},
        {"code": "DONE", "label": "Done", "is_terminal": True, "order": 50},
    ),
    "transitions": (
        {
            "action_id": "BUNDLE_START",
            "from": "DRAFT",
            "to": "CUTTING",
            "mode": "OPTIMISTIC",
            "label": "Mulai Bundle",
        },
        {
            "action_id": "BUNDLE_ADVANCE",
            "from": "CUTTING",
            "to": "SEWING",
            "mode": "OPTIMISTIC",
            "label": "Lanjut ke Sewing",
        },
        {
            "action_id": "BUNDLE_QC",
            "from": "SEWING",
            "to": "QC",
            "mode": "OPTIMISTIC",
            "label": "Masuk QC",
        },
        {
            "action_id": "BUNDLE_FINISH",
            "from": "QC",
            "to": "DONE",
            "mode": "OPTIMISTIC",
            "label": "Selesai",
        },
        {
            "action_id": "BUNDLE_SCRAP",
            "from": "DRAFT",
            "to": "DONE",
            "mode": "PESSIMISTIC",
            "label": "Scrap Bundle",
        },
        {
            "action_id": "BUNDLE_SCRAP",
            "from": "CUTTING",
            "to": "DONE",
            "mode": "PESSIMISTIC",
            "label": "Scrap Bundle",
        },
        {
            "action_id": "BUNDLE_SCRAP",
            "from": "SEWING",
            "to": "DONE",
            "mode": "PESSIMISTIC",
            "label": "Scrap Bundle",
        },
        {
            "action_id": "BUNDLE_SCRAP",
            "from": "QC",
            "to": "DONE",
            "mode": "PESSIMISTIC",
            "label": "Scrap Bundle",
        },
    ),
}

WORK_ORDER_MACHINE = {
    "code": "garment.work_order",
    "name": "Garment Work Order",
    "description": "Alur work order: DRAFT -> IN_PROGRESS -> DONE / CANCELLED.",
    "states": (
        {"code": "DRAFT", "label": "Draft", "is_initial": True, "order": 10},
        {"code": "IN_PROGRESS", "label": "In Progress", "order": 20},
        {"code": "DONE", "label": "Done", "is_terminal": True, "order": 30},
        {"code": "CANCELLED", "label": "Cancelled", "is_terminal": True, "order": 40},
    ),
    "transitions": (
        {
            "action_id": "WO_START",
            "from": "DRAFT",
            "to": "IN_PROGRESS",
            "mode": "OPTIMISTIC",
            "label": "Mulai WO",
        },
        {
            "action_id": "WO_CLOSE",
            "from": "IN_PROGRESS",
            "to": "DONE",
            "mode": "PESSIMISTIC",
            "label": "Tutup WO",
        },
        {
            "action_id": "WO_CANCEL",
            "from": "DRAFT",
            "to": "CANCELLED",
            "mode": "PESSIMISTIC",
            "label": "Batalkan WO",
        },
        {
            "action_id": "WO_CANCEL",
            "from": "IN_PROGRESS",
            "to": "CANCELLED",
            "mode": "PESSIMISTIC",
            "label": "Batalkan WO",
        },
    ),
}

MACHINES = (BUNDLE_MACHINE, WORK_ORDER_MACHINE)


def seed_state_machines(apps, schema_editor):
    """Buat state machine + state + transition (idempotent)."""
    machine_model = apps.get_model("state_machine", "StateMachine")
    state_model = apps.get_model("state_machine", "State")
    transition_model = apps.get_model("state_machine", "Transition")

    for definition in MACHINES:
        machine, _ = machine_model.objects.get_or_create(
            code=definition["code"],
            defaults={
                "name": definition["name"],
                "description": definition["description"],
            },
        )

        states = {}
        for item in definition["states"]:
            state, _ = state_model.objects.get_or_create(
                machine=machine,
                code=item["code"],
                defaults={
                    "label": item.get("label", ""),
                    "is_initial": item.get("is_initial", False),
                    "is_terminal": item.get("is_terminal", False),
                    "order": item.get("order", 0),
                },
            )
            states[item["code"]] = state

        for item in definition["transitions"]:
            transition_model.objects.get_or_create(
                machine=machine,
                from_state=states[item["from"]],
                action_id=item["action_id"],
                defaults={
                    "to_state": states[item["to"]],
                    "label": item.get("label", ""),
                    "mode": item.get("mode", "PESSIMISTIC"),
                },
            )


def unseed_state_machines(apps, schema_editor):
    """Kebalikannya: hapus machine garmen (state & transition ikut terhapus)."""
    machine_model = apps.get_model("state_machine", "StateMachine")
    machine_model.objects.filter(code__in=[item["code"] for item in MACHINES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("garment", "0001_initial"),
        ("state_machine", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_state_machines, unseed_state_machines),
    ]
