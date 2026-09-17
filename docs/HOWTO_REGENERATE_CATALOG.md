# How to regenerate the artwork catalog from an empty checkout

Start from a fresh `git clone` with no images on disk and end with a running
installation showing all 169 artworks. This is the recovery path after the image
directories have been deleted — they are excluded from git by design, so a clone
never contains them.

Total wall-clock: **~3 hours on an Apple M-series**, most of it unattended.

## Prerequisites

- Python 3.10–3.12 (MediaPipe has no 3.13 wheels yet)
- A GPU: Apple M-series (MPS) or NVIDIA (CUDA). CPU works but takes ~10× longer.
- ~6 GB free disk (362 MB sources + ~0.7 GB pictures + 4 GB model cache)
- Network access to `collectionapi.metmuseum.org` and `huggingface.co`
- Optional: [Ollama](https://ollama.com) with the `llava` model, for prompt generation

```bash
cd uncanny_maker
pip install -r requirements.txt
```

## Step 1: Restore the source artworks

```bash
python restore_catalog.py
```

Downloads the exact 169 Met Museum images listed in
[`CATALOG_MANIFEST.md`](CATALOG_MANIFEST.md), each under its original filename.

Expected output:

```
Manifest: 169 artworks — 0 present, 169 missing
Target:   .../uncanny_maker/catalog

  [  1/169] 436284  A_Donor_Presented_by_a_Saint_436284
  ...
Restored 169/169 file(s).
```

**Use this to restore *this* catalog.** The download scripts discover artworks by
keyword search and select them by index into the result set. Met search results
shift over time, so re-running one yields a *different* catalog: different
artworks, different filename stems, and therefore different seeds and different
pictures. They are the right tool for building a *new* catalog, the wrong one for
restoring this one.

To build a **new** catalog instead, see
[Building a different catalog](#building-a-different-catalog) at the end.

Verify before continuing:

```bash
ls catalog/*.jpg | wc -l     # expect 169
```

If some artworks fail (the Met occasionally withdraws an image or revokes
public-domain status), the script lists them and continues. A smaller catalog is
fine — `CatalogManager` loads whatever is present.

## Step 2: Generate the picture sequences

Optional but recommended, in a second terminal:

```bash
ollama serve
ollama pull llava
```

Then:

```bash
python iterate_degrade.py
```

This is the long step: 169 artworks × 10 pictures, about **1 min per artwork on
M-series**, ~30 s on NVIDIA. Stable Diffusion v1.5 (~4 GB) downloads on first run
and is cached in `~/.cache/huggingface/`.

Expected output:

```
Catalog: 169 image(s) — 0 already complete, 169 to process
Settings: 10 pictures · direct 1–5 0.1→0.3 · chain 6–10 0.22→0.42 · guidance=6.0 · steps=25

Fetching LLaVA prompts in parallel (8 workers)…
  [A_Woman_Reading_435991.jpg] hyperrealistic woman reading, glassy eyes, waxy skin…

Loading Stable Diffusion pipeline…
[1/169] A_Donor_Presented_by_a_Saint_436284.jpg
   10/10  5.8s/iter  ETA 0.0 min
  Done in 1.0 min → catalog_iterations_10/A_Donor_Presented_by_a_Saint_436284
```

**Fully resumable.** Kill it and re-run any time; artworks whose `0010.jpg`
exists are skipped, and chained pictures reload their predecessor from disk.

`torch.compile()` is off by default because it is a pessimisation on Apple
silicon: its `mode="reduce-overhead"` relies on CUDA graphs, which MPS does not
have, so inductor falls back to code slower than eager. Measured on an M4, 25
steps at 648×408:

| | per picture | one-time |
|---|---|---|
| eager (default) | 10.2 s | — |
| `--compile` | 16.3 s | +49 s compilation |

On NVIDIA the original 15–25 % gain should still hold — enable it there:

```bash
python iterate_degrade.py --compile
```

## Step 3: Verify

```bash
ls -d catalog_iterations_10/*/ | wc -l              # expect 169
find catalog_iterations_10 -name '0010.jpg' | wc -l # expect 169 — all complete
du -sh catalog_iterations_10                        # expect ~0.5 GB (169 artworks)
```

Every artwork directory should hold 11 files, `0000.jpg` (the untouched source)
through `0010.jpg`.

## Step 4: Run the installation

```bash
cd ../ars_aut_abeat
./start.sh
```

Open `http://localhost:8000`. Raise both hands for 1.5 s to trigger a run, or
switch to SHOW mode and press Space.

## How exact is the reproduction?

Pictures are deterministic given the source image and its filename:
`iterate_degrade.py` seeds each artwork with `zlib.crc32(stem)` and each chained
step with `seed + i`. Same input file, same stem, same
`DIRECT_*`/`CHAIN_*`/`GUIDANCE`/`STEPS` → same pictures, bit for bit.

Two things break exactness, neither of which affects how the piece works:

1. **The LLaVA prompt.** Ollama's output is not deterministic, so a re-run
   produces a differently-worded anchoring prompt and therefore visually
   different (not worse) pictures. Running *without* Ollama is fully
   deterministic — every artwork falls back to the fixed prompt
   `"classical painting, human figure, museum artwork, detailed"`.
2. **Model or library versions.** A different `diffusers`, `torch`, or
   `stable-diffusion-v1-5` revision changes the numerics.

To reproduce the pictures exactly as first generated, run **without Ollama**.
To reproduce the *installation as exhibited*, any run is fine — the measurement
concept does not depend on specific pixels.

## Troubleshooting

**`No images found in .../catalog` from `iterate_degrade.py`**
Step 1 did not run or wrote elsewhere. Check `ls catalog/*.jpg | wc -l`.

**The app starts but stays on IDLE and never triggers**
`CatalogManager` found zero artworks, so `pick_next()` returns `None` and the
state machine cannot leave IDLE. It scans `uncanny_maker/catalog/*.jpg` and
requires a matching `catalog_iterations_10/{stem}/0010.jpg`. A source JPEG with
no completed sequence is silently skipped. Re-run Step 2.

**Pictures 404 in the browser, artwork title shows**
`/frames` is mounted at import time only if `catalog_iterations_10/` exists.
If you generated pictures while the server was running, restart it.

**`RuntimeError: Cannot reach Ollama`**
Harmless. Prompt generation falls back to the fixed prompt. Start `ollama serve`
first if you want LLaVA-guided prompts.

**Out of memory on MPS/CUDA**
Lower `STEPS` in `iterate_degrade.py` (25 → 15 roughly halves runtime and memory
pressure with minor quality loss). Do not add `--compile`; it raises memory
pressure without helping on MPS.

## Related

- [`CATALOG_MANIFEST.md`](CATALOG_MANIFEST.md) — the exact 169-artwork source list
- [`PIPELINE.md`](PIPELINE.md) — why the two-phase degradation works the way it does
- [`ARCHITECTURE.md`](ARCHITECTURE.md#configuration-reference-configpy) — every tunable parameter

---

## Building a different catalog

`restore_catalog.py` rebuilds the 169 artworks the installation was first shown
with. To collect a different — or larger — set instead, run the two download
scripts. They write into the same `catalog/` directory and skip files already
present, so they can be combined and re-run freely.

```bash
cd uncanny_maker

python download_paintings.py --target 200   # Met, filtered to paintings with people
python download_masterpieces.py             # the famous ones, from Wikimedia
```

**`download_paintings.py`** searches the Met's painting departments (European
Paintings, Robert Lehman, Medieval Art, The Cloisters) and then rejects anything
whose `classification` is not a painting and anything carrying no person tag.
What survives is ranked by how many people are in the picture, so multi-figure
works download first. `--min-score 4` restricts the run to crowded scenes;
`--dry-run` prints the ranking without downloading.

This replaces `download_human_figures.py`, whose searches on the Greek & Roman
department returned bronze jugs, strainers, rings and amphora fragments
alongside the figures.

**`download_masterpieces.py`** fetches a curated list of famous multi-figure
paintings that the Met does not hold — the Mona Lisa, the Last Supper, the Night
Watch, Las Meninas, Liberty Leading the People. It resolves each one through its
English Wikipedia article rather than through a hardcoded Commons filename,
because article titles are stable while Commons filenames are not, and prints the
resolved filename for every download so the picks stay auditable.

> **Both museum APIs reject anonymous clients.** The Met sits behind Akamai bot
> protection and answers a request carrying the default `python-requests` user
> agent with HTTP 403 and an HTML block page; Wikimedia answers 429. Every script
> here sends a descriptive user agent and retries with backoff. Parallel requests
> to the Met get flagged quickly, so metadata is fetched serially — a full
> 200-painting run takes roughly ten minutes, most of it waiting politely.

After either path, continue with Step 2 — `iterate_degrade.py` processes
whatever is in `catalog/`.
