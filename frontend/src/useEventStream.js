/**
 * Subscribes to the backend WebSocket and keeps events, chunk statuses,
 * session summaries, brand-safety alerts, live chat and demo thank-you alerts
 * in React state. Events are updated
 * in place by event_id (pending verification -> tipped / rejected).
 * Reconnects automatically.
 */
import { useEffect, useState } from 'react'

export function useEventStream() {
  const [events, setEvents] = useState([])
  const [chunks, setChunks] = useState({})
  const [sessions, setSessions] = useState({})
  const [safety, setSafety] = useState([])
  const [chat, setChat] = useState({}) // session_id -> recent messages
  const [alerts, setAlerts] = useState({}) // session_id -> latest thank-you alert
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    let ws
    let closed = false
    let retry

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws/events`)
      ws.onopen = () => {
        // The server re-sends every live session and recent chat on connect,
        // so drop anything left over from before a backend restart.
        setSessions({})
        setChat({})
        setConnected(true)
      }
      ws.onclose = () => {
        setConnected(false)
        if (!closed) retry = setTimeout(connect, 1500)
      }
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data)
        if (msg.type === 'event') {
          const ev = { ...msg.data, tipped: msg.tipped }
          setEvents((prev) => {
            const i = prev.findIndex((p) => p.event_id === ev.event_id)
            if (i === -1) return [ev, ...prev].slice(0, 200)
            const next = [...prev]
            next[i] = ev
            return next
          })
        } else if (msg.type === 'chat') {
          const c = msg.data
          setChat((prev) => ({ ...prev, [c.session_id]: [...(prev[c.session_id] || []), c].slice(-40) }))
        } else if (msg.type === 'alert') {
          const a = { ...msg.data, received_at: Date.now() }
          setAlerts((prev) => ({
            ...prev,
            [a.session_id]: prev[a.session_id]?.event_id === a.event_id
              ? { ...a, received_at: prev[a.session_id].received_at }
              : a,
          }))
        } else if (msg.type === 'safety') {
          setSafety((prev) => [{ ...msg.data, at: Date.now() }, ...prev].slice(0, 50))
        } else if (msg.type === 'chunk') {
          const c = msg.data
          setChunks((prev) => ({ ...prev, [`${c.session_id}:${c.chunk_index}`]: c }))
        } else if (msg.type === 'session') {
          setSessions((prev) => ({ ...prev, [msg.data.id]: msg.data }))
        } else if (msg.type === 'session_stopped') {
          setSessions((prev) => {
            const next = { ...prev }
            delete next[msg.data.id]
            return next
          })
        }
      }
    }

    fetch('/api/events')
      .then((r) => r.json())
      .then((recent) => setEvents(recent.map((m) => ({ ...m.data, tipped: m.tipped })).reverse()))
      .catch(() => {})
    connect()
    return () => {
      closed = true
      clearTimeout(retry)
      ws?.close()
    }
  }, [])

  return { events, chunks, sessions, safety, chat, alerts, connected }
}
