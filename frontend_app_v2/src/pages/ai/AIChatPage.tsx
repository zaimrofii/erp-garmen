import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { Toast, type ToastTone } from "@/components/atoms/Toast";
import { AIChatBox, type ChatMessage } from "@/components/molecules/AIChatBox";
// import { PageHeader } from "@/components/molecules/PageHeader";
import { decideApproval, fetchAllApprovals } from "@/api/hitl";
import { createAiChatClient, STUB_PREFIX } from "@/integrations/ai-chat";
import { useFeedback } from "@/app/app-runtime";
import { useApiClient } from "@/hooks/useApiClient";
import { cn } from "@/lib/cn";
import { CARD } from "@/lib/tokens";
import { generateUUID } from "@/lib/uuid";
import type { HitlApproval, HitlDecision } from "@/types/settings";

/**
 * AIChatPage - route `/ai/chat` (admin & owner - lihat ROLE_APPS: supervisor TIDAK punya 'ai').
 *
 * Dua sumber pesan digabung jadi satu transkrip:
 *  1. **Pengajuan agen dari adapter HITL** (`fetchAllApprovals`, REAL sejak F5.4.CLOSE —
 *     `GET /ai/hitl/queue/` untuk 4 state digabung) - dirender sebagai pesan assistant
 *     ber-kartu HITL. Keputusan APPROVE/REJECT memanggil `decideApproval()` →
 *     `POST /ai/hitl/<id>/approve|reject/` (reject memakai catatan default karena kartu
 *     chat belum punya input catatan), lalu query di-invalidate sehingga status yang
 *     tampil berasal dari server.
 *  2. **Percakapan sesi ini** (`createAiChatClient().send`) - endpoint `/ai/chat` masih stub
 *     `{ ok:false, reason:'not_implemented' }`; integration SUDAH mengubahnya jadi teks
 *     `[STUB] …`, dan halaman mendeteksi awalan itu (`STUB_PREFIX`) untuk menampilkan pesan
 *     ramah + satu usulan aksi simulasi supaya alur HITL tetap bisa didemokan.
 *
 * Catatan: ulasan HITL simulasi disimpan di message itu sendiri (state lokal) - sesuai
 * aturan "HITL pakai local state" karena belum ada backend approval untuk usulan AI.
 */

const HITL_QUERY_KEY = ["hitl-approvals"];

/** Awalan id pesan yang berasal dari adapter HITL (mis. `hitl-2`). */
const HITL_MESSAGE_PREFIX = "hitl-";

/** Awalan id pesan usulan simulasi dari percakapan (mis. `ai-<uuid>`). */
const SIMULATED_MESSAGE_PREFIX = "ai-";

const AI_UNAVAILABLE_MESSAGE =
  "Maaf, asisten AI belum tersedia (backend masih stub). Sementara itu, berikut satu usulan aksi sebagai contoh alur persetujuan.";

const SIMULATED_PROPOSAL =
  "Pindahkan 5 bundle dari Sablon ke Sablon-02 untuk membuka antrean brand.";

interface ToastState {
  title: string;
  description: string;
  tone: ToastTone;
}

const EMPTY_APPROVALS: HitlApproval[] = [];

export function AIChatPage() {
  const apiClient = useApiClient();
  const queryClient = useQueryClient();
  const feedback = useFeedback();

  const [sessionMessages, setSessionMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const aiClient = useMemo(() => createAiChatClient(apiClient), [apiClient]);

  const approvals = useQuery({
    queryKey: HITL_QUERY_KEY,
    queryFn: () => fetchAllApprovals(apiClient),
    staleTime: 15_000,
  });

  const approvalRows = approvals.data ?? EMPTY_APPROVALS;

  /** Pengajuan agen dari adapter -> pesan assistant ber-kartu HITL. */
  const seededMessages: ChatMessage[] = useMemo(
    () =>
      approvalRows.map((approval) => {
        const message: ChatMessage = {
          id: `${HITL_MESSAGE_PREFIX}${approval.id}`,
          role: "assistant",
          content: `Pengajuan agen: ${approval.action} pada ${approval.resource} ${approval.resource_id}.`,
          hitl: {
            id: `${HITL_MESSAGE_PREFIX}${approval.id}`,
            proposal: approval.reason,
            status: approval.status,
          },
        };

        return message;
      }),
    [approvalRows],
  );

  const messages: ChatMessage[] = useMemo(
    () => [...seededMessages, ...sessionMessages],
    [seededMessages, sessionMessages],
  );

  const decide = useMutation({
    mutationFn: (input: { id: number; decision: HitlDecision }) =>
      decideApproval(apiClient, input.id, input.decision),
    onSuccess: (approval) => {
      const approved = approval.status === "approved";

      feedback.trigger(approved ? "success" : "error");
      setToast({
        title: approved ? "Pengajuan disetujui" : "Pengajuan ditolak",
        description: `${approval.action} - ${approval.resource_id}`,
        tone: approved ? "success" : "default",
      });
      void queryClient.invalidateQueries({ queryKey: HITL_QUERY_KEY });
    },
    onError: () => {
      feedback.trigger("error");
      setToast({
        title: "Gagal memproses keputusan",
        description: "Pengajuan tidak ditemukan atau ditolak server.",
        tone: "error",
      });
    },
  });

  async function handleSend(text: string): Promise<void> {
    const question: ChatMessage = {
      id: generateUUID(),
      role: "user",
      content: text,
    };

    setSessionMessages((previous) => [...previous, question]);
    setLoading(true);

    try {
      const reply = await aiClient.send(text);
      const isStub = reply.content.startsWith(STUB_PREFIX);
      const answer: ChatMessage = {
        id: reply.id,
        role: "assistant",
        content: isStub ? AI_UNAVAILABLE_MESSAGE : reply.content,
      };

      if (isStub) {
        answer.hitl = {
          id: `${SIMULATED_MESSAGE_PREFIX}${reply.id}`,
          proposal: SIMULATED_PROPOSAL,
          status: "pending",
        };
      }

      setSessionMessages((previous) => [...previous, answer]);
      feedback.trigger(isStub ? "warning" : "success");

      if (isStub) {
        setToast({
          title: "AI belum tersedia",
          description:
            "Backend /ai/chat masih stub. Usulan aksi simulasi ditampilkan.",
          tone: "default",
        });
      }
    } finally {
      setLoading(false);
    }
  }

  function handleHitlDecision(
    id: string,
    decision: "approved" | "rejected",
  ): void {
    if (id.startsWith(HITL_MESSAGE_PREFIX)) {
      const numericId = Number(id.slice(HITL_MESSAGE_PREFIX.length));

      if (!Number.isFinite(numericId)) {
        feedback.trigger("error");
        setToast({
          title: "Pengajuan tidak dikenal",
          description: `ID "${id}" tidak bisa dibaca.`,
          tone: "error",
        });
        return;
      }

      decide.mutate({
        id: numericId,
        decision: decision === "approved" ? "approve" : "reject",
      });
      return;
    }

    // Usulan simulasi (sesi ini) -> status di message, sesuai aturan local state.
    setSessionMessages((previous) =>
      previous.map((message) => {
        const hitl = message.hitl;
        if (hitl === undefined || hitl.id !== id) return message;

        return {
          ...message,
          hitl: { id: hitl.id, proposal: hitl.proposal, status: decision },
        };
      }),
    );

    feedback.trigger(decision === "approved" ? "success" : "error");
    setToast({
      title: decision === "approved" ? "Usulan disetujui" : "Usulan ditolak",
      description:
        "Keputusan simulasi (belum ada endpoint approval untuk usulan AI).",
      tone: decision === "approved" ? "success" : "default",
    });
  }

  return (
    <div className="flex min-h-full flex-col gap-4 p-4 lg:p-6">
      {/* <PageHeader
        title="AI Assistant"
        subtitle="Tanya jawab tentang produksi - approval HITL untuk usulan aksi"
        breadcrumb={[{ label: "AI Assistant" }]}
      /> */}
      <h1 className="text-sm xl:text-base">
        Tanya jawab tentang produksi - Persetujuan usulan aksi
      </h1>

      {approvals.error === null ? null : (
        <div
          className={cn(
            CARD,
            "flex flex-wrap items-center justify-between gap-2 py-3 ",
          )}
        >
          <p role="alert" className="text-xs font-medium text-accent-coral">
            Gagal memuat pengajuan agen. Percakapan tetap bisa dipakai.
          </p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void approvals.refetch();
            }}
          >
            Coba Lagi
          </Button>
        </div>
      )}

      <main className="flex min-h-[60vh] flex-1 flex-col overflow-hidden">
        <div
          className={cn(
            CARD,
            "flex min-h-0 flex-1 flex-col items-center  overflow-hidden p-0",
          )}
        >
          <AIChatBox
            className="p-6"
            messages={messages}
            loading={loading}
            onSend={handleSend}
            onHitlDecision={handleHitlDecision}
          />
        </div>
      </main>

      {approvals.isLoading ? (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Spinner size="sm" />
          Memuat pengajuan agen...
        </p>
      ) : null}

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
