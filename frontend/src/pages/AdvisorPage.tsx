import { useMutation, useQuery } from "@tanstack/react-query";
import { Send, Sparkles } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatCard, StatusBadge } from "@/components/ui";
import { advisorApi, type Finding } from "@/lib/advisor";
import { formatNumber } from "@/lib/format";

function sev(value: string): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function sevTone(v: number): { bar: string; pct: string } {
  if (v >= 0.7) return { bar: "bg-red-500", pct: "text-red-600" };
  if (v >= 0.4) return { bar: "bg-amber-500", pct: "text-amber-600" };
  return { bar: "bg-brand-500", pct: "text-slate-500" };
}

function FindingRow({ f }: { f: Finding }) {
  const s = sev(f.severity);
  const tone = sevTone(s);
  return (
    <div className="px-5 py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <StatusBadge status={f.category} />
          <span className="text-sm font-semibold text-slate-900">{f.title}</span>
        </div>
        <div className="flex w-28 shrink-0 items-center gap-2">
          <div className="h-1.5 flex-1 rounded-full bg-slate-100">
            <div className={`h-1.5 rounded-full ${tone.bar}`} style={{ width: `${Math.min(100, s * 100)}%` }} />
          </div>
          <span className={`tabular text-xs ${tone.pct}`}>{Math.round(s * 100)}%</span>
        </div>
      </div>
      <p className="mt-1.5 text-sm text-slate-600">{f.detail}</p>
      {f.recommended_action && (
        <p className="mt-1.5 flex gap-1.5 text-sm text-slate-700">
          <span className="mt-0.5 text-brand-500">→</span>
          {f.recommended_action}
        </p>
      )}
    </div>
  );
}

export default function AdvisorPage() {
  const [question, setQuestion] = useState("");
  const briefing = useQuery({
    queryKey: ["advisor", "briefing"],
    queryFn: () => advisorApi.briefing(),
  });

  const ask = useMutation({
    mutationFn: (q: string) => advisorApi.ask(q),
  });

  const d = briefing.data;
  const m = d?.metrics ?? {};

  return (
    <div>
      <PageHeader
        title="AI Supply Chain Analyst"
        description="An explainable briefing grounded in your live reorder, intelligence, supplier, forecast, and container data."
      />

      {briefing.isLoading ? (
        <Spinner label="Assembling briefing…" />
      ) : briefing.isError ? (
        <Card className="p-8 text-center text-sm text-red-600">
          {(briefing.error as Error).message}
        </Card>
      ) : !d ? (
        <Card className="p-8 text-center text-sm text-slate-500">No briefing available.</Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard label="Findings" value={formatNumber(m.findings_total ?? d.findings.length)} hint="Surfaced this run" />
            <StatCard label="Pending Reorders" value={formatNumber(m.reorder_pending ?? 0)}
              tone={(m.reorder_expedite ?? 0) > 0 ? "warning" : "default"}
              hint={`${m.reorder_expedite ?? 0} expedite`} />
            <StatCard label="Active Signals" value={formatNumber(m.active_signals ?? 0)} />
            <StatCard label="Supplier Scorecards" value={formatNumber(m.supplier_scores ?? 0)} />
          </div>

          <p className="mt-4 text-sm text-slate-600">{d.summary}</p>

          {/* Ask box */}
          <Card className="mt-6 p-5">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Sparkles className="h-4 w-4 text-brand-500" /> Ask the analyst
            </h2>
            <div className="mt-3 flex gap-2">
              <input
                className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
                placeholder="e.g. Which suppliers are risky? What should I order this week?"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && question.trim()) ask.mutate(question.trim());
                }}
              />
              <Button onClick={() => ask.mutate(question.trim())} disabled={ask.isPending || !question.trim()}>
                <Send className="h-4 w-4" /> {ask.isPending ? "Asking…" : "Ask"}
              </Button>
            </div>
            {!d.llm_enabled && (
              <p className="mt-2 text-xs text-slate-400">
                LLM narration is off — answers return the most relevant deterministic findings. Set an
                Anthropic API key to enable natural-language answers.
              </p>
            )}
            {ask.isError && (
              <p className="mt-3 text-sm text-red-600">{(ask.error as Error).message}</p>
            )}
            {ask.data && (
              <div className="mt-4 border-t border-slate-100 pt-4">
                {ask.data.answer && (
                  <p className="mb-3 whitespace-pre-wrap text-sm text-slate-800">{ask.data.answer}</p>
                )}
                {ask.data.relevant_findings.length === 0 ? (
                  <p className="text-sm text-slate-400">No findings match that question.</p>
                ) : (
                  <div className="divide-y divide-slate-100 rounded-lg border border-slate-100">
                    {ask.data.relevant_findings.map((f, i) => (
                      <FindingRow key={i} f={f} />
                    ))}
                  </div>
                )}
              </div>
            )}
          </Card>

          {/* LLM narrative (only when configured) */}
          {d.narrative && (
            <Card className="mt-6 p-5">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                <Sparkles className="h-4 w-4 text-brand-500" /> Analyst narrative
              </h2>
              <p className="mt-3 whitespace-pre-wrap text-sm text-slate-800">{d.narrative}</p>
            </Card>
          )}

          {/* Findings */}
          <Card className="mt-6 overflow-hidden">
            <div className="border-b border-slate-200 px-5 py-3 text-sm font-semibold text-slate-900">
              Findings — what to act on
            </div>
            {d.findings.length === 0 ? (
              <div className="p-8 text-center text-sm text-slate-400">
                Nothing actionable right now — no pending reorders, signals, or risks.
              </div>
            ) : (
              <div className="divide-y divide-slate-100">
                {d.findings.map((f, i) => (
                  <FindingRow key={i} f={f} />
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
