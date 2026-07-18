export interface SystemStatus {
  initialized: boolean
  unlocked: boolean
  setup_needed: boolean
}

export interface User {
  id: number
  username: string
  display_name: string
  is_admin: number
}

export interface Account {
  id: number
  name: string
  institution: string
  type: string
  kind: 'ledger' | 'balance_only'
  currency: string
  low_balance_threshold_cents: number | null
  staleness_days: number
  archived: number
  latest_balance?: { as_of: string; balance_cents: number } | null
  last_activity?: string | null
  tx_count?: number
}

export interface Category {
  id: number
  name: string
  kind: 'expense' | 'income' | 'system'
  sort_order: number
  archived: number
  tx_count?: number
}

export interface Split {
  id: number
  transaction_id: number
  category_id: number
  amount_cents: number
  note: string
  category_name?: string
}

export interface Tx {
  id: number
  account_id: number
  posted_at: string
  amount_cents: number
  payee_raw: string
  payee_norm: string
  memo: string
  category_id: number | null
  cat_source: string
  cat_confidence: number | null
  transfer_id: number | null
  account_name: string
  category_name: string | null
  transfer_peer_account?: string | null
  is_transfer_in?: number
  splits: Split[]
}

export interface TxSearch {
  total: number
  transactions: Tx[]
}

export interface Transfer {
  id: number
  status: string
  posted_at: string
  amount_cents: number
  from_account: string
  to_account: string
  from_payee: string
  from_tx: number
  to_tx: number
}

export interface TransferCandidate {
  id: number
  score: number
  tx_a: number
  a_posted_at: string
  a_amount: number
  a_payee: string
  a_account: string
  tx_b: number
  b_posted_at: string
  b_amount: number
  b_payee: string
  b_account: string
}

export interface Recurring {
  id: number
  payee_norm: string
  display_name: string
  account_id: number
  account_name?: string
  amount_cents: number
  tolerance_cents: number
  period: string
  next_due: string | null
  status: 'proposed' | 'confirmed' | 'rejected' | 'paused'
  last_seen: string | null
}

export interface BudgetLine {
  category_id: number
  category_name: string
  budget_cents: number
  spent_cents: number
  remaining_cents: number
  pct: number | null
}

export interface BudgetProgress {
  budget_id: number
  month: string
  status: 'draft' | 'approved'
  reasoning: Record<string, unknown>
  lines: BudgetLine[]
  unbudgeted: { category_id: number; category_name: string; spent_cents: number }[]
  total_budget_cents: number
  total_spent_cents: number
  income_cents: number
}

export interface SavingsGoal {
  id: number
  name: string
  monthly_cents: number
  account_id: number | null
  account_name?: string | null
  enabled: number
}

export interface MonthlyReport {
  month: string
  budget: BudgetProgress | null
  categories: {
    category_id: number
    category_name: string
    spent_cents: number
    prev_spent_cents: number
    delta_cents: number
  }[]
  income_cents: number
  total_spent_cents: number
  net_cents: number
  savings_goal_cents: number
}

export interface Pulse {
  month: string
  pct_month: number
  pct_budget: number
  total_budget_cents: number
  spent_cents: number
  hot_categories: { name: string; pct: number; spent_cents: number; budget_cents: number }[]
  message?: string
}

export interface Receipt {
  id: number
  from_addr: string
  subject: string
  received_at: string | null
  status: 'quarantined' | 'parsed' | 'matched' | 'rejected'
  reject_reason: string | null
  matched_tx_id: number | null
  created_at: string
  parsed: {
    merchant: string
    date: string
    total_cents: number
    items: { description: string; amount_cents: number; category: string }[]
  } | null
}

export interface Rule {
  id: number
  field: 'payee' | 'memo'
  pattern: string
  category_id: number
  category_name?: string
  priority: number
  enabled: number
}

export interface ChatThread {
  id: number
  title: string
  created_at: string
  message_count?: number
}

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  text: string
  created_at: string
}

export interface Settings {
  secrets: Record<string, boolean>
  receipt_token: string | null
  receipt_allowed_senders: string[]
  imap: { host: string | null; port: number; username: string | null }
  models: { chat: string; categorize: string }
  base_url: string
}

export interface ImportResult {
  import_id: number
  imported: number
  duplicates: number
  balance_recorded: boolean
}

export interface Staleness {
  id: number
  name: string
  staleness_days: number
  freshest: string | null
  age_days: number | null
  stale: boolean
}

export interface BackupInfo {
  filename: string
  created_at: string
  size_bytes: number
}

export interface AlertLogRow {
  id: number
  type: string
  payload_json: string
  ok: number
  created_at: string
}
