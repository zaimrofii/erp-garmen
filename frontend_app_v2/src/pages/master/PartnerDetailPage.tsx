import { useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Pencil, RefreshCw, Users } from "lucide-react";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { Toast, type ToastTone } from "@/components/atoms/Toast";
import { Tooltip } from "@/components/atoms/Tooltip";
import { ImageUpload } from "@/components/molecules/ImageUpload";
import { PageHeader } from "@/components/molecules/PageHeader";
import { FloatingAIAssistant } from "@/components/organisms/FloatingAIAssistant";
import { buildChatContext } from "@/lib/ai-context";
import { deletePartnerImage, fetchPartner, uploadPartnerImage } from "@/api/masterPartners";
import { useApiClient } from "@/hooks/useApiClient";
import { cn } from "@/lib/cn";
import {
  displayOrDash,
  ordersCountLabel,
  partnerDetailItems,
  partnerRoleLabels,
} from "@/lib/master-partner";
import { CARD } from "@/lib/tokens";

/**
 * PartnerDetailPage - route `/master/partners/:id` (H1.6, READ-ONLY).
 *
 * Menampilkan satu partner (kontak, NPWP, peran, rank Odoo, jumlah order yang
 * memakainya) + jejak sync (`odoo_id`; `null` = belum pernah terkirim ke Odoo).
 * Halaman ini TIDAK menulis apa pun:
 *
 *   * **Edit** → `/master/partners/:id/edit` (form yang sama dengan "Partner Baru");
 *   * **Sync ke Odoo** → **placeholder DISABLED** + tooltip (endpoint push manual
 *     belum ada — push otomatis & asinkron tiap POST/PUT lewat task
 *     `erp_sync.push_master_partner`, pantau di `/settings/sync`).
 *
 * Soft delete dilakukan lewat form (checkbox `active` → PUT), konsisten H1.1–H1.5.
 */

/** Status toast halaman (K5.3 — unggah/hapus gambar). */
interface ToastState {
  title: string;
  description: string;
  tone: ToastTone;
}

export function PartnerDetailPage() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const client = useApiClient();

  const parsedId = id === undefined ? null : Number(id);
  const partnerId =
    parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const {
    data: partner,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ["master-partner", partnerId],
    queryFn: () => fetchPartner(client, partnerId ?? 0),
    enabled: partnerId !== null,
    staleTime: 15_000,
  });

  const queryClient = useQueryClient();
  const [toast, setToast] = useState<ToastState | null>(null);
  const [imageBusy, setImageBusy] = useState(false);

  // Sprint E.4 — konteks chat dari data partner yang tampil.
  const aiContext = buildChatContext(
    location,
    { id },
    "detail",
    "partner",
    {},
    partner === undefined
      ? {}
      : {
          code: partner.code,
          name: partner.name,
          is_customer: partner.is_customer,
          is_vendor: partner.is_vendor,
          city: partner.city,
        },
  );

  /** K5.3 — segarkan detail partner setelah gambar berubah (invalidate + refetch). */
  async function refreshPartner(): Promise<void> {
    await queryClient.invalidateQueries({ queryKey: ["master-partner", partnerId] });
    await refetch();
  }

  /** K5.3 — unggah gambar partner; validasi klien sudah jalan di `ImageUpload`. */
  async function handleUploadImage(file: File): Promise<void> {
    if (partnerId === null) return;

    setImageBusy(true);
    try {
      const payload = await uploadPartnerImage(client, partnerId, file);
      await refreshPartner();
      setToast({
        title: "Gambar partner tersimpan",
        description: payload.message,
        tone: "success",
      });
    } catch (caught) {
      setToast({
        title: "Gagal mengunggah gambar",
        description: caught instanceof Error ? caught.message : "Permintaan unggah gagal.",
        tone: "error",
      });
    } finally {
      setImageBusy(false);
    }
  }

  /** K5.3 — hapus gambar partner (backend idempotent: selalu 200). */
  async function handleDeleteImage(): Promise<void> {
    if (partnerId === null) return;

    setImageBusy(true);
    try {
      const payload = await deletePartnerImage(client, partnerId);
      await refreshPartner();
      setToast({
        title: "Gambar partner dihapus",
        description: payload.message,
        tone: "success",
      });
    } catch (caught) {
      setToast({
        title: "Gagal menghapus gambar",
        description: caught instanceof Error ? caught.message : "Permintaan hapus gagal.",
        tone: "error",
      });
    } finally {
      setImageBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={partner === undefined ? "Detail Partner" : partner.name}
        subtitle="Master partner MES (read-only) — gunakan Edit untuk mengubah"
        breadcrumb={[
          { label: "Inventory", href: "/inventory/products" },
          { label: "Master Partner", href: "/master/partners" },
          { label: partner === undefined ? "Detail" : partner.code },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              icon={ArrowLeft}
              onClick={() => navigate("/master/partners")}
            >
              Kembali
            </Button>

            <Button
              icon={Pencil}
              disabled={partner === undefined}
              onClick={() =>
                navigate(`/master/partners/${String(partnerId)}/edit`)
              }
            >
              Edit
            </Button>

            {/* H2 — endpoint push manual belum ada; push otomatis lewat task Celery. */}
            <Tooltip content="Sync manual tersedia di H2 — push sekarang otomatis & asinkron">
              <Button
                variant="secondary"
                icon={RefreshCw}
                disabled
                aria-label="Sync ke Odoo (belum tersedia, H2)"
              >
                Sync ke Odoo
              </Button>
            </Tooltip>

            {/* K5.3 — kotak gambar kecil di pojok kanan atas header (unggah/hapus). */}
            {partner !== undefined ? (
              <ImageUpload
                currentUrl={partner.image_display_url}
                fallbackIcon={<Users className="h-6 w-6" aria-hidden="true" />}
                size="sm"
                uploading={imageBusy}
                onUpload={handleUploadImage}
                onDelete={handleDeleteImage}
                onError={(message) => {
                  setToast({ title: "Gambar ditolak", description: message, tone: "error" });
                }}
              />
            ) : null}
          </div>
        }
      />

      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat partner…
        </div>
      ) : null}

      {error !== null ? (
        <section className={cn(CARD, "flex flex-col gap-2")}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat partner (perlu login atau partner tidak ada).
          </p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void refetch();
            }}
          >
            Coba Lagi
          </Button>
        </section>
      ) : null}

      {partner !== undefined ? (
        <>
          <section className={cn(CARD, "flex flex-wrap items-center gap-3")}>
            <span className="font-mono text-sm font-semibold text-foreground">
              {displayOrDash(partner.code)}
            </span>
            {partnerRoleLabels(partner).map((label) => (
              <Badge key={label} tone="muted">
                {label}
              </Badge>
            ))}
            <Badge tone="muted">
              {partner.is_company ? "Perusahaan" : "Perorangan"}
            </Badge>
            <Badge tone={partner.active ? "blue" : "muted"}>
              {partner.active ? "Aktif" : "Nonaktif"}
            </Badge>
            <Badge tone={partner.odoo_id === null ? "coral" : "blue"}>
              {partner.odoo_id === null
                ? "Belum sync Odoo"
                : `Odoo #${String(partner.odoo_id)}`}
            </Badge>
            <Badge tone="muted">{ordersCountLabel(partner)}</Badge>
          </section>

          <section
            className={cn(
              CARD,
              "grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3",
            )}
          >
            {partnerDetailItems(partner).map((item) => (
              <div key={item.label} className="flex flex-col gap-1">
                <span className="text-xs font-medium text-muted-foreground">
                  {item.label}
                </span>
                <span
                  className={cn(
                    "text-sm text-foreground",
                    item.mono === true ? "font-mono" : undefined,
                  )}
                >
                  {item.value}
                </span>
              </div>
            ))}
          </section>

          <section className={cn(CARD, "flex flex-col gap-1")}>
            <span className="text-xs font-medium text-muted-foreground">
              Alamat
            </span>
            <span className="whitespace-pre-line text-sm text-foreground">
              {displayOrDash(partner.address)}
            </span>
          </section>
        </>
      ) : null}

      <FloatingAIAssistant context={aiContext} />

      <Toast
        open={toast !== null}
        onOpenChange={(open) => {
          if (!open) setToast(null);
        }}
        title={toast?.title ?? ""}
        description={toast?.description}
        tone={toast?.tone ?? "default"}
      />
    </div>
  );
}
