# System Architecture — Vallis Simulacri

## Overview

The project is split into two independent systems that share only the filesystem:

- **`uncanny_maker`** — offline preprocessing pipeline (run once). Produces the artwork catalog.
- **`ars_aut_abeat`** — real-time gallery application (runs live during the installation).

```
┌──────────────────────────────────────────────────────────────────┐
│  OFFLINE PREPROCESSING  (run once before installation)           │
│                                                                  │
│  Met Museum API · Wikimedia Commons                              │
│      └──► download_paintings.py    (Met, ranked by figure count) │
│      └──► download_masterpieces.py (the famous multi-figure ones)│
│               └──► catalog/*.jpg  (source paintings)            │
│                        └──► iterate_degrade.py                  │
│                                 │  LLaVA → description prompt   │
│                                 │  Stable Diffusion × 10:       │
│                                 │  1–5 direct from original,    │
│                                 │  6–10 chained model collapse  │
│                                 └──► catalog_iterations_10/     │
│                                      {slug}/0000–0010.jpg        │
└──────────────────────────────────────────────────────────────────┘
                              │  shared filesystem
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  GALLERY APPLICATION  (live)                                     │
│                                                                  │
│  Kiosk Browser (Brave/Chrome)                                    │
│      │  JPEG frames via WebSocket binary  (10 Hz)               │
│      │  JSON ServerState via WebSocket text  (on change)        │
│      │                                                           │
│  FastAPI + Uvicorn (backend/)                                    │
│      │                                                           │
│      ├── GalleryProcessor (vision/)                              │
│      │     analysis thread @ 10 Hz:                             │
│      │     MediaPipe FaceLandmarker → blendshapes → 7 emotions   │
│      │     MediaPipe PoseLandmarker → hands_raised bool         │
│      │     OpenCV solvePnP          → gaze bool                 │
│      │     ↓ writes CameraState (thread-safe)                   │
│      │                                                           │
│      ├── InstallationState + advance_state() (core/)             │
│      │     FSM: IDLE → BASELINE → GALLERY → REVEAL → IDLE       │
│      │     called on every WebSocket tick                        │
│      │                                                           │
│      ├── ViewerSession (core/session.py)                         │
│      │     baseline samples + one bucket per gallery picture     │
│      │                                                           │
│      ├── Verdict engine (core/verdict.py)                        │
│      │     per-picture deviation from baseline → breaking point  │
│      │     → ARS / ABEAT split + VALLIS / LIMEN / FIRMA          │
│      │                                                           │
│      └── SQLite gallery.db (data/)                               │
│            artworks + viewings tables                            │
└──────────────────────────────────────────────────────────────────┘
```

---

## The Measurement Concept

The core question — *at which picture does art stop being art for you?* — is answered in three stages:

1. **Baseline (19 s).** The visitor reads the artwork's title and description while looking at the untouched original. Their average emotion vector during this window is their personal zero point: this is what their face looks like when looking at real art.
2. **Gallery (30 s).** Ten degraded pictures, one every 3 s with a 0.7 s crossfade. Every emotion sample is attributed to the picture currently provoking it — shifted by a 0.7 s **reaction lag**, because facial expressions trail the stimulus. Each picture therefore accumulates its own bucket of ~30 samples.
3. **Breaking point.** Each bucket's average is compared to the baseline using a weighted absolute deviation. The picture with the maximum deviation is where this visitor's recognition system fired. The picture *before* it is the last one that was still art (**ARS**); the breaking-point picture is no longer art (**ABEAT**, from the project name *ars aut abeat* — "art, or it departs").

The crossfade is kept short (0.7 s) so each picture change still produces a clean, attributable reaction spike — it matches the reaction-lag offset used for bucket attribution.

---

## File-by-File Reference

### `backend/`

| File | Role |
|------|------|
| `main.py` | FastAPI app entry point. Mounts `/frames` (→ `catalog_iterations_10/`) and `/catalog` as static dirs, registers `/ws` WebSocket endpoint, serves built React SPA from `frontend/dist/`. `/api/mode` toggles show mode; `/api/trigger` starts a run from IDLE in show mode. Pre-warms MediaPipe models and catalog on startup. |
| `ws_handler.py` | `GallerySession` handles one WebSocket connection. Singleton `GalleryProcessor` and `InstallationState` are shared across all connections (reconnects resume mid-session). Calls `advance_state()` on each frame tick and pushes a JSON `ServerState` diff to the client. Emotion sampling is enabled during BASELINE and GALLERY only. |
| `graphs.py` | Matplotlib chart generators for the attract screen (`attract_graph()`: verdict-distribution donut + average-emotion bars, base64 PNG). |

### `core/`

| File | Role |
|------|------|
| `state_machine.py` | `InstallationState` dataclass + `advance_state()` function. Called on every frame tick. Reads `CameraState` and wall-clock time; transitions phases; routes samples to baseline or gallery buckets; triggers `_finalize_viewing()` at GALLERY end. |
| `session.py` | `ViewerSession` per visitor. Stores a UUID, artwork ID, `baseline_samples`, and `gallery_buckets` — one list per picture. `add_gallery_sample()` computes the bucket index from elapsed time minus `REACTION_LAG_S`. |
| `verdict.py` | `deviation_score()` (weighted Σ\|Δ\| vs. baseline), `find_breaking_point()` (argmax over buckets, `None` below threshold), `verdict_from_deviation()`, `personal_verdict_text()`, `save_viewing()`, `collective_summary()`. |

### `vision/`

| File | Role |
|------|------|
| `camera.py` | `GalleryProcessor`. Receives JPEG bytes via `push_frame()`. Background analysis thread runs at 10 Hz: decodes JPEG, runs FaceLandmarker and PoseLandmarker, computes head pose, writes `CameraState`. Hands-lowered transitions are debounced with a 0.4 s grace period so brief detection dropouts don't reset the trigger timer. Thread-safe: one lock on the frame buffer, one on the state snapshot. |
| `emotion.py` | `_blendshapes_to_emotions()` maps MediaPipe's 52 FACS blendshape scores to 7 emotion channels using weighted sums. `neutral` is computed as a residual with a 1.5 baseline so quiet faces don't show as zero. `average_samples()` averages a list of per-frame dicts. |
| `face_detector.py` | `FaceResult` dataclass — thin wrapper kept for import compatibility. Actual detection runs in `camera.py`. |
| `gaze.py` | `is_looking_at_camera()` — returns True when `|yaw| ≤ 35°` and `|pitch| ≤ 30°`. `most_centered_face()` selects the face closest to the frame centre. |

### `catalog/`

| File | Role |
|------|------|
| `manager.py` | `CatalogManager` scans `uncanny_maker/catalog_iterations_10/` on startup. An artwork is loaded when `{slug}/0010.jpg` exists (10-picture mode); otherwise it falls back to the legacy 4-stage format or is skipped. Auto-registers artworks in SQLite. `pick_next()` selects the least-viewed artwork for balanced data collection. |

### `data/`

| File | Role |
|------|------|
| `db.py` | SQLite init via SQLAlchemy. `init_db()` creates the schema, runs `_migrate()` (adds columns introduced after the first deployment, e.g. `breaking_index`), and seeds from `catalog/artworks.json` if present. |
| `models.py` | `Artwork` and `Viewing` ORM models. |
| `stats.py` | `artwork_summary()` — aggregate emotion averages and verdict counts for one artwork. `concordance()` — how closely a viewer's emotion profile matches the crowd average for the same artwork. |

### `frontend/src/`

| File | Role |
|------|------|
| `hooks/useWebSocket.ts` | Manages the WebSocket connection. Sends binary JPEG blobs to server; parses incoming JSON into `ServerState`. Auto-reconnects on disconnect (2 s). `ServerState` is the single source of truth for all UI. |
| `hooks/useCamera.ts` | Wraps `getUserMedia`. Captures at 640×480, 15 fps. Every 100 ms (10 Hz) draws a frame to an off-screen canvas, encodes as JPEG at 70 % quality, passes to caller as a `Blob`. |
| `components/CameraBackground.tsx` | Always mounted — passes frames to `sendFrame` continuously. Never unmounts between phases, so the camera stream never stops. |
| `components/IdlePhase.tsx` | Mirror overlay. Shows visitor detection status and hands-raised prompt (or "press Space" in show mode). Switches to attract mode on a 30-second cycle. |
| `components/BaselinePhase.tsx` | Original painting + title on the left; "MENSVRA ANIMI" calibration text + progress bar on the right. Preloads all 11 pictures (`0000`–`0010`) during its 19-second window so GalleryPhase starts without stalls. |
| `components/GalleryPhase.tsx` | Crossfading picture sequence driven by `requestAnimationFrame`: `picture = floor(elapsed / secondsPerPicture) + 1`, anchored to `phase_started_at` (server timestamp) so it stays in sync across page refreshes. The previous picture stays mounted underneath while the new one fades in over it (`.gallery-fade-in`). Shows "PICTURE k / X" and live emotion bars. `secondsPerPicture` is derived client-side as `phase_duration / total_frames`. |
| `components/RevealPhase.tsx` | The verdict. Breaking point found: triptych — original, picture k−1 stamped **ARS** (gold), picture k stamped **ABEAT** (red) — panels staggered in, then an animated SVG line plot of all 10 deviations with the breaking point marked, caption "HERE, ART DIED FOR YOU", verdict badge. No breaking point: original centred, stamped **ARS MANSIT**, flat plot. |
| `components/SlidesPhase.tsx` | In-app presentation deck (German) for live demos: uncanny valley, AI & creativity, the experiment, the verdict tiers. Toggled via the SLIDES button; auto-advances every 10 s. |
| `App.tsx` | Phase router + show-mode controls (SELF/SHOW toggle, SLIDES toggle, Space/Enter trigger listener). |

---

## State Machine

Implemented in `core/state_machine.py`. `advance_state()` is called on every WebSocket tick (~10 Hz). All durations are configurable in `config.py`.

```
IDLE ──[hands raised ≥ 1.5 s | show-mode trigger]──► BASELINE ──[19 s]──► GALLERY ──[30 s]──► REVEAL ──[25 s]──► IDLE
```

| Phase | Duration | What happens |
|-------|----------|-------------|
| `IDLE` | Indefinite | Camera mirror; attract screen cycles every 30 s; waiting for hands-raised trigger (or `/api/trigger` in show mode) |
| `BASELINE` | 19 s | Original + title/description to read; emotion samples → `baseline_samples`; frontend preloads pictures |
| `GALLERY` | 30 s | 10 pictures, 3 s each, soft crossfade; emotion samples → per-picture buckets (0.7 s lag offset) |
| `REVEAL` | 25 s | `_finalize_viewing()` called once: baseline average, per-bucket averages, deviations, breaking point, verdict, DB write. UI: original / ARS / ABEAT triptych + animated reaction plot |

The DB write happens exactly once, at the start of `REVEAL`, inside `_finalize_viewing()`.

---

## Threading Model

```
WebSocket handler (asyncio event loop)
    ├── receive(): waits up to 2 s for JPEG bytes
    │       → on bytes: calls push_frame() — non-blocking (<1 ms, just stashes the frame)
    │       → on timeout: calls _tick(None) — advances state without a new frame
    └── _tick(): reads CameraState, calls advance_state(), sends JSON if state changed

GalleryProcessor analysis thread (daemon, started at server startup)
    loop @ ~10 Hz:
        copy latest_rgb  (frame lock)
        FaceLandmarker.detect()    → blendshapes → emotions
        PoseLandmarker.detect()    → wrist/shoulder → hands_raised (0.4 s down-debounce)
        solvePnP()                 → yaw/pitch → gaze
        write CameraState          (state lock)
```

Key property: `push_frame()` never blocks the analysis thread. The analysis thread always operates on the most recently stashed frame.

---

## WebSocket Protocol

**Client → Server:** binary (raw JPEG bytes, 640×480, ~10 Hz)

**Server → Client:** text JSON `ServerState`, sent only when the state changes (diff-suppressed)

```typescript
interface ServerState {
  show_mode:       boolean       // presentation mode active
  phase:           'IDLE' | 'BASELINE' | 'GALLERY' | 'REVEAL'
  phase_elapsed:   number        // seconds since phase start
  phase_duration:  number        // total duration of current phase
  phase_started_at: number       // Unix timestamp (seconds) — used by frontend animation clock
  attract_mode:    boolean       // show attract overlay in IDLE
  soul_count:      number        // total viewings so far
  emotions:        Record<string, number>   // 0–1 per key; populated during BASELINE+GALLERY
  face_present:    boolean
  hands_raised:    boolean
  artwork:         { slug, title, artist, total_frames } | null
  verdict:         'VALLIS' | 'LIMEN' | 'FIRMA' | ''
  personal_lines:  [name: string, pct: number][]   // see note on EMOTION_LATIN below
  breaking_index:  number | null  // 1-based picture where art broke; null = ARS MANSIT
  deviations:      number[]       // per-picture deviation scores (10 entries)
  collective:      { soul_count, dominant_latin, verdict, concordance } | null
  attract_graph:   string | null  // base64 PNG (aggregate donut + bars)
}
```

Pictures are served as static files: `/frames/{slug}/{n:04d}.png`. The frontend fetches them directly via HTTP — they do not travel through the WebSocket.

> **Naming note — `EMOTION_LATIN` is not Latin.** Both the backend map
> (`config.py: EMOTION_LATIN`) and its frontend twin
> (`GalleryPhase.tsx: EMOTION_LATIN`) currently map each emotion key to its plain
> **English** capitalisation (`happy → "Happy"`). The name is a leftover from an
> earlier design that displayed Latin emotion names alongside the Latin verdict
> tiers, and `ServerState.personal_lines` inherited the `latin_name` label from
> it. The verdicts (VALLIS / LIMEN / FIRMA / ARS / ABEAT) *are* Latin; the emotion
> labels are not. To restore Latin display, edit these two maps — they are the
> only place emotion labels are rendered, and they must be kept in sync.

### HTTP control endpoints (show mode)

| Endpoint | Method | Body | Purpose |
|----------|--------|------|---------|
| `/api/mode` | POST | `{"mode": "show" \| "self"}` | Toggle presentation mode |
| `/api/trigger` | POST | — | Start a run from IDLE (only honoured in show mode) |

---

## Emotion Detection

### Blendshape → Emotion Mapping (FACS)

MediaPipe FaceLandmarker returns 52 action-unit scores in `[0, 1]`. **18 of them**
are mapped to emotion channels (`_BLENDSHAPE_MAP` in `vision/emotion.py`); the
remaining 34 — eye blinks, gaze direction, tongue, most jaw and cheek shapes —
are ignored. The 18 are combined into 7 channels using weights derived from
Facial Action Coding System (FACS) research:

| Emotion | Key blendshapes |
|---------|-----------------|
| Happy | mouthSmileLeft/Right, cheekSquintLeft/Right |
| Disgust | noseSneerLeft/Right, mouthPucker |
| Fear | eyeWideLeft/Right + browInnerUp |
| Surprise | eyeWideLeft/Right, browOuterUpLeft/Right, jawOpen |
| Sad | mouthFrownLeft/Right, browInnerUp |
| Angry | browDownLeft/Right, noseSneer |
| Neutral | residual (1.5 baseline − sum of others) |

Normalization: all channels are summed; each channel is divided by the total so they form a probability distribution summing to 1.

### Gaze Gate

Head pose is estimated via `cv2.solvePnP` using 6 canonical 3D face landmarks and an estimated camera intrinsic matrix (focal length = frame width).

A face is considered "looking at the camera" when:
```
|yaw|   ≤ 35°
|pitch| ≤ 30°
```

Hands-raised trigger and emotion sampling are not gated on gaze — only the `face_centered` field in `CameraState` reflects this.

### Hands-Raised Detection

PoseLandmarker landmarks 15 (left wrist) and 16 (right wrist) are compared to landmarks 11 (left shoulder) and 12 (right shoulder). Both wrists must have a smaller `y` value than their respective shoulder (higher on screen = lower y in normalized coordinates).

The state machine requires this condition to hold continuously for `LOCK_STABILITY_DURATION` (default 1.5 s) before transitioning from IDLE to BASELINE. A 0.4 s grace period (`_HANDS_DOWN_GRACE_S` in `vision/camera.py`) tolerates brief detection dropouts without resetting the timer.

---

## Breaking-Point Scoring

```python
baseline    = mean(baseline_samples)                  # 19 s of original artwork
bucket_avg  = [mean(bucket) for bucket in buckets]    # one per picture

deviation_k = sum(BREAKING_WEIGHTS[e] * abs(bucket_avg[k][e] - baseline[e])
                  for e in EMOTION_KEYS)

breaking_index = argmax(deviation_k) + 1              # 1-based
                 # None if max(deviation) < BREAKING_MIN_DEVIATION
```

Weights (`config.py: BREAKING_WEIGHTS`) — any change counts, uncanny emotions count more:

| Emotion | Weight |
|---------|--------|
| Disgust | 1.0 |
| Fear | 0.9 |
| Surprise | 0.7 |
| Angry | 0.6 |
| Sad | 0.5 |
| Happy | 0.5 |
| Neutral | 0.2 |

Verdict (thresholds in `config.py`):

| Condition | Verdict |
|-----------|---------|
| max deviation ≥ `VERDICT_VALLIS_DEVIATION` (0.25) | VALLIS — fell into the valley |
| breaking point exists, below VALLIS threshold | LIMEN — at the threshold |
| max deviation < `BREAKING_MIN_DEVIATION` (0.08) | FIRMA — *ARS MANSIT*, never stopped being art |

---

## Two Verdict Systems (they are not the same)

`VALLIS` / `LIMEN` / `FIRMA` are produced by **two different scorers** depending on
whether the verdict is personal or collective. They share label names and nothing
else — different weights, different inputs, different thresholds, different scales.
Confusing them is the easiest mistake to make when reading this code.

| | Personal verdict | Collective verdict |
|---|---|---|
| Function | `verdict_from_deviation()` | `verdict_label()` ← `_score()` |
| Config weights | `BREAKING_WEIGHTS` (all positive, 0.2–1.0) | `VERDICT_WEIGHTS` (signed, −1.0–1.0) |
| Input | max per-picture deviation **from this viewer's baseline** | mean emotion vector across **all viewings of the artwork** |
| Measures | *how much the viewer changed* | *how negative the crowd's average mood is* |
| Thresholds | `VERDICT_VALLIS_DEVIATION` 0.25 / `BREAKING_MIN_DEVIATION` 0.08 | `VERDICT_VALLIS_THRESHOLD` 0.60 / `VERDICT_FIRMA_THRESHOLD` 0.40 |
| Written to | `viewings.verdict`, `ServerState.verdict` | `ServerState.collective.verdict` |

The distinction is conceptual, not incidental:

- The **personal** verdict is *change-based and sign-blind*. Every weight is
  positive, so a visitor who breaks into laughter at picture 7 scores exactly as
  strong a reaction as one who recoils. The claim is "something moved in you
  here", not "you were disgusted".
- The **collective** verdict is *valence-based*. `VERDICT_WEIGHTS` gives
  `happy: −1.0` and `neutral: −0.4` against `disgust: +1.0` and `fear: +0.9`, and
  `_score()` maps the weighted sum from `[−1, 1]` into `[0, 1]`. A crowd that
  mostly smiled lands near FIRMA; a crowd that mostly recoiled lands near VALLIS.
  With no viewings yet it returns the neutral default `0.5` → LIMEN.

So one artwork can legitimately show a personal `VALLIS` (this visitor reacted
hard) alongside a collective `FIRMA` (the crowd has mostly found it funny).

`verdict_label()` and `score_emotions()` in `core/verdict.py` are reachable only
through `collective_summary()`. The personal path never calls them.

---

## Concordance Metric

At reveal time, the visitor's mean emotion profile is compared to the collective average for the same artwork:

```python
concordance = 1.0 - (sum(|viewer[k] - crowd[k]| for k in keys) / (len(keys) * 1.0))
```

Returns `[0.0, 1.0]`: 1.0 = viewer matched the crowd exactly; 0.0 = opposite extreme on every emotion.

---

## Database Schema

SQLite at `data/gallery.db`. Created automatically on first run; `_migrate()` in `data/db.py` adds columns introduced after the first deployment.

### `artworks`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `slug` | TEXT UNIQUE | Filename stem, e.g. `The_Dance_Class_438817` |
| `title` | TEXT | Display name derived from stem |
| `artist` | TEXT | Always "Metropolitan Museum of Art" for current catalog |
| `year` | TEXT | |
| `image_path` | TEXT | Absolute path to source JPEG |
| `description` | TEXT | Optional curator note |
| `added_at` | DATETIME | UTC |

### `viewings`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `artwork_id` | INTEGER FK | → `artworks.id` |
| `session_id` | TEXT | UUID per visit |
| `timestamp` | DATETIME | UTC, session start |
| `duration_seconds` | FLOAT | Actual GALLERY duration |
| `emotion_json` | TEXT | JSON of mean emotion probabilities over the gallery phase |
| `dominant_emotion` | TEXT | Highest-probability emotion key |
| `verdict` | TEXT | `VALLIS` / `LIMEN` / `FIRMA` |
| `num_faces_in_frame` | INTEGER | Faces detected during GALLERY |
| `breaking_index` | INTEGER NULL | 1-based picture where art broke; NULL = ARS MANSIT |

Over time `breaking_index` answers the project's research question empirically: a histogram of breaking points per artwork shows where the crowd's uncanny valley begins.

---

## Catalog Management

`CatalogManager` (`catalog/manager.py`) abstracts over two catalog formats:

1. **10-picture (current):** `uncanny_maker/catalog_iterations_10/{slug}/0000.jpg … 0010.jpg`
2. **4-stage (legacy fallback):** `catalog_uncanny/20/{slug}.png`, `60/`, `80/`

The 10-picture format is used when `{slug}/0010.jpg` exists. Otherwise the legacy format is used if all three intermediate files are present. Artworks with neither are skipped.

`pick_next()` selects the artwork with the fewest viewings in the DB, ensuring data is collected evenly across the full catalog.

---

## Singleton Architecture

`GalleryProcessor`, `InstallationState`, and `CatalogManager` are module-level singletons, initialised on first access and shared across all WebSocket connections. This means:

- A page refresh does **not** reset the installation state — the session continues.
- MediaPipe models are loaded once at server startup, before any visitor connects.
- The analysis thread runs continuously regardless of whether a client is connected.

---

## Configuration Reference (`config.py`)

Complete listing of `ars_aut_abeat/config.py`. Every value is module-level and read
at import time — changing one requires a server restart.

### Timing

| Parameter | Default | Description |
|-----------|---------|-------------|
| `LOCK_STABILITY_DURATION` | 1.5 s | Hands must stay raised this long to trigger IDLE → BASELINE |
| `BASELINE_DURATION` | 19.0 s | Original + description; baseline calibration window |
| `GALLERY_DURATION` | 30.0 s | 10-picture sequence |
| `REVEAL_DURATION` | 25.0 s | Triptych verdict + reaction plot |
| `LOCKED_TRANSITION_DURATION` | 2.5 s | Unused by the FastAPI app — retired Streamlit path only |
| `FADE_DURATION` | 3.0 s | Unused by the FastAPI app — CSS owns all transitions |
| `INTRO_/MORPHING_/RECAP_DURATION` | aliases | Legacy names kept only for the retired `app.py` |

### Pictures

| Parameter | Default | Description |
|-----------|---------|-------------|
| `FRAME_COUNT` | 10 | Degradation pictures per artwork (plus `0000` = original) |
| `SECONDS_PER_PICTURE` | 3.0 s | Derived: `GALLERY_DURATION / FRAME_COUNT` |
| `REACTION_LAG_S` | 0.7 s | Reaction-lag offset for bucket attribution |
| `ITERATIONS_DIRNAME` | `catalog_iterations_10` | Pipeline output dir the app reads |
| `UNCANNY_OG_DIR` | `../uncanny_maker/catalog` | Source JPEGs — **the catalog scan starts here** |
| `UNCANNY_ITER_DIR` | `../uncanny_maker/catalog_iterations_10` | Picture sequences, mounted at `/frames` |
| `UNCANNY_20/60/80_DIR` | `../uncanny_maker/catalog_uncanny/*` | Legacy 4-stage fallback dirs |

### Vision

| Parameter | Default | Description |
|-----------|---------|-------------|
| `EMOTION_SAMPLE_RATE_HZ` | 10 | Analysis-thread target rate |
| `GAZE_YAW_THRESHOLD_DEG` | 35.0° | Max head yaw to count as looking at camera |
| `GAZE_PITCH_THRESHOLD_DEG` | 30.0° | Max head pitch |
| `MIN_FACE_AREA_FRACTION` | 0.01 | Minimum face bounding-box area (fraction of frame) |

Two vision constants live outside `config.py`:
`_HANDS_DOWN_GRACE_S` (0.4 s, `vision/camera.py`) and the FaceLandmarker limit
`num_faces=4` with confidence thresholds of 0.4.

### Personal verdict — breaking point

| Parameter | Default | Description |
|-----------|---------|-------------|
| `BREAKING_WEIGHTS` | disgust 1.0, fear 0.9, surprise 0.7, angry 0.6, sad 0.5, happy 0.5, neutral 0.2 | Per-emotion deviation weights, all positive |
| `BREAKING_MIN_DEVIATION` | 0.08 | Max deviation below this → no breaking point → FIRMA |
| `VERDICT_VALLIS_DEVIATION` | 0.25 | Max deviation above this → VALLIS, between → LIMEN |

### Collective verdict — crowd valence

| Parameter | Default | Description |
|-----------|---------|-------------|
| `VERDICT_WEIGHTS` | disgust 1.0, fear 0.9, surprise 0.4, sad 0.2, angry −0.1, neutral −0.4, happy −1.0 | Signed valence weights for the crowd score |
| `VERDICT_VALLIS_THRESHOLD` | 0.60 | Crowd score ≥ this → VALLIS |
| `VERDICT_FIRMA_THRESHOLD` | 0.40 | Crowd score ≥ this → LIMEN, below → FIRMA |

See [Two Verdict Systems](#two-verdict-systems-they-are-not-the-same) — these two
blocks are not interchangeable.

### Attract screen & misc

| Parameter | Default | Description |
|-----------|---------|-------------|
| `ATTRACT_CYCLE_S` | 30 s | Full attract cycle length |
| `ATTRACT_DURATION_S` | 15 s | Attract screen visible per cycle |
| `DB_PATH` | `data/gallery.db` | SQLite file, created on first run |
| `CATALOG_PATH` | `catalog/artworks.json` | Optional seed data, loaded by `_migrate()` if present |
| `EMOTION_LATIN` | English labels | Display names — see the naming note above |
