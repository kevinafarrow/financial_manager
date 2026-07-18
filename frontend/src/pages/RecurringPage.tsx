import { useCallback, useEffect, useState } from 'react'
import { ApiError, api, money } from '../api'
import type { Account, Recurring } from '../types'
import { Empty, StatusChip, toast } from '../components/ui'

export default function RecurringPage() {
  const [rows, setRows] = useState<Recurring[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [showAdd, setShowAdd] = useState(false)

  const refresh = useCallback(() => {
    void api.get<Recurring[]>('/api/recurring').then(setRows)
  }, [])

  useEffect(() => {
    void api.get<Account[]>('/api/accounts').then(setAccounts)
    refresh()
  }, [refresh])

  const detect = async () => {
    const r = await api.post<{ proposed: number; updated: number }>('/api/recurring/detect')
    toast(`Detection: ${r.proposed} new proposals, ${r.updated} updated`)
    refresh()
  }

  const setStatus = async (id: number, status: string) => {
    try {
      await api.patch(`/api/recurring/${id}`, { status })
      refresh()
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Failed', true)
    }
  }

  const checkBalances = async () => {
    const fired = await api.post<unknown[]>('/api/recurring/check-balances')
    toast(fired.length ? `${fired.length} low-balance warning(s) sent` : 'No balance threats found')
  }

  const proposed = rows.filter((r) => r.status === 'proposed')
  const confirmed = rows.filter((r) => r.status === 'confirmed')
  const other = rows.filter((r) => r.status === 'rejected' || r.status === 'paused')

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Recurring payments</h1>
          <div className="sub">
            Confirmed schedules drive the low-balance warnings before big payments hit.
          </div>
        </div>
        <div className="btn-row">
          <button className="btn" onClick={() => void detect()}>
            ↻ Detect from history
          </button>
          <button className="btn" onClick={() => void checkBalances()}>
            Check balances now
          </button>
          <button className="btn primary" onClick={() => setShowAdd(true)}>
            + Add manually
          </button>
        </div>
      </div>

      {proposed.length > 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>Proposed — confirm or reject</h2>
          {proposed.map((r) => (
            <div key={r.id} className="spread" style={{ padding: '8px 0', borderBottom: '1px solid var(--grid)' }}>
              <div>
                <strong>{r.display_name || r.payee_norm}</strong>
                <div className="small muted">
                  ~{money(r.amount_cents)} {r.period} from {r.account_name} · next due {r.next_due}
                </div>
              </div>
              <div className="btn-row">
                <button className="btn sm primary" onClick={() => void setStatus(r.id, 'confirmed')}>
                  Confirm
                </button>
                <button className="btn sm" onClick={() => void setStatus(r.id, 'rejected')}>
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <h2>Confirmed schedule</h2>
        {confirmed.length === 0 && <Empty>Nothing confirmed yet. Run detection or add manually.</Empty>}
        <table className="data">
          <thead>
            <tr>
              <th>Payment</th>
              <th>Account</th>
              <th>Period</th>
              <th>Next due</th>
              <th className="num">Amount</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {confirmed.map((r) => (
              <tr key={r.id}>
                <td>{r.display_name || r.payee_norm}</td>
                <td className="small muted">{r.account_name}</td>
                <td className="small">{r.period}</td>
                <td className="small">{r.next_due}</td>
                <td className="num mono">{money(r.amount_cents)}</td>
                <td className="num">
                  <button className="btn sm" onClick={() => void setStatus(r.id, 'paused')}>
                    Pause
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {other.length > 0 && (
        <div className="card">
          <h2>Paused / rejected</h2>
          {other.map((r) => (
            <div key={r.id} className="spread small" style={{ padding: '4px 0' }}>
              <span>
                {r.display_name || r.payee_norm} · {money(r.amount_cents)} {r.period}{' '}
                <StatusChip status={r.status} />
              </span>
              <button className="btn sm" onClick={() => void setStatus(r.id, 'confirmed')}>
                Re-confirm
              </button>
            </div>
          ))}
        </div>
      )}

      {showAdd && <AddRecurring accounts={accounts} onClose={() => setShowAdd(false)} onDone={refresh} />}
    </>
  )
}

function AddRecurring({
  accounts,
  onClose,
  onDone,
}: {
  accounts: Account[]
  onClose: () => void
  onDone: () => void
}) {
  const [name, setName] = useState('')
  const [accountId, setAccountId] = useState(accounts[0] ? String(accounts[0].id) : '')
  const [amount, setAmount] = useState('')
  const [period, setPeriod] = useState('monthly')
  const [nextDue, setNextDue] = useState('')
  const [error, setError] = useState('')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await api.post('/api/recurring', {
        display_name: name,
        account_id: Number(accountId),
        amount_cents: Math.round(parseFloat(amount) * 100),
        period,
        next_due: nextDue,
      })
      onDone()
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed')
    }
  }

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'grid', placeItems: 'center', zIndex: 40 }}
      onClick={onClose}
    >
      <form className="card" style={{ width: 380 }} onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2>Add scheduled payment</h2>
        <label className="field">
          <span className="lbl">Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="Car insurance" />
        </label>
        <label className="field">
          <span className="lbl">Account it pays from</span>
          <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="lbl">Amount ($)</span>
          <input type="number" step="0.01" min="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} required />
        </label>
        <label className="field">
          <span className="lbl">Period</span>
          <select value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option value="weekly">weekly</option>
            <option value="biweekly">biweekly</option>
            <option value="monthly">monthly</option>
            <option value="yearly">yearly</option>
          </select>
        </label>
        <label className="field">
          <span className="lbl">Next due date</span>
          <input type="date" value={nextDue} onChange={(e) => setNextDue(e.target.value)} required />
        </label>
        {error && <p className="error-text">{error}</p>}
        <div className="btn-row">
          <button className="btn primary">Add</button>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}
