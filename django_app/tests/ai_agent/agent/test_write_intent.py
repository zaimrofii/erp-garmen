"""Test pre-flight write detection di agent loop (demo-ready)."""

from __future__ import annotations

import pytest

from integrations.ai_agent.agent.loop import WRITE_REFUSAL, _is_write_intent, run_agent
from integrations.ai_agent.llm_wrapper.base import LLMResponse


class FakeProvider:
    def __init__(self):
        self.calls = []

    def chat(self, messages, tools=None, max_tokens=1000):
        self.calls.append(list(messages))
        return LLMResponse(
            text="Halo", prompt_tokens=1, completion_tokens=1,
            total_cost_usd=0.0, model="fake", latency_ms=1, raw={},
        )


def _messages(text: str) -> list[dict]:
    return [{"role": "system", "content": "s"}, {"role": "user", "content": text}]


@pytest.mark.parametrize(
    "message",
    [
        "Ubah harga Jaket Bomber jadi 100rb",
        "hapus produk termahal",
        "tolong update status order S00018",
        "buat order baru untuk customer A",
        "reset data bundle",
    ],
)
def test_write_intent_terdeteksi(message):
    assert _is_write_intent(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "Produk termahal apa?",
        "Berapa produk aktif?",
        "bundle di SEWING-2 berapa?",
        "tampilkan order yang telat",
    ],
)
def test_bukan_write_intent(message):
    assert _is_write_intent(message) is False


@pytest.mark.django_db
def test_ubah_harga_diblokir_tanpa_llm():
    provider = FakeProvider()
    result = run_agent(_messages("Ubah harga Jaket Bomber jadi 100rb"), "SUPERVISOR",
                       config={"provider": provider})
    assert result.blocked_reason == "write_intent"
    assert result.answer == WRITE_REFUSAL
    assert result.tool_calls == []
    assert result.cost_usd == 0.0
    assert provider.calls == []


@pytest.mark.django_db
def test_hapus_produk_diblokir():
    provider = FakeProvider()
    result = run_agent(_messages("Hapus produk termahal"), "SUPERVISOR",
                       config={"provider": provider})
    assert result.blocked_reason == "write_intent"
    assert provider.calls == []


@pytest.mark.django_db
def test_pertanyaan_biasa_tidak_diblokir():
    provider = FakeProvider()
    result = run_agent(_messages("Produk termahal apa?"), "SUPERVISOR",
                       config={"provider": provider})
    assert result.blocked_reason is None
    assert len(provider.calls) == 1
