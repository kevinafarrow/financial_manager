import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, currentMonth, money, pct } from '../api'
import type { Account, BudgetProgress, Pulse, Staleness, Transfer, TxSearch } from '../types'
import { Empty, Meter, Money, Tile } from '../components/ui'

export default function Dashboard() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [budget, setBudget] = useState<BudgetProgress | null>(null)
  const [pulse, setPulse] = useState<Pulse | null>(null)
  const [recent, setRecent] = useState<TxSearch | null>(null)
  const [transfers, setTransfers] = useState<Transfer[]>([])
  const [staleness, setStaleness] = useState<Staleness[]>([])

  useEffect(() => {
    void api.get<Account[]>('/api/accounts').then(setAccounts)
    void api.get<BudgetProgress>(`/api/budgets/${currentMonth()}`).then(setBudget).catch(() => setBudget(null))
    void api.get<Pulse>('/api/reports/pulse').then(setPulse).catch(() => setPulse(null))
    void api.get<TxSearch>('/api/transactions', { limit: 8, include_transfers: false }).then(setRecent)
    void api.get<Transfer[]>('/api/transfers').then((t) => setTransfers(t.slice(0, 4)))
    void api.get<Staleness[]>('/api/imports/staleness').then(setStaleness)
  }, [])

  const cash = accounts
    .filter((a) => !a.archived && (a.type === 'checking' || a.type === 'savings'))
    .reduce((sum, a) => sum + (a.latest_balance?.balance_cents ?? 0), 0)
  const cardDebt = accounts
    .filter((a) => !a.archived && a.type === 'credit')
    .reduce((sum, a) => sum + (a.latest_balance?.balance_cents ?? 0), 0)
  const stale = staleness.filter((s) => s.stale)
  const month = currentMonth()

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <div className="sub">{pulse?.message ?? `Month to date, ${month}`}</div>
        </div>
        <Link className="btn" to="/import">
          ⇪ Import files
        </Link>
      </div>

      {stale.length > 0 && (
        <div className="card" style={{ borderColor: 'var(--warning)', marginBottom: 16 }}>
          <strong>Data getting stale:</strong>{' '}
          {stale.map((s) => `${s.name} (${s.age_days ?? '—'}d)`).join(', ')} —{' '}
          <Link to="/import">import fresh exports</Link>.
        </div>
      )}

      <div className="grid cols-3">
        <Tile label="Cash on hand" value={money(cash)} detail="checking + savings" />
        <Tile
          label="Card balances"
          value={money(cardDebt)}
          detail="credit accounts, as of last import"
        />
        <Tile
          label={`Spent in ${month}`}
          value={money(budget?.total_spent_cents ?? pulse?.spent_cents ?? null)}
          detail={
            budget
              ? `${pct(pulse?.pct_budget ?? null)} of ${money(budget.total_budget_cents)} budget`
              : 'no budget yet'
          }
        />
      </div>

      <div className="grid cols-2" style={{ marginTop: 16, alignItems: 'start' }}>
        <div className="card">
          <div className="spread">
            <h2>Budget — {month}</h2>
            <Link className="small" to="/budget">
              Full budget →
            </Link>
          </div>
          {!budget && <Empty>No budget for this month. Draft one on the Budget page.</Empty>}
          {budget &&
            budget.lines.slice(0, 8).map((line) => (
              <div key={line.category_id} style={{ marginBottom: 10 }}>
                <div className="spread small" style={{ marginBottom: 3 }}>
                  <span>{line.category_name}</span>
                  <span className="mono muted">
                    {money(line.spent_cents)} / {money(line.budget_cents)}
                  </span>
                </div>
                <Meter frac={line.pct} />
              </div>
            ))}
        </div>

        <div className="stack">
          <div className="card">
            <div className="spread">
              <h2>Accounts</h2>
              <Link className="small" to="/settings">
                Manage →
              </Link>
            </div>
            {accounts.length === 0 && <Empty>Add accounts in Settings.</Empty>}
            <table className="data">
              <tbody>
                {accounts
                  .filter((a) => !a.archived)
                  .map((a) => (
                    <tr key={a.id}>
                      <td>
                        {a.name}
                        <div className="small muted">{a.institution}</div>
                      </td>
                      <td className="num">
                        <Money cents={a.latest_balance?.balance_cents ?? null} />
                        <div className="small muted">{a.latest_balance?.as_of ?? 'no data'}</div>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>

          <div className="card">
            <h2>Recent transfers</h2>
            {transfers.length === 0 && <Empty>No linked transfers yet.</Empty>}
            {transfers.map((t) => (
              <div key={t.id} className="spread small" style={{ padding: '4px 0' }}>
                <span>
                  <span className="mono">{money(t.amount_cents)}</span> from{' '}
                  <strong>{t.from_account}</strong> to <strong>{t.to_account}</strong>
                </span>
                <span className="muted">{t.posted_at}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="spread">
          <h2>Latest transactions</h2>
          <Link className="small" to="/transactions">
            All transactions →
          </Link>
        </div>
        {recent && recent.transactions.length === 0 && (
          <Empty>Nothing imported yet — start on the Import page.</Empty>
        )}
        <table className="data">
          <tbody>
            {recent?.transactions.map((t) => (
              <tr key={t.id}>
                <td className="muted small" style={{ width: 90 }}>
                  {t.posted_at}
                </td>
                <td>{t.payee_raw}</td>
                <td>
                  {t.splits.length > 0 ? (
                    <span className="chip accent">split ×{t.splits.length}</span>
                  ) : t.category_name ? (
                    <span className="chip">{t.category_name}</span>
                  ) : (
                    <span className="chip warn">uncategorized</span>
                  )}
                </td>
                <td className="num">
                  <Money cents={t.amount_cents} sign />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
