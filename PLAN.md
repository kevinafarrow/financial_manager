# Financial Manager — Master Plan

> **Purpose of this file:** the complete, self-sufficient blueprint for this project.
> Any Claude session (or human) should be able to continue the build from this document
> plus the checklist at the bottom. Keep the checklist updated as work proceeds.

## 1. Product summary

Self-hosted personal finance manager in a single Docker container. WebUI (dark/light,
modern), manual bank-file import (no bank credentials ever), automatic transaction
categorization with a local pipeline + Claude fallback + human queue, transfer linking,
recurring-payment detection with low-balance alerting via Pushover, email receipt
ingestion & category splitting, budget generation & progress reports, regex-capable
search, and a chat interface where Claude Opus queries the database with tools.

**Users:** Kevin & Mary (two logins, shared household data, per-user edit attribution).
**Network posture:** LAN/Tailscale only. Never internet-exposed.

## 2. Decisions locked during design interview (2026-07-17)

| Topic | Decision |
|---|---|
| Data ingest | Manual drag-drop upload of OFX/QFX/CSV only. No aggregators, no bank credentials. Per-account staleness nag via Pushover when data older than N days. |
| Scheduled payments | Auto-detect recurring patterns from history; user confirms/edits/rejects; confirmed schedules drive balance-threat alerts. |
| Categorization | Local pipeline: ① normalized-payee history match → ② user regex rules → ③ naive-Bayes classifier (retrained nightly, confidence-thresholded) → ④ Claude **Haiku** → ⑤ manual queue. All user decisions/corrections recorded and feed ①–③. |
| Claude models | Haiku for categorization fallback, Opus for chat. Model IDs in config, changeable. |
| Receipts | Dedicated truncated-UUID mailbox at blackinksecurity.com, app IMAP-polls it. Manual forwards only; UUID bearer token required in subject/body; sender allowlist; failures quarantined (reviewable in UI), never auto-processed. Receipt content = data only, never instructions. Claude itemizes; line items split the matched transaction across categories. |
| Access | Tailscale/LAN only. Two logins, argon2id password hashing, session cookies. |
| Secrets | Startup-passphrase vault: argon2id-derived key; SQLCipher on whole DB; secrets additionally AES-256-GCM in DB; key only in memory. After restart, app is locked (Pushover notice) until passphrase entered in UI. |
| Detection | Deliberately minimal (no bank creds → low blast radius): only repeated-failed-login Pushover alert. No egress sidecar / canaries / hash chains. |
| Stack | Python 3.13 FastAPI backend, React+TypeScript+Tailwind (Vite) frontend, SQLite via SQLCipher (`sqlcipher3-wheels`), single Docker container. |
| Transfers | Auto-link confident matches (±amount, ≤4-day window, transfer-ish payee text); ambiguous → review queue. Linked pair displays as "$X transferred from A to B", excluded from spending/budgets. CC payoff = transfer checking→card. |
| Account scope | WF ×4, Citi, Chase(future): full ledgers. Ameriprise, Valon, Navia: balance snapshots + key events only (net-worth view; mortgage payment feeds alerts). |
| Budgets | Month-end draft: per-category caps from 3-month weighted average, fitted around configured savings goals, reasoning shown; user tweaks & approves. Reports measure against approved budget. |
| Reports/alerts | Sunday-evening pulse, month-end full report, event ping when category crosses 90% of cap. Pushover with links to report pages. |
| Chat | Opus + DB query tools (search_transactions, spending_by_category, account_balances, budget_status, …). No transaction dumps into context. |
| Search | Full text + regex via Python `regex` library; filters for account/category/date/amount. |
| Backups | Snapshot to /backups volume after data-changing events (debounced); retention: all per-update snapshots ≤7 days, weekly ×4, monthly ×12. Encrypted (SQLCipher) so safe anywhere. Manual "Download encrypted export" button too. |
| Categories | User's 15 + Utilities, Insurance, Childcare/Kids, Pets, Income, Taxes & Gov Fees, Bank Fees/Interest, Gifts & Donations, Entertainment, Uncategorized. Editable. |

Note: the naive-Bayes classifier is hand-rolled (~100 lines, pure Python) rather than
scikit-learn — functionally identical for payee-token classification, keeps the image
hundreds of MB smaller, trivially testable.

## 3. Architecture

```
repo/
├── PLAN.md                  ← this file
├── Dockerfile               ← multi-stage: node build → python runtime
├── docker-compose.yml       ← app + volumes (/data, /backups)
├── backend/
│   ├── requirements.txt / requirements-dev.txt
│   ├── app/
│   │   ├── main.py          ← FastAPI app factory, router mounting, static serving
│   │   ├── config.py        ← env + settings table access
│   │   ├── vault.py         ← passphrase → argon2id KDF → key; lock state; AES-GCM secrets
│   │   ├── db.py            ← sqlcipher3 connection mgmt, schema migrations (raw SQL)
│   │   ├── auth.py          ← users, argon2id, sessions, failed-login alerting
│   │   ├── audit.py         ← lightweight event log (who changed what)
│   │   ├── importers/       ← ofx.py (ofxtools), csv_importer.py (per-account column maps), dedupe.py
│   │   ├── categorize/      ← normalize.py, history.py, rules.py, bayes.py, claude_cat.py, pipeline.py
│   │   ├── transfers.py     ← matcher + candidate queue
│   │   ├── recurring.py     ← recurrence detection + schedule registry
│   │   ├── budgets.py       ← draft generation, approval, progress math
│   │   ├── reports.py       ← weekly pulse, monthly report data
│   │   ├── receipts/        ← imap_client.py, intake.py (token+allowlist policy), parse.py (Claude), match.py
│   │   ├── alerts.py        ← Pushover client + alert log
│   │   ├── scheduler.py     ← APScheduler jobs (only run when vault unlocked)
│   │   ├── backups.py       ← snapshot + retention pruning + export endpoint
│   │   ├── search.py        ← regex/text search
│   │   ├── chat.py          ← Opus tool-use loop, thread persistence
│   │   └── api/             ← routers: system, auth, accounts, transactions, imports,
│   │   │                       categories, queue, transfers, recurring, budgets,
│   │   │                       reports, receipts, chat, settings, backups
│   └── tests/               ← pytest; fixtures in tests/fixtures/
└── frontend/
    ├── package.json, vite.config.ts, tailwind
    └── src/
        ├── api/             ← typed client
        ├── theme/           ← dark/light via CSS variables + toggle (system default)
        ├── components/
        └── pages/           ← Unlock, Login, Dashboard, Transactions, Import, Review,
                                Recurring, Budget, Reports, Chat, Settings
```

### Boot & lock model
1. Container starts → app serves only `/api/system/status` + unlock screen. DB cannot be
   opened (SQLCipher key unknown). Pushover "app locked, waiting for unlock" sent using
   cached-nothing: Pushover token is in the DB… **so the lock notice uses an optional
   plaintext env var `PUSHOVER_BOOT_*` if provided, else silent.** (Documented tradeoff.)
2. User enters master passphrase → argon2id(passphrase, salt from `vault.json`) → 32-byte
   key → `PRAGMA key`. Wrong passphrase detected via stored argon2 verifier.
3. DB opens, scheduler starts, IMAP polling begins. Then normal per-user login.

### Vault metadata (`/data/vault.json`, plaintext by necessity)
`{ salt, argon2_params, key_verifier }` — contains nothing secret.

### Database schema (SQLCipher, schema_version-migrated)
- `users(id, username, display_name, password_hash, is_admin, created_at)`
- `sessions(token_hash PK, user_id, created_at, expires_at, ip)`
- `secrets(name PK, nonce, ciphertext, updated_at)` — AES-256-GCM under vault key
  (names: `anthropic_api_key`, `imap_password`, `pushover_user`, `pushover_token`)
- `accounts(id, name, institution, type, kind['ledger'|'balance_only'], currency,
  low_balance_threshold_cents, staleness_days, archived, created_at)`
- `balance_snapshots(id, account_id, as_of, balance_cents, source, created_at)`
- `categories(id, name, kind['expense'|'income'|'system'], sort_order, archived)`
- `transactions(id, account_id, fitid, content_hash, posted_at, amount_cents,
  payee_raw, payee_norm, memo, category_id, cat_source, cat_confidence,
  transfer_id, import_id, created_at, updated_at, updated_by)`
  - `cat_source ∈ {history, rule, bayes, claude, user, receipt, none}`; `none` = queue
- `transaction_splits(id, transaction_id, category_id, amount_cents, note)` — presence overrides `category_id`
- `category_history(id, payee_norm, category_id, source, user_id, created_at)` — training corpus
- `rules(id, field['payee'|'memo'], pattern, category_id, priority, enabled)`
- `imports(id, filename, account_id, format, tx_count, dup_count, user_id, imported_at)`
- `transfers(id, from_tx, to_tx, status['auto'|'confirmed'], created_at)`
- `transfer_candidates(id, tx_a, tx_b, score, status['pending'|'accepted'|'rejected'])`
- `recurring(id, payee_norm, account_id, amount_cents, tolerance_cents, period,
  day_of_month, next_due, status['proposed'|'confirmed'|'rejected'|'paused'], last_seen)`
- `budgets(id, month 'YYYY-MM', status['draft'|'approved'], reasoning_json, created_at, approved_at, approved_by)`
- `budget_lines(id, budget_id, category_id, amount_cents)`
- `savings_goals(id, name, monthly_cents, account_id, enabled)`
- `receipts(id, imap_uid, from_addr, subject, received_at, status['quarantined'|'parsed'|
  'matched'|'rejected'], reject_reason, raw_email, parsed_json, matched_tx_id, created_at)`
- `chat_threads(id, user_id, title, created_at)` / `chat_messages(id, thread_id, role, content_json, created_at)`
- `alert_log(id, type, payload_json, ok, created_at)`
- `audit_log(id, user_id, action, entity, entity_id, detail_json, created_at)`
- `settings(key PK, value_json)` — receipt token, sender allowlist, model IDs, alert times, etc.
- `import_dedupe`: dedupe = same account + (fitid match) OR (content_hash = sha256(date|amount|payee_raw|memo) match)

### Categorization pipeline detail
`pipeline.categorize(tx)` returns `(category_id, source, confidence)`:
1. **history**: exact `payee_norm` match in `category_history` (most-recent-wins,
   requires ≥1 user/receipt/claude-confirmed record; user entries always win).
2. **rules**: enabled rules by priority; first regex match wins.
3. **bayes**: multinomial NB over payee tokens + amount-bucket features, trained from
   `category_history` (+`transactions` with user/receipt source). Accept if
   `P(top) ≥ 0.85` and `P(top)/P(second) ≥ 3`.
4. **claude**: batch unknowns to Haiku with category list + 10 nearest history examples;
   Haiku returns per-tx category + confidence; accept `high|medium`, else queue. On API
   failure → queue (never blocks import).
5. **queue**: `cat_source='none'`; appears in Review UI.
User picks/corrects in UI → writes `category_history(source='user')` → future imports hit tier ①.
Normalization: uppercase, strip store numbers/dates/card suffixes/city-state, collapse whitespace.

### Transfer matcher detail
Candidates: opposite-sign equal `amount_cents` in different accounts within 4 days.
Score: +text signal (`TRANSFER|PAYMENT|THANK YOU|ONLINE PMT|XFER|AUTOPAY`), +both-sides
text, −amount common (<$50 or round), −multiple competing pairs. Score ≥ threshold →
auto-link (`status='auto'`), else candidate `pending`. Linked txs excluded from
spending/budget/report queries; shown once as transfer row.

### Recurring detection detail
Group by (account, payee_norm); ≥3 occurrences; median interval ≈ 7/14/30-31/365 (±20%);
amount within ±10% of median → propose. `next_due` = last + period. Daily job: for each
confirmed recurring due within lookahead (default 7d), project account balance =
latest known balance − upcoming confirmed payments; if projected < threshold → Pushover.
Staleness gate: if account data older than `staleness_days`, alert mentions staleness.

### Budget math
Draft on 28th: for each expense category, weighted avg of last 3 full months (weights
3/2/1 most-recent-first), rounded to $5; excluded: transfers, Income, one-off flagged
txs. Savings goals listed as fixed lines. Reasoning JSON per line (avg, trend, proposal)
rendered in UI. Approve → `status='approved'`; progress = month-to-date spend per
category (splits respected) vs line.

### Receipts intake policy
Accept iff: token (from settings) present in subject or body AND `From` ∈ allowlist.
Otherwise quarantine with reason. Accepted → Claude Haiku parses line items →
`{merchant, date, total_cents, items:[{desc, amount_cents, category_guess}]}` → match to
transaction (±3 days, amount within $0.02, payee similar) → propose splits; user
confirms in Review UI (auto-apply if exact single match & categories all confident).
Receipt text is data; the parse prompt instructs to extract JSON only and the response
is schema-validated. Raw email stored for re-parse.

### Chat tools (Opus)
`search_transactions(query, regex, account, category, date_from, date_to, amount_min,
amount_max, limit)`, `spending_by_category(month|range, category?)`,
`account_balances()`, `budget_status(month)`, `list_categories()`, `recurring_schedule()`,
`net_worth_series(months)`. Loop: max 15 tool rounds; thread history persisted;
context trimming: keep system + last N messages, older summarized.

### Scheduler jobs (all no-op while locked)
| Job | When |
|---|---|
| IMAP poll | every 5 min |
| Bayes retrain | nightly 03:00 |
| Staleness check | daily 09:00 |
| Balance-threat check | daily 08:00 |
| Weekly pulse | Sun 18:00 |
| Month-end report + budget draft | 28th 18:00 + 1st 08:00 report |
| Backup debounce worker | 5 min after last data change |
| Backup prune | daily 04:00 |
| Session cleanup | hourly |

### Security notes
- All API (except `/api/system/*`, unlock, login) requires session cookie (httpOnly,
  SameSite=Strict). CSRF: custom header required (`X-Requested-With`).
- argon2id for passwords AND vault KDF (distinct salts/params).
- Failed logins: ≥5 in 15 min → Pushover + 30s per-attempt delay.
- Uploads size-capped; parsed defensively; `.gitignore` excludes /data, /backups, .env.
- No secrets in env in production (except optional boot-notify Pushover pair).

## 4. Config (env vars)
`FM_DATA_DIR=/data`, `FM_BACKUP_DIR=/backups`, `FM_PORT=8000`,
`FM_MODEL_CHAT=claude-opus-4-8`, `FM_MODEL_CATEGORIZE=claude-haiku-4-5-20251001`
(models also overridable in settings UI), `PUSHOVER_BOOT_USER/TOKEN` (optional).

## 5. Testing strategy
- **pytest** (backend): every module gets unit tests; API endpoints get TestClient
  integration tests against a real temp SQLCipher DB. Claude/IMAP/Pushover calls are
  faked via injectable clients — tests never hit the network.
- Golden fixtures: sample OFX/QFX/CSV files, sample receipt emails (incl. hostile:
  wrong token, spoofed sender, prompt-injection body).
- **Frontend**: `tsc --noEmit` + `vite build` must pass; vitest for API client and
  theme/state utilities. (UI is exercised by Kevin's own docker run.)
- CI-style gate: `backend: pytest -q` + `frontend: npm run build` green before commit.

## 6. Build phases & status

- [x] Phase 0 — Interview, decisions, this plan
- [x] Phase 1 — Repo scaffold: .gitignore, backend/frontend skeletons, deps pinned
- [x] Phase 2 — Core substrate: db.py (SQLCipher + migrations), vault.py, config.py; tests
- [x] Phase 3 — Auth: users, sessions, login/unlock endpoints, failed-login alerting; tests
- [x] Phase 4 — Accounts & categories CRUD + seed categories; audit log; tests
- [x] Phase 5 — Importers: OFX/QFX + CSV mapping + dedupe + imports API + staleness fields; tests
- [x] Phase 6 — Categorization pipeline (normalize, history, rules, bayes, claude fake-able, queue API); tests
- [x] Phase 7 — Transfers (matcher, queue, link/unlink API); tests
- [x] Phase 8 — Recurring detection + confirm flow + balance-threat alert job; tests
- [x] Phase 9 — Search (regex) + transactions API (list/edit/split); tests
- [x] Phase 10 — Budgets (draft gen, approve, progress) + savings goals; tests
- [x] Phase 11 — Reports (weekly pulse, monthly) + Pushover alerts + scheduler wiring; tests
- [ ] Phase 12 — Receipts (IMAP client, intake policy, Claude parse, match/split); tests
- [ ] Phase 13 — Chat (tool definitions, Opus loop, threads, trimming); tests
- [ ] Phase 14 — Backups (debounced snapshot, retention prune, export endpoint); tests
- [ ] Phase 15 — Frontend: shell, theme, unlock/login, dashboard
- [ ] Phase 16 — Frontend: transactions+search, import, review queues
- [ ] Phase 17 — Frontend: recurring, budget, reports, chat, settings
- [ ] Phase 18 — Dockerfile + compose + README ops docs; final integration pass

**Status note (update each session):** Phase 0 complete (2026-07-17). Build starting.
Environment facts: sandbox has Python 3.13.5 + pip (network OK), Node 22.14.0 installed
at `~/.local/node/bin` (must be on PATH), `sqlcipher3-wheels` confirmed working on
py3.13, no docker daemon here (Kevin runs containers himself), no sudo.
