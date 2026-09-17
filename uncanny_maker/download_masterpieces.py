"""
Download the famous multi-figure paintings — the ones an audience recognises.

The Met is a fine bulk source, but it does not hold the Mona Lisa, the Last
Supper, the Night Watch or Las Meninas. Those are the pictures whose decay the
visitor reads instantly, because they already know what the painting is supposed
to look like. This script fetches a hand-curated list of them from Wikimedia.

Resolution goes through the English Wikipedia article rather than through
hardcoded Commons filenames: for a painting article the lead image IS the
painting, and article titles are stable while Commons filenames are not. The
resolved Commons filename is printed for every download so the picks stay
auditable.

Images are fetched at MAX_WIDTH on the long side. The originals run up to
39137 x 22279 (Garden of Earthly Delights) and the pipeline generates at 512 px
anyway, so full resolution would only waste disk — the reason the last catalog
had to be deleted.

Saves to uncanny_maker/catalog/ as "{Title}_{pageid}.jpg", matching the naming
the rest of the pipeline expects: the stem is the artwork slug, the DB slug,
and the Stable Diffusion seed input.

Skips files that already exist — safe to re-run.

Usage:
    python download_masterpieces.py
    python download_masterpieces.py --width 2048
    python download_masterpieces.py --dry-run     # resolve and print, download nothing

No API key required. Every painting listed here is public domain.
"""

import re
import time
import argparse
import pathlib

import requests

CATALOG_DIR = pathlib.Path(__file__).parent / "catalog"
WIKI_API    = "https://en.wikipedia.org/w/api.php"
MAX_WIDTH   = 1600
BATCH       = 20  # Wikipedia accepts up to 50 titles per query; 20 keeps URLs short
DELAY       = 1.5  # between batches — Wikipedia answers 429 without it
RETRIES     = 5

# Wikimedia blocks the default requests user agent.
HEADERS = {
    "User-Agent": "VallisSimulacri/1.0 (TH Augsburg student art installation) python-requests"
}

# English Wikipedia article titles. Curated for the thing that worked at the
# exhibition: many people, recognisable, painted rather than sculpted.
PAINTINGS = [
    # ── Leonardo / Italian Renaissance ────────────────────────────────────
    "Mona Lisa",
    "The Last Supper (Leonardo)",
    "The School of Athens",
    "The Birth of Venus",
    "Primavera (painting)",
    "The Creation of Adam",
    "The Last Judgment (Michelangelo)",
    "Sistine Madonna",
    "Transfiguration (Raphael)",
    "The Wedding at Cana (Veronese)",
    "The Calling of Saint Matthew (Caravaggio)",
    "Supper at Emmaus (Caravaggio, London)",
    "Judith Beheading Holofernes (Caravaggio)",
    "Venus of Urbino",
    "Bacchus and Ariadne",

    # ── Louvre / French court and revolution ──────────────────────────────
    "The Coronation of Napoleon",
    "Liberty Leading the People",
    "The Raft of the Medusa",
    "Oath of the Horatii",
    "The Death of Marat",
    "The Intervention of the Sabine Women",
    "The Death of Socrates",
    "Napoleon Crossing the Alps",
    "Grande Odalisque",
    "The Turkish Bath",
    "The Embarkation for Cythera",
    "The Gleaners",
    "The Angelus (painting)",
    "A Burial At Ornans",
    "The Birth of Venus (Cabanel)",

    # ── Dutch and Flemish ─────────────────────────────────────────────────
    "The Night Watch",
    "The Anatomy Lesson of Dr. Nicolaes Tulp",
    "Syndics of the Drapers' Guild",
    "Girl with a Pearl Earring",
    "The Milkmaid (Vermeer)",
    "The Art of Painting",
    "The Garden of Earthly Delights",
    "The Haywain Triptych",
    "The Tower of Babel (Bruegel)",
    "The Peasant Wedding",
    "The Hunters in the Snow",
    "The Triumph of Death",
    "Netherlandish Proverbs",
    "Arnolfini Portrait",
    "Ghent Altarpiece",
    "The Descent from the Cross (Rubens, 1612–1614)",
    "Massacre of the Innocents (Rubens)",

    # ── Spanish ───────────────────────────────────────────────────────────
    "Las Meninas",
    "The Surrender of Breda",
    "The Triumph of Bacchus",
    "The Third of May 1808",
    "Saturn Devouring His Son",
    "Charles IV of Spain and His Family",
    "The Burial of the Count of Orgaz",

    # ── Later, still crowded and still recognisable ───────────────────────
    "The Ambassadors (Holbein)",
    "A Sunday Afternoon on the Island of La Grande Jatte",
    "Bal du moulin de la Galette",
    "Luncheon of the Boating Party",
    "The Dance Class",
    "Ophelia (Millais)",
    "The Lady of Shalott (painting)",
    "The Scream",
    "The Kiss (Klimt)",
]


def resolve(titles, width):
    """Article title → (pageid, image url) for a batch. Missing articles are dropped.

    Wikipedia answers 429 when batches follow each other too quickly, so every
    batch retries with a growing pause before giving up.
    """
    params = {
        "action":      "query",
        "titles":      "|".join(titles),
        "prop":        "pageimages",
        "piprop":      "original|thumbnail",
        "pithumbsize": width,
        "format":      "json",
        "redirects":   1,
    }
    last = None
    for attempt in range(RETRIES):
        try:
            resp = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=40)
            resp.raise_for_status()
            break
        except Exception as e:
            last = e
            wait = 3.0 * (attempt + 1)
            print(f"  … {e.__class__.__name__}, warte {wait:.0f}s")
            time.sleep(wait)
    else:
        raise last

    pages = resp.json().get("query", {}).get("pages", {})

    out = []
    for page in pages.values():
        # Prefer the scaled thumbnail; fall back to the original when Wikipedia
        # declines to scale (already smaller than the requested width).
        image = page.get("thumbnail") or page.get("original")
        if not image:
            print(f"  ! kein Bild: {page.get('title', '?')}")
            continue
        out.append({
            "pageid": page["pageid"],
            "title":  page["title"],
            "url":    image["source"],
            "w":      image.get("width", 0),
            "h":      image.get("height", 0),
        })
    return out


def commons_name(url):
    """Readable Commons filename out of an upload URL, for the audit log."""
    name = url.split("?", 1)[0].rsplit("/", 1)[-1]
    return requests.utils.unquote(name)


def safe_filename(title, pageid):
    """'The Night Watch' + 12345 → 'The_Night_Watch_12345.jpg'."""
    slug = re.sub(r"\s*\([^)]*\)", "", title)          # drop disambiguators
    slug = "".join(c if c.isalnum() or c in "-_ " else "" for c in slug)
    slug = slug.strip().replace(" ", "_")[:50].strip("_")
    return f"{slug}_{pageid}.jpg"


def download_image(url, dest):
    tmp = dest.with_suffix(".part")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=120, stream=True)
        resp.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
        tmp.rename(dest)
        return True
    except Exception as e:
        tmp.unlink(missing_ok=True)
        print(f"    ! {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Download famous paintings from Wikimedia")
    parser.add_argument("--width", type=int, default=MAX_WIDTH, help="long-side pixels")
    parser.add_argument("--dry-run", action="store_true", help="resolve and print, download nothing")
    args = parser.parse_args()

    CATALOG_DIR.mkdir(exist_ok=True)
    print(f"{len(PAINTINGS)} curated paintings — resolving via Wikipedia…")
    print(f"Saving to: {CATALOG_DIR}  (long side {args.width} px)\n")

    resolved = []
    for i in range(0, len(PAINTINGS), BATCH):
        resolved.extend(resolve(PAINTINGS[i:i + BATCH], args.width))
        time.sleep(DELAY)

    resolved.sort(key=lambda p: p["title"])
    print(f"{len(resolved)} of {len(PAINTINGS)} resolved\n")

    downloaded = skipped = 0
    for p in resolved:
        dest = CATALOG_DIR / safe_filename(p["title"], p["pageid"])
        if dest.exists():
            skipped += 1
            continue

        print(f"  {p['title'][:40]:42} {p['w']:>5}x{p['h']:<5}  {commons_name(p['url'])[:46]}")
        if args.dry_run or download_image(p["url"], dest):
            downloaded += 1

    verb = "would download" if args.dry_run else "downloaded"
    print(f"\nDone — {verb} {downloaded}, {skipped} already present")
    if not args.dry_run:
        total = len(list(CATALOG_DIR.glob("*.jpg")))
        print(f"catalog/ now holds {total} source images")
        print("Next step: python iterate_degrade.py")


if __name__ == "__main__":
    main()
