import { useCallback, useEffect, useState } from 'react'
import { ApiError, api, currentMonth, money, shiftMonth } from '../api'
import type { BudgetProgress, SavingsGoal } from '../types'
import { Empty, Meter, Money, StatusChip, toast } from '../components/ui'

export default function Budget() {
  const [month, setMonth] = useState(currentMonth())
  const [budget, setBudget] = useState<BudgetProgress | null>(null)
  const [goals, setGoals] = useState<SavingsGoal[]>([])
  const [edits, setEdits] = useState<Record<number, string>>({})
  const [missing, setMissing] = useState(false)

  const refresh = useCallback(async (m: string) => {
    setEdits({})
    try {
      setBudget(await api.get<BudgetProgress>(`/api/budgets/${m}`))
      setMissing(false)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setBudget(null)
        setMissing(true)
      }
    }
    setGoals(await api.get<SavingsGoal[]>('/api/savings-goals'))
  }, [])

  useEffect(() => {
    void refresh(month)
  }, [month, refresh])

  const draft = async () => {
    try {
      setBudget(await api.post<BudgetProgress>(`/api/budgets/${month}/draft`))
      setMissing(false)
      toast('Draft generated from your last three months of spending.')
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Draft failed', true)
    }
  }

  const saveEdits = async () => {
    if (!budget) return
    const lines = budget.lines.map((l) => ({
      category_id: l.category_id,
      amount_cents: edits[l.category_id] !== undefined
        ? Math.round(parseFloat(edits[l.category_id] || '0') * 100)
        : l.budget_cents,
    }))
    try {
      setBudget(await api.put<BudgetProgress>(`/api/budgets/${budget.budget_id}/lines`, { lines }))
      setEdits({})
      toast('Budget lines saved.')
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Save failed', true)
    }
  }

  const approve = async () => {
    if (!budget) return
    try {
      setBudget(await api.post<BudgetProgress>(`/api/budgets/${budget.budget_id}/approve`))
      toast('Budget approved — progress alerts now measure against it.')
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Approve failed', true)
    }
  }

  const reasoningFor = (categoryId: number): string => {
    const r = budget?.reasoning?.[String(categoryId)] as
      | { weighted_avg_cents?: number; months?: Record<string, number> }
      | undefined
    if (!r) return ''
    const months = Object.entries(r.months ?? {})
      .map(([m, c]) => `${m}: ${money(c)}`)
      .join(' · ')
    return `3-mo weighted avg ${money(r.weighted_avg_cents ?? null)} (${months})`
  }

  const goalTotal = goals.filter((g) => g.enabled).reduce((s, g) => s + g.monthly_cents, 0)
  const dirty = Object.keys(edits).length > 0

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Budget</h1>
          <div className="sub">
            Drafted from a weighted average of the prior three months, fitted around your savings
            goals. You approve it; alerts measure against the approved version.
          </div>
        </div>
        <div className="btn-row">
          <button className="btn sm" onClick={() => setMonth(shiftMonth(month, -1))}>
            ←
          </button>
          <strong>{month}</strong>
          <button className="btn sm" onClick={() => setMonth(shiftMonth(month, 1))}>
            →
          </button>
        </div>
      </div>

      {missing && (
        <div className="card">
          <Empty>
            No budget for {month} yet.
            <div style={{ marginTop: 12 }}>
              <button className="btn primary" onClick={() => void draft()}>
                Draft from spending history
              </button>
            </div>
          </Empty>
        </div>
      )}

      {budget && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="spread">
              <div className="row">
                <StatusChip status={budget.status} />
                <span className="small muted">
                  {money(budget.total_budget_cents)} budgeted · {money(budget.total_spent_cents)}{' '}
                  spent · income {money(budget.income_cents)}
                </span>
              </div>
              <div className="btn-row">
                {budget.status === 'draft' && (
                  <>
                    <button className="btn" onClick={() => void draft()}>
                      Re-draft
                    </button>
                    {dirty && (
                      <button className="btn" onClick={() => void saveEdits()}>
                        Save edits
                      </button>
                    )}
                    <button className="btn primary" disabled={dirty} onClick={() => void approve()}>
                      Approve budget
                    </button>
                  </>
                )}
              </div>
            </div>
            {goalTotal > 0 && (
              <div className="small muted" style={{ marginTop: 8 }}>
                Savings goals reserve {money(goalTotal)}/month:{' '}
                {goals.filter((g) => g.enabled).map((g) => `${g.name} ${money(g.monthly_cents)}`).join(', ')}
              </div>
            )}
          </div>

          <div className="card">
            <table className="data">
              <thead>
                <tr>
                  <th>Category</th>
                  <th style={{ width: '30%' }}>Progress</th>
                  <th className="num">Spent</th>
                  <th className="num">Cap</th>
                  <th className="num">Left</th>
                </tr>
              </thead>
              <tbody>
                {budget.lines.map((l) => (
                  <tr key={l.category_id}>
                    <td>
                      {l.category_name}
                      <div className="small muted">{reasoningFor(l.category_id)}</div>
                    </td>
                    <td>
                      <Meter frac={l.pct} />
                    </td>
                    <td className="num mono">{money(l.spent_cents)}</td>
                    <td className="num">
                      {budget.status === 'draft' ? (
                        <input
                          style={{ width: 90, textAlign: 'right' }}
                          value={edits[l.category_id] ?? (l.budget_cents / 100).toFixed(2)}
                          onChange={(e) =>
                            setEdits({ ...edits, [l.category_id]: e.target.value })
                          }
                        />
                      ) : (
                        <span className="mono">{money(l.budget_cents)}</span>
                      )}
                    </td>
                    <td className="num">
                      <Money cents={l.remaining_cents} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {budget.unbudgeted.length > 0 && (
              <div className="small muted" style={{ marginTop: 12 }}>
                Unbudgeted spending:{' '}
                {budget.unbudgeted.map((u) => `${u.category_name} ${money(u.spent_cents)}`).join(', ')}
              </div>
            )}
          </div>
        </>
      )}

      <GoalsCard goals={goals} onChanged={() => void refresh(month)} />
    </>
  )
}

function GoalsCard({ goals, onChanged }: { goals: SavingsGoal[]; onChanged: () => void }) {
  const [name, setName] = useState('')
  const [amount, setAmount] = useState('')

  const add = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await api.post('/api/savings-goals', {
        name,
        monthly_cents: Math.round(parseFloat(amount) * 100),
      })
      setName('')
      setAmount('')
      onChanged()
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Failed', true)
    }
  }

  const toggle = async (g: SavingsGoal) => {
    await api.patch(`/api/savings-goals/${g.id}`, { enabled: !g.enabled })
    onChanged()
  }

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2>Savings goals</h2>
      {goals.map((g) => (
        <div key={g.id} className="spread small" style={{ padding: '4px 0' }}>
          <span className={g.enabled ? '' : 'muted'}>
            {g.name} — {money(g.monthly_cents)}/month
          </span>
          <button className="btn sm" onClick={() => void toggle(g)}>
            {g.enabled ? 'Disable' : 'Enable'}
          </button>
        </div>
      ))}
      <form className="row" style={{ marginTop: 10 }} onSubmit={add}>
        <input placeholder="Goal name" value={name} onChange={(e) => setName(e.target.value)} required />
        <input
          type="number"
          step="0.01"
          min="0.01"
          placeholder="$/month"
          style={{ width: 120 }}
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          required
        />
        <button className="btn">Add goal</button>
      </form>
    </div>
  )
}
