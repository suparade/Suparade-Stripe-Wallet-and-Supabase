/**
 * Live chat for one stream (Twitch, demo script, or typed here). Messages are
 * sent to Gemini with each clip so it can score how the audience reacted.
 */
import { useEffect, useRef, useState } from 'react'

const HYPE = ['W {brand}', 'W {brand} W {brand}', 'HYDRATION CHECK', 'stay hydrated king', '{brand} gang',
  'ok now im thirsty', 'W hydration', 'PogChamp', '{brand} supremacy', 'hydrate or diedrate']
const USERS = ['pixelpanda', 'gg_owen', 'sleepy_kat', 'nova_rush', 'hydrohomie', 'brickbyte', 'zeke_99', 'frostbyte']

const pick = (list) => list[Math.floor(Math.random() * list.length)]

export default function ChatPanel({ sessionId, brand, messages }) {
  const [text, setText] = useState('')
  const listRef = useRef(null)

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight
  }, [messages.length])

  const post = (body) =>
    fetch(`/api/sessions/${sessionId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })

  function send() {
    if (!text.trim()) return
    post({ user: 'you', text: text.trim() })
    setText('')
  }

  async function hypeBurst() {
    for (let i = 0; i < 10; i++) {
      post({ user: pick(USERS), text: pick(HYPE).replaceAll('{brand}', brand || 'Gatorade') })
      await new Promise((r) => setTimeout(r, 250 + Math.random() * 400))
    }
  }

  return (
    <div className="chat" onClick={(e) => e.stopPropagation()}>
      <div className="chat-list" ref={listRef}>
        {messages.length === 0 && <div className="muted small">No chat yet.</div>}
        {messages.map((m, i) => (
          <div key={i} className="chat-line"><b>{m.user}</b> {m.text}</div>
        ))}
      </div>
      <div className="chat-input">
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Send a chat message"
               onKeyDown={(e) => e.key === 'Enter' && send()} />
        <button className="small-btn" onClick={send} disabled={!text.trim()}>Chat</button>
        <button className="small-btn hype" onClick={hypeBurst} title="Simulate chat reacting to the brand">
          Hype burst
        </button>
      </div>
    </div>
  )
}
