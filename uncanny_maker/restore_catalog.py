"""
Restore the exact source catalog the installation was built from.

download_human_figures.py discovers artworks by keyword search and picks them by
index into the result set. Met search results shift over time, so re-running it
produces a DIFFERENT catalog — different artworks, different filename stems, and
therefore different Stable Diffusion seeds and different pictures.

This script instead downloads a fixed list of Met object IDs under their exact
original filenames, read from docs/CATALOG_MANIFEST.md. That restores the
byte-identical inputs, which makes iterate_degrade.py reproduce the same
sequences (the seed is crc32 of the filename stem).

Usage:
    python restore_catalog.py                 # restore everything missing
    python restore_catalog.py --dry-run       # list what would be downloaded
    python restore_catalog.py --manifest PATH # non-default manifest location

Skips files that already exist — safe to re-run and resumable.
"""

import re
import sys
import time
import pathlib
import argparse
from typing import Optional

import requests

CATALOG_DIR = pathlib.Path(__file__).parent / "catalog"
MANIFEST    = pathlib.Path(__file__).parent.parent / "docs" / "CATALOG_MANIFEST.md"
API_BASE    = "https://collectionapi.metmuseum.org/public/collection/v1"
DELAY       = 0.3

# Matches the manifest's artwork rows: | 12 | `Some_Slug_436284` | [436284](...) |
_ROW = re.compile(r"^\|\s*\d+\s*\|\s*`([^`]+)`\s*\|\s*\[(\d+)\]")



# The Met API sits behind Akamai bot protection: a request carrying the default
# python-requests user agent is answered with HTTP 403 and an HTML block page.
# One Session with a descriptive user agent fixes it.
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "VallisSimulacri/1.0 (TH Augsburg student art installation; non-commercial)",
})
# Accept is set per request, never on the session: the same session downloads
# the images, and images.metmuseum.org answers 406 Not Acceptable when the
# client claims to accept only JSON.
JSON_ACCEPT  = {"Accept": "application/json"}
IMAGE_ACCEPT = {"Accept": "image/jpeg,image/*,*/*"}

def parse_manifest(path: pathlib.Path) -> list[tuple[str, int]]:
    """Returns [(stem, object_id)] in manifest order."""
    if not path.exists():
        sys.exit(f"Manifest not found: {path}")
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _ROW.match(line.strip())
        if m:
            entries.append((m.group(1), int(m.group(2))))
    if not entries:
        sys.exit(f"No artwork rows parsed from {path} — is the manifest intact?")
    return entries


def image_url(object_id: int) -> Optional[str]:
    resp = SESSION.get(f"{API_BASE}/objects/{object_id}",
                       headers=JSON_ACCEPT, timeout=30)
    resp.raise_for_status()
    obj = resp.json()
    return obj.get("primaryImage") or obj.get("primaryImageSmall") or None


def download(url: str, dest: pathlib.Path) -> bool:
    tmp = dest.with_suffix(".part")
    try:
        resp = SESSION.get(url, headers=IMAGE_ACCEPT, timeout=180, stream=True)
        resp.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=16384):
                f.write(chunk)
        tmp.replace(dest)  # atomic: a half-written file never looks complete
        return True
    except Exception as e:
        print(f"    ! {e}")
        tmp.unlink(missing_ok=True)
        return False


def main():
    ap = argparse.ArgumentParser(description="Restore the exact source catalog")
    ap.add_argument("--dry-run", action="store_true", help="List missing files, download nothing")
    ap.add_argument("--manifest", type=pathlib.Path, default=MANIFEST, help="Manifest path")
    args = ap.parse_args()

    entries = parse_manifest(args.manifest)
    CATALOG_DIR.mkdir(exist_ok=True)

    missing = [(s, i) for s, i in entries if not (CATALOG_DIR / f"{s}.jpg").exists()]
    print(f"Manifest: {len(entries)} artworks — {len(entries) - len(missing)} present, "
          f"{len(missing)} missing")
    print(f"Target:   {CATALOG_DIR}\n")

    if not missing:
        print("Catalog already complete. Next: python iterate_degrade.py")
        return

    if args.dry_run:
        for stem, obj_id in missing:
            print(f"  would download {obj_id}  →  {stem}.jpg")
        print(f"\n{len(missing)} file(s) would be downloaded.")
        return

    ok = 0
    failed: list[tuple[str, int]] = []
    for n, (stem, obj_id) in enumerate(missing, 1):
        dest = CATALOG_DIR / f"{stem}.jpg"
        print(f"  [{n:>3}/{len(missing)}] {obj_id}  {stem[:52]}")
        try:
            url = image_url(obj_id)
            time.sleep(DELAY)
        except Exception as e:
            print(f"    ! metadata error: {e}")
            failed.append((stem, obj_id))
            continue

        if not url:
            # Public-domain status can be revoked, or the image withdrawn.
            print("    ! no primary image available for this object")
            failed.append((stem, obj_id))
            continue

        if download(url, dest):
            ok += 1
        else:
            failed.append((stem, obj_id))
        time.sleep(DELAY)

    print(f"\nRestored {ok}/{len(missing)} file(s).")
    if failed:
        print(f"\n{len(failed)} could not be restored:")
        for stem, obj_id in failed:
            print(f"  {obj_id}  {stem}")
        print("\nThese artworks will simply be absent from the catalog. The installation")
        print("runs fine with fewer artworks — CatalogManager loads whatever is present.")
    print("\nNext: python iterate_degrade.py")


if __name__ == "__main__":
    main()
