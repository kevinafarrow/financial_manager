import { useCallback, useEffect, useState } from 'react'
import { ApiError, api, money } from '../api'
import type { Category, Receipt, TransferCandidate, Tx } from '../types'
import { Empty, Money, StatusChip, toast } from '../components/ui'

type Tab = 'queue' | 'transfers' | 'receipts'

export default function Review({ onChanged }: { onChanged: () => void }) {
  const [tab, setTab] = useState<Tab>('queue')
  const [queue, setQueue] = useState<Tx[]>([])
  const [candidates, setCandidates] = useState<TransferCandidate[]>([])
  const [receipts, setReceipts] = useState<Receipt[]>([])
  const [categories, setCategories] = useState<Category[]>([])

  const refresh = useCallback(() => {
    void api.get<Tx[]>('/api/queue', { limit: 200 }).then(setQueue)
    void api.get<TransferCandidate[]>('/api/transfers/candidates').then(setCandidates)
    void api.get<Receipt[]>('/api/receipts').then(setReceipts)
    onChanged()
  }, [onChanged])

  useEffect(() => {
    void api.get<Category[]>('/api/categories').then(setCategories)
    refresh()
  }, [refresh])

  const assign = async (txId: number, categoryId: number) => {
    try {
      await api.post(`/api/queue/${txId}`, { category_id: categoryId })
      toast('Categorized — this merchant is now learned.')
      refresh()
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Failed', true)
    }
  }

  const candidateAction = async (id: number, action: 'accept' | 'reject') => {
    try {
      await api.post(`/api/transfers/candidates/${id}/${action}`)
      refresh()
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Failed', true)
    }
  }

  const pollReceipts = async () => {
    try {
      const r = await api.post<{ fetched: number; accepted: number; quarantined: number }>('/api/receipts/poll')
      toast(`Fetched ${r.fetched} (accepted ${r.accepted}, quarantined ${r.quarantined})`)
      refresh()
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Poll failed', true)
    }
  }

  const receiptAction = async (id: number, action: 'process' | 'reject') => {
    try {
      await api.post(`/api/receipts/${id}/${action}`)
      refresh()
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Failed', true)
    }
  }

  const expenseCategories = categories.filter((c) => !c.archived && c.kind !== 'system')
  const pendingReceipts = receipts.filter((r) => r.status !== 'matched' && r.status !== 'rejected')

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Review</h1>
          <div className="sub">Everything the pipeline needs your judgment on.</div>
        </div>
      </div>

      <div className="tabs">
        <button className={`tab${tab === 'queue' ? ' active' : ''}`} onClick={() => setTab('queue')}>
          Categorize <span className="badge">{queue.length}</span>
        </button>
        <button className={`tab${tab === 'transfers' ? ' active' : ''}`} onClick={() => setTab('transfers')}>
          Transfers <span className="badge">{candidates.length}</span>
        </button>
        <button className={`tab${tab === 'receipts' ? ' active' : ''}`} onClick={() => setTab('receipts')}>
          Receipts <span className="badge">{pendingReceipts.length}</span>
        </button>
      </div>

      {tab === 'queue' && (
        <div className="stack">
          {queue.length === 0 && (
            <div className="card">
              <Empty>Queue is clear — everything categorized itself. 🎉</Empty>
            </div>
          )}
          {queue.map((t) => (
            <div className="card" key={t.id}>
              <div className="spread" style={{ marginBottom: 10 }}>
                <div>
                  <strong>{t.payee_raw}</strong>
                  {t.memo && <span className="muted"> · {t.memo}</span>}
                  <div className="small muted">
                    {t.posted_at} · {t.account_name}
                  </div>
                </div>
                <Money cents={t.amount_cents} sign />
              </div>
              <div className="btn-row">
                {expenseCategories.map((c) => (
                  <button key={c.id} className="btn sm" onClick={() => void assign(t.id, c.id)}>
                    {c.name}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === 'transfers' && (
        <div className="stack">
          {candidates.length === 0 && (
            <div className="card">
              <Empty>No transfer candidates awaiting review.</Empty>
            </div>
          )}
          {candidates.map((c) => (
            <div className="card" key={c.id}>
              <div className="spread">
                <div>
                  <div>
                    <span className="mono">{money(Math.abs(c.a_amount))}</span> from{' '}
                    <strong>{c.a_account}</strong> to <strong>{c.b_account}</strong>?
                  </div>
                  <div className="small muted">
                    {c.a_posted_at} “{c.a_payee}” → {c.b_posted_at} “{c.b_payee}” · score{' '}
                    {c.score.toFixed(2)}
                  </div>
                </div>
                <div className="btn-row">
                  <button className="btn sm primary" onClick={() => void candidateAction(c.id, 'accept')}>
                    Link as transfer
                  </button>
                  <button className="btn sm" onClick={() => void candidateAction(c.id, 'reject')}>
                    Not a transfer
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === 'receipts' && (
        <div className="stack">
          <div className="btn-row">
            <button className="btn" onClick={() => void pollReceipts()}>
              ↻ Poll mailbox now
            </button>
          </div>
          {receipts.length === 0 && (
            <div className="card">
              <Empty>No receipts yet. Forward one (with your token) to the receipts mailbox.</Empty>
            </div>
          )}
          {receipts.map((r) => (
            <div className="card" key={r.id}>
              <div className="spread">
                <div>
                  <strong>{r.subject || '(no subject)'}</strong>{' '}
                  <StatusChip status={r.status} />
                  <div className="small muted">
                    from {r.from_addr} · {r.received_at ?? r.created_at}
                  </div>
                  {r.reject_reason && <div className="small error-text">{r.reject_reason}</div>}
                  {r.parsed && (
                    <div className="small" style={{ marginTop: 6 }}>
                      {r.parsed.merchant} · {r.parsed.date} · {money(r.parsed.total_cents)} —{' '}
                      {r.parsed.items.map((i) => `${i.category} ${money(i.amount_cents)}`).join(', ')}
                    </div>
                  )}
                </div>
                <div className="btn-row">
                  {r.status === 'quarantined' && (
                    <button className="btn sm" onClick={() => void receiptAction(r.id, 'process')}>
                      Trust & parse
                    </button>
                  )}
                  {r.status === 'parsed' && <MatchButton receipt={r} onDone={refresh} />}
                  {r.status !== 'rejected' && r.status !== 'matched' && (
                    <button className="btn sm danger" onClick={() => void receiptAction(r.id, 'reject')}>
                      Reject
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  )
}

function MatchButton({ receipt, onDone }: { receipt: Receipt; onDone: () => void }) {
  const [candidates, setCandidates] = useState<Tx[] | null>(null)

  const load = async () => {
    setCandidates(await api.get<Tx[]>(`/api/receipts/${receipt.id}/candidates`))
  }

  const match = async (txId: number) => {
    try {
      await api.post(`/api/receipts/${receipt.id}/match`, { tx_id: txId })
      toast('Receipt applied — transaction split by category.')
      onDone()
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Match failed', true)
    }
  }

  if (candidates === null) {
    return (
      <button className="btn sm primary" onClick={() => void load()}>
        Match to transaction…
      </button>
    )
  }
  if (candidates.length === 0) {
    return <span className="small muted">no candidate transactions found</span>
  }
  return (
    <div className="btn-row">
      {candidates.map((t) => (
        <button key={t.id} className="btn sm" onClick={() => void match(t.id)}>
          {t.posted_at} · {t.payee_raw} · {money(t.amount_cents)}
        </button>
      ))}
    </div>
  )
}
