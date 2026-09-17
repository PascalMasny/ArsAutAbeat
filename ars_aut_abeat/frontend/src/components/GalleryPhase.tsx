import { useEffect, useRef, useState } from 'react'
import type { ServerState } from '../hooks/useWebSocket'

interface Props {
  state: ServerState
}

const EMOTION_ORDER = ['happy', 'sad', 'angry', 'surprise', 'fear', 'disgust', 'neutral']
const EMOTION_LATIN: Record<string, string> = {
  happy: 'Happy', sad: 'Sad', angry: 'Angry',
  surprise: 'Surprise', fear: 'Fear', disgust: 'Disgust', neutral: 'Neutral',
}

export function GalleryPhase({ state }: Props) {
  const { artwork, emotions, phase_started_at, phase_duration } = state
  const [picture, setPicture] = useState(1)
  const rafRef = useRef<number | null>(null)
  const prevRef = useRef(1)

  const totalFrames = artwork?.total_frames ?? 10
  const slug = artwork?.slug ?? ''
  const secondsPerPicture = phase_duration / totalFrames

  // Picture k for elapsed in [(k-1)·3s, k·3s); new picture crossfades in
  useEffect(() => {
    if (!slug) return
    const tick = () => {
      const elapsed = Date.now() / 1000 - phase_started_at
      const idx = Math.min(Math.max(Math.floor(elapsed / secondsPerPicture) + 1, 1), totalFrames)
      setPicture((cur) => {
        if (idx !== cur) prevRef.current = cur
        return idx
      })
      if (elapsed < phase_duration) rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current) }
  }, [slug, totalFrames, secondsPerPicture, phase_started_at, phase_duration])

  if (!artwork) return null

  const ext = artwork.frame_ext
  const frameSrc = (i: number) => `/frames/${slug}/${String(i).padStart(4, '0')}${ext}`
  const visibleEmotions = EMOTION_ORDER.filter((k) => k in emotions)

  return (
    <div className="phase-layout phase-enter">
      <div className="phase-left" style={{ background: '#0a0806' }}>
        {/* previous picture stays beneath; new one fades in over it */}
        <img className="morphing-img" src={frameSrc(prevRef.current)} alt="" />
        <img key={picture} className="morphing-img gallery-fade-in" src={frameSrc(picture)} alt="" />
        <div className="progress-track">
          <div
            className="progress-fill"
            style={{ width: `${((picture / totalFrames) * 100).toFixed(1)}%` }}
          />
        </div>
      </div>
      <div className="phase-right">
        <div className="morphing-top">
          <div className="morphing-title">{artwork.title}</div>
          <div className="morphing-frame-label">
            PICTURE {picture} / {totalFrames}
          </div>
        </div>
        <div className="morphing-emotion-section">
          <div className="emotion-section-label">YOUR EMOTIONS</div>
          {visibleEmotions.length > 0 ? (
            visibleEmotions.map((key) => {
              const pct = Math.round(emotions[key] * 1000) / 10
              return (
                <div className="emotion-bar-row" key={key}>
                  <div className="emotion-bar-header">
                    <span>{EMOTION_LATIN[key]}</span>
                    <span>{pct}%</span>
                  </div>
                  <div className="emotion-bar-track">
                    <div className="emotion-bar-fill" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              )
            })
          ) : (
            <div style={{
              fontFamily: "'Cormorant Garamond', serif",
              fontStyle: 'italic',
              color: 'var(--gold-dark)',
              textAlign: 'center',
              fontSize: 'clamp(1.2rem,3vh,2.8rem)',
            }}>
              Reading…
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
