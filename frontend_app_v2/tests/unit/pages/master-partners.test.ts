import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS, legacyAppIdForPath } from '@/app/nav-config';
import { PartnerDetailPage } from '@/pages/master/PartnerDetailPage';
import { PartnerFormPage } from '@/pages/master/PartnerFormPage';
import { PartnersPage } from '@/pages/master/PartnersPage';
import {
  displayOrDash,
  EMPTY_PARTNER_FORM,
  formatNpwp,
  isEmailLike,
  isPartnerFormValid,
  normalizeNpwp,
  ordersCountLabel,
  partnerDetailItems,
  partnerFormFromRow,
  partnerInputFromForm,
  partnerRoleLabels,
  validatePartnerForm,
  type PartnerFormValues,
} from '@/lib/master-partner';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { MasterPartnerDetail, MasterPartnerRow } from '@/types/master-partner';

/**
 * H1.6 — halaman master partner (`/master/partners*`).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` (pohon dibangun `createElement` agar
 *      file tetap `.ts`), dibungkus `QueryClientProvider` + `MemoryRouter` +
 *      konteks runtime palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav, validasi form
 *      (`lib/master-partner.ts`) & helper tampilan (NPWP, peran, detail items).
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const NAV = read('src/app/nav-config.ts');
const LIST_PAGE = 'src/pages/master/PartnersPage.tsx';
const FORM_PAGE = 'src/pages/master/PartnerFormPage.tsx';
const DETAIL_PAGE = 'src/pages/master/PartnerDetailPage.tsx';

/** Konteks feedback palsu — `useFeedback()` di halaman form butuh provider. */
const FEEDBACK: FeedbackRuntime = {
  flash: null,
  trigger: () => undefined,
  clear: () => undefined,
};

function renderPage(
  element: ReactElement,
  initialPath: string,
  routePath = initialPath,
): { html: string; text: string } {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = createElement(
    QueryClientProvider,
    { client },
    createElement(
      MemoryRouter,
      { initialEntries: [initialPath] },
      createElement(
        FeedbackRuntimeContext.Provider,
        { value: FEEDBACK },
        createElement(Routes, null, createElement(Route, { path: routePath, element })),
      ),
    ),
  );

  return { html: htmlOf(tree), text: textOf(tree) };
}

const ROW: MasterPartnerRow = {
  id: 7,
  code: 'PTR-PT-BUYER-EXPORT',
  name: 'PT Buyer Export',
  email: 'buyer@example.com',
  phone: '+62 812',
  city: 'Bandung',
  address: 'Jl. Merdeka 10\nBlok C',
  npwp: '012345678901000',
  is_customer: true,
  is_vendor: false,
  is_company: true,
  customer_rank: 3,
  supplier_rank: 0,
  active: true,
  odoo_id: null,
  created_at: null,
  updated_at: null,
};

const DETAIL: MasterPartnerDetail = { ...ROW, orders_count: 2 };

const VALID_FORM: PartnerFormValues = {
  code: 'PTR-PT-BUYER-EXPORT',
  name: 'PT Buyer Export',
  email: 'buyer@example.com',
  phone: '+62 812',
  city: 'Bandung',
  address: 'Jl. Merdeka 10\nBlok C',
  npwp: '012345678901000',
  is_customer: true,
  is_vendor: false,
  is_company: true,
  active: true,
};

describe('H1.6 — route & guard (App.tsx)', () => {
  it('4 route master partner terdaftar dengan guard INVENTORY_ROLES', () => {
    for (const routePath of [
      '/master/partners',
      '/master/partners/new',
      '/master/partners/:id',
      '/master/partners/:id/edit',
    ]) {
      expect(APP, routePath).toContain(`path="${routePath}"`);
    }

    expect(APP).toContain('<MasterPartnersPage />');
    expect(APP).toContain('<MasterPartnerFormPage />');
    expect(APP).toContain('<MasterPartnerDetailPage />');
    expect(APP).toMatch(/path="\/master\/partners"[\s\S]{0,220}INVENTORY_ROLES/);
  });

  it('path `/master/partners*` dipetakan ke app inventory (nav-config alias)', () => {
    expect(NAV).toContain("{ prefix: '/master/partners', appId: 'inventory' }");
    expect(legacyAppIdForPath('/master/partners')).toBe('inventory');
    expect(legacyAppIdForPath('/master/partners/7/edit')).toBe('inventory');
  });

  it('menu Inventory punya item Master Partner (link biasa, bukan dropdown)', () => {
    const inventory = NAV_APPS.find((app) => app.id === 'inventory');
    const item = inventory?.topbar.find((menu) => menu.label === 'Master Partner');

    expect(item?.path).toBe('/master/partners');
    expect(item?.children).toBeUndefined();
  });
});

describe('H1.6 — render halaman (react-dom/server)', () => {
  it('halaman list: judul, kolom (Peran/Kota/NPWP), tab peran, CTA Partner Baru', () => {
    const { html, text } = renderPage(createElement(PartnersPage), '/master/partners');

    expect(text).toContain('Master Partner');
    expect(text).toContain('Partner Baru');
    for (const label of ['Kode', 'Nama', 'Peran', 'Kota', 'Telepon', 'NPWP', 'Status', 'Odoo ID']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Semua');
    expect(text).toContain('Pelanggan');
    expect(text).toContain('Supplier');
    expect(text).toContain('Export CSV');
    expect(html).toContain('aria-busy');
  });

  it('halaman form (baru): 7 input + 4 checkbox + tombol submit', () => {
    const { html, text } = renderPage(createElement(PartnerFormPage), '/master/partners/new');

    expect(text).toContain('Partner Baru');
    for (const label of ['Nama *', 'Kode (opsional)', 'Email', 'Telepon', 'Kota', 'NPWP', 'Alamat']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Pelanggan (dipakai di Sales Order)');
    expect(text).toContain('Supplier / vendor (dipakai di Purchase Order)');
    expect(text).toContain('Perusahaan');
    expect(text).toContain('Partner aktif');
    expect(text).toContain('Simpan Partner');
    expect(html).toContain('type="submit"');
  });

  it('halaman form (edit): mode edit + breadcrumb Edit', () => {
    const { text } = renderPage(
      createElement(PartnerFormPage),
      '/master/partners/7/edit',
      '/master/partners/:id/edit',
    );

    expect(text).toContain('Edit Partner');
    expect(text).toContain('Simpan Perubahan');
  });

  it('halaman detail: tombol Edit ada, tombol Sync DISABLED + tooltip H2', () => {
    const { html, text } = renderPage(createElement(PartnerDetailPage), '/master/partners/7');

    expect(text).toContain('Detail Partner');
    expect(text).toContain('Edit');
    expect(text).toContain('Sync ke Odoo');
    expect(html).toContain('disabled');
    expect(html).toContain('Sync manual tersedia di H2');
  });
});

describe('H1.6 — sumber halaman (wiring API)', () => {
  it('list: adapter real, filter server (search + peran), tabel dense, klik → detail', () => {
    const page = read(LIST_PAGE);

    expect(page).toContain("from '@/api/masterPartners'");
    expect(page).toContain('fetchPartners(client, {');
    expect(page).toContain('PARTNERS_LIMIT_MAX');
    expect(page).toContain("queryKey: ['master-partners'");
    expect(page).toContain('roleParamsForStatus(role)');
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).not.toContain('<table');
    expect(page).toContain("navigate(`/master/partners/${String(row.id)}`)");
  });

  it('form: create/update lewat adapter + validasi pure + checkbox peran', () => {
    const page = read(FORM_PAGE);

    expect(page).toContain('createPartner(client, input)');
    expect(page).toContain('updatePartner(client, partnerId, input)');
    expect(page).toContain('validatePartnerForm(values)');
    expect(page).toContain('partnerInputFromForm(values)');
    expect(page).toContain("onCheckedChange={(checked) => setField('is_customer', checked)}");
    expect(page).toContain("onCheckedChange={(checked) => setField('is_vendor', checked)}");
    expect(page).toContain('onSubmit={handleSubmit}');
    expect(page).not.toMatch(/\bfetch\(/);
  });

  it('detail: read-only + Sync placeholder H2 + orders_count', () => {
    const page = read(DETAIL_PAGE);

    expect(page).toContain('fetchPartner(client, partnerId ?? 0)');
    expect(page).toContain('Tooltip content="Sync manual tersedia di H2');
    expect(page).toContain('/master/partners/${String(partnerId)}/edit');
    expect(page).toContain('ordersCountLabel(partner)');
    expect(page).not.toContain('useMutation');
    expect(page).not.toContain('deletePartner');
  });
});

describe('H1.6 — validasi form (nama, peran, NPWP, email)', () => {
  it('form valid → tanpa error (siap dikirim ke POST/PUT)', () => {
    const errors = validatePartnerForm(VALID_FORM);

    expect(errors).toEqual({});
    expect(isPartnerFormValid(errors)).toBe(true);
    expect(partnerInputFromForm(VALID_FORM)).toEqual({
      code: 'PTR-PT-BUYER-EXPORT',
      name: 'PT Buyer Export',
      email: 'buyer@example.com',
      phone: '+62 812',
      city: 'Bandung',
      address: 'Jl. Merdeka 10\nBlok C',
      npwp: '012345678901000',
      is_customer: true,
      is_vendor: false,
      is_company: true,
      active: true,
    });
    expect('customer_rank' in partnerInputFromForm(VALID_FORM)).toBe(false);
    expect('orders_count' in partnerInputFromForm(VALID_FORM)).toBe(false);
  });

  it('nama KOSONG → error "wajib diisi" & TIDAK valid (tidak dikirim)', () => {
    const errors = validatePartnerForm({ ...VALID_FORM, name: '   ' });

    expect(errors.name).toBe('Nama partner wajib diisi.');
    expect(isPartnerFormValid(errors)).toBe(false);
  });

  it('kedua peran dimatikan → error peran (minimal satu)', () => {
    const errors = validatePartnerForm({ ...VALID_FORM, is_customer: false, is_vendor: false });

    expect(errors.roles).toBe('Pilih minimal satu peran: pelanggan atau supplier.');
    expect(isPartnerFormValid(errors)).toBe(false);
  });

  it('NPWP: 15/16 digit valid, panjang lain → error', () => {
    expect(validatePartnerForm({ ...VALID_FORM, npwp: '01.234.567.8-901.000' }).npwp).toBeUndefined();
    expect(validatePartnerForm({ ...VALID_FORM, npwp: '0123456789010001' }).npwp).toBeUndefined();
    expect(validatePartnerForm({ ...VALID_FORM, npwp: '' }).npwp).toBeUndefined(); // opsional

    expect(validatePartnerForm({ ...VALID_FORM, npwp: '12345' }).npwp).toBe(
      'NPWP harus 15 atau 16 digit (terbaca 5 digit).',
    );
  });

  it('email tidak valid & teks terlalu panjang → error', () => {
    expect(validatePartnerForm({ ...VALID_FORM, email: 'bukan-email' }).email).toBe(
      'Email tidak valid (contoh: nama@domain.com).',
    );
    expect(validatePartnerForm({ ...VALID_FORM, email: '' }).email).toBeUndefined(); // opsional
    expect(validatePartnerForm({ ...VALID_FORM, city: 'X'.repeat(65) }).city).toBe(
      'Kota maksimal 64 karakter.',
    );
    expect(validatePartnerForm({ ...VALID_FORM, code: 'C'.repeat(65) }).code).toContain(
      'Kode maksimal 64 karakter',
    );
  });

  it('form awal (EMPTY_PARTNER_FORM) valid: default pelanggan & output kosong', () => {
    const errors = validatePartnerForm(EMPTY_PARTNER_FORM);

    expect(errors.name).toBe('Nama partner wajib diisi.');
    expect(errors.roles).toBeUndefined(); // default: pelanggan aktif
    expect(Object.keys(errors)).toEqual(['name']);
  });

  it('edit: partnerFormFromRow ↔ partnerInputFromForm konsisten', () => {
    const form = partnerFormFromRow(ROW);

    expect(form).toEqual(VALID_FORM);
    expect(partnerInputFromForm(form)).toEqual(partnerInputFromForm(VALID_FORM));

    const person = partnerFormFromRow({ ...ROW, is_company: false, is_vendor: true, npwp: '' });
    expect(person.is_company).toBe(false);
    expect(person.is_vendor).toBe(true);
    expect(person.npwp).toBe('');
  });
});

describe('H1.6 — helper tampilan (lib)', () => {
  it('normalizeNpwp & isEmailLike', () => {
    expect(normalizeNpwp('01.234.567.8-901.000')).toBe('012345678901000');
    expect(normalizeNpwp('  ')).toBe('');
    expect(normalizeNpwp('abc123')).toBe('123');

    expect(isEmailLike('nama@domain.com')).toBe(true);
    expect(isEmailLike('nama@domain')).toBe(false);
    expect(isEmailLike('bukan-email')).toBe(false);
  });

  it('formatNpwp: 15/16 digit dikelompokkan, selain itu apa adanya / "-"', () => {
    expect(formatNpwp('012345678901000')).toBe('01.234.567.8-901.000');
    expect(formatNpwp('0123456789010001')).toBe('0123 4567 8901 0001');
    expect(formatNpwp('123')).toBe('123');
    expect(formatNpwp('')).toBe('-');
  });

  it('partnerRoleLabels: pelanggan/supplier/keduanya', () => {
    expect(partnerRoleLabels({ is_customer: true, is_vendor: false })).toEqual(['Pelanggan']);
    expect(partnerRoleLabels({ is_customer: false, is_vendor: true })).toEqual(['Supplier']);
    expect(partnerRoleLabels({ is_customer: true, is_vendor: true })).toEqual([
      'Pelanggan',
      'Supplier',
    ]);
  });

  it('partnerDetailItems: peran, jenis, NPWP terformat, rank & odoo_id jelas', () => {
    const items = partnerDetailItems(ROW);

    expect(items.find((item) => item.label === 'Peran')?.value).toBe('Pelanggan');
    expect(items.find((item) => item.label === 'Jenis')?.value).toBe('Perusahaan');
    expect(items.find((item) => item.label === 'NPWP')?.value).toBe('01.234.567.8-901.000');
    expect(items.find((item) => item.label === 'Rank Pelanggan')?.value).toBe('3');
    expect(items.find((item) => item.label === 'Odoo ID')?.value).toBe('belum dikirim');
    expect(
      partnerDetailItems({ ...ROW, odoo_id: 45 }).find((item) => item.label === 'Odoo ID')?.value,
    ).toBe('45');
    expect(
      partnerDetailItems({ ...ROW, is_company: false, is_customer: false, is_vendor: true }).find(
        (item) => item.label === 'Jenis',
      )?.value,
    ).toBe('Perorangan');
  });

  it('ordersCountLabel & displayOrDash', () => {
    expect(ordersCountLabel(DETAIL)).toBe('2 order');
    expect(ordersCountLabel({ ...DETAIL, orders_count: 0 })).toBe('0 order');

    expect(displayOrDash('  Bandung  ')).toBe('Bandung');
    expect(displayOrDash('')).toBe('-');
    expect(displayOrDash(null)).toBe('-');
    expect(displayOrDash(0)).toBe('0');
  });
});


