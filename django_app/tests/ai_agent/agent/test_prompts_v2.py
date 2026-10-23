"""Test prompt final (demo-ready): prioritas stok di depan, panjang terkendali."""

from __future__ import annotations

from integrations.ai_agent.agent.prompts import SYSTEM_PROMPT_TEMPLATE, build_system_prompt


def test_aturan_stok_di_500_karakter_pertama():
    prompt = build_system_prompt(today="2026-10-23", role="SUPERVISOR")
    head = prompt[:500]
    assert "stok" in head.lower()
    assert "get_stock" in head


def test_prompt_tidak_lebih_2000_karakter():
    prompt = build_system_prompt(today="2026-10-23", role="SUPERVISOR")
    assert len(prompt) <= 2000


def test_prompt_memuat_tanggal_dan_konversi_periode():
    prompt = build_system_prompt(today="2026-10-23", role="supervisor")
    assert "2026-10-23" in prompt
    assert "Senin minggu ini" in prompt
    assert "SUPERVISOR" in prompt


def test_template_konsisten():
    assert SYSTEM_PROMPT_TEMPLATE.format(today="X", role="Y") == build_system_prompt(today="X", role="Y")
