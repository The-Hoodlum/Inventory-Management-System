import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { UserFormModal } from "@/components/UserFormModal";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { formatDate } from "@/lib/format";
import { usersApi } from "@/lib/users";
import type { AppUser } from "@/types/api";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

export default function UsersPage() {
  const { hasPermission } = useAuth();
  const canManage = hasPermission("user.manage");

  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<AppUser | null>(null);
  const [creating, setCreating] = useState(false);

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ["users", search, status, page],
    queryFn: () => usersApi.list({ search, status, page, page_size: 20 }),
    placeholderData: (prev) => prev,
  });

  return (
    <div>
      <PageHeader
        title="Users"
        description="Invite teammates, assign roles, and manage access."
        actions={
          canManage ? (
            <Button onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4" /> New user
            </Button>
          ) : undefined
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          placeholder="Search name or email…"
          className={`${INPUT} w-64`}
        />
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
          className={INPUT}
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
        </select>
        {isFetching && <Spinner />}
      </div>

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Spinner label="Loading users…" />
        </div>
      ) : isError ? (
        <Card className="p-6 text-sm text-red-700">
          Couldn’t load users. {(error as Error | null)?.message ?? ""}
        </Card>
      ) : !data || data.items.length === 0 ? (
        <Card className="p-10 text-center">
          <p className="text-sm font-medium text-slate-700">No users found</p>
          <p className="mt-1 text-sm text-slate-400">Add a teammate to get started.</p>
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-2.5 font-medium">Name</th>
                  <th className="px-4 py-2.5 font-medium">Roles</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Last login</th>
                  {canManage && <th className="w-20 px-4 py-2.5" />}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((u) => (
                  <tr
                    key={u.id}
                    className={canManage ? "cursor-pointer hover:bg-slate-50" : ""}
                    onClick={canManage ? () => setEditing(u) : undefined}
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-800">{u.full_name}</div>
                      <div className="text-xs text-slate-400">{u.email}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {u.roles.length ? u.roles.join(", ") : <span className="text-slate-400">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={u.is_active ? "active" : "inactive"} />
                    </td>
                    <td className="px-4 py-3 text-slate-500">
                      {u.last_login_at ? formatDate(u.last_login_at) : "—"}
                    </td>
                    {canManage && (
                      <td className="px-4 py-3 text-right">
                        <Button
                          variant="ghost"
                          onClick={(e) => {
                            e.stopPropagation();
                            setEditing(u);
                          }}
                        >
                          Edit
                        </Button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Pagination
        page={data?.page ?? 1}
        totalPages={data?.total_pages ?? 0}
        total={data?.total ?? 0}
        onChange={setPage}
      />

      {creating && <UserFormModal onClose={() => setCreating(false)} />}
      {editing && <UserFormModal user={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}
