# Preprocessing Pipeline — uncanny_maker

The `uncanny_maker` pipeline is a standalone tool that produces the artwork catalog consumed by the gallery application. It runs entirely offline and only needs to be executed once per catalog update.

## Overview

```
Met Museum Open Access API   ·   Wikimedia Commons
         │
         ▼
download_paintings.py  +  download_masterpieces.py
         │  saves JPEGs (Wikimedia capped at 1600 px)
         ▼
  catalog/<ObjectID>_<Title>.jpg   (source images)
         │
         ▼
iterate_degrade.py  (one run per image)
         │  LLaVA → description prompt
         │  Stable Diffusion img2img × 10 pictures:
         │  1–5 direct from original (0.10 → 0.30, fixed seed)
         │  6–10 chained feedback / model collapse (0.22 → 0.42)
         ▼
  catalog_iterations_10/<stem>/0000.jpg … 0010.jpg
```

---

## Step 1 — Acquiring Source Artworks

Two scripts fill `catalog/`. Both skip files already on disk, so they combine freely and are safe to re-run.

**`download_paintings.py`: the Met, filtered.** Searches the painting departments
(11 European Paintings, 15 Robert Lehman, 17 Medieval Art, 7 The Cloisters), then
rejects everything whose `classification` is not a painting and everything carrying
no person tag. What survives is ranked by an estimate of how many people are in it,
so multi-figure works download first:

```
figure_score = (person tags) + 2 × (scene tags) − 2 × (self-portrait)
```

Person tags are AAT terms naming who is present: `Men`, `Women`, `Children`,
`Saints`, `Angels`. Scene tags name an activity that needs a group (`Banquets`,
`Processions`, `Battles`, `Dancing`) and count double, because they are the
strongest available signal for a populated canvas. A score of 0 means nobody is in
the picture and the artwork is dropped.

This supersedes `download_human_figures.py`, whose searches on department 13
(Greek & Roman Art) matched any bronze or marble object, not just figures. That
is how bronze jugs, strainers, rings and amphora fragments ended up in the first
exhibition catalog.

**`download_masterpieces.py`: the famous ones.** The Met holds none of the
paintings a visitor recognises on sight. This script fetches a curated list of
them from Wikimedia (the Mona Lisa, the Last Supper, the Night Watch, Las
Meninas, Liberty Leading the People), resolving each through its English Wikipedia
article rather than a hardcoded Commons filename, because article titles are
stable while Commons filenames are not.

> **Both APIs reject anonymous clients.** The Met sits behind Akamai bot
> protection: a request carrying the default `python-requests` user agent gets
> HTTP 403 and an HTML block page, and parallel requests are flagged within
> seconds. Wikimedia answers 429. Every script sends a descriptive user agent,
> fetches Met metadata serially, and retries with backoff.

**Legacy query strategy** (`download_human_figures.py`, superseded)

30 keyword searches are issued in sequence, each scoped to one Met department and
carrying its own `pick` quota (`SEARCHES`):

| Department | Searches | Examples |
|------------|----------|----------|
| 13 — Greek & Roman Art | 12 | `kouros`, `marble statue figure`, `Aphrodite Venus`, `marble portrait bust` |
| 11 — European Paintings | 18 | `portrait woman`, `Madonna Child`, `Rembrandt portrait`, `Baroque portrait` |

Each search runs with `hasImages=true` and `isPublicDomain=true` as API parameters,
so filtering happens server-side. Results are then sampled with a stride
(`new[::step][:pick*2]`) to spread picks across the whole result set rather than
taking the first N, which would over-represent one artist or one acquisition batch.

The only client-side filter is that the object must carry a `primaryImage` or
`primaryImageSmall` URL. There is **no** medium-keyword scan — the department
scoping and query wording do that work.

Collection stops at `TARGET = 200` downloaded files.

**Output**

Images are saved as `catalog/<sanitised_title>_<objectID>.jpg` — title first,
object ID last (`safe_filename()` truncates the title to 50 chars). That trailing
ID is what `catalog/manager.py` strips to build display titles, and the full stem
is what seeds Stable Diffusion.

The script is resumable: an object is skipped if its exact destination filename
already exists, or if its ID appears as the trailing segment of any `catalog/*.jpg`.

Typical run: ~200 images, runtime depends on network speed.

> **Restoring the exact catalog?** Do not use this script — its index-based
> sampling of shifting search results produces a different set every time. Use
> `restore_catalog.py`, which downloads a fixed object-ID list. See
> [`HOWTO_REGENERATE_CATALOG.md`](HOWTO_REGENERATE_CATALOG.md).

---

## Step 2 — Generating Degradation Sequences

`iterate_degrade.py` generates 10 pictures per source image in **two phases**:

- **Phase 1 — pictures 1–5, direct.** Each is a single img2img pass straight from the original with a gentle strength ramp (0.10 → 0.30) and a per-artwork fixed seed. One VAE roundtrip per picture, so these stay genuinely close to the source: subtle, coherent drift.
- **Phase 2 — pictures 6–10, chained.** Each output becomes the next input (true *model collapse*) with strength 0.22 → 0.42 and a per-step seed. VAE-roundtrip damage and hallucinations compound: the paint surface disintegrates and the figure falls apart with accelerating wrongness while the composition survives.

The 10 pictures map directly onto the gallery experience: the installation shows one picture every 3 seconds and measures which one breaks the visitor.

### Algorithm

```
load source image
query LLaVA once → description_prompt
seed = crc32(filename)                                  # stable per artwork

for i in 1..5:                                          # phase 1: direct
    strength_i = 0.10 + (0.30 − 0.10) · (i − 1) / 4
    picture_i  = SD_img2img(original 512×512, prompt, strength_i, seed)

current = picture_5
for i in 6..10:                                         # phase 2: chained
    strength_i = 0.22 + (0.42 − 0.22) · (i − 6) / 4
    picture_i  = SD_img2img(current, prompt, strength_i, seed + i)
    current    = picture_i

save original as 0000.jpg; pictures as <i:04d>.png      # guidance 6.0, steps 25
```

Full strength schedule: `0.10 · 0.15 · 0.20 · 0.25 · 0.30 │ 0.22 · 0.27 · 0.32 · 0.37 · 0.42` (the `│` marks the phase switch). The first pictures stay almost faithful — the visitor should not be jolted immediately — the collapse sets in at picture 6 and deepens to full disintegration by 10. This mirrors the uncanny-valley curve itself: a slow approach, then a plunge.

### Why two phases (findings from visual testing)

1. **A pure chain fails early.** Every img2img pass sends the image through SD's VAE (encode → latent → decode) plus a resize to 512×512. That roundtrip repaints fine texture *regardless of strength*; chained from picture 1, the damage compounds and the paint surface is mush by picture 5 — too much, too early.
2. **A pure direct ramp fails late.** Single passes at high strength re-cohere: instead of collapsing, picture 10 becomes a clean *different* painting. No disintegration character.
3. **Chain strength must stay low.** Chained passes above ~0.5 also re-cohere into a new scene. Keeping the chain at 0.22–0.42 lets roundtrip damage accumulate into painterly disintegration while the composition survives.
4. **Chain seeds must vary.** Re-injecting the *same* noise pattern into a feedback loop resonates and explodes into high-frequency artefacts within one step; per-step seeds (`seed + i`) produce organic collapse instead.

The hybrid keeps the best of both: pictures 1–5 genuinely sit next to the original (one roundtrip each), pictures 6–10 are true model collapse.

### Why this produces uncanny imagery

Stable Diffusion's training distribution has a strong prior on what a human looks like — symmetrical, smooth, proportions near the statistical mean. As its freedom grows, the model substitutes its prior for the painter's choices: features erode, asymmetries symmetrise, and details it cannot read (eyes, hands, fabric) are hallucinated back imperfectly. In the chained phase these errors become the next pass's ground truth and compound. The figure remains recognisably human while becoming deeply wrong — simultaneously over-familiar and foreign. That tension is the operating principle of the piece.

### Prompt generation (LLaVA)

Before the iteration loop, every pending source image is sent to a locally-running
LLaVA instance (via Ollama) — all prompts are fetched in parallel across a thread
pool before Stable Diffusion loads, so the GPU never waits on the LLM.

The system prompt (`core/llm.py: _SYSTEM_PROMPT`) does **not** ask for a neutral
description. It asks for a prompt that actively pushes toward the uncanny valley:

> "You are an expert in the uncanny valley phenomenon. When given an image, you
> write a concise Stable Diffusion img2img prompt (maximum 30 words,
> comma-separated tags only, no sentences) that will push the subject toward the
> uncanny valley: hyperrealistic but subtly wrong — glassy eyes, waxy skin,
> slightly off proportions, unsettling stillness. Output ONLY the prompt string,
> nothing else."

The response is truncated to 30 words and used as the Stable Diffusion prompt for
all 10 pictures of that artwork.

This matters for interpreting results. The degradation is **not** a neutral
"what does the model do when left alone" experiment: the prompt is a deliberate
artistic instrument, steering each pass toward waxiness and glassy stillness while
img2img strength controls how far it gets to act. Two forces produce the final
pictures — compounding VAE-roundtrip damage (unguided) and the uncanny prompt
(guided). Anyone reading the visitor data as evidence about model collapse in
general should know the prompt is on the scale.

**Fallback**: if Ollama is unreachable, `_fetch_prompt()` catches the error and
substitutes a fixed neutral prompt:

```
"classical painting, human figure, museum artwork, detailed"
```

Running without Ollama is therefore both fully deterministic and artistically
different — the collapse still happens, but nothing is steering it toward
waxy-and-glassy. The difference is clearest on figurative paintings and close to
invisible on sculpture photographs.

### Hardware requirements

| Device | Estimated runtime per image (10 iterations) |
|--------|---------------------------------------------|
| Apple M-series (MPS) | ~1 min |
| NVIDIA GPU (CUDA) | ~30 s |
| CPU only | ~10 min |

Device is detected automatically: MPS → CUDA → CPU.

The script is resumable: existing pictures are skipped; chained pictures reload their predecessor from disk. An artwork is considered complete when `0010.jpg` exists; delete its directory to force regeneration. Fixed seeds make reruns reproduce identical pictures.

### Model

`runwayml/stable-diffusion-v1-5` via Hugging Face `diffusers`. Downloaded automatically on first run (~4 GB). The model is cached in `~/.cache/huggingface/` and reused across runs.

---

## Output Format

```
uncanny_maker/
└── catalog_iterations_10/
    └── The_Dance_Class_438817/
        ├── 0000.jpg   ← source image (copy), shown during BASELINE
        ├── 0001.jpg   ← direct, strength 0.10 (texture retouch)
        │   …
        ├── 0005.jpg   ← direct, strength 0.30 (drifting, still the painting)
        ├── 0006.jpg   ← chained, collapse sets in
        │   …
        └── 0010.jpg   ← chained, disintegrated
```

All frames are 512×512 px (Stable Diffusion native resolution). The gallery app upscales them to fit the display via CSS `object-fit: contain`.

The directory is excluded from version control (see `.gitignore`). The older 50/100-frame sets in `catalog_iterations/` are kept as an archive but are no longer read by the app.

---

## Configuration

`uncanny_maker/config.py` — note that only the first three affect a normal run:

| Parameter | Default | Effect |
|-----------|---------|--------|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server address |
| `OLLAMA_MODEL` | `llava` | Vision LLM for prompt generation |
| `SD_MODEL_ID` | `runwayml/stable-diffusion-v1-5` | Diffusion base model |
| `DEFAULT_STRENGTH` | 0.55 | **Unused by `iterate_degrade.py`** — it computes strength from its own ramp constants |
| `DEFAULT_GUIDANCE` | 7.5 | **Unused by `iterate_degrade.py`** — overridden by its local `GUIDANCE = 6.0` |
| `NEGATIVE_PROMPT` | `"cartoon, anime, painting, …"` | **Unused by `iterate_degrade.py`** — it calls the pipeline without a negative prompt |

The bottom three are read only by `core/transform.py: run_img2img()`, a
single-shot helper used by `test_single.py` and the archived scripts. Editing them
has no effect on the production pipeline. (`NEGATIVE_PROMPT` also lists `painting`
as something to avoid, which would work against a catalog of classical paintings —
another reason the main pipeline does not use it.)

In `iterate_degrade.py` itself — these are the ones that matter:

| Variable | Default | Effect |
|----------|---------|--------|
| `ITERATIONS` | 10 | Pictures per artwork |
| `DIRECT_COUNT` | 5 | Pictures generated directly from the original |
| `DIRECT_START` / `DIRECT_END` | 0.10 / 0.30 | Strength ramp of the direct phase |
| `CHAIN_START` / `CHAIN_END` | 0.22 / 0.42 | Strength ramp of the chained phase (higher values re-cohere into a different painting instead of collapsing) |
| `GUIDANCE` | 6.0 | Overrides `DEFAULT_GUIDANCE` |
| `STEPS` | 25 | Inference steps per picture (speed vs. quality) |

Reducing `STEPS` to 15 roughly halves runtime with only minor quality loss. If the early drift is too strong, lower `DIRECT_END`; if the collapse is too tame, raise `CHAIN_END` (stay below ~0.5). Test a single artwork first with `python test_single.py catalog/<image>.jpg`.

---

## Archive

`uncanny_maker/_archive/` contains earlier approaches that were superseded:

- **4-stage approach** (`catalog_uncanny/`): Only four fixed degradation levels (0 %, 20 %, 60 %, 80 % strength). Produced discontinuous jumps rather than a gradual descent. Still supported by `CatalogManager` as a fallback format.
- **Feedback-chain degradation** (`catalog_iterations/`, 50–100 frames): each output fed back as the next input — model collapse as a compositional tool. Visually compelling in the late frames but unusable early: compounding VAE-roundtrip damage repainted the texture from picture 1. Replaced by direct per-picture generation with a fixed seed.
