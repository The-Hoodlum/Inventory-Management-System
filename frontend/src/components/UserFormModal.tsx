import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { Field, inputClass } from "@/components/form";
import { Button, Spinner } from "@/components/ui";
import { usersApi, type UserUpdateInput } from "@/lib/users";
import type { AppUser } from "@/types/api";

function passwordProblems(pw: string): string[] {
  const p: string[] = [];
  if (pw.length < 10) p.push("at least 10 characters");
  if (!/[A-Za-z]/.test(pw)) p.push("at least one letter");
  if (!/\d/.test(pw)) p.push("at least one digit");
  return p;
}

export function UserFormModal({ user, onClose }: { user?: AppUser | null; onClose: () => void }) {
  const editing = !!user;
  const qc = useQueryClient();
  const { user: me } = useAuth();

  const rolesQuery = useQuery({ queryKey: ["users", "roles"], queryFn: usersApi.roles });

  const [email, setEmail] = useState(user?.email ?? "");
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [password, setPassword] = useState("");
  const [isActive, setIsActive] = useState(user?.is_active ?? true);
  const [roleIds, setRoleIds] = useState<string[]>(user?.role_ids ?? []);
  const [err, setErr] = useState<string | null>(null);

  const toggleRole = (id: string) =>
    setRoleIds((ids) => (ids.includes(id) ? ids.filter((r) => r !== id) : [...ids, id]));

  const invalidate = () => qc.invalidateQueries({ queryKey: ["users"] });

  const save = useMutation({
    mutationFn: () => {
      if (editing && user) {
        const body: UserUpdateInput = {
          full_name: fullName.trim(),
          is_active: isActive,
          role_ids: roleIds,
        };
        if (password.trim()) body.password = password;
        return usersApi.update(user.id, body);
      }
      return usersApi.create({
        email: email.trim(),
        full_name: fullName.trim(),
        password,
        role_ids: roleIds,
        is_active: isActive,
      });
    },
    onSuccess: () => {
      invalidate();
      onClose();
    },
    onError: (e) => setErr((e as Error).message),
  });

  const deactivate = useMutation({
    mutationFn: () => usersApi.deactivate(user!.id),
    onSuccess: () => {
      invalidate();
      onClose();
    },
    onError: (e) => setErr((e as Error).message),
  });

  const submit = () => {
    if (!fullName.trim()) return setErr("Full name is required.");
    if (!editing) {
      if (!email.trim()) return setErr("Email is required.");
      const pw = passwordProblems(password);
      if (pw.length) return setErr("Password must contain " + pw.join(", ") + ".");
    } else if (password.trim()) {
      const pw = passwordProblems(password);
      if (pw.length) return setErr("Password must contain " + pw.join(", ") + ".");
    }
    setErr(null);
    save.mutate();
  };

  const busy = save.isPending || deactivate.isPending;
  const isSelf = !!(editing && me && user && me.id === user.id);

  return (
    <Modal
      title={editing ? "Edit user" : "New user"}
      onClose={onClose}
      footer={
        <>
          {editing && user?.is_active && !isSelf && (
            <Button
              variant="ghost"
              className="mr-auto text-red-600 hover:bg-red-50"
              disabled={busy}
              onClick={() => {
                if (window.confirm(`Deactivate ${user.full_name}? They will lose access.`))
                  deactivate.mutate();
              }}
            >
              Deactivate
            </Button>
          )}
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={busy}>
            {save.isPending ? "Saving…" : editing ? "Save changes" : "Create user"}
          </Button>
        </>
      }
    >
      {err && (
        <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}
      <div className="space-y-4">
        <Field label="Email" required={!editing}>
          {editing ? (
            <div className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-600">{user?.email}</div>
          ) : (
            <input
              type="email"
              className={inputClass}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@company.com"
            />
          )}
        </Field>
        <Field label="Full name" required>
          <input className={inputClass} value={fullName} onChange={(e) => setFullName(e.target.value)} />
        </Field>
        <Field
          label={editing ? "New password" : "Password"}
          required={!editing}
          hint={editing ? "Leave blank to keep current" : "Min 10 chars, with a letter and a digit"}
        >
          <input
            type="password"
            className={inputClass}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
          />
        </Field>

        <Field label="Roles">
          {rolesQuery.isLoading ? (
            <Spinner />
          ) : rolesQuery.isError ? (
            <div className="text-sm text-red-700">Couldn’t load roles.</div>
          ) : (
            <div className="max-h-44 space-y-1.5 overflow-y-auto rounded-lg border border-slate-200 p-2">
              {(rolesQuery.data ?? []).map((r) => (
                <label key={r.id} className="flex cursor-pointer items-start gap-2 rounded p-1 hover:bg-slate-50">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={roleIds.includes(r.id)}
                    onChange={() => toggleRole(r.id)}
                  />
                  <span className="text-sm">
                    <span className="font-medium text-slate-800">{r.name}</span>
                    {r.is_system && <span className="ml-1 text-xs text-slate-400">(system)</span>}
                    {r.description && <span className="block text-xs text-slate-400">{r.description}</span>}
                  </span>
                </label>
              ))}
            </div>
          )}
        </Field>

        {(editing || !isActive) && (
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
            Active
          </label>
        )}
        {isSelf && (
          <p className="text-xs text-slate-400">You can’t deactivate your own account.</p>
        )}
      </div>
    </Modal>
  );
}
