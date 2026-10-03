/**
 * Evidence thumbnail with Gemini's bounding boxes drawn on top.
 * box_2d is [ymin, xmin, ymax, xmax] normalized to 0-1000.
 */
export default function BoxedThumb({ src, href, boxes = [], sponsor, large = false }) {
  return (
    <a className={`boxed-thumb ${large ? 'large' : ''}`} href={href || src} target="_blank" rel="noreferrer"
       title="Open evidence clip" onClick={(e) => e.stopPropagation()}>
      <img src={src} alt="evidence" />
      {boxes.map((b, i) => {
        const [ymin, xmin, ymax, xmax] = b.box_2d
        const isSponsor = sponsor && b.label.toLowerCase().includes(sponsor.toLowerCase())
        return (
          <span key={i} className={`bbox ${isSponsor ? 'sponsor' : ''}`}
                style={{ top: `${ymin / 10}%`, left: `${xmin / 10}%`,
                         height: `${(ymax - ymin) / 10}%`, width: `${(xmax - xmin) / 10}%` }}>
            <span className="bbox-label">{b.label}</span>
          </span>
        )
      })}
    </a>
  )
}
