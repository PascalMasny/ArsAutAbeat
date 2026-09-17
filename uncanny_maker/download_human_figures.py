"""
SUPERSEDED by download_paintings.py; kept because docs/CATALOG_MANIFEST.md was
built with it.

Its searches on the Greek & Roman department returned bronze jugs, strainers,
rings and amphora fragments alongside the figures, which is how those objects
ended up in the exhibition catalog. Use download_paintings.py instead: it filters
on classification and ranks by how many people are in the picture.

Download ~100 public-domain images of human figures from the Met Museum API.
Covers classical sculptures, Renaissance/Baroque portraits, and figure paintings
(think: Mona Lisa, Girl with a Pearl Earring, marble statues, bronze figures).

Saves full-resolution JPEGs to uncanny_maker/catalog/.
Skips files that already exist — safe to re-run.

Usage:
    python download_human_figures.py

No API key required. All images are public domain.
"""

import time
import pathlib
import requests
from typing import Optional

CATALOG_DIR = pathlib.Path(__file__).parent / "catalog"
API_BASE    = "https://collectionapi.metmuseum.org/public/collection/v1"
TARGET      = 200
DELAY       = 0.3   # seconds between API calls

# Department IDs used below:
#   11 = European Paintings
#   13 = Greek & Roman Art
#   15 = Arts of Africa, Oceania, and the Americas (has some figure sculptures)
#   21 = Modern and Contemporary Art
#   6  = Asian Art (has some figure paintings/sculptures)
#
# Each entry: how many candidates to pick from that result set.
SEARCHES = [
    # ── Sculptures / statues (dept 13 = Greek & Roman) ───────────────────
    {"q": "kouros",                  "dept": 13, "pick": 8},
    {"q": "marble statue figure",    "dept": 13, "pick": 10},
    {"q": "standing nude",           "dept": 13, "pick": 8},
    {"q": "Aphrodite Venus",         "dept": 13, "pick": 8},
    {"q": "Apollo standing",         "dept": 13, "pick": 6},
    {"q": "Herakles Hercules",       "dept": 13, "pick": 6},
    {"q": "bronze figure standing",  "dept": 13, "pick": 6},
    {"q": "Doryphoros athlete",      "dept": 13, "pick": 5},
    {"q": "marble portrait bust",    "dept": 13, "pick": 6},
    {"q": "Dionysos figure",         "dept": 13, "pick": 5},
    {"q": "Eros Nike figure",        "dept": 13, "pick": 5},
    {"q": "satyr figure bronze",     "dept": 13, "pick": 4},

    # ── European paintings (dept 11) ──────────────────────────────────────
    {"q": "portrait woman",          "dept": 11, "pick": 12},
    {"q": "portrait man",            "dept": 11, "pick": 12},
    {"q": "Madonna Child",           "dept": 11, "pick": 7},
    {"q": "figure nude painting",    "dept": 11, "pick": 8},
    {"q": "Venus goddess painting",  "dept": 11, "pick": 7},
    {"q": "mythological figure",     "dept": 11, "pick": 8},
    {"q": "young woman portrait",    "dept": 11, "pick": 8},
    {"q": "allegory figure",         "dept": 11, "pick": 7},
    {"q": "Rembrandt portrait",      "dept": 11, "pick": 6},
    {"q": "Velazquez figure",        "dept": 11, "pick": 5},
    {"q": "Renaissance portrait",    "dept": 11, "pick": 8},
    {"q": "Baroque portrait",        "dept": 11, "pick": 7},
    {"q": "half-length portrait",    "dept": 11, "pick": 7},
    {"q": "saint figure painting",   "dept": 11, "pick": 6},
    {"q": "biblical figure",         "dept": 11, "pick": 6},
    {"q": "self portrait artist",    "dept": 11, "pick": 5},
    {"q": "nude figure oil",         "dept": 11, "pick": 6},

    # ── American & British paintings (dept 15 + dept 11 broader) ─────────
    {"q": "portrait colonial",       "dept": 11, "pick": 5},
    {"q": "Neoclassical figure",     "dept": 11, "pick": 5},
]



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

def search_objects(q: str, dept: int) -> list[int]:
    resp = SESSION.get(
        f"{API_BASE}/search",
        headers=JSON_ACCEPT,
        params={
            "hasImages":     "true",
            "isPublicDomain": "true",
            "q":             q,
            "departmentId":  dept,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("objectIDs") or []


def fetch_object(object_id: int) -> Optional[dict]:
    resp = SESSION.get(f"{API_BASE}/objects/{object_id}",
                       headers=JSON_ACCEPT, timeout=30)
    resp.raise_for_status()
    obj  = resp.json()
    url  = obj.get("primaryImage") or obj.get("primaryImageSmall")
    if not url:
        return None
    return {
        "id":     object_id,
        "title":  obj.get("title", "Untitled"),
        "artist": obj.get("artistDisplayName", "Unknown"),
        "url":    url,
    }


def safe_filename(title: str, object_id: int) -> str:
    slug = "".join(c if c.isalnum() or c in "-_ " else "" for c in title)
    slug = slug.strip().replace(" ", "_")[:50]
    return f"{slug}_{object_id}.jpg"


def download_image(url: str, dest: pathlib.Path) -> bool:
    try:
        resp = SESSION.get(url, headers=IMAGE_ACCEPT, timeout=180, stream=True)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=16384):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"    ! {e}")
        return False


def main():
    CATALOG_DIR.mkdir(exist_ok=True)

    # Count already-downloaded images
    existing = {p.stem.rsplit("_", 1)[-1] for p in CATALOG_DIR.glob("*.jpg")
                if p.stem.rsplit("_", 1)[-1].isdigit()}
    already  = len(list(CATALOG_DIR.glob("*.jpg")))
    print(f"Target: {TARGET} images  ({already} already in catalog/)")
    print(f"Saving to: {CATALOG_DIR}\n")

    seen_ids:   set[int]  = set()
    candidates: list[int] = []

    for search in SEARCHES:
        if len(candidates) >= TARGET * 4:
            break
        ids = search_objects(search["q"], search["dept"])
        new = [i for i in ids if i not in seen_ids]
        seen_ids.update(new)
        pick = search["pick"]
        # Spread picks evenly across the result set for variety
        step = max(1, len(new) // (pick * 2))
        selected = new[::step][:pick * 2]
        candidates.extend(selected)
        print(f"  dept {search['dept']}  '{search['q']}': "
              f"{len(ids)} results, {len(new)} new → {len(selected)} queued")
        time.sleep(DELAY)

    # Deduplicate while preserving order
    seen: set[int] = set()
    candidates = [x for x in candidates if not (x in seen or seen.add(x))]

    print(f"\n{len(candidates)} unique candidates — fetching metadata & downloading…\n")

    downloaded = already
    skipped    = 0
    for obj_id in candidates:
        if downloaded >= TARGET:
            break
        # Skip already-downloaded by object ID
        if str(obj_id) in existing:
            skipped += 1
            downloaded += 1
            continue

        try:
            meta = fetch_object(obj_id)
            time.sleep(DELAY)
        except Exception as e:
            print(f"  [{obj_id}] metadata error: {e}")
            continue

        if meta is None:
            continue

        filename = safe_filename(meta["title"], meta["id"])
        dest     = CATALOG_DIR / filename

        if dest.exists():
            skipped += 1
            downloaded += 1
            continue

        print(f"  [{downloaded+1:>3}/{TARGET}] {meta['title'][:50]}  "
              f"({meta['artist'][:22]})")
        if download_image(meta["url"], dest):
            downloaded += 1

        time.sleep(DELAY)

    new_count = downloaded - already
    print(f"\nDone — {new_count} new images downloaded  "
          f"({downloaded} total in catalog/,  {skipped} skipped)")
    print(f"Next step: run  python iterate_degrade.py  to generate 10-picture sequences.")


if __name__ == "__main__":
    main()
