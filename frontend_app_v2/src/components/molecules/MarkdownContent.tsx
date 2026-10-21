import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/cn";

interface MarkdownContentProps {
  content: string;
  className?: string;
}

/**
 * MarkdownContent — render jawaban assistant (GFM) dengan HTML mentah tetap
 * tidak diaktifkan. Heading dibatasi h4–h6 agar tidak mendominasi bubble chat.
 */
export function MarkdownContent({ content, className }: MarkdownContentProps) {
  if (!content) return null;

  return (
    <div className={cn("prose-chat", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h4 className="font-semibold text-base mt-2 mb-1">{children}</h4>
          ),
          h2: ({ children }) => (
            <h5 className="font-semibold text-sm mt-2 mb-1">{children}</h5>
          ),
          h3: ({ children }) => (
            <h6 className="font-semibold text-sm mt-1 mb-1">{children}</h6>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline"
            >
              {children}
            </a>
          ),
          code: ({ children, className: cls }) => {
            const inline = !cls?.includes("language-");
            return inline ? (
              <code className="bg-muted px-1 py-0.5 rounded text-xs">
                {children}
              </code>
            ) : (
              <code className="text-xs">{children}</code>
            );
          },
          pre: ({ children }) => (
            <pre className="bg-muted p-2 rounded text-xs overflow-x-auto my-2">
              {children}
            </pre>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto my-2">
              <table className="min-w-full text-xs border-collapse border border-border">
                {children}
              </table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-border px-2 py-1 bg-muted text-left">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-border px-2 py-1">{children}</td>
          ),
          ul: ({ children }) => (
            <ul className="list-disc list-inside my-1 space-y-0.5">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal list-inside my-1 space-y-0.5">
              {children}
            </ol>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
