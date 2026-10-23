"""Test prompt synthesizer final (Fase 2)."""

from __future__ import annotations

from integrations.ai_agent.agent.prompts import SYSTEM_PROMPT_TEMPLATE, build_system_prompt


def test_prompt_memuat_tanggal_hari_ini():
    prompt = build_system_prompt(today="2026-10-23", role="supervisor")
    assert "2026-10-23" in prompt
    assert "SUPERVISOR" in prompt


def test_prompt_memuat_instruksi_kunci():
    prompt = build_system_prompt(today="2026-10-23")
    keys = [
        "JANGAN mengarang angka",
        "stats.avg",
        "stats.max",
        "stats.min",
        "stats.latest",
        "Tidak ada data untuk periode itu",
        "SEMUA klausa",
        "Informasi ini belum bisa diakses dari sistem",
        "is_active=true",
        "propose_action",
        "hanya membaca",
        "di luar produksi garmen",
    ]
    for key in keys:
        assert key in prompt, key


def test_template_konsisten_dengan_prompt():
    assert SYSTEM_PROMPT_TEMPLATE.format(today="X", role="Y") == build_system_prompt(
        today="X", role="Y"
    )


def test_prompt_role_kosong_jadi_user():
    assert "Peran pengguna: USER" in build_system_prompt(today="2026-10-23")
