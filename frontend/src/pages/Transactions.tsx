import { useCallback, useEffect, useState } from 'react'
import { ApiError, api, money } from '../api'
import type { Account, Category, Tx, TxSearch } from '../types'
import { Empty, Money, toast } from '../components/ui'

const PAGE = 50

export default function Transactions() {
  const [q, setQ] = useState('')
  const [useRegex, setUseRegex] = useState(false)
  const [accountId, setAccountId] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [offset, setOffset] = useState(0)
  const [result, setResult] = useState<TxSearch | null>(null)
  const [error, setError] = useState('')
  const [accounts, setAccounts] = useState<Account[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [editing, setEditing] = useState<Tx | null>(null)

  useEffect(() => {
    void api.get<Account[]>('/api/accounts').then(setAccounts)
    void api.get<Category[]>('/api/categories').then(setCategories)
  }, [])

  const search = useCallback(
    async (newOffset = 0) => {
      try {
        setError('')
        const r = await api.get<TxSearch>('/api/transactions', {
          q: q || undefined,
          regex: useRegex || undefined,
          account_id: accountId || undefined,
          category_id: categoryId || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          limit: PAGE,
          offset: newOffset,
        })
        setResult(r)
        setOffset(newOffset)
      } catch (e) {
        setError(e instanceof ApiError ? e.message : 'Search failed')
      }
    },
    [q, useRegex, accountId, categoryId, dateFrom, dateTo],
  )

  useEffect(() => {
    void search(0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, categoryId, dateFrom, dateTo, useRegex])

  const setCategory = async (tx: Tx, categoryId: number) => {
    try {
      await api.post(`/api/transactions/${tx.id}/category`, { category_id: categoryId })
      toast('Category updated — the pipeline will remember this merchant.')
      setEditing(null)
      void search(offset)
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Update failed', true)
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Transactions</h1>
          <div className="sub">{result ? `${result.total} matching` : ''}</div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <form
          className="row"
          style={{ flexWrap: 'wrap' }}
          onSubmit={(e) => {
            e.preventDefault()
            void search(0)
          }}
        >
          <div style={{ flex: '2 1 260px' }}>
            <input
              placeholder={useRegex ? String.raw`Regex, e.g. COSTCO|WHOLEFDS or ^AMZN.*\d{4}$` : 'Search payee or memo…'}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <label className="row small" style={{ gap: 6 }}>
            <input type="checkbox" style={{ width: 'auto' }} checked={useRegex} onChange={(e) => setUseRegex(e.target.checked)} />
            regex
          </label>
          <select style={{ flex: '1 1 140px' }} value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            <option value="">All accounts</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
          <select style={{ flex: '1 1 140px' }} value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
            <option value="">All categories</option>
            {categories
              .filter((c) => !c.archived)
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
          </select>
          <input type="date" style={{ flex: '0 1 150px' }} value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          <input type="date" style={{ flex: '0 1 150px' }} value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          <button className="btn primary">Search</button>
        </form>
        {error && <p className="error-text" style={{ marginBottom: 0 }}>{error}</p>}
      </div>

      <div className="card">
        {result && result.transactions.length === 0 && <Empty>No transactions match.</Empty>}
        <table className="data">
          <thead>
            <tr>
              <th>Date</th>
              <th>Payee</th>
              <th>Account</th>
              <th>Category</th>
              <th className="num">Amount</th>
            </tr>
          </thead>
          <tbody>
            {result?.transactions.map((t) => {
              // a transfer renders once, on its outgoing leg
              if (t.transfer_id && t.is_transfer_in) return null
              if (t.transfer_id) {
                return (
                  <tr key={t.id}>
                    <td className="muted small">{t.posted_at}</td>
                    <td colSpan={3}>
                      <span className="chip accent">transfer</span>{' '}
                      <span className="mono">{money(Math.abs(t.amount_cents))}</span> from{' '}
                      <strong>{t.account_name}</strong> to <strong>{t.transfer_peer_account}</strong>
                    </td>
                    <td className="num mono">{money(Math.abs(t.amount_cents))}</td>
                  </tr>
                )
              }
              return (
                <tr key={t.id} className="clickable" onClick={() => setEditing(t)}>
                  <td className="muted small">{t.posted_at}</td>
                  <td>
                    {t.payee_raw}
                    {t.memo && <div className="small muted">{t.memo}</div>}
                  </td>
                  <td className="small muted">{t.account_name}</td>
                  <td>
                    {t.splits.length > 0 ? (
                      <span title={t.splits.map((s) => `${s.category_name}: ${money(Math.abs(s.amount_cents))}`).join(', ')} className="chip accent">
                        split ×{t.splits.length}
                      </span>
                    ) : t.category_name ? (
                      <span className="chip">{t.category_name}</span>
                    ) : (
                      <span className="chip warn">uncategorized</span>
                    )}
                    {t.cat_source !== 'none' && t.splits.length === 0 && (
                      <span className="small muted" style={{ marginLeft: 6 }}>
                        via {t.cat_source}
                      </span>
                    )}
                  </td>
                  <td className="num">
                    <Money cents={t.amount_cents} sign />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {result && result.total > PAGE && (
          <div className="btn-row" style={{ marginTop: 12, justifyContent: 'center' }}>
            <button className="btn sm" disabled={offset === 0} onClick={() => void search(Math.max(0, offset - PAGE))}>
              ← Newer
            </button>
            <span className="small muted">
              {offset + 1}–{Math.min(offset + PAGE, result.total)} of {result.total}
            </span>
            <button className="btn sm" disabled={offset + PAGE >= result.total} onClick={() => void search(offset + PAGE)}>
              Older →
            </button>
          </div>
        )}
      </div>

      {editing && (
        <CategoryEditor
          tx={editing}
          categories={categories.filter((c) => !c.archived && c.kind !== 'system')}
          onPick={(cid) => void setCategory(editing, cid)}
          onClose={() => setEditing(null)}
        />
      )}
    </>
  )
}

function CategoryEditor({
  tx,
  categories,
  onPick,
  onClose,
}: {
  tx: Tx
  categories: Category[]
  onPick: (categoryId: number) => void
  onClose: () => void
}) {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.4)',
        display: 'grid',
        placeItems: 'center',
        zIndex: 40,
      }}
      onClick={onClose}
    >
      <div className="card" style={{ width: 420, maxHeight: '80vh', overflowY: 'auto' }} onClick={(e) => e.stopPropagation()}>
        <div className="spread">
          <h2 style={{ marginBottom: 4 }}>{tx.payee_raw}</h2>
          <button className="btn sm" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="small muted" style={{ marginBottom: 12 }}>
          {tx.posted_at} · {money(tx.amount_cents)} · {tx.account_name}
        </div>
        <div className="btn-row">
          {categories.map((c) => (
            <button
              key={c.id}
              className={`btn sm${c.id === tx.category_id ? ' primary' : ''}`}
              onClick={() => onPick(c.id)}
            >
              {c.name}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
