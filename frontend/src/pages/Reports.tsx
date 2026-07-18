import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, currentMonth, money, shiftMonth } from '../api'
import type { AlertLogRow, MonthlyReport } from '../types'
import { Empty, Money, Tile } from '../components/ui'

export default function Reports() {
  const { month: routeMonth } = useParams()
  const [month, setMonth] = useState(routeMonth ?? currentMonth())
  const [report, setReport] = useState<MonthlyReport | null>(null)
  const [alerts, setAlerts] = useState<AlertLogRow[]>([])

  useEffect(() => {
    if (routeMonth) setMonth(routeMonth)
  }, [routeMonth])

  useEffect(() => {
    void api.get<MonthlyReport>(`/api/reports/monthly/${month}`).then(setReport)
    void api.get<AlertLogRow[]>('/api/reports/alerts').then(setAlerts)
  }, [month])

  const maxSpent = Math.max(1, ...(report?.categories.map((c) => c.spent_cents) ?? [1]))

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Reports</h1>
          <div className="sub">Where the money went, and how it compares to last month.</div>
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

      {report && (
        <>
          <div className="grid cols-3">
            <Tile label="Income" value={money(report.income_cents)} />
            <Tile label="Spending" value={money(report.total_spent_cents)} />
            <Tile
              label="Net"
              value={<Money cents={report.net_cents} sign />}
              detail={
                report.savings_goal_cents
                  ? `savings goal ${money(report.savings_goal_cents)} — ${
                      report.net_cents >= report.savings_goal_cents ? 'met ✓' : 'missed'
                    }`
                  : undefined
              }
            />
          </div>

          <div className="card" style={{ marginTop: 16 }}>
            <h2>Spending by category</h2>
            {report.categories.length === 0 && <Empty>No categorized spending this month.</Empty>}
            {report.categories.map((c) => (
              <div className="hbar-row" key={c.category_id}>
                <span className="lbl">{c.category_name}</span>
                <div className="hbar-track">
                  <i style={{ width: `${(c.spent_cents / maxSpent) * 100}%` }} />
                </div>
                <span className="val">
                  {money(c.spent_cents)}
                  {c.delta_cents !== 0 && (
                    <span className={c.delta_cents > 0 ? '' : 'pos'}>
                      {' '}
                      {c.delta_cents > 0 ? '▲' : '▼'}
                      {money(Math.abs(c.delta_cents))}
                    </span>
                  )}
                </span>
              </div>
            ))}
            <div className="small muted" style={{ marginTop: 6 }}>
              ▲/▼ show the change vs the previous month.
            </div>
          </div>
        </>
      )}

      <div className="card" style={{ marginTop: 16 }}>
        <h2>Alert history</h2>
        {alerts.length === 0 && <Empty>No alerts sent yet.</Empty>}
        <table className="data">
          <tbody>
            {alerts.slice(0, 20).map((a) => {
              let title = a.type
              try {
                title = (JSON.parse(a.payload_json) as { title?: string }).title ?? a.type
              } catch {
                /* raw type is fine */
              }
              return (
                <tr key={a.id}>
                  <td className="small muted" style={{ width: 150 }}>
                    {a.created_at}
                  </td>
                  <td>
                    <span className="chip">{a.type}</span> {title}
                  </td>
                  <td className="num small">{a.ok ? 'delivered' : 'logged only'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}
