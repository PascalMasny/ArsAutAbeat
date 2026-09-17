import { useEffect, useRef, useState } from 'react'
import type { ServerState } from '../hooks/useWebSocket'

interface Props {
  state: ServerState
}

export function BaselinePhase({ state }: Props) {
  const { artwork, phase_started_at, phase_duration } = state
  const [progress, setProgress] = useState(0)
  const rafRef = useRef<number | null>(null)

  // Preload all gallery pictures while the viewer studies the original
  useEffect(() => {
    if (!artwork) return
    const { slug, total_frames, frame_ext } = artwork
    for (let i = 0; i <= total_frames; i++) {
      const img = new Image()
      img.src = `/frames/${slug}/${String(i).padStart(4, '0')}${frame_ext}`
    }
  }, [artwork?.slug])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const tick = () => {
      const elapsed = Date.now() / 1000 - phase_started_at
      setProgress(Math.min(elapsed / phase_duration, 1) * 100)
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current) }
  }, [phase_started_at, phase_duration])

  if (!artwork) return null

  const firstFrameUrl = `/frames/${artwork.slug}/0000${artwork.frame_ext}`

  return (
    <div className="phase-layout phase-enter">
      <div className="phase-left">
        <img className="intro-artwork" src={firstFrameUrl} alt={artwork.title} />
      </div>
      <div className="phase-right">
        <div className="intro-right">
          <div className="baseline-meta">
            <div className="intro-label">THIS IS</div>
            <div className="intro-title">{artwork.title}</div>
            {artwork.artist && (
              <div className="baseline-artist">{artwork.artist}</div>
            )}
          </div>

          <div className="divider">❧ · · ❧</div>

          <div className="intro-body">
            Take your time. Look at the brushwork, the light, the face.
            This painting was made by a human hand.
            <br /><br />
            While you read this, the camera is quietly measuring your
            expression — this is your <span className="intro-em">baseline</span>:
            your face in front of real art.
          </div>

          <div className="intro-body" style={{ color: 'var(--gold-dark)' }}>
            In a moment, an AI will show you this painting ten times —
            and each time, it will take more liberties.
            Your face will decide where it stops being art.
          </div>

          <div className="baseline-progress-track">
            <div className="baseline-progress-fill" style={{ width: `${progress.toFixed(1)}%` }} />
          </div>
          <div className="intro-closing">The gallery opens shortly.</div>
        </div>
      </div>
    </div>
  )
}
