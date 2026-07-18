import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api'
import type { ChatMessage, ChatThread } from '../types'
import { Empty, toast } from '../components/ui'

export default function Chat() {
  const [threads, setThreads] = useState<ChatThread[]>([])
  const [threadId, setThreadId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const logRef = useRef<HTMLDivElement>(null)

  const loadThreads = useCallback(async () => {
    const t = await api.get<ChatThread[]>('/api/chat/threads')
    setThreads(t)
    return t
  }, [])

  useEffect(() => {
    void loadThreads()
  }, [loadThreads])

  useEffect(() => {
    if (threadId === null) return setMessages([])
    void api
      .get<{ messages: ChatMessage[] }>(`/api/chat/threads/${threadId}`)
      .then((t) => setMessages(t.messages))
  }, [threadId])

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight })
  }, [messages, busy])

  const send = async (e: React.FormEvent) => {
    e.preventDefault()
    const text = input.trim()
    if (!text || busy) return
    setBusy(true)
    setInput('')
    try {
      let tid = threadId
      if (tid === null) {
        const t = await api.post<ChatThread>('/api/chat/threads')
        tid = t.id
        setThreadId(tid)
      }
      setMessages((m) => [
        ...m,
        { id: -1, role: 'user', text, created_at: '' },
      ])
      const r = await api.post<{ reply: string }>(`/api/chat/threads/${tid}/messages`, { text })
      setMessages((m) => [...m, { id: -2, role: 'assistant', text: r.reply, created_at: '' }])
      void loadThreads()
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Send failed', true)
    } finally {
      setBusy(false)
    }
  }

  const removeThread = async (id: number) => {
    await api.delete(`/api/chat/threads/${id}`)
    if (id === threadId) setThreadId(null)
    void loadThreads()
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Chat</h1>
          <div className="sub">
            Ask Claude about your transactions — it queries the database with tools, so answers
            are grounded in your real data.
          </div>
        </div>
        <button className="btn" onClick={() => setThreadId(null)}>
          + New chat
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 16, alignItems: 'start' }}>
        <div className="card" style={{ padding: 10 }}>
          {threads.length === 0 && <div className="empty small">No chats yet</div>}
          {threads.map((t) => (
            <div key={t.id} className="spread" style={{ gap: 4 }}>
              <button
                className={`navlink${t.id === threadId ? ' active' : ''}`}
                style={{ overflow: 'hidden' }}
                onClick={() => setThreadId(t.id)}
              >
                <span className="label" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {t.title}
                </span>
              </button>
              <button className="btn sm" title="Delete" onClick={() => void removeThread(t.id)}>
                ✕
              </button>
            </div>
          ))}
        </div>

        <div className="card" style={{ display: 'flex', flexDirection: 'column', minHeight: 480 }}>
          <div ref={logRef} className="chat-log" style={{ flex: 1, overflowY: 'auto', maxHeight: '60vh' }}>
            {messages.length === 0 && !busy && (
              <Empty>
                Try: “How much did we spend eating out last month?” or “Any subscriptions that
                crept up this year?”
              </Empty>
            )}
            {messages.map((m, i) => (
              <div key={`${m.id}-${i}`} className={`msg ${m.role}`}>
                {m.text}
              </div>
            ))}
            {busy && <div className="msg assistant muted">Looking at your data…</div>}
          </div>
          <form className="row" onSubmit={send}>
            <input
              placeholder="Ask about your finances…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={busy}
            />
            <button className="btn primary" disabled={busy || !input.trim()}>
              Send
            </button>
          </form>
        </div>
      </div>
    </>
  )
}
