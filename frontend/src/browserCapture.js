/**
 * Browser capture: records a MediaStream in fixed-length clips and uploads
 * each one. MediaRecorder is stopped and restarted per clip (rather than using
 * a timeslice) so every upload is a standalone, decodable webm file.
 */

function pickMime() {
  const options = ['video/webm;codecs=vp8,opus', 'video/webm;codecs=vp9,opus', 'video/webm', 'video/mp4']
  return options.find((m) => MediaRecorder.isTypeSupported(m)) || ''
}

export function startClipUploader(stream, sessionId, chunkSeconds, onError) {
  const mimeType = pickMime()
  let stopped = false
  let recorder

  const recordOne = () => {
    if (stopped) return
    const parts = []
    const startedAt = performance.now()
    recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 800_000 })
    recorder.ondataavailable = (e) => e.data.size && parts.push(e.data)
    recorder.onstop = async () => {
      const duration = (performance.now() - startedAt) / 1000
      if (!stopped) recordOne()
      const blob = new Blob(parts, { type: recorder.mimeType || 'video/webm' })
      if (!blob.size) return
      const form = new FormData()
      const ext = blob.type.includes('mp4') ? 'mp4' : 'webm'
      form.append('file', blob, `clip.${ext}`)
      form.append('duration', String(duration))
      try {
        const r = await fetch(`/api/sessions/${sessionId}/chunk`, { method: 'POST', body: form })
        if (!r.ok) onError?.(`upload failed: ${r.status}`)
      } catch (err) {
        onError?.(String(err))
      }
    }
    recorder.start()
    setTimeout(() => recorder.state === 'recording' && recorder.stop(), chunkSeconds * 1000)
  }

  recordOne()
  return () => {
    stopped = true
    if (recorder?.state === 'recording') recorder.stop()
  }
}
