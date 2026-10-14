"""App `master`: master data yang disinkronkan dari Odoo.

Fase 0 hanya memuat model minimal sebagai cermin (mirror) master Odoo, supaya
model domain garmen (Fase 2) bisa merujuk master data tanpa perlu membuat
relasi yang rumit lebih dulu:

  * ``Product``  — mirror ``product.template`` / ``product.product`` Odoo
    (kode, nama, ``odoo_id``, status aktif, timestamp).
  * ``BOM``      — mirror ``mrp.bom`` Odoo (header).
  * ``BOMLine``  — mirror ``mrp.bom.line`` Odoo (komponen/baris BOM).
  * ``Partner``  — mirror ``res.partner`` Odoo (pelanggan/supplier).

Fase 1 menambah 6 model master minimal (mirror Odoo) dengan field paling dasar
(``odoo_id``, ``code``, ``name``, ``active``) supaya alur stok/akuntansi bisa
merujuk master ini tanpa relasi rumit lebih dulu:

  * ``UoM``        — mirror ``uom.uom`` Odoo (unit of measure / PCS).
  * ``Location``   — mirror ``stock.location`` Odoo (lokasi stok).
  * ``Warehouse``  — mirror ``stock.warehouse`` Odoo (gudang).
  * ``Tax``        — mirror ``account.tax`` Odoo (pajak).
  * ``Journal``    — mirror ``account.journal`` Odoo (jurnal akuntansi).
  * ``Currency``   — mirror ``res.currency`` Odoo (mata uang).

H3.4 menambah satu mirror **pull-only** (chart of accounts):

  * ``Account``    — mirror ``account.account`` Odoo (akun buku besar); dipakai
    dropdown form Journal Entry manual. Tidak pernah di-push ke Odoo.

Keenam model itu mengikuti pola ``Product``: ``odoo_id``
(``PositiveBigIntegerField(null=True, blank=True, unique=True)``), ``code``
(``unique=True``), ``name``, dan ``is_active`` — tanpa ``created_at`` /
``updated_at`` (field minimal).

Konvensi:

  * ``odoo_id`` = id record di Odoo, dipakai sebagai kunci idempotensi saat
    sinkronisasi (`null=True, unique=True` supaya record yang dibuat manual di
    Django — tanpa asal Odoo — tetap boleh ada).
  * ``code`` = kode bisnis yang unik per model (``default_code`` /
    ``reference`` / ``ref`` di Odoo).
  * Semua model memakai ``is_active`` + ``created_at`` / ``updated_at`` dan
    tidak memuat aturan bisnis (aturan ada di engine/service, bukan di model).
"""

from decimal import Decimal

from django.db import models


class Product(models.Model):
    """Produk (barang jadi / bahan) — mirror ``product.template`` Odoo."""

    odoo_id = models.PositiveBigIntegerField(
        "odoo id",
        null=True,
        blank=True,
        unique=True,
        help_text="ID record di Odoo (product.template / product.product).",
    )
    odoo_tmpl_id = models.PositiveBigIntegerField(
        "odoo template id",
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "ID product.template di Odoo — BEDA dari product.product.id; "
            "dipakai memetakan mrp.bom.product_tmpl_id. TIDAK unik: beberapa "
            "varian (product.product) berbagi satu template yang sama."
        ),
    )
    code = models.CharField(
        "kode",
        max_length=64,
        unique=True,
        help_text="Kode produk (default_code di Odoo).",
    )
    name = models.CharField("nama", max_length=255)
    # --- H1.1 (MES = source of truth master) ---------------------------------
    # Field berikut ditambahkan H1.1 supaya Product bisa di-CRUD penuh dari MES
    # (bukan cuma mirror Odoo). Semua **aditif**: field lama tidak diubah, jadi
    # `sync_master_products` (pull Odoo) & endpoint lama tetap jalan apa adanya.
    #
    # Catatan `uom`: nama field-nya TANPA akhiran `_id` (konvensi repo — lihat
    # `Bundle.current_work_center`) sehingga atribut `product.uom_id` = **pk**
    # dan `product.uom` = instance UoM; kolom DB-nya tetap `uom_id`. API
    # mengekspor `uom_id` (pk) + `uom_code`.
    category = models.CharField(
        "kategori",
        max_length=64,
        blank=True,
        default="",
        help_text="Kategori produk (teks bebas; pemetaan ke categ_id Odoo menyusul).",
    )
    uom = models.ForeignKey(
        "UoM",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="products",
        verbose_name="uom",
        help_text="Satuan produk (diisi dari master UoM — H1.2); null = belum ditentukan.",
    )
    sale_price = models.DecimalField(
        "harga jual",
        max_digits=16,
        decimal_places=2,
        default=0,
        help_text="Harga jual ke pelanggan (dipakai OrderLine/Invoice — H2/H3).",
    )
    cost_price = models.DecimalField(
        "harga pokok",
        max_digits=16,
        decimal_places=2,
        default=0,
        help_text="Harga pokok produksi/HPP (dasar laporan HPP — H4).",
    )
    price_updated_at = models.DateTimeField(
        "harga diubah pada",
        null=True,
        blank=True,
        help_text=(
            "Waktu terakhir `sale_price`/`cost_price` diubah dari MES (audit trail harga, H3.5); "
            "null = belum pernah diubah setelah produk dibuat."
        ),
    )
    weight = models.FloatField(
        "berat (kg)",
        null=True,
        blank=True,
        help_text="Berat satuan dalam kg; null = belum diketahui.",
    )
    image_url = models.URLField(
        "url gambar",
        blank=True,
        default="",
        help_text="URL gambar produk (opsional, tidak diunggah ke repo).",
    )
    is_active = models.BooleanField("aktif", default=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Product"
        verbose_name_plural = "Products"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class BOM(models.Model):
    """Bill of Material — mirror ``mrp.bom`` Odoo (header).

    Menyimpan header + relasi ke ``Product`` (boleh ``NULL`` kalau produk belum
    tersinkron); komponen (``mrp.bom.line``) ada di model :class:`BOMLine`
    (``related_name="lines"``).

    H1.5 menambahkan 3 field supaya BOM bisa di-CRUD penuh dari MES **tanpa**
    mengarang data saat push ke Odoo (probe ``fields_get`` ``mrp.bom``: ``product_qty``
    dan ``product_uom_id`` WAJIB):

    * ``output_qty`` — jumlah output BOM (Odoo: ``product_qty``);
    * ``uom`` — FK ke ``master.UoM`` (Odoo: ``product_uom_id``), null = belum dipilih
      (push menolak dengan pesan jelas, bukan mengarang id);
    * ``notes`` — catatan bebas (murni MES, tidak dikirim ke Odoo).

    ``product`` tetap **nullable + ``SET_NULL``** (bukan ``PROTECT``) karena pull
    Odoo (``_bom_defaults``) sengaja membuat BOM tanpa produk bila produknya belum
    tersinkron — keputusan H1.5: jangan memecah alur tarik yang sudah jalan.
    """

    odoo_id = models.PositiveBigIntegerField(
        "odoo id",
        null=True,
        blank=True,
        unique=True,
        help_text="ID record di Odoo (mrp.bom).",
    )
    product = models.ForeignKey(
        Product,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="boms",
        verbose_name="produk",
        help_text="Produk yang dihasilkan BOM ini (null kalau produk belum tersinkron).",
    )
    code = models.CharField(
        "kode",
        max_length=64,
        unique=True,
        help_text="Kode BOM (reference di Odoo).",
    )
    name = models.CharField("nama", max_length=255, blank=True, default="")
    # --- H1.5 (MES = source of truth master) ---------------------------------
    output_qty = models.DecimalField(
        "jumlah output",
        max_digits=16,
        decimal_places=3,
        default=1,
        help_text="Jumlah produk jadi per 1 siklus BOM (Odoo: product_qty); wajib > 0.",
    )
    uom = models.ForeignKey(
        "UoM",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="boms",
        verbose_name="satuan",
        help_text="Satuan output (Odoo: product_uom_id); null = belum dipilih.",
    )
    notes = models.TextField(
        "catatan",
        blank=True,
        default="",
        help_text="Catatan internal MES (tidak dikirim ke Odoo).",
    )
    is_active = models.BooleanField("aktif", default=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "BOM"
        verbose_name_plural = "BOM"
        ordering = ("code",)

    def __str__(self) -> str:
        product = self.product.code if self.product_id else ""
        return f"{self.code} - {self.name or product}"


class BOMLine(models.Model):
    """Komponen Bill of Material — mirror ``mrp.bom.line`` Odoo.

    Baris komponen milik satu :class:`BOM` (``bom``) dan merujuk ``Product``
    bahan (``product``). ``product`` boleh kosong (``SET_NULL``) untuk bahan
    yang belum tersinkron dari Odoo.

    H1.5 menambahkan 3 field (``mrp.bom.line`` hasil probe: ``product_qty`` +
    ``product_uom_id`` WAJIB, ``sequence`` opsional):

    * ``uom`` — FK ke ``master.UoM`` (Odoo: ``product_uom_id``); null = warisi
      satuan produk saat push (Odoo punya default dari ``product_id``);
    * ``sequence`` — urutan tampil baris (Odoo: ``sequence``, default 10);
    * ``notes`` — catatan internal MES (tidak dikirim ke Odoo).

    **``qty`` TIDAK ditambahkan**: kolom kuantitas sudah ada di ``product_qty``
    (FloatField) dan dipakai ``integrations/erp_sync/services/material_readiness.py``
    (``Σ bom.lines…product_qty``) + pull Odoo, jadi API H1.5 mengekspor
    ``product_qty`` sebagai ``qty`` (tanpa duplikasi data).
    """

    odoo_id = models.PositiveBigIntegerField(
        "odoo id",
        null=True,
        blank=True,
        unique=True,
        help_text="ID record di Odoo (mrp.bom.line).",
    )
    bom = models.ForeignKey(
        BOM,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="BOM",
        help_text="BOM induk baris komponen ini.",
    )
    product = models.ForeignKey(
        Product,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="bom_lines",
        verbose_name="komponen",
        help_text="Produk bahan (mrp.bom.line.product_id).",
    )
    code = models.CharField(
        "kode",
        max_length=64,
        blank=True,
        default="",
        help_text="Kode baris BOM (opsional; tidak unik).",
    )
    product_qty = models.FloatField("qty", default=0)
    # --- H1.5 (MES = source of truth master) ---------------------------------
    uom = models.ForeignKey(
        "UoM",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="bom_lines",
        verbose_name="satuan",
        help_text="Satuan komponen (Odoo: product_uom_id); null = warisi satuan produk.",
    )
    sequence = models.PositiveIntegerField(
        "urutan",
        default=10,
        help_text="Urutan tampil baris komponen (Odoo: sequence).",
    )
    notes = models.TextField(
        "catatan",
        blank=True,
        default="",
        help_text="Catatan internal MES (tidak dikirim ke Odoo).",
    )
    is_active = models.BooleanField("aktif", default=True)

    class Meta:
        verbose_name = "BOM Line"
        verbose_name_plural = "BOM Lines"
        ordering = ("bom", "id")

    def __str__(self) -> str:
        component = self.product.code if self.product_id else self.code
        return f"{self.bom.code} - {component}"


class Partner(models.Model):
    """Partner bisnis — mirror ``res.partner`` Odoo (pelanggan / supplier).

    H1.6 menambahkan field yang diminta UI (CHANGES-DETAIL §8: ``email``,
    ``phone``, ``city``, ``address``, ``npwp``, ``is_vendor``, ``is_customer``)
    plus 3 field pendukung yang **terbukti** ada di ``res.partner`` Odoo 17 (probe
    ``fields_get``):

    * ``is_company`` — Boolean; di Odoo field mandiri (data dev membuktikan
      perusahaan bisa **tanpa** ``vat``), jadi TIDAK di-derive dari NPWP;
      push mengirim ``is_company`` + ``company_type`` (``company``/``person``);
    * ``customer_rank`` / ``supplier_rank`` — hitungan transaksi Odoo (bukan 0/1);
      disimpan supaya UI menampilkan angka nyata hasil tarikan, dan saat **create**
      LazyMES hanya mengirim 1/0 sebagai penanda customer/vendor (update tidak
      mengirim rank agar tidak menurunkan hitungan Odoo).

    ``npwp`` = NPWP Indonesia (Odoo ``vat``); disimpan ternormalisasi digit
    (15/16 digit) dan dipetakan ke ``vat`` saat push/tarik. ``address`` (TextField)
    ↔ Odoo ``street`` (tarikan menggabung ``street`` + ``street2`` dengan newline).
    """

    odoo_id = models.PositiveBigIntegerField(
        "odoo id",
        null=True,
        blank=True,
        unique=True,
        help_text="ID record di Odoo (res.partner).",
    )
    code = models.CharField(
        "kode",
        max_length=64,
        unique=True,
        help_text="Kode partner (ref di Odoo).",
    )
    name = models.CharField("nama", max_length=255)
    # --- H1.6 (MES = source of truth master) ---------------------------------
    is_customer = models.BooleanField(
        "pelanggan",
        default=True,
        help_text="Dipakai sebagai pelanggan (Odoo: customer_rank > 0).",
    )
    is_vendor = models.BooleanField(
        "supplier",
        default=False,
        help_text="Dipakai sebagai supplier/vendor (Odoo: supplier_rank > 0).",
    )
    is_company = models.BooleanField(
        "perusahaan",
        default=True,
        help_text="True = badan usaha (Odoo: is_company/company_type).",
    )
    email = models.EmailField("email", max_length=254, blank=True, default="")
    phone = models.CharField("telepon", max_length=32, blank=True, default="")
    city = models.CharField("kota", max_length=64, blank=True, default="")
    address = models.TextField(
        "alamat",
        blank=True,
        default="",
        help_text="Alamat bebas (Odoo: street; tarikan menggabung street + street2).",
    )
    npwp = models.CharField(
        "npwp",
        max_length=32,
        blank=True,
        default="",
        help_text="NPWP (Odoo: vat); bila diisi wajib 15/16 digit — divalidasi service.",
    )
    customer_rank = models.PositiveIntegerField(
        "customer rank",
        default=0,
        help_text="Hitungan pelanggan dari Odoo (0 = belum pernah transaksi).",
    )
    supplier_rank = models.PositiveIntegerField(
        "supplier rank",
        default=0,
        help_text="Hitungan supplier dari Odoo (0 = belum pernah transaksi).",
    )
    is_active = models.BooleanField("aktif", default=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Partner"
        verbose_name_plural = "Partners"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class UoM(models.Model):
    """Unit of Measure — mirror ``uom.uom`` Odoo.

    H1.2 menambahkan 4 field supaya UoM bisa di-CRUD penuh dari MES **tanpa**
    mengarang data saat push ke Odoo (``category_id``, ``uom_type``, ``factor``,
    ``rounding`` semuanya WAJIB di ``uom.uom`` — hasil probe ``fields_get``):
    ``category``, ``uom_type``, ``factor``, ``rounding``. Field lama
    (``odoo_id``/``code``/``name``/``is_active``) tidak diubah.
    """

    class UomType(models.TextChoices):
        """Jenis UoM — nilai HARUS sama dengan selection ``uom.uom.uom_type`` Odoo."""

        BIGGER = "bigger", "Lebih besar dari unit referensi"
        REFERENCE = "reference", "Unit referensi kategori"
        SMALLER = "smaller", "Lebih kecil dari unit referensi"

    odoo_id = models.PositiveBigIntegerField(
        "odoo id",
        null=True,
        blank=True,
        unique=True,
        help_text="ID record di Odoo (uom.uom).",
    )
    code = models.CharField(
        "kode",
        max_length=64,
        unique=True,
        blank=True,
        default="",
        help_text="Kode UoM.",
    )
    name = models.CharField("nama", max_length=255)
    # --- H1.2 (MES = source of truth master) ---------------------------------
    category = models.CharField(
        "kategori",
        max_length=64,
        blank=True,
        default="",
        help_text="Nama kategori Odoo (uom.category); dipakai saat push (dicari/dibuat).",
    )
    uom_type = models.CharField(
        "tipe",
        max_length=16,
        choices=UomType.choices,
        default=UomType.REFERENCE,
        help_text="Jenis UoM terhadap unit referensi kategorinya (Odoo: uom_type).",
    )
    factor = models.FloatField(
        "rasio",
        default=1.0,
        help_text="Rasio terhadap unit referensi kategori (Odoo: factor); > 0.",
    )
    rounding = models.FloatField(
        "presisi pembulatan",
        default=0.01,
        help_text="Presisi pembulatan kuantitas (Odoo: rounding); > 0.",
    )
    is_active = models.BooleanField("aktif", default=True)

    class Meta:
        verbose_name = "UoM"
        verbose_name_plural = "UoM"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Location(models.Model):
    """Lokasi stok — mirror ``stock.location`` Odoo.

    H1.4 menambahkan 3 field yang **benar ada** di ``stock.location`` (probe
    ``fields_get``: ``usage`` wajib; ``location_id`` = induk; sedangkan
    ``warehouse_id`` diturunkan Odoo dari hierarki):

    * ``usage`` — 7 nilai, sama persis dengan selection Odoo;
    * ``parent_id`` — self-FK (``PROTECT``: induk tidak bisa dihapus saat masih
      punya anak);
    * ``warehouse_id`` — FK ke ``master.Warehouse`` (``PROTECT``), nullable karena
      Odoo punya banyak lokasi global/view tanpa gudang.

    ``complete_name`` & ``parent_path`` **sengaja TIDAK disimpan** (keputusan H1.4):
    ``complete_name`` di-*derive* saat serialize (rantai induk), ``parent_path``
    hanya milik Odoo (fetch on-demand kalau perlu).

    Catatan penamaan FK (konvensi repo, sama seperti ``Product.uom`` di H1.1): field
    FK-nya bernama ``parent`` & ``warehouse`` **tanpa** akhiran ``_id`` sehingga
    atribut ``location.parent_id``/``location.warehouse_id`` = **pk** (dan kolom DB
    tetap ``parent_id``/``warehouse_id``); API mengekspor ``parent_id``/
    ``warehouse_id`` + ``parent_name``/``warehouse_name``.
    """

    class Usage(models.TextChoices):
        """Jenis lokasi — nilai HARUS sama dengan selection ``stock.location.usage`` Odoo."""

        SUPPLIER = "supplier", "Lokasi Vendor"
        VIEW = "view", "View (hanya wadah)"
        INTERNAL = "internal", "Lokasi Internal"
        CUSTOMER = "customer", "Lokasi Pelanggan"
        INVENTORY = "inventory", "Kehilangan Persediaan"
        PRODUCTION = "production", "Produksi"
        TRANSIT = "transit", "Transit"

    odoo_id = models.PositiveBigIntegerField(
        "odoo id",
        null=True,
        blank=True,
        unique=True,
        help_text="ID record di Odoo (stock.location).",
    )
    code = models.CharField(
        "kode",
        max_length=64,
        unique=True,
        blank=True,
        default="",
        help_text="Kode lokasi.",
    )
    name = models.CharField("nama", max_length=255)
    # --- H1.4 (MES = source of truth master) ---------------------------------
    usage = models.CharField(
        "jenis",
        max_length=32,
        choices=Usage.choices,
        default=Usage.INTERNAL,
        db_index=True,
        help_text="Jenis lokasi (Odoo: usage) — internal/view/supplier/customer/…",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        verbose_name="induk",
        help_text="Lokasi induk (Odoo: location_id); null = lokasi akar.",
    )
    warehouse = models.ForeignKey(
        "Warehouse",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="locations",
        verbose_name="gudang",
        help_text="Gudang pemilik lokasi; null = lokasi global/view.",
    )
    is_active = models.BooleanField("aktif", default=True)

    class Meta:
        verbose_name = "Location"
        verbose_name_plural = "Locations"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Warehouse(models.Model):
    """Gudang — mirror ``stock.warehouse`` Odoo.

    H1.3 menambahkan 2 field yang **benar ada** di ``stock.warehouse`` dan
    ``required=True`` di Odoo (hasil probe ``fields_get``): ``reception_steps`` &
    ``delivery_steps`` — sehingga push punya nilai nyata, tanpa mengarang.

    Catatan: field ``usage`` (internal|view|supplier|…) **TIDAK** ditambahkan di sini
    karena itu milik ``stock.location`` (ditangani di H1.4 Location).
    ``view_location_id``/``lot_stock_id``/``company_id`` juga **tidak** ditambahkan:
    sprint utang `warehouse-create-mapping` membuktikan Odoo 17 **membuat sendiri**
    ``view_location_id`` + ``lot_stock_id`` di ``create()`` (sumber
    ``stock/models/stock_warehouse.py`` baris 109–126) dan ``company_id``
    ``readonly`` (default dari company user) — jadi push create cukup 6 field MES.
    """

    class ReceptionSteps(models.TextChoices):
        """Alur penerimaan — nilai HARUS sama dengan selection Odoo."""

        ONE_STEP = "one_step", "Terima langsung ke stok (1 langkah)"
        TWO_STEPS = "two_steps", "Terima ke input lalu stok (2 langkah)"
        THREE_STEPS = "three_steps", "Terima ke input, QC, lalu stok (3 langkah)"

    class DeliverySteps(models.TextChoices):
        """Alur pengiriman — nilai HARUS sama dengan selection Odoo."""

        SHIP_ONLY = "ship_only", "Kirim langsung (1 langkah)"
        PICK_SHIP = "pick_ship", "Ambil lalu kirim (2 langkah)"
        PICK_PACK_SHIP = "pick_pack_ship", "Ambil, kemas, lalu kirim (3 langkah)"

    odoo_id = models.PositiveBigIntegerField(
        "odoo id",
        null=True,
        blank=True,
        unique=True,
        help_text="ID record di Odoo (stock.warehouse).",
    )
    code = models.CharField(
        "kode",
        max_length=64,
        unique=True,
        blank=True,
        default="",
        help_text="Kode gudang (short_name di Odoo — Odoo membatasi 5 karakter).",
    )
    name = models.CharField("nama", max_length=255)
    # --- H1.3 (MES = source of truth master) ---------------------------------
    reception_steps = models.CharField(
        "langkah penerimaan",
        max_length=16,
        choices=ReceptionSteps.choices,
        default=ReceptionSteps.ONE_STEP,
        help_text="Alur penerimaan barang (Odoo: reception_steps).",
    )
    delivery_steps = models.CharField(
        "langkah pengiriman",
        max_length=16,
        choices=DeliverySteps.choices,
        default=DeliverySteps.SHIP_ONLY,
        help_text="Alur pengiriman barang (Odoo: delivery_steps).",
    )
    is_active = models.BooleanField("aktif", default=True)

    class Meta:
        verbose_name = "Warehouse"
        verbose_name_plural = "Warehouses"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Tax(models.Model):
    """Pajak — mirror ``account.tax`` Odoo.

    H3.6 menambahkan **tarif & jenis** (aditif; field lama ``odoo_id``/``code``/``name``/
    ``is_active`` tidak diubah) supaya pajak bisa dikonfigurasi dari MES
    (`docs/CHANGES-DETAIL-H1H5.md` §6: default PPN 11%, konfigurabel).
    """

    class AmountType(models.TextChoices):
        """Tipe nilai pajak — sama dengan selection ``account.tax.amount_type`` yang dipakai."""

        PERCENT = "percent", "Persen (%)"
        FIXED = "fixed", "Nominal tetap"

    class TaxUse(models.TextChoices):
        """Jenis pemakaian pajak — selection ``account.tax.type_tax_use`` Odoo."""

        SALE = "sale", "Penjualan"
        PURCHASE = "purchase", "Pembelian"
        NONE = "none", "Tanpa jenis"

    odoo_id = models.PositiveBigIntegerField(
        "odoo id",
        null=True,
        blank=True,
        unique=True,
        help_text="ID record di Odoo (account.tax).",
    )
    code = models.CharField(
        "kode",
        max_length=64,
        unique=True,
        blank=True,
        default="",
        help_text="Kode pajak.",
    )
    name = models.CharField("nama", max_length=255)
    # --- H3.6 (MES = source of truth master) ---------------------------------
    amount = models.DecimalField(
        "tarif",
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Tarif pajak (persen) atau nominal tetap; 0 diizinkan (PPN 0% / bebas pajak).",
    )
    amount_type = models.CharField(
        "tipe nilai",
        max_length=16,
        choices=AmountType.choices,
        default=AmountType.PERCENT,
        help_text="Persen (default) atau nominal tetap — Odoo: account.tax.amount_type.",
    )
    type_tax_use = models.CharField(
        "jenis pajak",
        max_length=16,
        choices=TaxUse.choices,
        default=TaxUse.SALE,
        db_index=True,
        help_text="Penjualan / pembelian / tanpa jenis — Odoo: account.tax.type_tax_use.",
    )
    price_include = models.BooleanField(
        "harga termasuk pajak",
        default=False,
        help_text="True kalau harga sudah termasuk pajak (Odoo: price_include).",
    )
    is_default = models.BooleanField(
        "pajak default",
        default=False,
        db_index=True,
        help_text=(
            "Penanda pajak default MES (dipakai form order/invoice); maksimal satu baris "
            "aktif — dijaga oleh service `set_default_tax`."
        ),
    )
    is_active = models.BooleanField("aktif", default=True)

    class Meta:
        verbose_name = "Tax"
        verbose_name_plural = "Taxes"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Journal(models.Model):
    """Jurnal akuntansi — mirror ``account.journal`` Odoo."""

    class JournalType(models.TextChoices):
        """Jenis jurnal Odoo (``account.journal.type``) — H3.4.

        Hanya ``GENERAL`` yang boleh dipakai Journal Entry manual MES (keputusan
        STEP 0 H3.4): journal ``sale``/``purchase``/``bank``/``cash`` dipakai Odoo
        sendiri untuk invoice/bill/payment sehingga posting manual di sana akan
        mengacaukan alur akuntansi.
        """

        GENERAL = "general", "Umum (General)"
        SALE = "sale", "Penjualan"
        PURCHASE = "purchase", "Pembelian"
        BANK = "bank", "Bank"
        CASH = "cash", "Kas"

    odoo_id = models.PositiveBigIntegerField(
        "odoo id",
        null=True,
        blank=True,
        unique=True,
        help_text="ID record di Odoo (account.journal).",
    )
    code = models.CharField(
        "kode",
        max_length=64,
        unique=True,
        blank=True,
        default="",
        help_text="Kode jurnal.",
    )
    name = models.CharField("nama", max_length=255)
    #: H3.4 — jenis jurnal (aditif). Kosong = belum pernah di-pull dari Odoo
    #: (baris lama) ⇒ guard journal general di service H3.4 **longgar** supaya
    #: baris lama tidak memblokir pembuatan journal entry.
    journal_type = models.CharField(
        "jenis",
        max_length=16,
        blank=True,
        default="",
        db_index=True,
        help_text=(
            "Jenis jurnal Odoo (account.journal.type): general/sale/purchase/bank/cash. "
            "Kosong = belum di-pull. Hanya 'general' yang boleh untuk Journal Entry H3.4."
        ),
    )
    is_active = models.BooleanField("aktif", default=True)

    class Meta:
        verbose_name = "Journal"
        verbose_name_plural = "Journals"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Currency(models.Model):
    """Mata uang — mirror ``res.currency`` Odoo."""

    odoo_id = models.PositiveBigIntegerField(
        "odoo id",
        null=True,
        blank=True,
        unique=True,
        help_text="ID record di Odoo (res.currency).",
    )
    code = models.CharField(
        "kode",
        max_length=64,
        unique=True,
        blank=True,
        default="",
        help_text="Kode mata uang (ISO, mis. IDR).",
    )
    name = models.CharField("nama", max_length=255)
    # --- H5.2 (mata uang MES: simbol + kurs + penanda default) ----------------
    symbol = models.CharField(
        "simbol",
        max_length=8,
        blank=True,
        default="",
        help_text="Simbol tampilan (mis. Rp, $, €); kosong = tidak ditampilkan.",
    )
    rate = models.DecimalField(
        "kurs",
        max_digits=20,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=(
            "Kurs terhadap mata uang utama — **mirror Odoo** (`res.currency.rate`, "
            "diisi pull I1); MES hanya menampilkan/mengisi manual sebagai cadangan."
        ),
    )
    is_default = models.BooleanField(
        "default",
        default=False,
        help_text=(
            "Mata uang default MES — dijaga tunggal oleh `set_default_currency`; "
            "**bukan** field Odoo (keputusan MES, pola `Tax.is_default` H3.6)."
        ),
    )
    is_active = models.BooleanField("aktif", default=True)

    class Meta:
        verbose_name = "Currency"
        verbose_name_plural = "Currencies"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Company(models.Model):
    """Profil perusahaan MES (H5.1) — **greenfield** + **singleton** (1 baris/instalasi).

    Sumber tunggal identitas perusahaan (nama, alamat, NPWP, logo, mata uang default)
    yang dipakai header dokumen/cetak. **Bukan** mirror ``res.company`` Odoo (probe
    STEP 0: tidak ada transport/pull company & tidak ada konsumen MES yang memakainya;
    ``res.company`` = konfigurasi akuntansi Odoo) ⇒ **MES-only**: setiap tulis menulis
    ``SyncRecord`` ``master.company``/``MASTER_PUSH`` ber-status ``SKIPPED`` +
    ``AuditLog`` (pola H5.2/Sprint C).

    **Singleton** ditegakkan di service (`company_services.update_company`): endpoint
    hanya GET/PUT — baris pertama di-update, dibuat **sekali** bila belum ada
    (create-on-first-PUT) ⇒ tidak mungkin ada 2 baris lewat API.

    ``npwp`` disimpan **ternormalisasi digit** (15/16 digit bila diisi; reuse
    `partner_services.normalize_npwp` — H1.6). ``currency`` menunjuk `master.Currency`
    (H5.2) dengan ``PROTECT`` sehingga mata uang yang dipakai perusahaan tidak bisa
    dihapus.
    """

    name = models.CharField("nama", max_length=255)
    legal_name = models.CharField("nama legal", max_length=255, blank=True, default="")
    address = models.TextField("alamat", blank=True, default="")
    city = models.CharField("kota", max_length=64, blank=True, default="")
    country = models.CharField(
        "negara",
        max_length=2,
        blank=True,
        default="",
        help_text="Kode ISO 3166-1 alpha-2 (mis. ID) — teks, bukan FK (master.Country tidak ada).",
    )
    phone = models.CharField("telepon", max_length=32, blank=True, default="")
    email = models.EmailField("email", max_length=254, blank=True, default="")
    npwp = models.CharField(
        "NPWP",
        max_length=32,
        blank=True,
        default="",
        help_text="NPWP Indonesia — digit saja (15/16 digit), normalisasi pola H1.6.",
    )
    website = models.URLField("website", max_length=200, blank=True, default="")
    logo_url = models.URLField(
        "logo",
        max_length=500,
        blank=True,
        default="",
        help_text="URL logo perusahaan (dipakai header cetak/dokumen).",
    )
    currency = models.ForeignKey(
        "master.Currency",
        verbose_name="mata uang",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="companies",
        help_text="Mata uang default MES (H5.2) — PROTECT: tidak bisa dihapus saat dipakai.",
    )
    timezone = models.CharField("zona waktu", max_length=64, default="Asia/Jakarta")
    is_active = models.BooleanField("aktif", default=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Company"
        verbose_name_plural = "Companies"
        ordering = ("pk",)

    def __str__(self) -> str:
        return f"{self.name} ({self.pk})"


class IntegrationConfig(models.Model):
    """Profil konfigurasi integrasi MES ↔ Odoo (H5.6) — **singleton** (1 baris).

    **Keputusan STEP 0 (Opsi B — "tersimpan + viewer efektif")**: baris ini menyimpan
    **profil config** yang bisa diisi/diedit dari UI (ber-jejak ledger ``SKIPPED`` +
    ``AuditLog``), **tetapi konsumen TIDAK membacanya** — kedelapan konsumen
    (``erp_sync/client.py``, ``adapters/factory.py``, ``transport/factory.py``,
    ``adapters/odoo.py``, ``services/scrap_sync.py``, ``services/payment_services.py``,
    ``tasks_reconciliation.py``, ``integrations/wa_bot``) tetap membaca
    ``django.conf.settings.*`` dari ``.env``. Jadi perubahan baru **AKTIF** setelah
    disalin ke ``.env`` + restart ``django``/``celery_worker``/``celery_beat`` — UI
    melaporkannya lewat ``effective`` / ``diverges`` / ``needs_restart`` pada
    ``GET /api/v1/settings/integration/``. Opsi C (DB meng-override ``.env``) ditolak:
    8 konsumen + 113 referensi test.

    ⚠️ ``odoo_api_key`` disimpan **plaintext** (keputusan STEP 0; enkripsi Fernet = V2)
    dan **selalu di-mask** ``***`` di response API (PUT ``***`` = tidak mengubah,
    PUT ``''`` = menghapus).

    Ini **bukan** mirror ``res.company``/config Odoo — murni profil MES (MES-only).
    """

    class Adapter(models.TextChoices):
        """Adapter ERP aktif (sama dengan nilai ``settings.ERP_ADAPTER``)."""

        ODOO = "odoo", "Odoo (JSON-RPC)"
        NULL = "null", "Null (tanpa ERP)"

    erp_adapter = models.CharField(
        "adapter ERP",
        max_length=16,
        choices=Adapter.choices,
        default=Adapter.ODOO,
        help_text="Sama dengan env ERP_ADAPTER: 'odoo' (JSON-RPC) atau 'null'.",
    )
    odoo_url = models.CharField(
        "URL Odoo",
        max_length=200,
        blank=True,
        default="",
        help_text="Base URL JSON-RPC Odoo (env ODOO_URL), mis. http://odoo:8069.",
    )
    odoo_db = models.CharField(
        "database Odoo", max_length=64, blank=True, default="", help_text="env ODOO_DB."
    )
    odoo_user = models.CharField(
        "user Odoo",
        max_length=64,
        blank=True,
        default="",
        help_text="Login user API Odoo (env ODOO_USER).",
    )
    odoo_api_key = models.CharField(
        "API key Odoo",
        max_length=255,
        blank=True,
        default="",
        help_text="API key/password user API (env ODOO_API_KEY) — plaintext, di-mask di API.",
    )
    odoo_timeout = models.DecimalField(
        "timeout Odoo (detik)",
        max_digits=6,
        decimal_places=2,
        default=Decimal("30.00"),
        help_text="env ODOO_TIMEOUT (detik).",
    )
    # --- id Odoo (env ODOO_*_ID) ---------------------------------------------
    odoo_location_wip_id = models.PositiveBigIntegerField(
        "lokasi WIP", null=True, blank=True, help_text="env ODOO_LOCATION_WIP_ID."
    )
    odoo_location_production_id = models.PositiveBigIntegerField(
        "lokasi produksi",
        null=True,
        blank=True,
        help_text="env ODOO_LOCATION_PRODUCTION_ID.",
    )
    odoo_location_fg_id = models.PositiveBigIntegerField(
        "lokasi FG", null=True, blank=True, help_text="env ODOO_LOCATION_FG_ID."
    )
    odoo_location_scrap_id = models.PositiveBigIntegerField(
        "lokasi scrap", null=True, blank=True, help_text="env ODOO_LOCATION_SCRAP_ID."
    )
    odoo_uom_id = models.PositiveBigIntegerField(
        "UoM default", null=True, blank=True, help_text="env ODOO_UOM_ID (mis. PCS)."
    )
    odoo_payment_journal_id = models.PositiveBigIntegerField(
        "journal pembayaran",
        null=True,
        blank=True,
        help_text="env ODOO_PAYMENT_JOURNAL_ID (H3.3, opsional).",
    )
    odoo_picking_type_internal_id = models.PositiveBigIntegerField(
        "picking type internal",
        null=True,
        blank=True,
        help_text="env ODOO_PICKING_TYPE_INTERNAL_ID (H2.6, opsional — dicari otomatis).",
    )
    # --- rekonsiliasi (env RECONCILIATION_*) ---------------------------------
    reconciliation_tolerance_units = models.DecimalField(
        "toleransi unit",
        max_digits=10,
        decimal_places=2,
        default=Decimal("5.00"),
        help_text="env RECONCILIATION_TOLERANCE_UNITS (selisih absolut wajar).",
    )
    reconciliation_tolerance_pct = models.DecimalField(
        "toleransi (%)",
        max_digits=8,
        decimal_places=4,
        default=Decimal("0.0100"),
        help_text="env RECONCILIATION_TOLERANCE_PCT (rasio 0..1; 0.01 = 1%).",
    )
    reconciliation_alert_wa_to = models.JSONField(
        "penerima alert WA",
        default=list,
        blank=True,
        help_text="Daftar nomor WA (env RECONCILIATION_ALERT_WA_TO) — kosong = alert dilewati.",
    )
    is_active = models.BooleanField("aktif", default=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Integration Config"
        verbose_name_plural = "Integration Configs"
        ordering = ("pk",)

    def __str__(self) -> str:
        return f"IntegrationConfig ({self.erp_adapter}, pk={self.pk})"


class WAConfig(models.Model):
    """Profil konfigurasi gateway WhatsApp (H5.8) — **singleton** (1 baris).

    **Keputusan STEP 0 (Opsi B — "tersimpan + viewer efektif")**: baris ini menyimpan
    **profil gateway** yang bisa diisi/diedit dari UI (ber-jejak ledger ``SKIPPED`` +
    ``AuditLog``), **tetapi konsumen TIDAK membacanya** — ketiga konsumen
    (``integrations/wa_bot/services.py`` :func:`get_wa_gateway` untuk pengiriman,
    ``integrations/erp_sync/tasks_reconciliation.py`` alert rekonsiliasi, dan
    ``integrations/ai/hitl_views.py`` alert HITL) tetap membaca
    ``django.conf.settings.WA_*`` dari ``.env``. Jadi perubahan baru **AKTIF** setelah
    disalin ke ``.env`` + restart ``django``/``celery_worker``/``celery_beat`` — UI
    melaporkannya lewat ``effective`` / ``diverges`` / ``needs_restart`` pada
    ``GET /api/v1/settings/wa/``.

    Model ini **terpisah** dari ``IntegrationConfig`` (H5.6) atas dasar SRP: H5.6 =
    profil Odoo, H5.8 = gateway WA (backend/url/key). Nomor penerima alert
    (``RECONCILIATION_ALERT_WA_TO``) tetap milik ``IntegrationConfig`` — **tidak**
    diduplikasi di sini supaya tidak ada dua sumber kebenaran.

    ⚠️ ``wa_api_key`` disimpan **plaintext** (keputusan STEP 0; enkripsi Fernet = V2)
    dan **selalu di-mask** ``***`` di response API (PUT ``***`` = tidak mengubah,
    PUT ``''`` = menghapus).

    Ini **bukan** mirror konfigurasi penyedia WA mana pun — murni profil MES (MES-only).
    """

    class Backend(models.TextChoices):
        """Backend gateway WA (nilai yang boleh diketik di UI; sama dengan env)."""

        MOCK = "mock", "Mock (tanpa jaringan)"
        REAL = "real", "Real (vendor WA)"
        API = "api", "API (HTTP)"

    wa_backend = models.CharField(
        "backend WA",
        max_length=16,
        choices=Backend.choices,
        default=Backend.MOCK,
        help_text="Sama dengan env WA_BACKEND: 'mock' | 'real' | 'api'.",
    )
    wa_api_url = models.CharField(
        "URL API WA",
        max_length=200,
        blank=True,
        default="",
        help_text="Base URL penyedia WA (env WA_API_URL), mis. https://api.vendor-wa.id.",
    )
    wa_api_key = models.CharField(
        "API key WA",
        max_length=255,
        blank=True,
        default="",
        help_text="API key penyedia WA (env WA_API_KEY) — plaintext, di-mask di API.",
    )
    is_active = models.BooleanField("aktif", default=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "WA Config"
        verbose_name_plural = "WA Configs"
        ordering = ("pk",)

    def __str__(self) -> str:
        return f"WAConfig ({self.wa_backend}, pk={self.pk})"


class PrinterConfig(models.Model):
    """Profil konfigurasi printer thermal ESC/POS (H5.7) — **singleton** (1 baris).

    **Keputusan STEP 0 (Opsi B — "tersimpan + viewer efektif")**: baris ini menyimpan
    **profil printer** yang bisa diisi/diedit dari UI (ber-jejak ledger ``SKIPPED`` +
    ``AuditLog``), **tetapi konsumen TIDAK membacanya** — ``integrations/printing``
    (``backends/__init__.get_backend()`` dipakai ``integrations/printing/api.py``:
    ``PrintBundleTagView``/``PrintCouponView``) tetap membaca ``django.conf.settings``
    ``PRINTER_*`` dari ``.env``. Jadi perubahan baru **AKTIF** setelah disalin ke
    ``.env`` + restart ``django``/``celery_worker``/``celery_beat`` — UI melaporkannya
    lewat ``effective`` / ``diverges`` / ``needs_restart`` pada
    ``GET /api/v1/settings/printer/``.

    ⚠️ **Tidak ada field rahasia** di sini (host/port/USB id/folder bukan kredensial)
    ⇒ response **tanpa mask** — beda dari ``IntegrationConfig`` (H5.6) &
    ``WAConfig`` (H5.8).

    Ini **bukan** mirror printer Odoo — murni profil MES (MES-only).
    """

    class Backend(models.TextChoices):
        """Backend cetak (sama dengan nilai ``settings.PRINTER_BACKEND``)."""

        MOCK = "mock", "Mock (file .bin, tanpa printer)"
        USB = "usb", "USB (stub: butuh python-escpos + libusb)"
        NETWORK = "network", "Network (TCP raw, mis. port 9100)"

    printer_backend = models.CharField(
        "backend printer",
        max_length=16,
        choices=Backend.choices,
        default=Backend.MOCK,
        help_text="Sama dengan env PRINTER_BACKEND: 'mock' | 'usb' | 'network'.",
    )
    printer_usb_vendor_id = models.CharField(
        "USB vendor id",
        max_length=32,
        blank=True,
        default="",
        help_text="env PRINTER_USB_VENDOR_ID (mis. 0x04b8). Wajib bila backend 'usb'.",
    )
    printer_usb_product_id = models.CharField(
        "USB product id",
        max_length=32,
        blank=True,
        default="",
        help_text="env PRINTER_USB_PRODUCT_ID. Wajib bila backend 'usb'.",
    )
    printer_network_host = models.CharField(
        "host printer",
        max_length=200,
        blank=True,
        default="",
        help_text="env PRINTER_NETWORK_HOST (mis. 192.168.1.50). Wajib bila backend 'network'.",
    )
    printer_network_port = models.PositiveIntegerField(
        "port printer",
        null=True,
        blank=True,
        help_text="env PRINTER_NETWORK_PORT (1..65535; raw printing umumnya 9100).",
    )
    printer_mock_dir = models.CharField(
        "folder mock",
        max_length=200,
        blank=True,
        default="",
        help_text="env PRINTER_MOCK_DIR (folder hasil 'cetak' mock; kosong = default /tmp/print_mock).",
    )
    is_active = models.BooleanField("aktif", default=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Printer Config"
        verbose_name_plural = "Printer Configs"
        ordering = ("pk",)

    def __str__(self) -> str:
        return f"PrinterConfig ({self.printer_backend}, pk={self.pk})"


class NumberSequence(models.Model):
    """Penomoran dokumen MES (Sprint C) — ``<prefix>-<year>-<seq:04d>`` per tahun.

    **MES-only** (probe Odoo 17 `ir.sequence`: model ADA — 19 field, 37 record —
    tetapi itu **counter internal dokumen Odoo sendiri** (`name='Chicago 1 Penomoran
    Internal'`, `prefix='CHIC1/INT/'`, `padding=5`) dan `code` tidak required;
    `ir.sequence.date_range` ADA tapi 0 record). Mengirim `number_next` ke sana =
    mengubah penomoran dokumen Odoo yang sudah berjalan ⇒ nomor MES **tidak**
    disinkronkan (ledger `SyncStatus.SKIPPED`, pola H1.7–H1.9), tanpa ``odoo_id``.

    Dipakai H2.1+ lewat `master/sequence_services.py` (`next_number`) — model ini
    **tidak** menggantikan ``Order.code``/``WorkOrder.code`` yang sudah ada (pemanggil
    boleh tetap mengisi manual; service baru = tambahan, bukan breaking).

    Reset per tahun: satu baris **per (code, year)**; baris tahun baru dibuat otomatis
    saat penomoran pertama di tahun itu (copy prefix/padding, ``last_seq=0``).
    """

    code = models.CharField(
        "kode",
        max_length=16,
        db_index=True,
        help_text=(
            "Identitas sequence, mis. SO/PO/WO (dipakai `next_number`). **Tidak** "
            "unik global: satu code punya satu baris PER TAHUN (reset per tahun) — "
            "keunikan dijaga constraint `(code, year)`."
        ),
    )
    name = models.CharField("nama", max_length=64, help_text="mis. Sales Order.")
    prefix = models.CharField(
        "prefiks",
        max_length=16,
        help_text="Teks awal nomor (boleh beda dari `code`), mis. SO.",
    )
    year = models.PositiveIntegerField(
        "tahun",
        help_text="Tahun berjalan sequence (reset: baris baru per tahun).",
    )
    last_seq = models.PositiveIntegerField("nomor terakhir", default=0)
    padding = models.PositiveIntegerField(
        "padding",
        default=4,
        help_text="Panjang minimum angka; angka lebih panjang tidak dipotong.",
    )
    is_active = models.BooleanField("aktif", default=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Number Sequence"
        verbose_name_plural = "Number Sequences"
        ordering = ("code", "year")
        constraints = [
            models.UniqueConstraint(
                fields=["code", "year"],
                name="uniq_sequence_code_year",
            )
        ]
        indexes = [models.Index(fields=["code", "year"], name="idx_sequence_code_year")]

    def __str__(self) -> str:
        return f"{self.code}/{self.year} - {self.last_seq}"


class Account(models.Model):
    """Akun buku besar — mirror ``account.account`` Odoo (H3.4, **pull-only**).

    Dibutuhkan H3.4 (Journal Entry manual): setiap baris jurnal menunjuk satu akun
    (``account_id`` Odoo), sehingga MES perlu daftar akun untuk dropdown form —
    di-*pull* dari Odoo (pola I1/H3.6), **tidak** pernah di-push ke Odoo
    (chart of accounts = wewenang akuntan di Odoo; probe STEP 0: 115 akun hidup).

    Catatan probe STEP 0 H3.4 (Odoo 17):
      * field wajib Odoo: ``code`` (unik **per company**), ``name``, ``account_type``,
        ``company_id``;
      * **TIDAK ADA** field ``active``/``is_active`` di ``account.account`` Odoo 17 —
        penanda nonaktif adalah ``deprecated`` (boolean) ⇒ ``is_active`` di sini
        = ``not deprecated`` (field MES-local, sama pola ``Journal.is_active``);
      * ``reconcile`` (Allow Reconciliation) ikut disimpan supaya UI bisa menandai
        akun yang bisa direkonsiliasi.
    """

    class AccountType(models.TextChoices):
        """``account.account.account_type`` Odoo 17 (18 pilihan — hasil probe)."""

        ASSET_RECEIVABLE = "asset_receivable", "Receivable"
        ASSET_CASH = "asset_cash", "Bank and Cash"
        ASSET_CURRENT = "asset_current", "Current Assets"
        ASSET_NON_CURRENT = "asset_non_current", "Non-current Assets"
        ASSET_PREPAYMENTS = "asset_prepayments", "Prepayments"
        ASSET_FIXED = "asset_fixed", "Fixed Assets"
        LIABILITY_PAYABLE = "liability_payable", "Payable"
        LIABILITY_CREDIT_CARD = "liability_credit_card", "Credit Card"
        LIABILITY_CURRENT = "liability_current", "Current Liabilities"
        LIABILITY_NON_CURRENT = "liability_non_current", "Non-current Liabilities"
        EQUITY = "equity", "Equity"
        EQUITY_UNAFFECTED = "equity_unaffected", "Current Year Earnings"
        INCOME = "income", "Income"
        INCOME_OTHER = "income_other", "Other Income"
        EXPENSE = "expense", "Expenses"
        EXPENSE_DEPRECIATION = "expense_depreciation", "Depreciation"
        EXPENSE_DIRECT_COST = "expense_direct_cost", "Cost of Revenue"
        OFF_BALANCE = "off_balance", "Off-Balance Sheet"

    odoo_id = models.PositiveBigIntegerField(
        "odoo id",
        null=True,
        blank=True,
        unique=True,
        help_text="ID record di Odoo (account.account) — kunci idempotensi pull.",
    )
    code = models.CharField(
        "kode",
        max_length=64,
        unique=True,
        blank=True,
        default="",
        help_text="Kode akun Odoo (mis. 11120005); fallback `ODOO-<id>` bila kosong.",
    )
    name = models.CharField("nama", max_length=255)
    account_type = models.CharField(
        "tipe akun",
        max_length=32,
        blank=True,
        default="",
        db_index=True,
        choices=AccountType.choices,
        help_text="account.account.account_type Odoo (asset/liability/equity/income/expense).",
    )
    reconcile = models.BooleanField(
        "boleh direkonsiliasi",
        default=False,
        help_text="Odoo: account.account.reconcile (Allow Reconciliation).",
    )
    is_active = models.BooleanField(
        "aktif",
        default=True,
        db_index=True,
        help_text="MES-local = NOT account.account.deprecated (Odoo 17 tidak punya `active`).",
    )

    class Meta:
        verbose_name = "Account"
        verbose_name_plural = "Accounts"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"

