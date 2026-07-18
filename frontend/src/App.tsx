import { useCallback, useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { ApiError, api } from './api'
import type { SystemStatus, User } from './types'
import { applyTheme, initialTheme, type Theme } from './theme'
import { ToastHost } from './components/ui'
import Setup from './pages/Setup'
import Unlock from './pages/Unlock'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Transactions from './pages/Transactions'
import ImportPage from './pages/ImportPage'
import Review from './pages/Review'
import RecurringPage from './pages/RecurringPage'
import Budget from './pages/Budget'
import Reports from './pages/Reports'
import Chat from './pages/Chat'
import SettingsPage from './pages/SettingsPage'

type Phase = 'loading' | 'setup' | 'locked' | 'login' | 'ready'

export default function App() {
  const [phase, setPhase] = useState<Phase>('loading')
  const [user, setUser] = useState<User | null>(null)
  const [theme, setTheme] = useState<Theme>(initialTheme)
  const [queueCount, setQueueCount] = useState(0)

  const boot = useCallback(async () => {
    try {
      const status = await api.get<SystemStatus>('/api/system/status')
      if (status.setup_needed) return setPhase('setup')
      if (!status.unlocked) return setPhase('locked')
      try {
        setUser(await api.get<User>('/api/auth/me'))
        setPhase('ready')
      } catch (e) {
        if (e instanceof ApiError && (e.status === 401 || e.status === 423)) setPhase('login')
        else throw e
      }
    } catch {
      setPhase('loading')
      setTimeout(boot, 2000)
    }
  }, [])

  useEffect(() => {
    void boot()
  }, [boot])

  const refreshBadges = useCallback(async () => {
    try {
      const [queue, candidates] = await Promise.all([
        api.get<unknown[]>('/api/queue', { limit: 500 }),
        api.get<unknown[]>('/api/transfers/candidates'),
      ])
      setQueueCount(queue.length + candidates.length)
    } catch {
      /* badge only */
    }
  }, [])

  useEffect(() => {
    if (phase === 'ready') void refreshBadges()
  }, [phase, refreshBadges])

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    applyTheme(next)
  }

  if (phase === 'loading') {
    return (
      <div className="auth-wrap">
        <div className="muted">Connecting…</div>
      </div>
    )
  }
  if (phase === 'setup') return <Setup onDone={boot} />
  if (phase === 'locked') return <Unlock onDone={boot} />
  if (phase === 'login') return <Login onDone={boot} />

  const logout = async () => {
    try {
      await api.post('/api/auth/logout')
    } finally {
      setUser(null)
      void boot()
    }
  }

  const nav = [
    { to: '/', label: 'Dashboard', icon: '◧' },
    { to: '/transactions', label: 'Transactions', icon: '☰' },
    { to: '/review', label: 'Review', icon: '✓', badge: queueCount },
    { to: '/import', label: 'Import', icon: '⇪' },
    { to: '/budget', label: 'Budget', icon: '◔' },
    { to: '/reports', label: 'Reports', icon: '▤' },
    { to: '/recurring', label: 'Recurring', icon: '↻' },
    { to: '/chat', label: 'Chat', icon: '✦' },
    { to: '/settings', label: 'Settings', icon: '⚙' },
  ]

  return (
    <div className="shell">
      <nav className="sidebar">
        <div className="brand">
          <span className="dot" />
          <span>Family Finances</span>
        </div>
        {nav.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === '/'} className={({ isActive }) => `navlink${isActive ? ' active' : ''}`}>
            <span aria-hidden>{n.icon}</span>
            <span className="label">{n.label}</span>
            {n.badge ? <span className="badge">{n.badge}</span> : null}
          </NavLink>
        ))}
        <div className="foot">
          <button className="btn sm" onClick={toggleTheme}>
            {theme === 'dark' ? '☀ Light' : '☾ Dark'}
          </button>
          <div className="small muted">{user?.display_name}</div>
          <button className="btn sm" onClick={logout}>
            Sign out
          </button>
        </div>
      </nav>
      <main className="main">
        <div className="main-inner">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/transactions" element={<Transactions />} />
            <Route path="/review" element={<Review onChanged={refreshBadges} />} />
            <Route path="/import" element={<ImportPage onImported={refreshBadges} />} />
            <Route path="/budget" element={<Budget />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/reports/:month" element={<Reports />} />
            <Route path="/recurring" element={<RecurringPage />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </main>
      <ToastHost />
    </div>
  )
}
