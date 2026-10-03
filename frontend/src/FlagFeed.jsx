/**
 * Every beverage moment Gemini flagged, newest first, optionally filtered to
 * one stream. Shows why a moment was or wasn't tipped, plus evidence for tips.
 */
import { CATEGORY_LABELS, STATUS_LABELS, SUBJECT_LABELS, fmtDollars, fmtTime, reasonLabel, tipLabel } from './format.js'
import BoxedThumb from './BoxedThumb.jsx'

export default function FlagFeed({ flags, filterName, onClearFilter }) {
  return (
    <div className="feed">
      <h2>
        Gemini flags
        {filterName && (
          <span className="filter-chip" onClick={onClearFilter}>{filterName} ×</span>
        )}
      </h2>
      <div className="events">
        {flags.length === 0 && <div className="muted">Nothing flagged yet.</div>}
        {flags.map((e) => {
          const status = e.status || (e.tipped ? 'tipped' : 'blocked')
          return (
            <div key={e.event_id} className={`event ${status}`}>
              <div className="event-head">
                <span className="cat">{CATEGORY_LABELS[e.category] || e.category}</span>
                {e.brand && (
                  <span className={`brand ${e.is_competitor ? 'competitor' : e.is_sponsor ? 'sponsor' : ''}`}>
                    {e.brand}{e.is_competitor && ' · competitor'}
                  </span>
                )}
                {e.category !== 'sponsor_screen_time' && (
                  <span className="conf">{Math.round(e.confidence * 100)}%</span>
                )}
                {e.sentiment && <span className={`pill sentiment-${e.sentiment}`}>{e.sentiment}</span>}
                {e.subject_type && e.subject_type !== 'real_person' && (
                  <span className="pill warn-pill">{SUBJECT_LABELS[e.subject_type]}</span>
                )}
                <span className={`tip ${status}`}>
                  {status === 'tipped' ? tipLabel(e) : STATUS_LABELS[status]}
                </span>
              </div>
              <div className="event-body">
                {e.thumbnail_url && (
                  <BoxedThumb src={e.thumbnail_url} href={e.clip_url} boxes={e.boxes} sponsor={e.is_sponsor && e.brand} />
                )}
                <div>
                  <div className="desc">{e.description}</div>
                  {e.quote && <div className="quote">"{e.quote}"</div>}
                  {e.audience_reaction && (
                    <div className="reaction">
                      <span className={`pill reaction-${e.audience_reaction}`}>
                        chat reaction: {e.audience_reaction}
                        {e.reaction_multiplier > 1 && ` · ×${e.reaction_multiplier} tip`}
                      </span>
                      {e.reaction_summary && <span className="muted small-inline"> {e.reaction_summary}</span>}
                      {e.chat_highlights?.length > 0 && (
                        <div className="chat-highlights">
                          {e.chat_highlights.map((h, i) => <span key={i}>"{h}"</span>)}
                        </div>
                      )}
                    </div>
                  )}
                  {e.alert_message && (
                    <div className="alert-line">
                      <button className="small-btn" onClick={(ev) => { ev.stopPropagation(); new Audio(e.alert_audio_url).play() }}
                              disabled={!e.alert_audio_url} title="Replay the spoken thank-you alert">▶</button>
                      <span>{e.alert_message}</span>
                      {e.card_url && (
                        <a href={e.card_url} target="_blank" rel="noreferrer"><img className="card-thumb" src={e.card_url} alt="card" /></a>
                      )}
                    </div>
                  )}
                  {e.block_reasons?.length > 0 && (
                    <div className="reasons">
                      {e.block_reasons.map((r) => <span key={r} className="reason">{reasonLabel(r)}</span>)}
                    </div>
                  )}
                  {e.verification_reason && <div className="muted small">Verifier: {e.verification_reason}</div>}
                  {(e.stripe_transfer_id || e.payment_error) && (
                    <div className="payment-line">
                      {e.stripe_transfer_id && <span className="pill stripe-pill" title="Stripe transfer to the streamer">Stripe {e.stripe_transfer_id}</span>}
                      {e.requested_tip_cents && (
                        <span className="muted small-inline"> capped from {fmtDollars(e.requested_tip_cents)} by the campaign max</span>
                      )}
                      {e.payment_error && <span className="reason payment-error">payment: {reasonLabel(e.payment_error)}</span>}
                    </div>
                  )}
                </div>
              </div>
              <div className="muted small">
                <b>{e.streamer_id}</b> · stream time {fmtTime(e.stream_offset_seconds)} ·{' '}
                {new Date(e.detected_at).toLocaleTimeString()}
                {e.clip_url && !e.thumbnail_url && (
                  <> · <a href={e.clip_url} target="_blank" rel="noreferrer">evidence clip</a></>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
