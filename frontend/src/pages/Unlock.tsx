import { useState } from 'react'
import { ApiError, api } from '../api'

export default function Unlock({ onDone }: { onDone: () => void }) {
  const [passphrase, setPassphrase] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api.post('/api/system/unlock', { passphrase })
      onDone()
    } catch (err) {
      setError(err instanceof ApiError && err.status === 403 ? 'Wrong passphrase' : 'Unlock failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-wrap">
      <form className="card auth-card" onSubmit={submit}>
        <div className="brand">
          <span className="dot" /> Vault locked
        </div>
        <p className="small muted">
          The app restarted. Enter the master passphrase to decrypt the database and
          resume imports, polling, and alerts.
        </p>
        <label className="field">
          <span className="lbl">Master passphrase</span>
          <input type="password" value={passphrase} onChange={(e) => setPassphrase(e.target.value)} required autoFocus />
        </label>
        {error && <p className="error-text">{error}</p>}
        <button className="btn primary" disabled={busy} style={{ width: '100%', justifyContent: 'center' }}>
          {busy ? 'Unlocking…' : 'Unlock'}
        </button>
      </form>
    </div>
  )
}
