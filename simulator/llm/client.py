"""Klien LLM lokal via Ollama HTTP API — fase M3.

Memakai ``httpx.AsyncClient`` yang sudah menjadi dependency (tidak ada library
baru). Endpoint: ``POST {base_url}/api/chat`` (Ollama Chat API).

FASE 3.4 Fase 4 — **retry terbatas** untuk kegagalan yang layak diulang
(timeout / koneksi / HTTP 5xx = Ollama overload): ``max_retries`` percobaan
ulang dengan backoff 0.5s lalu 1s. Setelah habis menyerah dan raise
:class:`OllamaError` — agent yang memutuskan fallback ke scripted (lihat
:class:`~simulator.agents.operator.OperatorAgent`), jadi run tidak pernah mati
karena LLM. Error 4xx & respons tak valid **tidak** di-retry.

Tidak ada state yang dipersist — hanya handle ``AsyncClient`` selama run.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx

__all__ = ("OllamaClient", "OllamaError")

#: Jeda backoff (detik) untuk retry ke-1, ke-2, ... (percobaan terakhir di-cap).
_RETRY_BACKOFF_SECONDS: tuple[float, ...] = (0.5, 1.0)

#: Status HTTP yang layak di-retry (server sibuk/overload); 4xx TIDAK.
_RETRY_STATUS_CODES: tuple[int, ...] = (500, 502, 503, 504)


class OllamaError(Exception):
    """Kegagalan memanggil Ollama (timeout / koneksi / HTTP / respons tak valid)."""


class OllamaClient:
    """Klien minimal untuk ``POST /api/chat`` Ollama (non-streaming)."""

    def __init__(
        self,
        base_url: str = "http://ollama:11434",
        model: str = "qwen2.5:7b",
        temperature: float = 0.7,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = float(temperature)
        self.timeout = float(timeout)
        #: Percobaan ulang untuk kegagalan layak-retry (0 = tanpa retry).
        self.max_retries = max(int(max_retries), 0)
        self._client = httpx.AsyncClient(timeout=self.timeout)

    async def chat(self, system: str, user: str, json_mode: bool = False) -> str:
        """Kirim satu percakapan system+user, kembalikan ``message.content``.

        ``json_mode=True`` menambahkan ``format: "json"`` agar Ollama memaksa
        output JSON. Raise :class:`OllamaError` pada timeout/ConnectError/HTTPError
        atau bila bentuk respons tidak seperti yang diharapkan.
        """

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        if json_mode:
            body["format"] = "json"

        try:
            response = await self._post_with_retry(body)
            data = response.json()
            return data["message"]["content"]
        except OllamaError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise OllamaError(f"Respons Ollama tidak terduga: {exc}") from exc

    async def _post_with_retry(self, body: dict) -> "httpx.Response":
        """POST ``/api/chat`` dengan retry untuk timeout / koneksi / HTTP 5xx.

        Total percobaan = ``1 + max_retries``; jeda ``0.5s`` lalu ``1s``. Error
        4xx & respons tak valid **tidak** di-retry (mengulang tidak menolong).
        Percobaan habis → :class:`OllamaError` (run tetap hidup: agent fallback
        ke scripted).
        """

        attempt = 0
        while True:
            last_error = ""
            retryable = False
            try:
                response = await self._client.post(
                    f"{self.base_url}/api/chat", json=body
                )
                if response.status_code in _RETRY_STATUS_CODES:
                    retryable = True
                    last_error = f"HTTP {response.status_code}"
                else:
                    response.raise_for_status()
                    return response
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                # Spesifik dulu: keduanya subclass httpx.HTTPError.
                retryable = True
                last_error = f"{type(exc).__name__}: {exc}"
            except httpx.HTTPError as exc:
                # HTTPStatusError 4xx (permintaan salah) & error transport lain.
                raise OllamaError(f"Ollama chat gagal: {exc}") from exc

            if not retryable or attempt >= self.max_retries:
                raise OllamaError(
                    f"Ollama chat gagal setelah {attempt + 1} percobaan: {last_error}"
                )
            await asyncio.sleep(
                _RETRY_BACKOFF_SECONDS[min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)]
            )
            attempt += 1

    async def close(self) -> None:
        """Tutup koneksi klien."""

        await self._client.aclose()
