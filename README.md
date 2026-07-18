# Family Finances

Self-hosted household finance manager. Manual bank-file imports (no bank
credentials, no aggregators), automatic transaction categorization that learns
from your corrections, transfer linking, budget drafts you approve, receipt
splitting from a dedicated mailbox, Pushover alerting, and a Claude-powered
chat over your own data. Everything encrypted at rest behind a master
passphrase.

Design, architecture, and build status: see [PLAN.md](PLAN.md).

## Run it

```sh
docker compose up -d --build
# open http://localhost:8000
```

First run walks you through creating the master passphrase and your login.
After any container restart the app is **locked** — enter the passphrase in the
UI to decrypt the database and resume polling/alerts.

> Expose the port only on your LAN/Tailscale interface. This app is designed to
> never face the public internet.

## First-week checklist

1. **Settings → Accounts**: add your accounts. Mark the 401k/mortgage/FSA as
   *balance only*; set low-balance alert thresholds on checking accounts.
2. **Settings → Connections**: paste your Anthropic API key and Pushover keys
   (stored AES-256-GCM encrypted). Configure the receipts mailbox (IMAP host,
   username, password) plus the bearer token and sender allowlist.
3. **Import**: drag in OFX/QFX/CSV exports from each bank. Re-uploads are
   deduplicated, so overlapping exports are safe.
4. **Review**: work through the categorization queue once — every answer is
   remembered, so the queue shrinks fast.
5. **Recurring**: run *Detect from history* and confirm the real schedules
   (mortgage, subscriptions). Confirmed ones drive low-balance warnings.
6. **Budget**: draft next month from history, tweak the caps, approve.

## Development

```sh
# backend (Python 3.13)
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
cd backend && ../.venv/bin/python -m pytest

# frontend
cd frontend && npm install && npm test && npm run dev  # dev server proxies /api to :8000

# run the API against a local data dir
FM_DATA_DIR=./data FM_BACKUP_DIR=./backups .venv/bin/python -m uvicorn app.main:create_app \
  --factory --app-dir backend --reload
```

Tests must pass before committing: `pytest` (backend) and `npm run build`
(typecheck + bundle) + `npm test` (frontend).

## Security model

- No bank credentials ever — imports are files you download yourself, so the
  app cannot move money.
- Master passphrase → argon2id → key for SQLCipher (whole database) and
  AES-256-GCM (individual secrets: Anthropic key, IMAP password, Pushover).
  Key lives only in memory; `vault.json` on disk holds salt + verifier only.
- Receipts mailbox is a dedicated random address; mail is processed only when
  it carries your bearer token AND comes from an allowlisted sender; everything
  else is quarantined for inspection. Receipt/transaction text is always
  treated as data, never as instructions.
- Repeated failed logins trigger a Pushover alert and throttling.
- Backups are SQLCipher-encrypted snapshots (safe to sync anywhere), taken
  after data changes and pruned: daily ×7, weekly ×~4, monthly ×12.
