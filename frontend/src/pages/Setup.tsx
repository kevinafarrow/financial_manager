import { useState } from 'react'
import { ApiError, api } from '../api'

export default function Setup({ onDone }: { onDone: () => void }) {
  const [passphrase, setPassphrase] = useState('')
  const [passphrase2, setPassphrase2] = useState('')
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (passphrase !== passphrase2) return setError('Passphrases do not match')
    setBusy(true)
    setError('')
    try {
      await api.post('/api/system/setup', {
        passphrase,
        username,
        display_name: displayName || username,
        password,
      })
      onDone()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Setup failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-wrap">
      <form className="card auth-card" onSubmit={submit}>
        <div className="brand">
          <span className="dot" /> First-run setup
        </div>
        <p className="small muted">
          The master passphrase encrypts everything (SQLCipher + vault). It cannot be
          recovered — store it in your password manager. You&apos;ll enter it once after
          each container restart.
        </p>
        <label className="field">
          <span className="lbl">Master passphrase (min 10 chars)</span>
          <input type="password" value={passphrase} onChange={(e) => setPassphrase(e.target.value)} minLength={10} required autoFocus />
        </label>
        <label className="field">
          <span className="lbl">Confirm passphrase</span>
          <input type="password" value={passphrase2} onChange={(e) => setPassphrase2(e.target.value)} required />
        </label>
        <hr style={{ border: 'none', borderTop: '1px solid var(--grid)', margin: '16px 0' }} />
        <label className="field">
          <span className="lbl">Your username</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} required />
        </label>
        <label className="field">
          <span className="lbl">Display name</span>
          <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder={username} />
        </label>
        <label className="field">
          <span className="lbl">Login password (min 8 chars)</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required />
        </label>
        {error && <p className="error-text">{error}</p>}
        <button className="btn primary" disabled={busy} style={{ width: '100%', justifyContent: 'center' }}>
          {busy ? 'Setting up…' : 'Create vault'}
        </button>
      </form>
    </div>
  )
}
