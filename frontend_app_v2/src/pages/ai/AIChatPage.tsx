import { useMemo, useRef, useState, useEffect, type FormEvent } from "react";
import { useLocation } from "react-router-dom";
import { Button } from "@/components/atoms/Button";
import { Input } from "@/components/atoms/Input";
import { ChatMessageList } from "@/components/molecules/ChatMessageList";
import { ChatWelcome } from "@/components/molecules/ChatWelcome";
import { useAIChat } from "@/hooks/useAIChat";
import { cn } from "@/lib/cn";
import { minimalContext, validateContextForSubmit } from "@/lib/ai-context";
import { CARD } from "@/lib/tokens";
import type { AIChatUiMessage } from "@/types/ai-chat";

/**
 * AIChatPage — route `/ai/chat` (channel DESKTOP).
 *
 * Kontrak: docs/ai/CHAT-CONTRACT.md §2–§3, §7.
 * - Konteks halaman `/ai/chat` = minimal (bukan resource) → `page_type:null`.
 * - Riwayat percakapan dikirim maks 10 item (state lokal via `useAIChat`).
 * - Pre-validasi konteks (§5) dilakukan sebelum request; `forbidden_context`
 *   menampilkan fallback "Kirim tanpa konteks".
 */
export function AIChatPage({
  initialMessages = [],
}: {
  initialMessages?: AIChatUiMessage[];
} = {}) {
  const location = useLocation();
  const chat = useAIChat({ initialMessages });
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const context = useMemo(() => minimalContext("/ai/chat"), []);

  // 🔽 Auto-scroll ke bawah setiap messages / loading berubah
  useEffect(() => {
    const el = scrollRef.current;
    if (el === null) return;
    el.scrollTop = el.scrollHeight;
  }, [chat.messages, chat.loading]);

  // 🔽 Auto-focus setelah loading selesai (input tidak disabled, jadi aman)
  useEffect(() => {
    if (chat.loading) return;
    inputRef.current?.focus();
  }, [chat.loading]);

  async function submit(message: string): Promise<void> {
    const validation = validateContextForSubmit(context);
    if (!validation.ok) {
      setNotice(
        `Konteks tidak valid: ${validation.reason ?? "periksa halaman aktif"}`,
      );
      return;
    }

    setNotice(null);
    await chat.sendMessage(message, context, "DESKTOP");
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();

    const message = draft.trim();
    if (message.length === 0) return;

    setDraft("");
    void submit(message);
  }

  async function handleRetryWithoutContext(): Promise<void> {
    setNotice(null);
    await chat.retryWithoutContext(minimalContext(location.pathname));
  }

  return (
    <div className="flex min-h-full flex-col gap-4 p-4 lg:p-6">
      {/* <header>
        <h1 className="text-sm xl:text-base">Asisten AI</h1>
        <p className="mt-1 text-xs text-muted-foreground">
          Tanya jawab tentang produksi. AI hanya membaca data — aksi yang
          mengubah data selalu lewat persetujuan.
        </p>
      </header> */}

      <main className="flex min-h-[60vh] flex-1 flex-col overflow-hidden">
        <div
          ref={scrollRef}
          className={cn(
            CARD,
            "flex min-h-0 flex-1 flex-col gap-3 p-4 px-[5vw] md:px-[10vw] lg:px-[15vw] xl:px-[18vw] 2xl:px-[20vw] max-h-[85vh] overflow-y-auto",
          )}
        >
          {chat.messages.length === 0 ? <ChatWelcome /> : null}
          <ChatMessageList messages={chat.messages} loading={chat.loading} />

          {notice === null ? null : (
            <p role="alert" className="text-xs font-medium text-danger">
              {notice}
            </p>
          )}

          {chat.error === "forbidden_context" ? (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-warning/40 bg-warning/10 p-2">
              <p className="text-xs text-warning">
                Anda tidak berhak melihat data konteks ini.
              </p>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                onClick={() => {
                  void handleRetryWithoutContext();
                }}
              >
                Kirim tanpa konteks
              </Button>
            </div>
          ) : null}

          <form onSubmit={handleSubmit} className="flex items-end gap-2">
            <Input
              ref={inputRef}
              label="Pesan"
              value={draft}
              onChange={(event) => {
                setDraft(event.target.value);
              }}
              placeholder="Tanya tentang produksi..."
              autoComplete="off"
              maxLength={2000}
              // ✅ TIDAK ADA disabled — fokus tidak pernah hilang.
              //    Tombol Kirim di bawah yang mencegah kirim ganda.
            />
            <Button
              type="submit"
              disabled={chat.loading || draft.trim().length === 0}
            >
              Kirim
            </Button>
          </form>

          <p className="text-[11px] text-muted-foreground">
            Kanal DESKTOP · riwayat maks 10 pesan · jawaban deterministik tanpa
            LLM (RULE_HIT) memakai 0 token.
          </p>
        </div>
      </main>
    </div>
  );
}
