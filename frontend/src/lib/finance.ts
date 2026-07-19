// Finance API — accounts + derived balances (PR 1 of the cash book / treasury module).
// A balance is always DERIVED (opening + IN - OUT) and returned on read; it can never be
// set. Reads need finance.read; account admin needs finance.account.manage. Accounts are
// DEACTIVATED (is_active=false), never deleted — there is no delete endpoint.
import { api } from "@/lib/api";

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
};

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
