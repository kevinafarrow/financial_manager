import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api'
import type { Account, ImportResult, Staleness } from '../types'
import { Empty, toast } from '../components/ui'

interface HistoryRow {
  id: number
  filename: string
  account_name: string
  format: string
  tx_count: number
  dup_count: number
  imported_at: string
}

export default function ImportPage({ onImported }: { onImported: () => void }) {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [accountId, setAccountId] = useState('')
  const [history, setHistory] = useState<HistoryRow[]>([])
  const [staleness, setStaleness] = useState<Staleness[]>([])
  const [drag, setDrag] = useState(false)
  const [busy, setBusy] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  const refresh = useCallback(() => {
    void api.get<HistoryRow[]>('/api/imports').then(setHistory)
    void api.get<Staleness[]>('/api/imports/staleness').then(setStaleness)
  }, [])

  useEffect(() => {
    void api.get<Account[]>('/api/accounts').then((a) => {
      setAccounts(a.filter((x) => !x.archived))
      if (a.length > 0) setAccountId(String(a[0].id))
    })
    refresh()
  }, [refresh])

  const upload = async (files: FileList | File[]) => {
    if (!accountId) return toast('Pick an account first', true)
    setBusy(true)
    for (const file of Array.from(files)) {
      const form = new FormData()
      form.set('account_id', accountId)
      form.set('file', file)
      try {
        const r = await api.postForm<ImportResult>('/api/imports/upload', form)
        toast(
          `${file.name}: ${r.imported} imported, ${r.duplicates} duplicates` +
            (r.balance_recorded ? ', balance updated' : ''),
        )
      } catch (e) {
        toast(`${file.name}: ${e instanceof ApiError ? e.message : 'failed'}`, true)
      }
    }
    setBusy(false)
    refresh()
    onImported()
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Import</h1>
          <div className="sub">Drop OFX / QFX / CSV exports from your banks. Re-uploads are deduplicated.</div>
        </div>
      </div>

      <div className="card">
        <label className="field" style={{ maxWidth: 320 }}>
          <span className="lbl">Import into account</span>
          <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.institution || a.type})
              </option>
            ))}
          </select>
        </label>
        <div
          className={`dropzone${drag ? ' drag' : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            setDrag(true)
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDrag(false)
            void upload(e.dataTransfer.files)
          }}
          onClick={() => fileInput.current?.click()}
        >
          {busy ? 'Uploading…' : 'Drop bank files here, or click to browse'}
          <input
            ref={fileInput}
            type="file"
            multiple
            accept=".ofx,.qfx,.qbo,.csv"
            style={{ display: 'none' }}
            onChange={(e) => {
              if (e.target.files?.length) void upload(e.target.files)
              e.target.value = ''
            }}
          />
        </div>
      </div>

      <div className="grid cols-2" style={{ marginTop: 16, alignItems: 'start' }}>
        <div className="card">
          <h2>Data freshness</h2>
          <table className="data">
            <tbody>
              {staleness.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td className="num">
                    {s.age_days === null ? (
                      <span className="chip warn">no data</span>
                    ) : s.stale ? (
                      <span className="chip crit">{s.age_days}d old</span>
                    ) : (
                      <span className="chip good">{s.age_days}d</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h2>Import history</h2>
          {history.length === 0 && <Empty>No imports yet.</Empty>}
          <table className="data">
            <tbody>
              {history.slice(0, 12).map((h) => (
                <tr key={h.id}>
                  <td>
                    {h.filename}
                    <div className="small muted">
                      {h.account_name} · {h.imported_at}
                    </div>
                  </td>
                  <td className="num small">
                    {h.tx_count} new
                    {h.dup_count > 0 && <span className="muted"> / {h.dup_count} dup</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
