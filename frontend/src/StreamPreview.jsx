/**
 * Auto-playing preview for a stream tile.
 *
 * - Webcam / screen-share: the local MediaStream.
 * - Twitch / YouTube: the platform embed. Twitch won't autoplay embeds smaller
 *   than 400x300 or covered by other elements, so compact Twitch tiles need a
 *   click to start.
 * - Local files (demo replays): served by the backend and kept in sync with
 *   the analysis pipeline, which replays the file in real time from session start.
 */
import { useEffect, useRef } from 'react'
import { embedUrl } from './format.js'

function FileVideo({ session }) {
  const ref = useRef(null)

  async function start() {
    const v = ref.current
    if (!v) return
    if (v.duration) v.currentTime = (Date.now() / 1000 - session.started_at) % v.duration
    v.muted = false
    try {
      await v.play()
    } catch {
      v.muted = true // browsers only allow unmuted autoplay after the user has interacted with the page
      v.play().catch(() => {})
    }
  }

  return (
    <video ref={ref} src={`/api/sessions/${session.id}/media`} onLoadedMetadata={start}
           autoPlay loop playsInline controls onClick={(e) => e.stopPropagation()} />
  )
}

export default function StreamPreview({ session, localStream, mirrored }) {
  const videoRef = useRef(null)

  useEffect(() => {
    if (videoRef.current && localStream) videoRef.current.srcObject = localStream
  }, [localStream])

  if (localStream) return <video ref={videoRef} className={mirrored ? 'mirrored' : ''} autoPlay muted playsInline />
  if (session.source === 'browser') return <div className="placeholder">Preview only in the tab that started it</div>
  const embed = embedUrl(session.url)
  if (embed) return <iframe src={embed} title={session.streamer_id} allow="autoplay; fullscreen; encrypted-media" />
  if (session.local_file) return <FileVideo session={session} />
  return <div className="placeholder">{session.url}</div>
}
