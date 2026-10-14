from django.apps import AppConfig


class RuleEngineConfig(AppConfig):
    """App `core.rule_engine` — rule engine generik (routing, bundling, alokasi).

    Semua aturan = **konfigurasi di DB** (`Rule`/`RuleCondition`/`RuleAction`),
    bukan `if` di kode. Evaluasi dilakukan `services.RuleEngine` murni dengan
    dict mapping operator — TANPA `eval`/`exec`.

    `label` ditulis eksplisit (`rule_engine`) karena label inilah yang dipakai
    perintah `makemigrations rule_engine` dan nama tabel (`rule_engine_rule`).
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "core.rule_engine"
    label = "rule_engine"
    verbose_name = "Core Rule Engine"
