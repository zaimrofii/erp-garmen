import { useState, useEffect, useRef, type FormEvent } from "react";
import { Send } from "lucide-react";
import { Button } from "@/components/atoms/Button";
import { Input } from "@/components/atoms/Input";
import { Spinner } from "@/components/atoms/Spinner";
import { cn } from "@/lib/cn";
import { CARD, PILL } from "@/lib/tokens";

/**
 * AIChatBox - percakapan AI + kartu persetujuan HITL.
 *
 * `onSend` asinkron (halaman yang memanggil endpoint `/ai/chat`), sedangkan keputusan
 * HITL diteruskan ke `onHitlDecision` supaya halaman bisa memanggil endpoint approval.
 * Selama `status === 'pending'`, tombol APPROVE/REJECT tampil; setelah diputuskan,
 * kartunya berubah jadi label status.
 */

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  hitl?: {
    id: string;
    proposal: string;
    status: "pending" | "approved" | "rejected" | "expired";
  };
}

const HITL_STATUS_LABEL: Record<
  "pending" | "approved" | "rejected" | "expired",
  string
> = {
  pending: "Menunggu keputusan",
  approved: "Disetujui",
  rejected: "Ditolak",
  expired: "Kedaluwarsa",
};

interface AIChatBoxProps {
  onSend: (message: string) => Promise<void>;
  messages: ChatMessage[];
  loading?: boolean;
  onHitlDecision?: (id: string, decision: "approved" | "rejected") => void;
  className?: string;
}

export function AIChatBox({
  onSend,
  messages,
  loading = false,
  onHitlDecision,
  className,
}: AIChatBoxProps) {
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLLIElement>(null);

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();

    const message = draft.trim();
    if (message.length === 0) return;

    setDraft("");
    void onSend(message);
  }
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, loading]);

  return (
    <section
      className={cn(
        "flex min-h-0 flex-1 flex-col gap-4 max-h-[80vh] xl:max-h-[85vh]",
        className,
      )}
    >
      <ol className="flex flex-1 flex-col gap-3 overflow-y-auto scrollbar-hide min-h-0 pb-2 xl:w-220">
        {messages.map((message) => {
          const isUser = message.role === "user";
          // Disimpan ke const: narrowing `hitl !== undefined` tidak bertahan di dalam
          // closure kalau yang di-narrow adalah properti objek (`message.hitl`).
          const hitl = message.hitl;

          return (
            <li
              key={message.id}
              className={cn("max-w-[80%]", isUser ? "ml-auto" : "mr-auto")}
            >
              <div
                className={cn(
                  "px-4 py-2 text-sm",
                  isUser
                    ? "rounded-xl bg-primary text-primary-foreground"
                    : "rounded-xl border border-border/60 bg-card text-foreground",
                )}
              >
                {message.content}
              </div>

              {hitl !== undefined ? (
                <div className="mt-2 rounded-lg border border-accent-blue/30 bg-accent-blue/5 p-3">
                  <p className="text-xs font-semibold text-accent-blue">
                    AI mengusulkan
                  </p>
                  <p className="mt-1 text-sm text-foreground">
                    {hitl.proposal}
                  </p>

                  {hitl.status === "pending" ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => onHitlDecision?.(hitl.id, "approved")}
                        className={cn(
                          PILL,
                          "px-3 py-1.5 text-xs font-semibold text-primary-foreground",
                          "bg-accent-blue hover:opacity-90",
                        )}
                      >
                        APPROVE
                      </button>
                      <button
                        type="button"
                        onClick={() => onHitlDecision?.(hitl.id, "rejected")}
                        className={cn(
                          PILL,
                          "border border-accent-coral/40 bg-card px-3 py-1.5 text-xs font-semibold",
                          "text-accent-coral hover:bg-accent-coral/10",
                        )}
                      >
                        REJECT
                      </button>
                    </div>
                  ) : (
                    <p className="mt-2 text-xs font-medium text-muted-foreground">
                      {HITL_STATUS_LABEL[hitl.status]}
                    </p>
                  )}
                </div>
              ) : null}
            </li>
          );
        })}

        <li ref={bottomRef} aria-hidden="true" />
      </ol>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" />
          AI sedang menyusun jawaban...
        </div>
      ) : null}

      <form
        onSubmit={handleSubmit}
        className={cn(CARD, "flex items-center gap-2 p-3 shrink-0")}
      >
        <Input
          value={draft}
          placeholder="Tanya kondisi lantai produksi..."
          onChange={(event) => setDraft(event.target.value)}
        />
        <Button
          type="submit"
          icon={Send}
          aria-label="Kirim pesan"
          loading={loading}
          className="shrink-0 self-end"
        />
      </form>
    </section>
  );
}
