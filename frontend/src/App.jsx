/**
 * Monitor dashboard: watch several streams at once (stream URLs, webcam, or
 * screen-share), each as a tile, next to a combined feed of every beverage
 * moment Gemini flagged.
 */
import { useEffect, useRef, useState } from 'react'
import { useEventStream } from './useEventStream.js'
import { startClipUploader } from './browserCapture.js'
import { fmtDollars, fmtDuration } from './format.js'
import StreamTile from './StreamTile.jsx'
import FlagFeed from './FlagFeed.jsx'

export default function App() {
  const { events, chunks, sessions, safety, chat, alerts, connected } = useEventStream()
  const [health, setHealth] = useState(null)
  const [pay, setPay] = useState(null)
  const [url, setUrl] = useState('')
  const [streamerId, setStreamerId] = useState('demo-streamer')
  const [demoMode, setDemoMode] = useState(false)
  const [chatScript, setChatScript] = useState('')
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState('')
  // Browser-captured streams owned by this tab: id -> {stream, stopUploader}
  const local = useRef({})
  const [, rerender] = useState(0)

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then((h) => {
        setHealth(h)
        if (h.default_chat_script) setChatScript(h.default_chat_script)
      })
      .catch(() => setHealth(null))
  }, [])

  // Campaign budget from the payments API (Supabase + Stripe), refreshed while the page is open.
  useEffect(() => {
    const load = () => fetch('/api/payments').then((r) => r.json()).then(setPay).catch(() => setPay(null))
    load()
    const t = setInterval(load, 8000)
    return () => clearInterval(t)
  }, [])

  async function createSession(body) {
    const demo = demoMode ? { demo_alerts: true, chat_script: chatScript.trim() || null } : {}
    const r = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, ...demo, streamer_id: streamerId.trim() || 'streamer' }),
    })
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText)
    return r.json()
  }

  async function addUrl() {
    setError('')
    try {
      await createSession({ source: 'url', url: url.trim() })
      setUrl('')
    } catch (e) {
      setError(String(e.message || e))
    }
  }

  async function addBrowser(kind) {
    setError('')
    try {
      const stream =
        kind === 'webcam'
          ? await navigator.mediaDevices.getUserMedia({ video: { width: 854, height: 480 }, audio: true })
          : await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 15 }, audio: true })
      const s = await createSession({ source: 'browser' })
      const stopUploader = startClipUploader(stream, s.id, health?.chunk_seconds || 10, setError)
      local.current[s.id] = { stream, stopUploader, mirrored: kind === 'webcam' }
      stream.getVideoTracks()[0].addEventListener('ended', () => stop(s.id))
      rerender((n) => n + 1)
    } catch (e) {
      setError(String(e.message || e))
    }
  }

  function stop(id) {
    const l = local.current[id]
    if (l) {
      l.stopUploader()
      l.stream.getTracks().forEach((t) => t.stop())
      delete local.current[id]
    }
    if (selected === id) setSelected(null)
    fetch(`/api/sessions/${id}`, { method: 'DELETE' })
  }

  const streams = Object.values(sessions).sort((a, b) => a.started_at - b.started_at)
  const chunksBySession = {}
  for (const c of Object.values(chunks)) (chunksBySession[c.session_id] ||= []).push(c)
  for (const list of Object.values(chunksBySession)) list.sort((a, b) => b.chunk_index - a.chunk_index)
  const flagsBySession = {}
  for (const e of events) (flagsBySession[e.session_id] ||= []).push(e)

  const totalClips = streams.reduce((sum, s) => sum + s.chunks_analyzed, 0)
  const totalTips = events.filter((e) => e.status === 'tipped').reduce((sum, e) => sum + e.suggested_tip_cents, 0)
  const sponsorSeconds = streams.reduce((sum, s) => sum + (s.sponsor_screen_seconds || 0), 0)
  const feedFlags = selected ? flagsBySession[selected] || [] : events

  return (
    <div className="app">
      <header>
        <h1>Beverage Moment Monitor</h1>
        <div className="status">
          <span className={connected ? 'dot ok' : 'dot bad'} /> {connected ? 'connected' : 'disconnected'}
          {health && (
            <span className="muted">
              {' '}· {health.model}{health.verify_model && ` + ${health.verify_model} verify`} · {health.chunk_seconds}s clips
              {health.sponsor_brand && ` · sponsor: ${health.sponsor_brand}`}
              {!health.api_key_set && <b className="warn"> · GEMINI_API_KEY missing</b>}
            </span>
          )}
          {pay && (
            <span className="muted">
              {' '}·{' '}
              {!pay.enabled
                ? <b className="warn">payments simulated (set SUPARADE_API_URL)</b>
                : pay.ok
                  ? <>Stripe payouts on · campaign {pay.brand_name || pay.campaign_id?.slice(0, 8)}</>
                  : <b className="warn">payments API error: {pay.error}</b>}
            </span>
          )}
        </div>
      </header>

      <section className="kpis">
        <div><span>{streams.length}</span>streams live</div>
        <div><span>{totalClips}</span>clips analyzed</div>
        <div><span>{events.length}</span>Gemini flags</div>
        <div><span>{fmtDuration(sponsorSeconds)}</span>{health?.sponsor_brand || 'sponsor'} on screen</div>
        <div><span>{fmtDollars(totalTips)}</span>tipped</div>
        {pay?.ok && <div><span>{fmtDollars(pay.balance_cents || 0)}</span>campaign budget left</div>}
      </section>

      {safety.length > 0 && (
        <section className="safety-alert">
          <b>Brand-safety alert</b> · {safety[0].streamer_id}: {safety[0].flags.join(', ')}
          {safety[0].notes && <span className="muted"> · {safety[0].notes}</span>}
          {safety.length > 1 && <span className="muted"> · {safety.length - 1} earlier</span>}
        </section>
      )}

      <section className="controls">
        <input className="streamer" value={streamerId} onChange={(e) => setStreamerId(e.target.value)}
               placeholder="streamer id" />
        <input className="url" value={url} onChange={(e) => setUrl(e.target.value)}
               placeholder="https://twitch.tv/... or YouTube live URL (or local file path)"
               onKeyDown={(e) => e.key === 'Enter' && url && addUrl()} />
        <button onClick={addUrl} disabled={!url}>Add stream</button>
        <span className="muted">or</span>
        <button onClick={() => addBrowser('webcam')}>Webcam</button>
        <button onClick={() => addBrowser('screen')}>Screen-share a tab</button>
        <label className="demo-toggle" title="Spoken thank-you alerts + generated cards, and replay a scripted chat">
          <input type="checkbox" checked={demoMode} onChange={(e) => setDemoMode(e.target.checked)} />
          Demo mode
        </label>
        {demoMode && (
          <input className="url" value={chatScript} onChange={(e) => setChatScript(e.target.value)}
                 placeholder="chat script JSON (optional), e.g. backend/demo/chat_sample.json" />
        )}
        {error && <div className="error">{error}</div>}
      </section>

      <main>
        <div className="grid">
          {streams.length === 0 && (
            <div className="empty">No streams yet. Add a Twitch or YouTube live URL, or use your webcam.</div>
          )}
          {streams.map((s) => (
            <StreamTile
              key={s.id}
              session={s}
              localStream={local.current[s.id]?.stream}
              mirrored={local.current[s.id]?.mirrored}
              chunks={chunksBySession[s.id] || []}
              flags={flagsBySession[s.id] || []}
              chat={chat[s.id] || []}
              alert={alerts[s.id]}
              selected={selected === s.id}
              onSelect={() => setSelected(selected === s.id ? null : s.id)}
              onStop={() => stop(s.id)}
            />
          ))}
        </div>
        <FlagFeed
          flags={feedFlags}
          filterName={selected && sessions[selected]?.streamer_id}
          onClearFilter={() => setSelected(null)}
        />
      </main>
    </div>
  )
}
