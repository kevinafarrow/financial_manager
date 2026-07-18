// Typed API client. All mutating calls carry the CSRF header; 423 (locked)
// and 401 (unauthenticated) bubble up as typed errors the shell reacts to.

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

type Query = Record<string, string | number | boolean | undefined>

async function request<T>(
  method: string,
  path: string,
  opts: { body?: unknown; query?: Query; form?: FormData } = {},
): Promise<T> {
  let url = path
  if (opts.query) {
    const params = new URLSearchParams()
    for (const [k, v] of Object.entries(opts.query)) {
      if (v !== undefined && v !== '') params.set(k, String(v))
    }
    const qs = params.toString()
    if (qs) url += `?${qs}`
  }
  const headers: Record<string, string> = { 'X-Requested-With': 'XMLHttpRequest' }
  let body: BodyInit | undefined
  if (opts.form) {
    body = opts.form
  } else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  const resp = await fetch(url, { method, headers, body, credentials: 'same-origin' })
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const data = await resp.json()
      if (typeof data.detail === 'string') detail = data.detail
      else if (data.detail) detail = JSON.stringify(data.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, detail)
  }
  if (resp.status === 204) return undefined as T
  return resp.json()
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>('GET', path, { query }),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, { body }),
  postForm: <T>(path: string, form: FormData) => request<T>('POST', path, { form }),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, { body }),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, { body }),
  delete: <T>(path: string) => request<T>('DELETE', path),
}

// ---- shared formatting helpers ----

export function money(cents: number | null | undefined, opts?: { sign?: boolean }): string {
  if (cents === null || cents === undefined) return '—'
  const dollars = Math.abs(cents) / 100
  const s = dollars.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
  })
  if (cents < 0) return `-${s}`
  return opts?.sign ? `+${s}` : s
}

export function pct(x: number | null | undefined): string {
  if (x === null || x === undefined) return '—'
  return `${Math.round(x * 100)}%`
}

export function currentMonth(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

export function shiftMonth(month: string, delta: number): string {
  const y = parseInt(month.slice(0, 4), 10)
  const m = parseInt(month.slice(5, 7), 10)
  const total = y * 12 + (m - 1) + delta
  const ny = Math.floor(total / 12)
  const nm = (total % 12) + 1
  return `${String(ny).padStart(4, '0')}-${String(nm).padStart(2, '0')}`
}
