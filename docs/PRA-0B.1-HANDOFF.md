# PRA-0B.1 Handoff
- DB Odoo: garmen_db
- User: api_bot (uid=8)
- Container: odoo_garmen_db (postgres), odoo_garmen_app (odoo),
  garmen_django
- Bukti UI Odoo: api_bot punya "Inventory / Administrator"
- Login user API = api_bot@internal.com (uid=8); bukan 'api_bot'.
- Tujuan: verifikasi push inventory adjustment NYATA berhasil

## Verifikasi A — psql cek grup
docker exec -it odoo_garmen_db psql -U odoo -d garmen_db -c "
SELECT u.id, u.login, g.id, g.name->>'en_US'
FROM res_users u
JOIN res_groups_users_rel r ON r.uid = u.id
JOIN res_groups g ON g.id = r.gid
WHERE u.login = 'api_bot@internal.com'
  AND (g.name->>'en_US' ILIKE '%Inventory%'
       OR g.name->>'en_US' ILIKE '%Manager%'
       OR g.name->>'en_US' ILIKE '%Administrator%')
ORDER BY g.name->>'en_US';"

## Verifikasi B — _search_read
docker exec -w /app garmen_django python manage.py shell -c "
from integrations.erp_sync.transport import get_transport
t = get_transport()
grp = t._search_read('res.groups',
    [['full_name', 'ilike', 'Inventory / Administrator']],
    ['id', 'name', 'full_name'], limit=5)
print('RESULT_GROUPS:', grp)
if grp:
    gid = grp[0]['id']
    users = t._search_read('res.users',
        [['login', '=', 'api_bot@internal.com'], ['groups_id', 'in', [gid]]],
        ['id', 'login'], limit=5)
    print('RESULT_API_BOT_IN_GROUP:', users)
t.close()
" 2>&1 | grep RESULT_

## Verifikasi C — fetch_stock_quants
docker exec -w /app garmen_django python manage.py shell -c "
from integrations.erp_sync.transport import get_transport
t = get_transport()
locs = t.fetch_internal_locations()
ids = [l['id'] for l in locs]
print('RESULT_LOCS:', len(ids))
quants = t.fetch_stock_quants(ids, child_of=True) if ids else []
print('RESULT_QUANTS:', len(quants))
t.close()
" 2>&1 | grep RESULT_

## Verifikasi D — Push end-to-end
D.1 Cari admin MES:
docker exec -w /app garmen_django python manage.py shell -c "
from core_auth.models import User
u = User.objects.filter(role__code__in=['ADMIN','OWNER'], is_active=True).first()
print('RESULT_USER:', u.username if u else None)
" 2>&1 | grep RESULT_

D.2 Cari produk/lokasi:
docker exec -w /app garmen_django python manage.py shell -c "
from master.models import Product, Location
p = Product.objects.filter(odoo_id__isnull=False).first()
l = Location.objects.filter(usage='internal', odoo_id__isnull=False).first()
print('RESULT_PRODUCT:', p.id if p else None, p.odoo_id if p else None)
print('RESULT_LOCATION:', l.id if l else None, l.odoo_id if l else None)
" 2>&1 | grep RESULT_

D.3-D.5: login MES via curl, POST /inventory/adjust/,
POST commit, cek stock_quant di psql.
Detail sesuai handoff asli.

## Format Laporan
PRA-0B.1 — [DONE/BLOCKER]
A: [OK/kosong]
B: [OK/error] — api_bot in group: [ya/tidak]
C: [OK N/M / AccessError]
D: [DONE / BLOCKER — alasan]
Kesimpulan: [DONE/BLOCKER]
