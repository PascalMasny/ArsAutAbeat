# Vallis Simulacri
### *The Valley of Likeness* — Interactive Gallery Installation

> *At what point does a human find their own species wrong?*

---

## PLEB Art Consulting

**PLEB Art Consulting** is the four of us — **P**ascal Masny, **L**ukas Kraus,
**E**rik Reusch, **B**aha Tombul. Systems Engineering B.Sc., Technische Hochschule
Augsburg.

The name is a joke, and the joke is the thesis.

*Pleb* is short for **plebeian**: in Rome, everyone who wasn't patrician — the
ordinary people. The word survived into English as something the wealthy say when
they want to look down on someone. *Plebs.* The masses. People with no taste. We
are four engineering students who could not tell you why one canvas is worth eight
figures and the one beside it is worth nothing. By the standards of the art world,
we are precisely the plebs the word was invented for.

That is the entire point of the installation.

*Vallis Simulacri* does not ask a curator, a critic, or a model where art stops
being art. It asks whoever happens to be standing in front of the camera — and it
reads the answer off their face rather than out of their opinion, because a flinch
cannot be bluffed and doesn't need a vocabulary to be legible. The verdict screen
says it outright: **you drew this line — not the machine.** Not the expert either.

A consultancy of self-confessed plebs, building an instrument that lets other
plebs rule on what counts as art. We are unqualified in exactly the way the piece
requires.

---

## TL;DR — What this project does (for the confused colleague)

**In one sentence:** Visitors look at a classical painting while their emotional baseline is read, then walk through ten increasingly AI-distorted versions of it; the picture that provokes their strongest reaction becomes the verdict — everything before it was art (**ARS**), from there on it no longer is (**ABEAT**).

**What runs:** A FastAPI + React web app on a PC connected to a camera. The browser captures video, sends frames over WebSocket to a Python backend, which runs face/emotion analysis in real time, drives a state machine through four phases, and pushes results back to the frontend.

**How the distorted images are made:** A one-time offline pipeline (`uncanny_maker`) generates 10 pictures per painting with Stable Diffusion img2img in two phases: pictures 1–5 each directly from the original with a gentle strength ramp (subtle, coherent drift), pictures 6–10 chained output-to-input — true model collapse, where reconstruction errors compound and the painting disintegrates. The result is a body that is simultaneously too-human and deeply wrong.

**What "uncanny valley" means here:** Roboticist Masahiro Mori (1970) described how a near-perfect human likeness triggers revulsion more than a clearly non-human one. We measure that response in real visitors, one face at a time.

---

## The Experience (Visitor Perspective)

```
 IDLE        Large display shows a mirror view of visitors.
             Attract screen cycles every 30 s.
               │
               │  visitor raises both hands for 1.5 s
               │  (or presenter presses Space in show mode)
               ▼
 BASELINE    "THIS IS — [artwork title]"
             The untouched original for 19 s with title and description
             to read. Meanwhile the camera reads the visitor's
             face and stores the average as their personal baseline —
             their expression when looking at real art.
               │
               ▼
 GALLERY     Ten AI-degraded pictures, soft crossfade every 3 s (30 s) —
             like walking past ten works in a gallery. Each picture collects
             its own bucket of emotion samples (0.7 s reaction-lag offset).
             Live emotion bars float on the right.
               │
               ▼
 REVEAL      The picture whose bucket deviates most from the baseline is
             the breaking point. Three pictures side by side:
               ORIGINAL        — the human hand
               ARS    (gold)   — the last picture that was still art
               ABEAT  (red)    — the breaking point, strongest reaction
             Below: a reaction curve over all ten pictures.
             "HERE, ART DIED FOR YOU — your strongest reaction:
              picture k of 10. You drew this line — not the machine."
             No reaction at all → ARS MANSIT: it never stopped being art.
               │
               ▼
 IDLE        Resets. Waits for the next visitor.
```

---

## Repository Structure

```
.
├── ars_aut_abeat/          Real-time gallery application (FastAPI + React/Vite)
│   ├── backend/            FastAPI server: WebSocket handler, graph generation
│   ├── core/               Phase state machine, per-session data, verdict scoring
│   ├── vision/             MediaPipe emotion detection, head-pose gaze gate
│   ├── catalog/            Artwork loader — maps source images to 10-picture sequences
│   ├── data/               SQLAlchemy ORM, SQLite persistence, aggregate analytics
│   ├── frontend/           React + TypeScript + Vite UI
│   │   └── src/
│   │       ├── hooks/      useWebSocket.ts, useCamera.ts
│   │       └── components/ IdlePhase, BaselinePhase, GalleryPhase, RevealPhase, SlidesPhase
│   ├── start.sh            Production launcher (builds frontend, starts server, opens kiosk)
│   ├── install.sh          One-time Ubuntu/Debian setup
│   └── config.py           All tunable parameters (timings, thresholds, weights)
│
├── uncanny_maker/          Offline preprocessing pipeline (run once)
│   ├── iterate_degrade.py  Main script — 10 pictures per artwork (5 direct + 5 chained collapse)
│   ├── restore_catalog.py  Re-download the exact 169 artworks from the manifest
│   ├── download_paintings.py      Met scraper: paintings with people, ranked by figure count
│   ├── download_masterpieces.py   Wikimedia: the famous multi-figure works
│   ├── download_human_figures.py  Superseded by download_paintings.py
│   ├── core/               Stable Diffusion img2img + LLaVA prompt generation
│   └── catalog/            Source artwork JPEGs (git-ignored)
│
├── _prototypes/            Early experiments (not production code)
└── docs/
    ├── CONCEPT.md          Philosophy, the uncanny valley, model collapse as art
    ├── ARCHITECTURE.md     Technical architecture, data flow, all modules explained
    └── PIPELINE.md         Preprocessing pipeline — how the 10-picture sequences are made
```

---

## Quick Start

### Prerequisites

- Python 3.10–3.12 (MediaPipe does not support 3.13+ yet)
- Node.js 18+
- A webcam
- Brave Browser, Chrome, or Chromium (for kiosk mode)

### Ubuntu / Linux (recommended for the actual installation)

```bash
cd ars_aut_abeat
chmod +x install.sh start.sh
./install.sh          # one-time setup: Python venv, Node, system libs, browser
./start.sh            # builds frontend + starts server + opens kiosk browser
```

### macOS (development)

```bash
cd ars_aut_abeat
pip install -r requirements.txt
cd frontend && npm install && cd ..
./start.sh
```

Open `http://localhost:8000` in your browser.

> **First run note:** MediaPipe downloads two model files (~20 MB each) on first startup.
> The app loads immediately; face detection becomes active ~10–30 s later.

### Development mode (hot reload)

```bash
./dev.sh    # uvicorn with --reload + Vite HMR in parallel
            # frontend: http://localhost:5173 (proxies /ws and /frames to :8000)
```

---

## How the Artwork Images Are Made (Offline Pipeline)

Run once before the installation. Requires a GPU (Apple M-series MPS, NVIDIA CUDA, or slow CPU).

```bash
cd uncanny_maker
pip install -r requirements.txt

# Step 1 — get the source artworks. Two options:
python restore_catalog.py          # restore the exact 169 used in the exhibition

# …or build a new, larger catalog of paintings with people in them:
python download_paintings.py --target 200   # Met, filtered to paintings with figures
python download_masterpieces.py             # Mona Lisa, Last Supper, Night Watch, …

# Step 2 — generate 10 pictures per image:
#          1–5 direct from the original (subtle drift), 6–10 chained model collapse
ollama serve &          # optional — LLaVA writes the uncanny-steering prompt
python iterate_degrade.py
```

Use `restore_catalog.py` to rebuild *this* catalog: it downloads a fixed list of
Met object IDs under their original filenames, and since seeds are `crc32(stem)`
the pictures come back identical. The two download scripts sample shifting search
results, so they build a different catalog every time.

`download_paintings.py` filters the Met down to objects whose classification is
actually a painting and that carry a person tag, then ranks by how many people
are in the picture; the vases, bronzes and fragments that the first catalog
collected are rejected outright. `download_masterpieces.py` adds the famous
multi-figure works the Met does not own.

Output: `uncanny_maker/catalog_iterations_10/{artwork_slug}/0000.jpg … 0010.jpg`
(~3 MB per artwork; pictures are capped at 1600 px on the long side, which is
all the resolution Stable Diffusion put into them in the first place)

Both scripts are **fully resumable** — interrupted runs continue from where they stopped.

Estimated time per artwork: ~1 min on Apple M-series, ~30 s on NVIDIA GPU.

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + Uvicorn |
| Frontend | React 18 + TypeScript + Vite |
| Camera transport | WebSocket binary (JPEG frames, browser → server) |
| Computer vision | MediaPipe FaceLandmarker (52 FACS blendshapes) |
| Pose detection | MediaPipe PoseLandmarker (hands-raised trigger) |
| Head pose | OpenCV `solvePnP` (gaze gate: yaw ≤ 35°, pitch ≤ 30°) |
| Image generation | Stable Diffusion v1.5 via Hugging Face `diffusers` |
| Vision LLM | LLaVA via Ollama (optional — improves SD prompts) |
| Database | SQLite via SQLAlchemy 2.0 |
| Charts | Matplotlib → base64 PNG |
| Art source | Met Museum Open Access API (public domain) |
| Display | Large landscape display / video wall, 16:9 |

---

## Verdict System — the Breaking Point

During BASELINE the visitor's average emotion vector is stored as their personal zero point. During GALLERY each of the 10 pictures collects its own bucket of emotion samples. At reveal time every bucket is compared to the baseline:

```
deviation(picture k) = Σ over emotions  weight[e] × |bucket_avg_k[e] − baseline[e]|
breaking point       = picture with maximum deviation
```

| Emotion | Weight | Rationale |
|---------|--------|-----------|
| Disgust | 1.0 | Core uncanny signal |
| Fear | 0.9 | Threat response |
| Surprise | 0.7 | Strong involuntary reaction |
| Angry | 0.6 | Rejection |
| Sad | 0.5 | Negative shift |
| Happy | 0.5 | A laugh is also a reaction |
| Neutral | 0.2 | Mostly absorbs the others' movement |

Any *change* from the baseline counts as a reaction — the weights only decide how much.

| Condition | Verdict | Meaning |
|-----------|---------|---------|
| max deviation ≥ 0.25 | **VALLIS** | Strong reaction — fell into the valley |
| breaking point exists, < 0.25 | **LIMEN** | Measurable but mild — at the threshold |
| max deviation < 0.08 | **FIRMA** | *ARS MANSIT* — it never stopped being art |

The reveal screen shows the breaking-point picture stamped **ABEAT** (no longer art) next to the picture before it, stamped **ARS** (still art). The visitor — not the machine — drew the line.

---

## Privacy

- No video is stored anywhere.
- Emotion analysis runs entirely on the installation hardware.
- Only anonymous numerical scores are written to the database (no images, no identity).
- The visitor initiates by raising both hands — a deliberate consent gesture.

---

## Documentation

| File | Type | Contents |
|------|------|----------|
| [`docs/CONCEPT.md`](docs/CONCEPT.md) | Explanation | Philosophy — uncanny valley, model collapse as artistic medium, Freud, Mori |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Reference | System design, WebSocket protocol, vision pipeline, both verdict systems, full config reference |
| [`docs/PIPELINE.md`](docs/PIPELINE.md) | Reference | Preprocessing pipeline — Stable Diffusion loop, LLaVA, degradation mechanics |
| [`docs/HOWTO_RUN_SHOW.md`](docs/HOWTO_RUN_SHOW.md) | How-to | Running the installation at an exhibition; on-site troubleshooting |
| [`docs/HOWTO_REGENERATE_CATALOG.md`](docs/HOWTO_REGENERATE_CATALOG.md) | How-to | Rebuilding all images from an empty checkout |
| [`docs/CATALOG_MANIFEST.md`](docs/CATALOG_MANIFEST.md) | Reference | The exact 169 Met artworks the installation was built from |
| [`ars_aut_abeat/README.md`](ars_aut_abeat/README.md) | Reference | App-level reference: quick start, config, state machine, DB schema |

> **No images in a fresh clone.** The generated pictures (~0.8 GB) and source
> artworks (~450 MB) are excluded from version control. A clone has code and docs
> only — run [`docs/HOWTO_REGENERATE_CATALOG.md`](docs/HOWTO_REGENERATE_CATALOG.md)
> before the installation will start. Without a catalog the app runs but stays
> stuck in IDLE forever.

---

## Design Language

Deliberately anachronistic — a 21st-century computer-vision experiment dressed as a 17th-century cabinet of curiosities.

- **Fonts:** Cinzel (inscriptions), Cormorant Garamond (body text), Pinyon Script (flourishes)
- **Palette:** Ink black `#1C1410` · Parchment `#F4E8D0` · Gold `#C9A961` · Burgundy `#6B2C2C`
- **Layout:** `16:9` landscape viewport, letterboxed on non-16:9 screens
- **Text scale:** CSS `clamp()` throughout — readable from phone screen to 65-inch projection
