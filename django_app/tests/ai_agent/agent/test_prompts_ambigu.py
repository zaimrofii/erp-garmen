"""Test Perbaikan #3: aturan prompt untuk pertanyaan ambigu (tanya balik)."""

from __future__ import annotations

from integrations.ai_agent.agent import prompts

PROMPT = prompts.SYSTEM_PROMPT_TEMPLATE


def test_prompt_memuat_aturan_ambigu():
    assert "tanpa konteks" in PROMPT.lower()
    assert "TANYA BALIK" in PROMPT
    assert "Bisa diperjelas?" in PROMPT


def test_prompt_memuat_kata_kunci_pemicu():
    for keyword in ("order tadi", "produk itu", "tersebut", "yang kedua"):
        assert keyword in PROMPT


def test_pertanyaan_ambigu_tidak_dijawab_default_periode():
    # Aturan 14 melarang default periode untuk referensi tanpa konteks.
    rule = PROMPT.split("14.", 1)[1]
    assert "JANGAN" in rule
    assert "default periode" in rule
