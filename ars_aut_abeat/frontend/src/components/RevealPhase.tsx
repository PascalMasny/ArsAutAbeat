import type { ServerState } from '../hooks/useWebSocket'

interface Props {
  state: ServerState
}

const VERDICT_LABEL: Record<string, string> = {
  VALLIS: 'FALLEN',
  LIMEN: 'AT THE THRESHOLD',
  FIRMA: 'UNSHAKEN',
}

function frameUrl(slug: string, idx: number, ext: string) {
  return `/frames/${slug}/${String(idx).padStart(4, '0')}${ext}`
}

/** Line plot of per-picture deviation from baseline, breaking point marked. */
function ReactionPlot({ deviations, breakingIndex }: { deviations: number[]; breakingIndex: number | null }) {
  if (!deviations.length) return null

  const W = 1000
  const H = 220
  const PAD_X = 40
  const PAD_Y = 26
  const maxDev = Math.max(...deviations, 0.0001)
  const n = deviations.length

  const px = (i: number) => PAD_X + (i / (n - 1)) * (W - 2 * PAD_X)
  const py = (d: number) => H - PAD_Y - (d / maxDev) * (H - 2 * PAD_Y)
  const points = deviations.map((d, i) => `${px(i).toFixed(1)},${py(d).toFixed(1)}`).join(' ')

  return (
    <div className="reaction-plot">
      <div className="reaction-plot-label">YOUR REACTION · DEVIATION FROM BASELINE</div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        {/* baseline */}
        <line x1={PAD_X} y1={H - PAD_Y} x2={W - PAD_X} y2={H - PAD_Y}
              stroke="rgba(201,169,97,0.35)" strokeWidth="1.5" />
        {/* curve */}
        <polyline points={points} fill="none" stroke="var(--gold)" strokeWidth="3"
                  className="reaction-plot-line" />
        {/* picture markers + labels */}
        {deviations.map((d, i) => (
          <g key={i}>
            <circle cx={px(i)} cy={py(d)} r={i + 1 === breakingIndex ? 9 : 4.5}
                    fill={i + 1 === breakingIndex ? '#C03030' : 'var(--gold)'}
                    className="reaction-plot-dot" style={{ animationDelay: `${2 + i * 0.12}s` }} />
            <text x={px(i)} y={H - 6} textAnchor="middle"
                  fill={i + 1 === breakingIndex ? '#C03030' : 'var(--gold-dark)'}
                  fontSize="15" fontFamily="Cinzel, serif">
              {i + 1}
            </text>
          </g>
        ))}
      </svg>
    </div>
  )
}

export function RevealPhase({ state }: Props) {
  const { artwork, verdict, breaking_index, deviations } = state
  if (!artwork) return null

  const slug = artwork.slug

  // No breaking point — for this viewer, it never stopped being art.
  if (breaking_index === null) {
    return (
      <div className="reveal-layout phase-enter">
        <div className="reveal-single">
          <img src={frameUrl(slug, 0, artwork.frame_ext)} alt={artwork.title} />
          <div className="reveal-seal reveal-seal-ars">STILL ART</div>
        </div>
        <ReactionPlot deviations={deviations} breakingIndex={null} />
        <div className="reveal-caption">
          <div className="reveal-headline">FOR YOU, IT NEVER STOPPED BEING ART</div>
          <div className="reveal-subline">
            No picture moved you from your baseline. Unshaken — or a perfect poker face.
          </div>
          <div className="reveal-verdict" style={{ color: '#C9A961', borderColor: '#C9A961' }}>
            {VERDICT_LABEL[verdict] ?? 'UNSHAKEN'}
          </div>
        </div>
      </div>
    )
  }

  const arsIdx = breaking_index - 1   // 0 = the original
  const abeatIdx = breaking_index
  const verdictColor = verdict === 'VALLIS' ? '#8B2222' : '#8B9E6B'

  const panels = [
    { idx: 0, seal: null, sealClass: '', label: 'ORIGINAL', sub: 'the human hand' },
    {
      idx: arsIdx, seal: 'STILL ART', sealClass: 'reveal-seal-ars',
      label: arsIdx === 0 ? 'ORIGINAL' : `PICTURE ${arsIdx}`,
      sub: 'the last that was still art',
    },
    {
      idx: abeatIdx, seal: 'NOT ART', sealClass: 'reveal-seal-abeat',
      label: `PICTURE ${abeatIdx}`,
      sub: 'your strongest reaction',
    },
  ]

  return (
    <div className="reveal-layout phase-enter">
      <div className="reveal-triple">
        {panels.map((p, n) => (
          <div className="reveal-panel" key={n} style={{ animationDelay: `${0.3 + n * 0.55}s` }}>
            <img src={frameUrl(slug, p.idx, artwork.frame_ext)} alt={p.label} />
            {p.seal && (
              <div className={`reveal-seal ${p.sealClass}`}
                   style={{ animationDelay: `${0.7 + n * 0.55}s` }}>
                {p.seal}
              </div>
            )}
            <div className="reveal-frame-label">
              {p.label}
              <span className="reveal-frame-sub">{p.sub}</span>
            </div>
          </div>
        ))}
      </div>
      <ReactionPlot deviations={deviations} breakingIndex={breaking_index} />
      <div className="reveal-caption">
        <div className="reveal-headline">HERE, ART DIED FOR YOU</div>
        <div className="reveal-subline">
          Your strongest reaction: picture {breaking_index} of {artwork.total_frames}.
          You drew this line — not the machine.
        </div>
        <div className="reveal-verdict" style={{ color: verdictColor, borderColor: verdictColor }}>
          {VERDICT_LABEL[verdict] ?? verdict}
        </div>
      </div>
    </div>
  )
}
