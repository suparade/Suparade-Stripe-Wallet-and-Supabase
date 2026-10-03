/**
 * One monitored stream: live preview, a banner for Gemini's most recent flag,
 * and a strip showing the outcome of each analyzed clip.
 */
import { useEffect, useState } from 'react'
import { CATEGORY_LABELS, fmtDollars, fmtDuration, sourceLabel } from './format.js'
import ChatPanel from './ChatPanel.jsx'
import StreamPreview from './StreamPreview.jsx'
import ThankYouAlert from './ThankYouAlert.jsx'

const FLAG_BANNER_MS = 10000

export default function StreamTile({ session, localStream, mirrored, chunks, flags, chat, alert, selected, onSelect,
                                     onStop }) {
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])

  const latest = flags[0]
  const showBanner = latest && now - new Date(latest.detected_at).getTime() < FLAG_BANNER_MS
  const tipped = session.tips_cents ?? flags.filter((f) => f.tipped).reduce((sum, f) => sum + f.suggested_tip_cents, 0)
  const lastClip = chunks[0]
  const safetyFlags = Object.keys(session.safety_counts || {})

  return (
    <div className={`tile ${selected ? 'selected' : ''} ${showBanner ? 'flashing' : ''}`} onClick={onSelect}>
      <div className="tile-preview">
        <StreamPreview session={session} localStream={localStream} mirrored={mirrored} />
        <span className={`badge ${session.source_exited ? 'ended' : 'live'}`} title={session.exit_reason || ''}>
          {session.source_exited ? (session.exit_reason || 'ended').toUpperCase() : 'LIVE'}
        </span>
        {safetyFlags.length > 0 && (
          <span className="badge safety" title="Brand-safety flags seen on this stream (clips: count)">
            ⚠ {safetyFlags.map((f) => `${f} ×${session.safety_counts[f]}`).join(', ')}
          </span>
        )}
        <ThankYouAlert alert={alert} now={now} />
        {showBanner && (
          <div className="flag-banner">
            <b>Gemini flag</b> · {CATEGORY_LABELS[latest.category] || latest.category}
            {latest.brand && ` · ${latest.brand}`} · {Math.round(latest.confidence * 100)}%
          </div>
        )}
      </div>

      <div className="tile-body">
        <div className="tile-title">
          <b>{session.streamer_id}</b>
          <span className="muted">{sourceLabel(session)}</span>
          {session.demo_alerts && <span className="pill warn-pill">demo</span>}
          {session.chat_feeds?.length > 0 && <span className="muted small-inline">chat: {session.chat_feeds.join(', ')}</span>}
          <button className="stop small-btn" onClick={(e) => { e.stopPropagation(); onStop() }}>Stop</button>
        </div>
        <div className="tile-stats">
          <span><b>{flags.length}</b> flags</span>
          <span><b>{session.chunks_analyzed}</b> clips</span>
          <span className="tip-total">{fmtDollars(tipped)} tips</span>
          {session.sponsor_brand && (
            <span title={`${session.sponsor_weighted_seconds ?? 0}s prominence-weighted`}>
              {session.sponsor_brand} on screen <b>{fmtDuration(session.sponsor_screen_seconds || 0)}</b>
            </span>
          )}
          {session.competitor_mentions > 0 && (
            <span className="competitor-count">{session.competitor_mentions} competitor</span>
          )}
          {session.chunks_skipped > 0 && <span className="muted">{session.chunks_skipped} skipped</span>}
          <span className="muted">
            {lastClip
              ? `last clip: ${lastClip.status.replaceAll('_', ' ')}`
              : session.chunks_analyzed > 0 ? 'watching' : 'waiting for first clip'}
          </span>
        </div>
        <div className="clip-strip" title="Each square is one analyzed clip, newest on the right">
          {[...chunks].slice(0, 40).reverse().map((c) => (
            <span key={c.chunk_index}
                  className={`clip ${c.status} ${c.safety_flags?.length ? 'unsafe' : ''}`}
                  title={`#${c.chunk_index} ${c.status}${c.summary ? `: ${c.summary}` : ''}`} />
          ))}
        </div>
        <ChatPanel sessionId={session.id} brand={session.sponsor_brand} messages={chat} />
      </div>
    </div>
  )
}
