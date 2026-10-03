/**
 * Demo-mode thank-you alert over a stream tile: Gemini's message, spoken with
 * Gemini TTS, plus the generated thank-you card when it arrives.
 */
import { useEffect } from 'react'
import { fmtDollars } from './format.js'

const ALERT_MS = 15000
const played = new Set()

export default function ThankYouAlert({ alert, now }) {
  useEffect(() => {
    if (!alert?.alert_audio_url || played.has(alert.event_id)) return
    played.add(alert.event_id)
    new Audio(alert.alert_audio_url).play().catch(() => {})
  }, [alert?.event_id, alert?.alert_audio_url])

  if (!alert || now - alert.received_at > ALERT_MS) return null
  return (
    <div className="thank-you">
      {alert.card_url && <img src={alert.card_url} alt="thank-you card" />}
      <div>
        <div className="thank-you-amount">{alert.brand || 'Sponsor'} tipped {fmtDollars(alert.suggested_tip_cents)}</div>
        <div>{alert.alert_message}</div>
      </div>
    </div>
  )
}
