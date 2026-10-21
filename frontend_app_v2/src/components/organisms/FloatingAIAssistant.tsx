import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { MessageCircle, X } from "lucide-react";
import { Button } from "@/components/atoms/Button";
import { Input } from "@/components/atoms/Input";
import { ChatMessageList } from "@/components/molecules/ChatMessageList";
import { ChatWelcome } from "@/components/molecules/ChatWelcome";
import { useAIChat } from "@/hooks/useAIChat";
import { cn } from "@/lib/cn";
import {
  contextLabel,
  minimalContext,
  validateContextForSubmit,
} from "@/lib/ai-context";
import { CARD, PILL } from "@/lib/tokens";
import type { AIChatContext, AIChatUiMessage } from "@/types/ai-chat";

/**
 * FloatingAIAssistant — ikon mengambang + PANEL SAMPING (drawer), BUKAN redirect.
 *
 * Kontrak: docs/ai/CHAT-CONTRACT.md §7 (kanal FLOATING).
 * - Ikon: fixed kanan-bawah; klik membuka drawer dari kanan (`translate-x`).
 * - context = halaman aktif; `null` → konteks minimal (route saat ini).
 * - ESC menutup panel; Tutup menutup panel; keduanya TIDAK navigate.
 *
 * `initialOpen`/`initialMessages` disediakan untuk preview & test SSR (tanpa jsdom).
 */
export interface FloatingAIAssistantProps {
  context: AIChatContext | null;
  disabled?: boolean;
  initialOpen?: boolean;
  initialMessages?: AIChatUiMessage[];
}

export function FloatingAIAssistant({
  context,
  disabled = false,
  initialOpen = false,
  initialMessages = [],
}: FloatingAIAssistantProps) {
  const [open, setOpen] = useState(initialOpen);
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const chat = useAIChat({ initialMessages });

  const pathname =
    typeof window === "undefined" ? "/" : window.location.pathname;
  const effectiveContext = useMemo(
    () => context ?? minimalContext(pathname),
    [context, pathname],
  );

  useEffect(() => {
    if (!open) return;

    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape") setOpen(false);
    }

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (disabled) return null;

  async function submit(message: string): Promise<void> {
    try {
      await chat.sendMessage(message, effectiveContext, "FLOATING");
    } finally {
      inputRef.current?.focus();
      if (typeof window !== "undefined") {
        window.requestAnimationFrame(() => inputRef.current?.focus());
      }
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();

    const message = draft.trim();
    if (message.length === 0) return;

    const validation = validateContextForSubmit(effectiveContext);
    if (!validation.ok) {
      setNotice(
        `Konteks tidak valid: ${validation.reason ?? "periksa halaman aktif"}`,
      );
      return;
    }

    setNotice(null);
    setDraft("");
    void submit(message);
  }

  async function handleRetryWithoutContext(): Promise<void> {
    setNotice(null);
    await chat.retryWithoutContext(minimalContext(pathname));
  }

  return (
    <>
      <button
        type="button"
        aria-label="Buka Asisten AI"
        aria-expanded={open}
        aria-controls="floating-ai-panel"
        data-testid="floating-ai-icon"
        onClick={() => {
          setOpen(true);
        }}
        className={cn(
          PILL,
          "fixed bottom-6 right-6 z-40 h-10 w-10 xl:h-12 xl:w-12 bg-primary text-primary-foreground shadow-pill  cursor-pointer hover:scale-102",
          "origin-bottom",
          "animate-pulse",
          !open && "motion-safe:animate-bounce-squash",
        )}
      >
        <MessageCircle className="h-5 w-5" aria-hidden="true" />
      </button>

      {open ? (
        <>
          <button
            type="button"
            aria-label="Tutup panel Asisten AI"
            onClick={() => {
              setOpen(false);
            }}
            className="fixed inset-0 z-40 bg-foreground/20"
          />
          <aside
            id="floating-ai-panel"
            role="dialog"
            aria-label="Asisten AI"
            data-testid="floating-ai-panel"
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md translate-x-0 flex-col gap-3 border-l border-border/60 bg-background p-4 shadow-xl"
          >
            <header className="flex items-start justify-between gap-2">
              <div>
                <p className="text-sm font-semibold text-foreground">
                  Asisten AI
                </p>
                <p className="text-[11px] text-muted-foreground">
                  {contextLabel(effectiveContext)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setOpen(false);
                }}
                aria-label="Tutup"
                className={cn(PILL, "px-2 py-1 text-xs")}
              >
                <X className="mr-1 h-3 w-3" aria-hidden="true" />
                Tutup
              </button>
            </header>

            <div className={cn(CARD, "flex min-h-0 flex-1 flex-col p-3")}>
              {chat.messages.length === 0 ? <ChatWelcome /> : null}
              <ChatMessageList
                messages={chat.messages}
                loading={chat.loading}
              />
            </div>

            {notice === null ? null : (
              <p role="alert" className="text-xs font-medium text-danger">
                {notice}
              </p>
            )}

            {chat.error === "forbidden_context" ? (
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-warning/40 bg-warning/10 p-2">
                <p className="text-xs text-warning">
                  Konteks ini tidak boleh diakses.
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
                placeholder="Tanya tentang halaman ini..."
                autoComplete="off"
                maxLength={2000}
                disabled={chat.loading}
              />
              <Button
                type="submit"
                disabled={chat.loading || draft.trim().length === 0}
              >
                Kirim
              </Button>
            </form>
          </aside>
        </>
      ) : null}
    </>
  );
}
