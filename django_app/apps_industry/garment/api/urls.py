"""URL app `apps_industry.garment` (di-include dengan prefix `/api/`).

Fase A memindahkan path **core/lintas industri** (health, chatter, metadata) ke
`config/urls.py` supaya urutan resolve-nya eksplisit: kontrak core didaftarkan
sebelum pola industri. File ini sekarang hanya menangani pola **berindustri**:

  * ``v1/<industry>/<resource>/<id>/schema/`` — metadata satu instance (kontrak §1);
  * ``v1/<industry>/<resource>/<id>/<action>/`` — aksi idempotent (kontrak §2/§5/§8);
  * ``v1/<industry>/<resource>/`` — list resource (kontrak §3);
  * ``v1/<industry>/<resource>/<id>/`` — detail resource (kontrak §3).

URUTAN PENTING:

  1. ``schema/`` harus SEBELUM ``<str:action>/`` (keduanya cocok untuk "schema");
  2. pola ``list`` dibatasi daftar resource dari registry (``re_path``) supaya
     TIDAK men-shadows path core lain di ``/api/v1/`` (mis. ``/api/v1/devices/me``);
  3. segment ``<industry>`` divalidasi whitelist di view
     (``api/industries.py``) → industri tak dikenal = **404 eksplisit**.
"""

from __future__ import annotations

import re

from django.urls import path, re_path

from apps_industry.garment.api.actions.views import ActionView
from apps_industry.garment.api.resources.create_view import (
    BundleCreateView,
    WorkOrderCreateView,
)
from apps_industry.garment.api.resources.detail_view import ResourceDetailView
from apps_industry.garment.api.resources.list_view import ResourceListView
from apps_industry.garment.api.schema.registry import SCHEMA_BUILDERS
from apps_industry.garment.api.schema.views import SchemaView

app_name = "garment"

#: Daftar nama resource valid (dari registry), dipakai membatasi pola `list`.
_RESOURCE_PATTERN = "|".join(re.escape(name) for name in sorted(SCHEMA_BUILDERS))

urlpatterns = [
    # FASE 3.4 (D1) — jalur CREATE (POST). WAJIB SEBELUM pola `list` (`re_path` di
    # bawah) supaya `POST /api/v1/<industry>/bundles/` tidak jatuh ke
    # ResourceListView (GET-only -> 405). `GET` pada path yang sama diteruskan
    # kedua view ini ke list (lihat `_CreateViewMixin.get`), jadi kontrak §3 tidak
    # berubah dan bootstrap simulator tetap jalan.
    path(
        "v1/<str:industry>/work-orders/",
        WorkOrderCreateView.as_view(),
        name="work_order_create",
    ),
    path(
        "v1/<str:industry>/bundles/",
        BundleCreateView.as_view(),
        name="bundle_create",
    ),
    path(
        "v1/<str:industry>/<str:resource>/<int:id>/schema/",
        SchemaView.as_view(),
        name="schema",
    ),
    path(
        "v1/<str:industry>/<str:resource>/<int:id>/<str:action>/",
        ActionView.as_view(),
        name="action",
    ),
    re_path(
        rf"^v1/(?P<industry>[^/]+)/(?P<resource>{_RESOURCE_PATTERN})/$",
        ResourceListView.as_view(),
        name="list",
    ),
    path(
        "v1/<str:industry>/<str:resource>/<int:id>/",
        ResourceDetailView.as_view(),
        name="detail",
    ),
]

