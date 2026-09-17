# uncanny_maker

Offline preprocessing pipeline for *Vallis Simulacri*. Downloads public-domain artworks from the Met Museum Open Access API and generates 10-picture AI-degradation sequences used by the gallery application.

Run this once before the first installation session, or again whenever you want to expand the artwork catalog.

## Prerequisites

```bash
pip install -r requirements.txt
```

Optional but recommended: [Ollama](https://ollama.com) with the `llava` model for artwork-specific prompt generation.

```bash
ollama pull llava
ollama serve   # keep this running in a separate terminal
```

Without Ollama the pipeline falls back to a generic prompt — results are slightly less tailored but still work fine.

Stable Diffusion v1.5 (~4 GB) is downloaded automatically from Hugging Face on the first run of `iterate_degrade.py`.

## Usage

### Step 1 — Download source artworks

```bash
python download_paintings.py --target 200   # Met, paintings with people
python download_masterpieces.py             # the famous multi-figure works
```

`download_paintings.py` searches the Met's painting departments and keeps only objects whose classification is actually a painting and that carry a person tag, ranked by how many people are in the picture so multi-figure works come first. `--min-score 4` restricts the run to crowded scenes; `--dry-run` prints the ranking without downloading.

`download_masterpieces.py` adds ~60 paintings the Met does not hold (Mona Lisa, the Last Supper, the Night Watch, Las Meninas), from Wikimedia at 1600 px.

Both skip files already on disk, so they combine freely and are safe to re-run. To rebuild the *original* exhibition catalog instead, use `restore_catalog.py`.

> The Met API returns HTTP 403 to clients sending the default `python-requests` user agent, and flags parallel access. All scripts here send a descriptive user agent and fetch metadata serially.

### Step 2 — Test the curve on one artwork

```bash
python test_single.py catalog/<image>.jpg
```

Generates a single sequence into `catalog_iterations_10_TEST/` with the exact
pipeline settings so the degradation curve can be judged visually before
committing to a full run. Delete the TEST directory afterwards.

### Step 3 — Generate degradation sequences

```bash
python iterate_degrade.py
```

For each image in `catalog/`, generates 10 pictures with Stable Diffusion img2img in two phases: **pictures 1–5 directly from the original** (strength 0.10 → 0.30, fixed per-artwork seed; subtle coherent drift) and **pictures 6–10 chained** output-to-input (strength 0.22 → 0.42, per-step seeds; true model collapse, the paint disintegrates while the composition survives). Output frames are saved to `catalog_iterations_10/<slug>/0000.jpg` … `0010.jpg`.

Resumable: frames already on disk are skipped; an artwork is considered done when its `0010.jpg` exists. Interrupted runs continue from where they left off. Delete an artwork's output directory to force regeneration.

**Options:**

| Flag | Default | Effect |
|------|---------|--------|
| `--workers N` | `8` | Parallel threads for LLaVA prompt fetching |
| `--compile` | off | `torch.compile()` the UNet. A gain on CUDA, a ~60 % slowdown on MPS; measured 10.2 s vs 16.3 s per picture on an M4 |

**Tunable constants** (top of `iterate_degrade.py`):

| Variable | Default | Effect |
|----------|---------|--------|
| `ITERATIONS` | `10` | Pictures per artwork |
| `DIRECT_COUNT` | `5` | Pictures generated directly from the original |
| `DIRECT_START` / `DIRECT_END` | `0.10` / `0.30` | Strength ramp, direct phase |
| `CHAIN_START` / `CHAIN_END` | `0.22` / `0.42` | Strength ramp, chained phase (>~0.5 re-coheres into a different painting) |
| `GUIDANCE` | `6.0` | Classifier-free guidance scale |
| `STEPS` | `25` | Inference steps (speed vs. quality) |

## Hardware

Device is detected automatically: **MPS** (Apple Silicon) → **CUDA** → **CPU**.

Approximate runtimes per image at default settings (10 iterations):

| Hardware | Time |
|----------|------|
| M4 Max (MPS) | ~1 min |
| NVIDIA GPU (CUDA) | ~30 s |
| CPU only | ~10 min |

## Output

```
catalog_iterations_10/
└── The_Dance_Class_438817/
    ├── 0000.jpg   ← original (unmodified), shown during BASELINE
    ├── 0001.jpg   ← direct, strength 0.10
    │   …
    ├── 0005.jpg   ← direct, strength 0.30
    │   …
    └── 0010.jpg   ← chained, disintegrated
```

`catalog_iterations_10/` is excluded from version control. The app reads it via `UNCANNY_ITER_DIR` in `ars_aut_abeat/config.py`. The older 50/100-frame sets in `catalog_iterations/` are an archive of the previous concept and are no longer read.

## Directory Structure

```
uncanny_maker/
├── iterate_degrade.py          Main degradation script
├── test_single.py              One-artwork visual test of the current settings
├── download_paintings.py       Met scraper: paintings with people, ranked by figure count
├── download_masterpieces.py    Wikimedia: the famous multi-figure works
├── download_human_figures.py   Superseded by download_paintings.py
├── config.py                   Ollama / SD model settings
├── requirements.txt
├── catalog/                    Source images (git-ignored, ~400 MB)
├── catalog_iterations_10/      Generated 10-picture sequences (git-ignored)
├── catalog_iterations/         Old 50/100-frame sequences (archive, unused)
├── core/
│   ├── llm.py                  LLaVA prompt generation via Ollama
│   └── transform.py            Stable Diffusion img2img wrapper
└── _archive/
    └── old_scripts/            Superseded approaches (kept for reference)
```

## Configuration

All model/server settings are in `config.py`:

```python
OLLAMA_URL     = "http://localhost:11434"
OLLAMA_MODEL   = "llava"
SD_MODEL_ID    = "runwayml/stable-diffusion-v1-5"
DEFAULT_STRENGTH = 0.55
DEFAULT_GUIDANCE = 7.5
NEGATIVE_PROMPT  = "cartoon, anime, painting, sketch, blurry, ..."
```

See [`docs/PIPELINE.md`](../docs/PIPELINE.md) for a detailed explanation of the degradation algorithm and why it produces uncanny-valley-specific distortion.
