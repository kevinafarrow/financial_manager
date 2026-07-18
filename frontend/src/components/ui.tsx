import { useEffect, useState, type ReactNode } from 'react'
import { money } from '../api'

export function Money({ cents, sign }: { cents: number | null | undefined; sign?: boolean }) {
  const cls = cents !== null && cents !== undefined && cents > 0 && sign ? 'pos mono' : 'mono'
  return <span className={cls}>{money(cents, { sign })}</span>
}

export function Tile({ label, value, detail }: { label: string; value: ReactNode; detail?: ReactNode }) {
  return (
    <div className="card tile">
      <div className="k">{label}</div>
      <div className="v">{value}</div>
      {detail !== undefined && <div className="d">{detail}</div>}
    </div>
  )
}

export function Meter({ frac }: { frac: number | null }) {
  if (frac === null) return <div className="meter" />
  const cls = frac >= 1 ? 'over' : frac >= 0.9 ? 'warn' : ''
  return (
    <div className="meter">
      <i className={cls} style={{ width: `${Math.min(frac, 1) * 100}%` }} />
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}

let toastListener: ((msg: string, isError: boolean) => void) | null = null

export function toast(msg: string, isError = false): void {
  toastListener?.(msg, isError)
}

export function ToastHost() {
  const [current, setCurrent] = useState<{ msg: string; err: boolean } | null>(null)
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>
    toastListener = (msg, err) => {
      setCurrent({ msg, err })
      clearTimeout(timer)
      timer = setTimeout(() => setCurrent(null), 4000)
    }
    return () => {
      toastListener = null
      clearTimeout(timer)
    }
  }, [])
  if (!current) return null
  return <div className={`toast${current.err ? ' err' : ''}`}>{current.msg}</div>
}

export function StatusChip({ status }: { status: string }) {
  const cls =
    status === 'confirmed' || status === 'matched' || status === 'approved'
      ? 'good'
      : status === 'proposed' || status === 'parsed' || status === 'draft'
        ? 'accent'
        : status === 'quarantined'
          ? 'crit'
          : ''
  return <span className={`chip ${cls}`}>{status}</span>
}
