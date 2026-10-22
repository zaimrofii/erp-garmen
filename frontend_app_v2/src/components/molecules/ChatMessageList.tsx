import { useEffect, useRef } from "react";
import { Spinner } from "@/components/atoms/Spinner";
import { cn } from "@/lib/cn";
import { confidenceClass } from "@/lib/ai-chat-display";
import { BADGE, PILL } from "@/lib/tokens";
import type { AIChatResponse, AIChatUiMessage } from "@/types/ai-chat";
import { AIChart } from "./AIChart";
import { MarkdownContent } from "./MarkdownContent";

/**
 * ChatMessageList — daftar bubble percakapan AI (Sprint E.2/E.3).
 *
 * Metadata response §3 ditampilkan ringkas: tool_calls (collapsible), confidence,
 * HITL banner, decision gate, token, dan badge cache. Dipakai bersama oleh
 * `/ai/chat` (DESKTOP) dan panel floating (FLOATING).
 */

interface ChatMessageListProps {
  messages: AIChatUiMessage[];
  loading?: boolean;
  className?: string;
}

function ConfidenceBadge({ score }: { score: number | null }) {
  if (score === null) return null;

  return (
    <span
      data-testid="ai-confidence"
      className={cn(BADGE, "bg-muted/60", confidenceClass(score))}
    >
      confidence {score.toFixed(2)}
    </span>
  );
}

function ResponseMeta({ response }: { response: AIChatResponse }) {
  const totalTokens = response.tokens.prompt + response.tokens.completion;

  return (
    <div className="mt-2 flex flex-col gap-2">
      {response.hitl_required ? (
        <div
          role="status"
          className="rounded-lg border border-warning/40 bg-warning/10 p-2 text-xs text-warning"
        >
          Perlu persetujuan
          {response.hitl_request_id === null
            ? ""
            : ` (pengajuan #${response.hitl_request_id})`}
        </div>
      ) : null}

      {response.tool_calls.length > 0 ? (
        <details className="rounded-lg border border-border/60 bg-muted/30 p-2">
          <summary className="cursor-pointer text-xs font-medium text-foreground">
            Tool dipanggil ({response.tool_calls.length})
          </summary>
          <ul className="mt-2 flex flex-col gap-1">
            {response.tool_calls.map((call, index) => (
              <li
                key={`${call.tool}-${String(index)}`}
                className="text-xs text-muted-foreground"
              >
                <span className="font-semibold text-foreground">
                  {call.tool}
                </span>
                {call.output_summary.length > 0
                  ? ` — ${call.output_summary}`
                  : ""}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <span className={cn(BADGE, "bg-muted/60 text-muted-foreground")}>
          {response.decision_gate_result}
        </span>
        <ConfidenceBadge score={response.confidence_score} />
        {response.cache_hit ? (
          <span className={cn(BADGE, "bg-info/10 text-info")}>dari cache</span>
        ) : null}
        <span className="text-[11px] text-muted-foreground">
          {totalTokens} tokens
        </span>
      </div>
    </div>
  );
}

export function ChatMessageList({
  messages,
  loading = false,
  className,
}: ChatMessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  return (
    <ol
      aria-live="polite"
      className={cn(
        "flex flex-1 flex-col gap-3 overflow-y-auto scrollbar-hide min-h-0 p-1",
        className,
      )}
    >
      {messages.map((message) => {
        const isUser = message.role === "user";

        return (
          <li
            key={message.id}
            data-testid={`ai-message-${message.role}`}
            className={cn("max-w-[85%]", isUser ? "ml-auto" : "mr-auto")}
          >
            <div
              className={cn(
                "px-4 py-2 text-sm",
                isUser
                  ? "whitespace-pre-wrap rounded-xl bg-primary text-primary-foreground"
                  : "rounded-xl border border-border/60 bg-card text-foreground",
              )}
            >
              {isUser ? (
                message.content
              ) : (
                <>
                  <MarkdownContent content={message.content} />
                  {message.response?.chart_data ? (
                    <AIChart
                      type={message.response.chart_data.type}
                      data={message.response.chart_data.data}
                      title={message.response.chart_data.title}
                      unit={message.response.chart_data.unit}
                    />
                  ) : null}
                </>
              )}
            </div>
            {message.response === undefined ? null : (
              <ResponseMeta response={message.response} />
            )}
          </li>
        );
      })}

      {loading ? (
        <li className="mr-auto flex items-center gap-2 text-xs text-muted-foreground">
          <Spinner size="sm" />
          sedang analisa data & menyusun jawaban...
        </li>
      ) : null}

      <div ref={bottomRef} data-testid="chat-bottom-sentinel" />
    </ol>
  );
}

/** Indikator kecil untuk panel (dipakai header). */
export function ChatCloseButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(PILL, "px-2 py-1 text-xs")}
    >
      Tutup
    </button>
  );
}
