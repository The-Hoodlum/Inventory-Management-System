// AI assistant slide-over. A lightweight chat over the existing /assistant/ask engine
// (the model runs server-side through permission-gated tools — it never touches the DB
// from here). Conversation is kept in local state for the session.
import { useMutation } from "@tanstack/react-query";
import { Send, Sparkles, X } from "lucide-react";
import { useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import { assistantApi } from "@/lib/assistant";

interface Turn {
  role: "user" | "assistant";
  text: string;
}

const SUGGESTIONS = [
  "Show unpaid invoices",
  "Who owes us money?",
  "What is low on stock?",
];

export function AssistantPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const scroller = useRef<HTMLDivElement>(null);

  const ask = useMutation({
    mutationFn: (q: string) => assistantApi.ask(q),
    onSuccess: (res) => {
      setTurns((t) => [...t, { role: "assistant", text: res.answer }]);
      queueMicrotask(() => scroller.current?.scrollTo({ top: scroller.current.scrollHeight }));
    },
    onError: (e) =>
      setTurns((t) => [
        ...t,
        {
          role: "assistant",
          text:
            e instanceof ApiError && e.status === 403
              ? "The AI assistant isn’t enabled for your account."
              : "Sorry — I couldn’t answer that just now.",
        },
      ]),
  });

  const send = (q: string) => {
    const question = q.trim();
    if (!question || ask.isPending) return;
    setTurns((t) => [...t, { role: "user", text: question }]);
    setInput("");
    ask.mutate(question);
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[60]">
      <button aria-hidden className="absolute inset-0 bg-ink-950/40" onClick={onClose} />
      <aside className="absolute right-0 top-0 flex h-full w-full max-w-md flex-col border-l border-line bg-surface shadow-pop">
        <header className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-600 text-white">
              <Sparkles className="h-4 w-4" />
            </span>
            <span className="text-sm font-semibold text-content">AI Assistant</span>
          </div>
          <button onClick={onClose} className="rounded p-1 text-content-subtle hover:bg-canvas">
            <X className="h-4 w-4" />
          </button>
        </header>

        <div ref={scroller} className="flex-1 space-y-3 overflow-auto p-4">
          {turns.length === 0 && (
            <div className="text-sm text-muted">
              <p className="mb-3">Ask about your data — for example:</p>
              <div className="flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="rounded-full border border-line px-3 py-1.5 text-xs text-content-muted hover:bg-canvas"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {turns.map((t, i) => (
            <div key={i} className={t.role === "user" ? "flex justify-end" : "flex justify-start"}>
              <div
                className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm ${
                  t.role === "user"
                    ? "bg-brand-600 text-white"
                    : "border border-line bg-canvas text-content"
                }`}
              >
                {t.text}
              </div>
            </div>
          ))}
          {ask.isPending && <div className="text-xs text-content-subtle">Thinking…</div>}
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
          className="flex items-center gap-2 border-t border-line p-3"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask the assistant…"
            className="flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-content placeholder:text-content-subtle focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
          />
          <button
            type="submit"
            disabled={ask.isPending}
            className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
          >
            <Send className="h-4 w-4" />
          </button>
        </form>
      </aside>
    </div>
  );
}
