"""Pencarian dokumen SOP (TEMPORARY — ganti ChromaDB di Fase Berat).

PostgreSQL full-text (`SearchVector`/`SearchRank`) + fallback kemiripan
trigram-like (SequenceMatcher) untuk typo. Tidak ada dependency baru.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from .models import Document

__all__ = ("get_document", "search_documents")


def _row(document: Document, score: float, method: str) -> dict:
    return {
        "id": document.pk,
        "title": document.title,
        "content": document.content,
        "category": document.category,
        "tags": list(document.tags or []),
        "score": round(float(score), 4),
        "method": method,
    }


def search_documents(query: str, limit: int = 5) -> list[dict]:
    """Cari dokumen: full-text dulu, lalu fallback kemiripan judul/isi."""
    text = str(query or "").strip()
    if not text:
        return []

    results: list[dict] = []
    seen: set[int] = set()

    try:
        from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector

        vector = SearchVector("title", weight="A") + SearchVector("content", weight="B")
        search_query = SearchQuery(text, search_type="websearch")
        rows = (
            Document.objects.annotate(rank=SearchRank(vector, search_query))
            .filter(rank__gt=0)
            .order_by("-rank")[: max(1, limit)]
        )
        for document in rows:
            results.append(_row(document, float(getattr(document, "rank", 0) or 0), "fulltext"))
            seen.add(document.pk)
    except Exception:  # noqa: BLE001 - FTS vendor-specific tidak boleh crash chat
        results = []

    if len(results) < limit:
        needle = text.lower()
        candidates = Document.objects.all()[:100]
        scored: list[tuple[float, Document]] = []
        for document in candidates:
            if document.pk in seen:
                continue
            haystack = f"{document.title} {document.content} {' '.join(document.tags or [])}".lower()
            ratio = SequenceMatcher(None, needle, haystack).ratio()
            if needle in haystack:
                ratio = max(ratio, 0.6)
            else:
                for word in needle.split():
                    if len(word) >= 3:
                        ratio = max(
                            ratio,
                            SequenceMatcher(None, word, document.title.lower()).ratio(),
                        )
            if ratio >= 0.30:
                scored.append((ratio, document))

        scored.sort(key=lambda item: -item[0])
        for ratio, document in scored[: limit - len(results)]:
            results.append(_row(document, ratio, "similarity"))
            seen.add(document.pk)

    return results


def get_document(document_id: int) -> dict | None:
    """Ambil satu dokumen by id (None bila tidak ada)."""
    document = Document.objects.filter(pk=document_id).first()
    if document is None:
        return None
    return _row(document, 1.0, "id")
