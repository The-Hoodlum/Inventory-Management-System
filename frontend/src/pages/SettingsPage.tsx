import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { FEATURE_LABELS, tenantApi, type TenantSettings } from "@/lib/tenantSettings";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 disabled:bg-slate-50 disabled:text-slate-500";

type Form = TenantSettings;

export default function SettingsPage() {
  const { hasPermission } = useAuth();
  const canManage = hasPermission("settings.manage");
  const qc = useQueryClient();
  const [form, setForm] = useState<Form | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const { data, isLoading } = useQuery({ queryKey: ["tenant", "settings"], queryFn: tenantApi.get });
  useEffect(() => {
    if (data) setForm(data);
  }, [data]);

  const save = useMutation({
    mutationFn: (f: Form) =>
      tenantApi.update({
        company_name: f.company_name,
        brand_name: f.brand_name,
        industry: f.industry,
        default_currency: f.default_currency,
        fx_rate: f.fx_rate,
        vat_rate: f.vat_rate,
        country: f.country,
        timezone: f.timezone,
        logo_url: f.logo_url,
        assistant_name: f.assistant_name,
        assistant_prompt: f.assistant_prompt,
        branding_colors: f.branding_colors,
        feature_flags: f.feature_flags,
      }),
    onSuccess: (updated) => {
      qc.setQueryData(["tenant", "settings"], updated);
      setMsg({ kind: "ok", text: "Settings saved." });
    },
    onError: (e) =>
      setMsg({ kind: "err", text: e instanceof ApiError ? e.message : "Could not save settings." }),
  });

  if (isLoading || !form) {
    return (
      <div>
        <PageHeader title="Settings" description="Your company profile and modules." />
        <div className="flex h-48 items-center justify-center"><Spinner label="Loading settings…" /></div>
      </div>
    );
  }

  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => (f ? { ...f, [key]: value } : f));
  const color = (k: string) => form.branding_colors?.[k] ?? "#0aa06e";

  return (
    <div className="max-w-3xl">
      <PageHeader
        title="Settings"
        description="Company identity, branding, and the modules enabled for your business."
        actions={
          canManage ? (
            <Button disabled={save.isPending} onClick={() => { setMsg(null); save.mutate(form); }}>
              {save.isPending ? "Saving…" : "Save changes"}
            </Button>
          ) : undefined
        }
      />

      {msg && (
        <div
          className={`mb-4 rounded-lg px-3 py-2 text-sm ${
            msg.kind === "ok" ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"
          }`}
        >
          {msg.text}
        </div>
      )}

      <Card className="mb-5 p-5">
        <h3 className="mb-3 text-sm font-semibold text-slate-800">General</h3>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Company name">
            <input className={`${INPUT} w-full`} disabled={!canManage} value={form.company_name}
              onChange={(e) => set("company_name", e.target.value)} />
          </Field>
          <Field label="Brand name">
            <input className={`${INPUT} w-full`} disabled={!canManage} value={form.brand_name ?? ""}
              onChange={(e) => set("brand_name", e.target.value)} />
          </Field>
          <Field label="Industry">
            <input className={`${INPUT} w-full`} disabled={!canManage} value={form.industry ?? ""}
              placeholder="e.g. Motorcycles, Food, Hardware, Pharmacy"
              onChange={(e) => set("industry", e.target.value)} />
          </Field>
          <Field label="Base currency">
            <input className={`${INPUT} w-full uppercase`} disabled={!canManage} maxLength={3}
              value={form.default_currency} onChange={(e) => set("default_currency", e.target.value.toUpperCase())} />
          </Field>
          <Field label="Exchange rate (USD → billing currency)">
            <input className={`${INPUT} w-full`} type="number" min="0" step="0.000001" disabled={!canManage}
              value={form.fx_rate} onChange={(e) => set("fx_rate", e.target.value)} />
            <span className="mt-1 block text-xs text-slate-400">
              Current rate. Applied to new sales documents when issued; existing documents keep their frozen rate.
            </span>
          </Field>
          <Field label="VAT rate (%)">
            <input className={`${INPUT} w-full`} type="number" min="0" max="100" step="0.01" disabled={!canManage}
              value={form.vat_rate ? String(Number(form.vat_rate) * 100) : "0"}
              onChange={(e) => set("vat_rate", String((Number(e.target.value) || 0) / 100))} />
            <span className="mt-1 block text-xs text-slate-400">
              Parts add VAT on top of the net price; motorcycle prices are VAT-inclusive. Applied to new documents; existing keep their frozen rate.
            </span>
          </Field>
          <Field label="Country">
            <input className={`${INPUT} w-full`} disabled={!canManage} value={form.country ?? ""}
              onChange={(e) => set("country", e.target.value)} />
          </Field>
          <Field label="Timezone">
            <input className={`${INPUT} w-full`} disabled={!canManage} value={form.timezone}
              placeholder="e.g. Africa/Lusaka" onChange={(e) => set("timezone", e.target.value)} />
          </Field>
          <Field label="Logo URL">
            <input className={`${INPUT} w-full`} disabled={!canManage} value={form.logo_url ?? ""}
              onChange={(e) => set("logo_url", e.target.value)} />
          </Field>
          <Field label="Assistant name">
            <input className={`${INPUT} w-full`} disabled={!canManage} value={form.assistant_name ?? ""}
              placeholder="e.g. Acme Assistant" onChange={(e) => set("assistant_name", e.target.value)} />
          </Field>
        </div>
      </Card>

      <Card className="mb-5 p-5">
        <h3 className="mb-3 text-sm font-semibold text-slate-800">Branding colors</h3>
        <div className="flex gap-6">
          {(["primary", "secondary"] as const).map((k) => (
            <Field key={k} label={k[0].toUpperCase() + k.slice(1)}>
              <div className="flex items-center gap-2">
                <input type="color" disabled={!canManage} value={color(k)}
                  onChange={(e) => set("branding_colors", { ...form.branding_colors, [k]: e.target.value })}
                  className="h-8 w-12 rounded border border-slate-300" />
                <span className="font-mono text-xs text-slate-500">{color(k)}</span>
              </div>
            </Field>
          ))}
        </div>
      </Card>

      <Card className="p-5">
        <h3 className="mb-1 text-sm font-semibold text-slate-800">Modules</h3>
        <p className="mb-3 text-xs text-slate-400">Turn platform modules on or off for your business.</p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {FEATURE_LABELS.map((f) => (
            <label key={f.key} className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm">
              <input type="checkbox" disabled={!canManage} checked={!!form.feature_flags[f.key]}
                onChange={(e) => set("feature_flags", { ...form.feature_flags, [f.key]: e.target.checked })} />
              <span className="text-slate-700">{f.label}</span>
            </label>
          ))}
        </div>
      </Card>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      {children}
    </label>
  );
}
