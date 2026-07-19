// Finance API — accounts + derived balances (PR 1 of the cash book / treasury module).
// A balance is always DERIVED (opening + IN - OUT) and returned on read; it can never be
// set. Reads need finance.read; account admin needs finance.account.manage. Accounts are
// DEACTIVATED (is_active=false), never deleted — there is no delete endpoint.
import { api, BASE_URL, tokenStore } from "@/lib/api";

export type AccountType = "CASH" | "BANK" | "MOBILE_MONEY" | "CUSTODY";

export interface FinanceAccount {
  id: string;
  tenant_id: string;
  branch_id: string | null;
  branch_name: string | null;
  name: string;
  type: AccountType;
  currency: string;
  opening_balance: string;
  opening_as_of: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  // Present on list / get (AccountBalanceOut) — the derived position.
  total_in: string;
  total_out: string;
  balance: string;
}

export interface AccountCreateInput {
  name: string;
  type: AccountType;
  branch_id?: string | null;
  currency?: string;
  opening_balance?: string;
  opening_as_of?: string | null;
}

export interface AccountUpdateInput {
  name?: string;
  is_active?: boolean;
}

export const ACCOUNT_TYPE_LABELS: Record<AccountType, string> = {
  CASH: "Cash in hand",
  BANK: "Bank",
  MOBILE_MONEY: "Mobile money",
  CUSTODY: "Custody",
};

// Sales payment methods that can be mapped to a finance account (mirrors the backend).
export type PaymentMethod =
  | "cash" | "card" | "mobile_money" | "bank_transfer" | "cheque" | "store_credit";

export const PAYMENT_METHODS: PaymentMethod[] = [
  "cash", "mobile_money", "bank_transfer", "card", "cheque", "store_credit",
];

export const PAYMENT_METHOD_LABELS: Record<PaymentMethod, string> = {
  cash: "Cash",
  mobile_money: "Mobile money",
  bank_transfer: "Bank transfer",
  card: "Card",
  cheque: "Cheque",
  store_credit: "Store credit",
};

export interface PaymentMapping {
  id: string;
  branch_id: string;
  branch_name: string | null;
  method: PaymentMethod;
  account_id: string;
  account_name: string | null;
}

export const financeApi = {
  listAccounts: (params: { branch_id?: string; active_only?: boolean; type?: string } = {}) => {
    const p = new URLSearchParams();
    if (params.branch_id) p.set("branch_id", params.branch_id);
    if (params.active_only) p.set("active_only", "true");
    if (params.type) p.set("type", params.type);
    const qs = p.toString();
    return api.get<FinanceAccount[]>(`/finance/accounts${qs ? `?${qs}` : ""}`);
  },
  getAccount: (id: string) => api.get<FinanceAccount>(`/finance/accounts/${id}`),
  createAccount: (body: AccountCreateInput) => api.post<FinanceAccount>("/finance/accounts", body),
  updateAccount: (id: string, body: AccountUpdateInput) =>
    api.patch<FinanceAccount>(`/finance/accounts/${id}`, body),

  // Money-in: per-branch payment-method -> account mapping.
  listMappings: () => api.get<PaymentMapping[]>("/finance/payment-mappings"),
  setMapping: (body: { branch_id: string; method: PaymentMethod; account_id: string }) =>
    api.put<PaymentMapping>("/finance/payment-mappings", body),
  deleteMapping: (id: string) => api.del<void>(`/finance/payment-mappings/${id}`),

  // Expense categories (configurable tenant list).
  listCategories: (activeOnly = false) =>
    api.get<ExpenseCategory[]>(`/finance/expense-categories${activeOnly ? "?active_only=true" : ""}`),
  createCategory: (name: string) => api.post<ExpenseCategory>("/finance/expense-categories", { name }),
  updateCategory: (id: string, body: { name?: string; is_active?: boolean }) =>
    api.patch<ExpenseCategory>(`/finance/expense-categories/${id}`, body),

  // Expenses (money out).
  listExpenses: (params: {
    branch_id?: string; category_id?: string; account_id?: string;
    status?: string; date_from?: string; date_to?: string;
  } = {}) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v) p.set(k, v);
    const qs = p.toString();
    return api.get<Expense[]>(`/finance/expenses${qs ? `?${qs}` : ""}`);
  },
  createExpense: (body: ExpenseInput) => api.post<Expense>("/finance/expenses", body),
  updateExpense: (id: string, body: Partial<ExpenseInput>) =>
    api.patch<Expense>(`/finance/expenses/${id}`, body),
  voidExpense: (id: string, reason: string) =>
    api.post<Expense>(`/finance/expenses/${id}/void`, { reason }),
  uploadReceipt: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.upload<void>(`/finance/expenses/${id}/attachment`, form);
  },
  receiptUrl: (id: string) => `/finance/expenses/${id}/attachment`,

  // Transfers between accounts (paired OUT + IN).
  listTransfers: () => api.get<Transfer[]>("/finance/transfers"),
  createTransfer: (body: { from_account_id: string; to_account_id: string; amount: string; reference_no?: string | null; notes?: string | null }) =>
    api.post<Transfer>("/finance/transfers", body),
  reverseTransfer: (id: string, reason: string) => api.post<Transfer>(`/finance/transfers/${id}/reverse`, { reason }),

  // Cash handovers (two-sided).
  listHandovers: (params: { branch_id?: string; status?: string; person?: string; date_from?: string; date_to?: string } = {}) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v) p.set(k, v);
    const qs = p.toString();
    return api.get<Handover[]>(`/finance/handovers${qs ? `?${qs}` : ""}`);
  },
  createHandover: (body: HandoverInput) => api.post<Handover>("/finance/handovers", body),
  confirmHandover: (id: string, confirmed_amount: string, discrepancy_reason?: string) =>
    api.post<Handover>(`/finance/handovers/${id}/confirm`, { confirmed_amount, discrepancy_reason }),
  reverseHandover: (id: string, reason: string) => api.post<Handover>(`/finance/handovers/${id}/reverse`, { reason }),
  slipUrl: (id: string) => `/finance/handovers/${id}/slip`,

  // Dashboard, statement, day book.
  dashboard: (params: { date_from?: string; date_to?: string; branch_id?: string } = {}) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v) p.set(k, v);
    const qs = p.toString();
    return api.get<FinanceDashboard>(`/finance/dashboard${qs ? `?${qs}` : ""}`);
  },
  statement: (accountId: string, params: { date_from?: string; date_to?: string } = {}) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v) p.set(k, v);
    const qs = p.toString();
    return api.get<AccountStatement>(`/finance/accounts/${accountId}/statement${qs ? `?${qs}` : ""}`);
  },
  statementPdfPath: (accountId: string, params: { date_from?: string; date_to?: string }) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v) p.set(k, v);
    return `/finance/accounts/${accountId}/statement.pdf?${p.toString()}`;
  },
  dayBook: (params: { period?: string; date?: string; branch_id?: string } = {}) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v) p.set(k, v);
    const qs = p.toString();
    return api.get<DayBook>(`/finance/day-book${qs ? `?${qs}` : ""}`);
  },
  dayBookPdfPath: (params: { period?: string; date?: string; branch_id?: string }) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v) p.set(k, v);
    return `/finance/day-book.pdf?${p.toString()}`;
  },
};

export interface FinanceDashboard {
  date_from: string;
  date_to: string;
  accounts: FinanceAccount[];
  money_in: string;
  expenses_out: string;
  handovers_out: string;
  transfers_out: string;
  net_movement: string;
  money_in_by_account: { account_id: string; account_name: string | null; amount: string }[];
}

export interface StatementRow {
  id: string;
  occurred_at: string;
  description: string | null;
  category: string | null;
  reference_type: string | null;
  direction: "IN" | "OUT";
  amount: string;
  in_amount: string;
  out_amount: string;
  running_balance: string;
}

export interface AccountStatement {
  account_id: string;
  account_name: string | null;
  currency: string;
  date_from: string;
  date_to: string;
  opening_balance: string;
  rows: StatementRow[];
  total_in: string;
  total_out: string;
  closing_balance: string;
}

export interface DayBookRow {
  branch_id: string | null;
  branch_name: string | null;
  opening: string;
  money_in: string;
  expenses: string;
  handovers: string;
  transfers_in: string;
  transfers_out: string;
  other_in: string;
  other_out: string;
  closing: string;
}

export interface DayBook {
  period: string;
  label: string;
  date_from: string;
  date_to: string;
  rows: DayBookRow[];
  totals: DayBookRow;
}

// Authenticated blob download for a finance PDF (statement / day book / slip).
export async function downloadFinancePdf(path: string, filename: string): Promise<void> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${tokenStore.getAccess() ?? ""}` },
  });
  if (!res.ok) return;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export interface Transfer {
  id: string;
  from_account_id: string;
  from_account_name: string | null;
  to_account_id: string;
  to_account_name: string | null;
  amount: string;
  occurred_at: string;
  reference_no: string | null;
  notes: string | null;
  status: "completed" | "reversed";
  created_at: string;
}

export type HandoverStatus = "PENDING_CONFIRMATION" | "CONFIRMED" | "DISPUTED";

export interface Handover {
  id: string;
  branch_id: string | null;
  branch_name: string | null;
  from_account_id: string;
  from_account_name: string | null;
  to_account_id: string;
  to_account_name: string | null;
  amount: string;
  handover_datetime: string;
  handed_over_by_name: string | null;
  received_by_name: string;
  reference_no: string | null;
  notes: string | null;
  denomination_breakdown: Record<string, unknown> | null;
  status: HandoverStatus;
  confirmed_amount: string | null;
  discrepancy_amount: string | null;
  discrepancy_reason: string | null;
  reversed_at: string | null;
  reverse_reason: string | null;
  has_attachment: boolean;
  created_at: string;
}

export interface HandoverInput {
  from_account_id: string;
  to_account_id: string;
  branch_id?: string | null;
  amount: string;
  handed_over_by_name?: string | null;
  received_by_name: string;
  reference_no?: string | null;
  notes?: string | null;
  denomination_breakdown?: Record<string, number> | null;
}

export interface ExpenseCategory {
  id: string;
  name: string;
  is_active: boolean;
}

export interface Expense {
  id: string;
  tenant_id: string;
  branch_id: string | null;
  branch_name: string | null;
  account_id: string;
  account_name: string | null;
  amount: string;
  expense_date: string;
  category_id: string | null;
  category_name: string | null;
  payee: string | null;
  description: string | null;
  reference_no: string | null;
  status: "recorded" | "voided";
  recorded_by: string | null;
  void_reason: string | null;
  voided_by: string | null;
  voided_at: string | null;
  has_attachment: boolean;
  created_at: string;
}

export interface ExpenseInput {
  account_id?: string;
  branch_id?: string | null;
  amount?: string;
  expense_date?: string;
  category_id?: string | null;
  payee?: string | null;
  description?: string | null;
  reference_no?: string | null;
}
