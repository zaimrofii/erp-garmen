"""Tool `find_entity` — resolve nama/kode menjadi kandidat id (read-only)."""

from __future__ import annotations

from .base import ENTITIES, ToolResult, fn_schema, model_for

NAME = "find_entity"
ALL_ROLES = frozenset({"ADMIN", "INVENTORY", "OPERATOR", "OWNER", "PURCHASING", "QC", "SUPERVISOR"})
SCHEMA = fn_schema(
    NAME,
    "Cari entity berdasarkan potongan nama/kode. Kembalikan {matches, ambiguous, count}."
    " Pakai sebelum filter bila user menyebut nama (mis. 'SEWING-2').",
    {
        "entity": {"type": "string", "enum": list(ENTITIES)},
        "text": {"type": "string"},
    },
    ["entity", "text"],
)


def run(entity: str, text: str) -> ToolResult:
    from django.db.models import Q

    entity_key = str(entity or "").strip().lower()
    model = model_for(entity_key)
    fields = {f.name for f in model._meta.fields}
    query = Q()
    if "code" in fields:
        query |= Q(code__icontains=str(text))
    if "name" in fields:
        query |= Q(name__icontains=str(text))
    if not query:
        return ToolResult.success({"matches": [], "ambiguous": False, "count": 0})

    columns = [column for column in ("id", "code", "name") if column in fields]
    matches = list(model.objects.filter(query).values(*columns)[:10])
    return ToolResult.success(
        {"matches": matches, "ambiguous": len(matches) > 1, "count": len(matches)},
        row_count=len(matches),
        filters_applied={"entity": entity_key, "text": str(text)},
        warnings=[] if matches else ["not_found"],
    )


__all__ = ("ALL_ROLES", "NAME", "SCHEMA", "run")
