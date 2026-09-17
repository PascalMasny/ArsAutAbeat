"""
Two-phase AI degradation — optimised for Apple M4 Max / MPS.

Each artwork yields ITERATIONS pictures in two phases:

  Phase 1 (pictures 1..DIRECT_COUNT)  — each generated DIRECTLY from the
      original via a single img2img pass with a gentle strength ramp and a
      per-artwork fixed seed. One VAE roundtrip per picture, so the early
      pictures stay genuinely close to the source: subtle, coherent drift.

  Phase 2 (pictures DIRECT_COUNT+1..ITERATIONS) — CHAINED: each output
      becomes the next input (true model collapse). VAE-roundtrip damage
      and hallucinations compound, so the paint surface degrades and the
      figure falls apart with accelerating wrongness.

LLaVA is called once per image to produce an anchoring prompt shared by
all pictures. A pure chain from picture 1 was tested and rejected — the
compounding roundtrip damage wrecks texture before the drift gets
interesting; a pure direct ramp lacks the collapse character at the end.

Performance features (M4 Max / MPS):
  • All LLaVA prompts are fetched in parallel before SD starts
  • Frame saves happen in a background I/O thread — SD never stalls on disk
  • enable_attention_slicing + enable_vae_slicing for MPS memory throughput
  • torch.compile() on the UNet: OFF by default, see --compile below
  • Exponential-moving-average ETA per image

Output:
    catalog_iterations_10/<stem>/0000.jpg  ← original
    catalog_iterations_10/<stem>/0001.jpg  ← iteration 1
    …
    catalog_iterations_10/<stem>/0010.jpg  ← iteration 10

The run is resumable: frames already on disk are skipped.

Usage:
    python iterate_degrade.py [--workers N] [--compile]

torch.compile() is opt-in because it is a pessimisation on Apple silicon. Its
mode="reduce-overhead" relies on CUDA graphs, which MPS does not have; inductor
falls back to code that runs slower than eager. Measured on an M4, 25 steps at
648x408: 10.2 s eager vs 16.3 s compiled, plus 49 s of one-time compilation.
On NVIDIA the original 15–25 % gain should still hold; hence the flag.
"""

import io
import sys
import time
import queue
import pathlib
import threading
import argparse
import concurrent.futures
from typing import Optional

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from PIL import Image

# ── Configuration ──────────────────────────────────────────────────────────────
CATALOG_DIR  = pathlib.Path(__file__).parent / "catalog"
OUTPUT_ROOT  = pathlib.Path(__file__).parent / "catalog_iterations_10"
IMAGE_EXTS   = {".jpg", ".jpeg", ".png", ".webp"}

ITERATIONS   = 10     # pictures per artwork

# Output format. The generated pictures carry no detail above the SD canvas
# size, so storing them at the source resolution as PNG only wastes disk; that
# is what made the previous catalog 11 GB and forced it to be deleted. Capped
# JPEG is visually identical and roughly twenty times smaller.
FRAME_EXT     = ".jpg"
JPEG_QUALITY  = 90
JPEG_SUBSAMPLING = 2   # 4:2:0; invisible on already-degraded output, ~25 % smaller
MAX_LONG_SIDE = 1600   # px on the long side of every stored picture

# SD canvas. A square 512x512 was fine for the portrait-format Met paintings,
# but the famous multi-figure works are wide; the Last Supper is 1.9:1.
# Squashing those into a square makes SD generate on a distorted canvas and the
# faces come back stretched, which reads as a rendering fault rather than as the
# uncanny. The canvas therefore follows the painting's aspect, clamped, because
# SD 1.5 starts duplicating figures on canvases far from its training size.
PIXEL_BUDGET  = 512 * 512
MAX_ASPECT    = 1.6

# Phase 1 — pictures 1..DIRECT_COUNT are generated DIRECTLY from the original
# (single img2img pass, fixed seed). This keeps them genuinely close to the
# source: subtle, coherent drift with exactly one VAE roundtrip each.
DIRECT_COUNT    = 5
DIRECT_START    = 0.10  # picture 1: barely perceptible retouch
DIRECT_END      = 0.30  # picture 5: clearly drifting, still the same painting

# Phase 2 — pictures DIRECT_COUNT+1..ITERATIONS are CHAINED (each output feeds
# the next input): true model collapse. VAE-roundtrip damage and hallucinations
# compound, so the paint surface degrades and the figure falls apart fast.
CHAIN_START     = 0.22  # picture 6: collapse sets in
CHAIN_END       = 0.42  # picture 10: disintegrated — higher values re-cohere
                        # into a clean DIFFERENT painting instead of collapsing

GUIDANCE        = 6.0   # classifier-free guidance scale
STEPS           = 25    # inference steps per picture
# ──────────────────────────────────────────────────────────────────────────────


def _strength_for(i: int) -> float:
    """Strength schedule across both phases."""
    if i <= DIRECT_COUNT:
        t = (i - 1) / max(DIRECT_COUNT - 1, 1)
        return DIRECT_START + (DIRECT_END - DIRECT_START) * t
    t = (i - DIRECT_COUNT - 1) / max(ITERATIONS - DIRECT_COUNT - 1, 1)
    return CHAIN_START + (CHAIN_END - CHAIN_START) * t


def _seed_for(stem: str) -> int:
    """Stable per-artwork seed so reruns reproduce the same sequence."""
    import zlib
    return zlib.crc32(stem.encode("utf-8"))


# ── Background I/O thread ─────────────────────────────────────────────────────

class _SaveWorker:
    """Saves PIL images to disk on a dedicated thread so SD is never I/O-bound."""

    def __init__(self):
        self._q: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def submit(self, image: Image.Image, path: pathlib.Path) -> None:
        self._q.put((image, path))

    def flush(self) -> None:
        self._q.join()

    def _loop(self) -> None:
        while True:
            image, path = self._q.get()
            try:
                if path.suffix.lower() in (".jpg", ".jpeg"):
                    image.save(path, quality=JPEG_QUALITY,
                               subsampling=JPEG_SUBSAMPLING, optimize=True)
                else:
                    image.save(path)
            finally:
                self._q.task_done()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _all_done(out_dir: pathlib.Path) -> bool:
    return (out_dir / f"{ITERATIONS:04d}{FRAME_EXT}").exists()


def _working_size(size: tuple[int, int]) -> tuple[int, int]:
    """SD canvas for a painting: keeps its aspect, both sides multiples of 8."""
    w, h = size
    aspect = max(1 / MAX_ASPECT, min(MAX_ASPECT, w / h))
    height = (PIXEL_BUDGET / aspect) ** 0.5
    width  = height * aspect
    snap   = lambda v: max(8, int(round(v / 8)) * 8)
    return snap(width), snap(height)


def _cap(image: Image.Image) -> Image.Image:
    """Scale down so the long side is at most MAX_LONG_SIDE. Never scales up."""
    w, h = image.size
    longest = max(w, h)
    if longest <= MAX_LONG_SIDE:
        return image
    scale = MAX_LONG_SIDE / longest
    return image.resize((round(w * scale), round(h * scale)), Image.LANCZOS)


def _fetch_prompt(img_path: pathlib.Path) -> tuple[pathlib.Path, str]:
    """Fetch a LLaVA prompt for one image (called from a thread pool)."""
    from core.llm import analyze_and_prompt
    image_bytes = img_path.read_bytes()
    try:
        prompt = analyze_and_prompt(image_bytes)
    except (RuntimeError, Exception):
        prompt = "classical painting, human figure, museum artwork, detailed"
    return img_path, prompt


def _ema(prev: float, new: float, alpha: float = 0.25) -> float:
    return alpha * new + (1.0 - alpha) * prev


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Iterative AI degradation pipeline")
    parser.add_argument("--workers", type=int, default=8,
                        help="Thread-pool workers for parallel LLaVA queries (default: 8)")
    parser.add_argument("--compile", action="store_true",
                        help="torch.compile() the UNet. Helps on CUDA, hurts on MPS (see module docstring)")
    args = parser.parse_args()

    images = sorted(p for p in CATALOG_DIR.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not images:
        print(f"No images found in {CATALOG_DIR}")
        print("Run download_human_figures.py first.")
        sys.exit(1)

    pending = [p for p in images if not _all_done(OUTPUT_ROOT / p.stem)]
    total   = len(images)
    done    = total - len(pending)
    print(f"Catalog: {total} image(s) — {done} already complete, {len(pending)} to process")
    if not pending:
        print("Nothing to do.")
        return

    print(f"Settings: {ITERATIONS} pictures · direct 1–{DIRECT_COUNT} {DIRECT_START}→{DIRECT_END} "
          f"· chain {DIRECT_COUNT+1}–{ITERATIONS} {CHAIN_START}→{CHAIN_END} "
          f"· guidance={GUIDANCE} · steps={STEPS}\n")

    # ── Pre-fetch all LLaVA prompts in parallel ────────────────────────────────
    print(f"Fetching LLaVA prompts in parallel ({args.workers} workers)…")
    prompts: dict[pathlib.Path, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_fetch_prompt, p): p for p in pending}
        for fut in concurrent.futures.as_completed(futures):
            img_path, prompt = fut.result()
            prompts[img_path] = prompt
            short = prompt[:60] + "…" if len(prompt) > 60 else prompt
            print(f"  [{img_path.name}] {short}")
    print()

    # ── Load Stable Diffusion pipeline ────────────────────────────────────────
    import torch
    from core.transform import load_pipeline

    print("Loading Stable Diffusion pipeline…")
    pipe = load_pipeline()

    # torch.compile() on the UNet, opt-in: a gain on CUDA, a loss on MPS
    if args.compile and hasattr(torch, "compile"):
        print("Compiling UNet with torch.compile() (first inference will be slower)…")
        try:
            pipe.unet = torch.compile(pipe.unet, mode="reduce-overhead", fullgraph=False)
        except Exception as e:
            print(f"  torch.compile() failed ({e}) — continuing without it")
    print("Pipeline ready.\n")

    saver = _SaveWorker()

    # ── Process each image sequentially ───────────────────────────────────────
    for idx, img_path in enumerate(pending, 1):
        out_dir = OUTPUT_ROOT / img_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)

        prompt = prompts[img_path]
        print(f"[{idx}/{len(pending)}] {img_path.name}")
        print(f"  Prompt: {prompt}")

        original    = _cap(Image.open(img_path).convert("RGB"))
        output_size = original.size
        work_size   = _working_size(output_size)
        source_work = original.resize(work_size, Image.LANCZOS)
        seed        = _seed_for(img_path.stem)

        # Frame 0 = unmodified source (capped, but never touched by SD)
        saver.submit(original.copy(), out_dir / f"0000{FRAME_EXT}")

        ema_sec: Optional[float] = None
        t0 = time.perf_counter()
        current_work: Optional[Image.Image] = None  # chain input for phase 2

        for i in range(1, ITERATIONS + 1):
            frame_path = out_dir / f"{i:04d}{FRAME_EXT}"
            if frame_path.exists():
                # Resume: direct pictures are independent; chained ones need
                # the predecessor as input, so reload it for the next step.
                if i >= DIRECT_COUNT:
                    current_work = Image.open(frame_path).convert("RGB").resize(work_size, Image.LANCZOS)
                continue
            t_iter = time.perf_counter()

            working = source_work if i <= DIRECT_COUNT else current_work
            # Direct phase: one fixed seed → coherent drift between pictures.
            # Chain phase: vary the seed per step — re-injecting the identical
            # noise pattern into a feedback loop resonates and explodes into
            # high-frequency artefacts instead of painterly collapse.
            generator = torch.Generator(pipe.device.type).manual_seed(
                seed if i <= DIRECT_COUNT else seed + i
            )
            result  = pipe(
                prompt            = prompt,
                image             = working,
                strength          = _strength_for(i),
                guidance_scale    = GUIDANCE,
                num_inference_steps = STEPS,
                generator         = generator,
            ).images[0]
            if i >= DIRECT_COUNT:
                current_work = result

            # Non-blocking save
            saver.submit(result.resize(output_size, Image.LANCZOS), frame_path)

            iter_sec = time.perf_counter() - t_iter
            ema_sec  = iter_sec if ema_sec is None else _ema(ema_sec, iter_sec)
            remaining = ema_sec * (ITERATIONS - i)
            print(
                f"  {i:>3}/{ITERATIONS}  {iter_sec:.1f}s/iter  "
                f"ETA {remaining/60:.1f} min          ",
                end="\r",
            )

        elapsed = time.perf_counter() - t0
        print(f"\n  Done in {elapsed/60:.1f} min → {out_dir}\n")

    # Flush remaining saves before exit
    print("Flushing remaining frame saves…")
    saver.flush()
    print(f"\nAll done. Output: {OUTPUT_ROOT}")


if __name__ == "__main__":
    main()
