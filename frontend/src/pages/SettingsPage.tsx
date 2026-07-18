import { useCallback, useEffect, useState } from 'react'
import { ApiError, api, money } from '../api'
import type { Account, BackupInfo, Category, Rule, Settings } from '../types'
import { Empty, toast } from '../components/ui'

type Tab = 'accounts' | 'categories' | 'rules' | 'connections' | 'backups'

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>('accounts')
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
        </div>
      </div>
      <div className="tabs">
        {(
          [
            ['accounts', 'Accounts'],
            ['categories', 'Categories'],
            ['rules', 'Rules'],
            ['connections', 'Connections'],
            ['backups', 'Backups'],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button key={key} className={`tab${tab === key ? ' active' : ''}`} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>
      {tab === 'accounts' && <AccountsTab />}
      {tab === 'categories' && <CategoriesTab />}
      {tab === 'rules' && <RulesTab />}
      {tab === 'connections' && <ConnectionsTab />}
      {tab === 'backups' && <BackupsTab />}
    </>
  )
}

// ---------------------------------------------------------------- accounts

const ACCOUNT_TYPES = ['checking', 'savings', 'credit', 'investment', 'mortgage', 'benefits']

function AccountsTab() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [name, setName] = useState('')
  const [institution, setInstitution] = useState('')
  const [type, setType] = useState('checking')
  const [kind, setKind] = useState('ledger')

  const refresh = useCallback(() => {
    void api.get<Account[]>('/api/accounts').then(setAccounts)
  }, [])
  useEffect(refresh, [refresh])

  const add = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await api.post('/api/accounts', { name, institution, type, kind })
      setName('')
      setInstitution('')
      refresh()
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Failed', true)
    }
  }

  const patch = async (id: number, body: Record<string, unknown>) => {
    try {
      await api.patch(`/api/accounts/${id}`, body)
      refresh()
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Failed', true)
    }
  }

  const addSnapshot = async (a: Account) => {
    const val = window.prompt(`Current balance for ${a.name} (e.g. 12345.67, negative for debt):`)
    if (val === null) return
    const asOf = window.prompt('As of date (YYYY-MM-DD):', new Date().toISOString().slice(0, 10))
    if (asOf === null) return
    try {
      await api.post(`/api/accounts/${a.id}/snapshots`, {
        as_of: asOf,
        balance_cents: Math.round(parseFloat(val) * 100),
      })
      refresh()
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Failed', true)
    }
  }

  return (
    <>
      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Add account</h2>
        <form className="row" style={{ flexWrap: 'wrap' }} onSubmit={add}>
          <input placeholder="Name (e.g. Joint Checking)" style={{ flex: '1 1 180px' }} value={name} onChange={(e) => setName(e.target.value)} required />
          <input placeholder="Institution" style={{ flex: '1 1 140px' }} value={institution} onChange={(e) => setInstitution(e.target.value)} />
          <select style={{ flex: '0 1 130px' }} value={type} onChange={(e) => setType(e.target.value)}>
            {ACCOUNT_TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          <select style={{ flex: '0 1 170px' }} value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="ledger">full ledger</option>
            <option value="balance_only">balance only</option>
          </select>
          <button className="btn primary">Add</button>
        </form>
        <p className="small muted" style={{ marginBottom: 0 }}>
          “Balance only” suits the 401k, mortgage, and FSA accounts — snapshots instead of
          transaction imports.
        </p>
      </div>

      <div className="card">
        <table className="data">
          <thead>
            <tr>
              <th>Account</th>
              <th>Kind</th>
              <th className="num">Balance</th>
              <th className="num">Low-balance alert</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {accounts.map((a) => (
              <tr key={a.id} style={a.archived ? { opacity: 0.5 } : undefined}>
                <td>
                  {a.name}
                  <div className="small muted">
                    {a.institution || '—'} · {a.type} · {a.tx_count} txs
                  </div>
                </td>
                <td className="small">{a.kind === 'ledger' ? 'ledger' : 'balance only'}</td>
                <td className="num mono">
                  {money(a.latest_balance?.balance_cents ?? null)}
                  <div className="small muted">{a.latest_balance?.as_of ?? ''}</div>
                </td>
                <td className="num">
                  <input
                    style={{ width: 100, textAlign: 'right' }}
                    placeholder="off"
                    defaultValue={a.low_balance_threshold_cents != null ? (a.low_balance_threshold_cents / 100).toFixed(0) : ''}
                    onBlur={(e) => {
                      const v = e.target.value.trim()
                      void patch(a.id, {
                        low_balance_threshold_cents: v ? Math.round(parseFloat(v) * 100) : null,
                      })
                    }}
                  />
                </td>
                <td className="num">
                  <div className="btn-row" style={{ justifyContent: 'flex-end' }}>
                    <button className="btn sm" onClick={() => void addSnapshot(a)}>
                      Balance…
                    </button>
                    <button className="btn sm" onClick={() => void patch(a.id, { archived: !a.archived })}>
                      {a.archived ? 'Restore' : 'Archive'}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

// -------------------------------------------------------------- categories

function CategoriesTab() {
  const [categories, setCategories] = useState<Category[]>([])
  const [name, setName] = useState('')
  const refresh = useCallback(() => {
    void api.get<Category[]>('/api/categories').then(setCategories)
  }, [])
  useEffect(refresh, [refresh])

  const add = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await api.post('/api/categories', { name })
      setName('')
      refresh()
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Failed', true)
    }
  }

  const patch = async (id: number, body: Record<string, unknown>) => {
    try {
      await api.patch(`/api/categories/${id}`, body)
      refresh()
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Failed', true)
    }
  }

  return (
    <div className="card">
      <form className="row" style={{ marginBottom: 14, maxWidth: 420 }} onSubmit={add}>
        <input placeholder="New category name" value={name} onChange={(e) => setName(e.target.value)} required />
        <button className="btn primary">Add</button>
      </form>
      <table className="data">
        <tbody>
          {categories.map((c) => (
            <tr key={c.id} style={c.archived ? { opacity: 0.5 } : undefined}>
              <td>
                {c.name} {c.kind !== 'expense' && <span className="chip">{c.kind}</span>}
              </td>
              <td className="small muted num">{c.tx_count} txs</td>
              <td className="num">
                {c.kind !== 'system' && (
                  <div className="btn-row" style={{ justifyContent: 'flex-end' }}>
                    <button
                      className="btn sm"
                      onClick={() => {
                        const newName = window.prompt('Rename category:', c.name)
                        if (newName && newName !== c.name) void patch(c.id, { name: newName })
                      }}
                    >
                      Rename
                    </button>
                    <button className="btn sm" onClick={() => void patch(c.id, { archived: !c.archived })}>
                      {c.archived ? 'Restore' : 'Archive'}
                    </button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ------------------------------------------------------------------- rules

function RulesTab() {
  const [rules, setRules] = useState<Rule[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [pattern, setPattern] = useState('')
  const [field, setField] = useState<'payee' | 'memo'>('payee')
  const [categoryId, setCategoryId] = useState('')

  const refresh = useCallback(() => {
    void api.get<Rule[]>('/api/rules').then(setRules)
  }, [])
  useEffect(() => {
    void api.get<Category[]>('/api/categories').then((c) => {
      setCategories(c.filter((x) => !x.archived && x.kind !== 'system'))
      if (c.length) setCategoryId(String(c[0].id))
    })
    refresh()
  }, [refresh])

  const add = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await api.post('/api/rules', { pattern, field, category_id: Number(categoryId) })
      setPattern('')
      refresh()
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Failed', true)
    }
  }

  return (
    <div className="card">
      <p className="small muted">
        Regex rules run after exact history matching and before the classifier. First match by
        priority wins.
      </p>
      <form className="row" style={{ flexWrap: 'wrap', marginBottom: 14 }} onSubmit={add}>
        <input placeholder={String.raw`Pattern, e.g. COSTCO|WHOLEFDS`} style={{ flex: '2 1 220px' }} value={pattern} onChange={(e) => setPattern(e.target.value)} required />
        <select style={{ flex: '0 1 100px' }} value={field} onChange={(e) => setField(e.target.value as 'payee' | 'memo')}>
          <option value="payee">payee</option>
          <option value="memo">memo</option>
        </select>
        <select style={{ flex: '1 1 150px' }} value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <button className="btn primary">Add rule</button>
      </form>
      {rules.length === 0 && <Empty>No rules yet.</Empty>}
      <table className="data">
        <tbody>
          {rules.map((r) => (
            <tr key={r.id} style={r.enabled ? undefined : { opacity: 0.5 }}>
              <td>
                <code>{r.pattern}</code>
                <span className="small muted"> on {r.field}</span>
              </td>
              <td>
                <span className="chip">{r.category_name}</span>
              </td>
              <td className="num">
                <div className="btn-row" style={{ justifyContent: 'flex-end' }}>
                  <button className="btn sm" onClick={async () => {
                    await api.patch(`/api/rules/${r.id}`, { enabled: !r.enabled })
                    refresh()
                  }}>
                    {r.enabled ? 'Disable' : 'Enable'}
                  </button>
                  <button className="btn sm danger" onClick={async () => {
                    await api.delete(`/api/rules/${r.id}`)
                    refresh()
                  }}>
                    Delete
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ------------------------------------------------------------- connections

const SECRET_LABELS: Record<string, string> = {
  anthropic_api_key: 'Anthropic API key (categorization + chat + receipts)',
  imap_password: 'IMAP password (receipts mailbox)',
  pushover_user: 'Pushover user key',
  pushover_token: 'Pushover app token',
}

function ConnectionsTab() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [secretValues, setSecretValues] = useState<Record<string, string>>({})
  const [token, setToken] = useState('')
  const [senders, setSenders] = useState('')
  const [imapHost, setImapHost] = useState('')
  const [imapUser, setImapUser] = useState('')

  const refresh = useCallback(async () => {
    const s = await api.get<Settings>('/api/settings')
    setSettings(s)
    setToken(s.receipt_token ?? '')
    setSenders(s.receipt_allowed_senders.join(', '))
    setImapHost(s.imap.host ?? '')
    setImapUser(s.imap.username ?? '')
  }, [])
  useEffect(() => {
    void refresh()
  }, [refresh])

  const saveSecret = async (name: string) => {
    const value = secretValues[name]
    if (!value) return
    try {
      await api.put('/api/settings/secrets', { name, value })
      setSecretValues((v) => ({ ...v, [name]: '' }))
      toast('Secret stored (encrypted).')
      void refresh()
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Failed', true)
    }
  }

  const saveReceipts = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await api.put('/api/settings/receipts', {
        receipt_token: token,
        receipt_allowed_senders: senders.split(',').map((s) => s.trim()).filter(Boolean),
        imap_host: imapHost,
        imap_username: imapUser,
      })
      toast('Receipt settings saved.')
      void refresh()
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Failed', true)
    }
  }

  if (!settings) return null
  return (
    <div className="grid cols-2" style={{ alignItems: 'start' }}>
      <div className="card">
        <h2>Secrets (encrypted at rest)</h2>
        {Object.entries(SECRET_LABELS).map(([name, label]) => (
          <div key={name} className="field" style={{ marginBottom: 14 }}>
            <span className="lbl">
              {label}{' '}
              {settings.secrets[name] ? (
                <span className="chip good">set</span>
              ) : (
                <span className="chip warn">not set</span>
              )}
            </span>
            <div className="row">
              <input
                type="password"
                placeholder={settings.secrets[name] ? '••••••••  (enter to replace)' : 'paste value'}
                value={secretValues[name] ?? ''}
                onChange={(e) => setSecretValues((v) => ({ ...v, [name]: e.target.value }))}
              />
              <button className="btn sm" onClick={() => void saveSecret(name)} disabled={!secretValues[name]}>
                Save
              </button>
            </div>
          </div>
        ))}
        <p className="small muted">
          Models in use: {settings.models.categorize} (categorize) · {settings.models.chat} (chat)
        </p>
      </div>

      <form className="card" onSubmit={saveReceipts}>
        <h2>Receipts mailbox</h2>
        <label className="field">
          <span className="lbl">Bearer token (must appear in forwarded receipt subject/body)</span>
          <input value={token} onChange={(e) => setToken(e.target.value)} placeholder="paste a UUID" />
        </label>
        <label className="field">
          <span className="lbl">Allowed senders (comma-separated — your own addresses)</span>
          <input value={senders} onChange={(e) => setSenders(e.target.value)} placeholder="kevin@…, mary@…" />
        </label>
        <label className="field">
          <span className="lbl">IMAP host</span>
          <input value={imapHost} onChange={(e) => setImapHost(e.target.value)} placeholder="mail.blackinksecurity.com" />
        </label>
        <label className="field">
          <span className="lbl">IMAP username</span>
          <input value={imapUser} onChange={(e) => setImapUser(e.target.value)} placeholder="a3f8c2d1@blackinksecurity.com" />
        </label>
        <button className="btn primary">Save receipt settings</button>
        <p className="small muted" style={{ marginBottom: 0, marginTop: 10 }}>
          Set the IMAP password in Secrets. Mail must carry the token AND come from an allowed
          sender, or it is quarantined.
        </p>
      </form>
    </div>
  )
}

// ----------------------------------------------------------------- backups

function BackupsTab() {
  const [backups, setBackups] = useState<BackupInfo[]>([])
  const refresh = useCallback(() => {
    void api.get<BackupInfo[]>('/api/backups').then(setBackups)
  }, [])
  useEffect(refresh, [refresh])

  const snapshot = async () => {
    const r = await api.post<{ filename: string }>('/api/backups/snapshot')
    toast(`Snapshot written: ${r.filename}`)
    refresh()
  }

  return (
    <div className="card">
      <div className="spread" style={{ marginBottom: 12 }}>
        <p className="small muted" style={{ margin: 0 }}>
          Snapshots fire automatically after data changes (debounced) and are pruned to: all from
          the last 7 days, weekly for a month, monthly for a year. Files are SQLCipher-encrypted —
          useless without your passphrase.
        </p>
        <div className="btn-row">
          <button className="btn" onClick={() => void snapshot()}>
            Snapshot now
          </button>
          <a className="btn primary" href="/api/backups/export">
            ⇩ Download export
          </a>
        </div>
      </div>
      {backups.length === 0 && <Empty>No snapshots yet.</Empty>}
      <table className="data">
        <tbody>
          {backups.map((b) => (
            <tr key={b.filename}>
              <td className="mono">{b.filename}</td>
              <td className="num small muted">{(b.size_bytes / 1024).toFixed(0)} KB</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
