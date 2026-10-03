export const CATEGORY_LABELS = {
  sports_drink_mention: 'Sports drink mention',
  drinking_water: 'Drinking water',
  drinking_other: 'Drinking (other)',
  holding_or_showing_beverage: 'Showing a beverage',
  verbal_beverage_mention: 'Talks about drinks',
  sponsor_screen_time: 'Sponsor screen time',
}

export const STATUS_LABELS = {
  tipped: 'tipped',
  blocked: 'blocked',
  pending_verification: 'verifying…',
  rejected_by_verifier: 'rejected by verifier',
  paying: 'paying via Stripe…',
  payment_failed: 'payment failed',
}

export function tipLabel(e) {
  const amount = fmtDollars(e.suggested_tip_cents)
  if (e.payment_status === 'paid') return `paid ${amount} via Stripe`
  if (e.payment_status === 'pending') return `${amount} · Stripe pending`
  if (e.payment_status === 'simulated') return `tipped ${amount} (simulated)`
  return `tipped ${amount}`
}

export const SUBJECT_LABELS = {
  real_person: 'real person',
  animated_character: 'animated',
  video_playback: 'video playback',
}

export function reasonLabel(r) {
  const [kind, value] = r.split(':')
  if (kind === 'safety') return `unsafe: ${value}`
  if (kind === 'sentiment') return `${value} sentiment`
  if (kind === 'subject') return SUBJECT_LABELS[value] || value
  return r.replaceAll('_', ' ')
}

export function fmtDuration(s) {
  const total = Math.round(s)
  const m = Math.floor(total / 60)
  return m ? `${m}m ${total % 60}s` : `${total}s`
}

export function embedUrl(url) {
  try {
    const u = new URL(url)
    const host = u.hostname.replace('www.', '')
    if (host.endsWith('twitch.tv')) {
      const channel = u.pathname.split('/').filter(Boolean)[0]
      return `https://player.twitch.tv/?channel=${channel}&parent=${location.hostname}&muted=true&autoplay=true`
    }
    if (host === 'youtu.be') return `https://www.youtube.com/embed/${u.pathname.slice(1)}?autoplay=1&mute=1`
    if (host.endsWith('youtube.com')) {
      const parts = u.pathname.split('/').filter(Boolean)
      const id = u.searchParams.get('v') || (parts[0] === 'live' || parts[0] === 'shorts' ? parts[1] : null)
      if (id) return `https://www.youtube.com/embed/${id}?autoplay=1&mute=1`
    }
  } catch {}
  return null
}

export function fmtTime(s) {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${String(sec).padStart(2, '0')}`
}

export function fmtDollars(cents) {
  return `$${(cents / 100).toFixed(2)}`
}

export function sourceLabel(session) {
  if (session.source === 'browser') return 'webcam / screen'
  try {
    return new URL(session.url).hostname.replace('www.', '')
  } catch {
    return 'local file'
  }
}
