"""URL AI Agent (D.5) — dipakai thin adapter `integrations/ai/api.py`."""

from __future__ import annotations

from django.urls import path

from .views import AiChatView

urlpatterns = [
    path("chat", AiChatView.as_view(), name="ai_agent_chat"),
]

