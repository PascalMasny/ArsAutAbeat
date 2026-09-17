"""
Download public-domain PAINTINGS with human figures from the Met Museum API.

Replaces download_human_figures.py, whose keyword searches on the Greek & Roman
department pulled in bronze jugs, strainers, rings and amphora fragments; the
objects that visibly did not work at the exhibition. This script applies three
hard filters and a ranking:

  1. classification / objectName must contain "painting"  → no vases, no bronzes
  2. the object must carry at least one person tag        → no landscapes, no still lifes
  3. fragments and studies are rejected outright

  Ranking: artworks are scored by how many people they show. Tags naming a
  distinct group (Men + Women + Children) and scene tags that imply a crowd
  (Banquets, Processions, Battles) score highest, so multi-figure paintings,
  the ones that worked, are downloaded first.

Two things the old script got wrong, both fixed here:

  • The Met API sits behind Akamai bot protection. A request carrying the
    default python-requests user agent is answered with HTTP 403 and an HTML
    block page, and parallel requests get flagged faster. Every call here goes
    through one Session with a descriptive user agent, serially, with retries.

  • Network errors are never swallowed. Failures are counted and reported, and
    the script refuses to finish quietly when nothing came back.

Saves full-resolution JPEGs to uncanny_maker/catalog/ under the same
"{Title}_{objectID}.jpg" convention the rest of the pipeline expects: the stem
is the artwork slug, the DB slug, and the Stable Diffusion seed input.

Skips files that already exist; safe to re-run.

Usage:
    python download_paintings.py                 # 200 paintings, multi-figure first
    python download_paintings.py --target 300
    python download_paintings.py --min-score 4   # only crowded scenes
    python download_paintings.py --dry-run       # rank and print, download nothing

No API key required. All images are public domain.
"""

import time
import argparse
import pathlib

import requests

CATALOG_DIR = pathlib.Path(__file__).parent / "catalog"
API_BASE    = "https://collectionapi.metmuseum.org/public/collection/v1"
DELAY       = 0.12   # between API calls; keeps Akamai calm
RETRIES     = 4

# 11 = European Paintings · 15 = Robert Lehman · 17 = Medieval Art · 7 = The Cloisters
DEPARTMENTS = [11, 15, 17, 7]

# One session for everything: connection reuse plus a user agent that identifies
# the project. Without this the API answers 403 with an Akamai block page.
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "VallisSimulacri/1.0 (TH Augsburg student art installation; non-commercial)",
})
# Accept is set per request, never on the session: the same session downloads
# the images, and images.metmuseum.org answers 406 Not Acceptable when the
# client claims to accept only JSON.
JSON_ACCEPT  = {"Accept": "application/json"}
IMAGE_ACCEPT = {"Accept": "image/jpeg,image/*,*/*"}

# Subject queries, ordered the way the exhibition reacted to them: scenes with
# many people first, single portraits last. The Met search is full-text over
# title and description, so these read as subjects rather than as object types.
QUERIES = [
    # ── crowded scenes ────────────────────────────────────────────────────
    "last supper", "crucifixion", "adoration of the magi", "nativity",
    "lamentation", "massacre", "battle", "triumph", "coronation", "procession",
    "banquet", "feast", "wedding", "dance", "concert", "card players",
    "market scene", "tavern", "peasants", "harvest", "hunt", "crowd",
    "assembly", "council", "sacrifice", "judgment", "abduction",
    "supper at emmaus", "pentecost", "resurrection", "entombment",
    "shepherds", "family group", "soldiers", "musicians", "children playing",
    # ── two or three figures ──────────────────────────────────────────────
    "madonna and child", "holy family", "mother and child", "lovers",
    "venus and cupid", "mars and venus", "annunciation", "visitation",
    "saint and donor", "allegory", "mythology", "history painting",
    # ── single figures (still good, ranked lower) ─────────────────────────
    "portrait", "woman", "man", "young woman", "saint", "christ", "virgin",
    "nude", "renaissance", "baroque", "self-portrait", "figure", "scene",
]

# Each tag naming a kind of person present in the picture.
PERSON_TAGS = {
    "men", "women", "children", "infants", "boys", "girls", "mothers",
    "fathers", "families", "saints", "angels", "soldiers", "musicians",
    "dancers", "shepherds", "peasants", "servants", "nobility", "kings",
    "queens", "nudes", "priests", "monks", "nuns", "warriors", "knights",
    "hunters", "beggars", "sailors", "merchants", "scholars", "poets",
    "portraits", "couples", "brides", "grooms", "apostles", "prophets",
    "martyrs", "donors", "putti", "cherubs", "cupid", "christ",
    "virgin mary", "madonna", "adam", "eve", "moses", "venus", "mars",
    "apollo", "diana", "hercules", "jupiter", "bacchus", "minerva",
    "john the baptist", "mary magdalene", "saint peter", "saint john",
}

# Tags describing an activity that needs a group of people. Worth double,
# because they are the strongest available signal for a populated canvas.
SCENE_TAGS = {
    "crowds", "groups", "processions", "banquets", "feasts", "battles",
    "weddings", "dancing", "games", "music", "working", "eating", "drinking",
    "markets", "fighting", "celebrations", "ceremonies", "meals", "hunting",
    "gambling", "playing", "teaching", "praying", "mourning", "suffering",
}

# A self-portrait is by definition one person.
SOLO_TAGS = {"self-portraits"}

# Object names that are never a usable source image.
REJECT_WORDS = ("fragment", "sketch", "study", "cartoon", "sample", "swatch")


class BlockedError(RuntimeError):
    """The API answered with a bot-protection page instead of JSON."""


def api_get(path, params=None):
    """One GET against the Met API, with retries. Raises rather than returning junk."""
    last = None
    for attempt in range(RETRIES):
        try:
            resp = SESSION.get(f"{API_BASE}/{path}", params=params,
                               headers=JSON_ACCEPT, timeout=30)
            if resp.status_code == 403 and "html" in resp.headers.get("content-type", ""):
                raise BlockedError("HTTP 403; Akamai bot protection")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))  # linear backoff
    raise last


def search_objects(query, department):
    data = api_get("search", {
        "hasImages":      "true",
        "isPublicDomain": "true",
        "q":              query,
        "departmentId":   department,
    })
    return data.get("objectIDs") or []


def fetch_object(object_id):
    """Full metadata for one object, or None if it does not pass the filters."""
    obj = api_get(f"objects/{object_id}")

    url = obj.get("primaryImage") or obj.get("primaryImageSmall")
    if not url or not obj.get("isPublicDomain"):
        return None

    # Filter 1: it has to be a painting.
    kind = f"{obj.get('classification', '')} {obj.get('objectName', '')}".lower()
    if "painting" not in kind:
        return None

    title = obj.get("title") or "Untitled"
    if any(w in f"{title} {kind}".lower() for w in REJECT_WORDS):
        return None

    tags = [t["term"].lower() for t in (obj.get("tags") or []) if t.get("term")]

    # Filter 2: somebody has to be in it.
    score = figure_score(tags)
    if score <= 0:
        return None

    return {
        "id":     object_id,
        "title":  title,
        "artist": obj.get("artistDisplayName") or "Metropolitan Museum of Art",
        "date":   obj.get("objectDate", ""),
        "url":    url,
        "tags":   tags,
        "score":  score,
    }


def figure_score(tags):
    """How crowded the painting probably is. 0 means nobody is in it."""
    people = sum(1 for t in tags if t in PERSON_TAGS)
    if people == 0:
        return 0
    scenes = sum(1 for t in tags if t in SCENE_TAGS)
    solo   = sum(1 for t in tags if t in SOLO_TAGS)
    return people + 2 * scenes - 2 * solo


def safe_filename(title, object_id):
    """'The Harvesters' + 435809 → 'The_Harvesters_435809.jpg'."""
    slug = "".join(c if c.isalnum() or c in "-_ " else "" for c in title)
    slug = slug.strip().replace(" ", "_")[:50].strip("_")
    return f"{slug}_{object_id}.jpg"


def download_image(url, dest):
    tmp = dest.with_suffix(".part")
    try:
        resp = SESSION.get(url, headers=IMAGE_ACCEPT, timeout=180, stream=True)
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


def collect_candidates():
    """Object IDs from every query in every department, de-duplicated, order kept."""
    print(f"Searching {len(QUERIES)} subjects across {len(DEPARTMENTS)} departments…")
    candidates, seen, failures = [], set(), 0
    for query in QUERIES:
        found = 0
        for dept in DEPARTMENTS:
            try:
                ids = search_objects(query, dept)
            except Exception as e:
                failures += 1
                print(f"  ! search '{query}' dept {dept}: {e}")
                continue
            for obj_id in ids:
                if obj_id not in seen:
                    seen.add(obj_id)
                    candidates.append(obj_id)
                    found += 1
            time.sleep(DELAY)
        print(f"  {query:24} +{found:>4} new  (total {len(candidates)})")
    return candidates, failures


def main():
    parser = argparse.ArgumentParser(description="Download Met paintings with human figures")
    parser.add_argument("--target", type=int, default=200, help="how many paintings to end up with")
    parser.add_argument("--min-score", type=int, default=1, help="reject anything below this figure score")
    parser.add_argument("--dry-run", action="store_true", help="rank and print, download nothing")
    args = parser.parse_args()

    CATALOG_DIR.mkdir(exist_ok=True)
    existing_ids = {
        p.stem.rsplit("_", 1)[-1]
        for p in CATALOG_DIR.glob("*.jpg")
        if p.stem.rsplit("_", 1)[-1].isdigit()
    }
    print(f"Target: {args.target} paintings  ({len(existing_ids)} already in catalog/)")
    print(f"Saving to: {CATALOG_DIR}\n")

    candidate_ids, search_failures = collect_candidates()
    if not candidate_ids:
        raise SystemExit("\nNo candidates at all; the Met API is unreachable or blocking. Nothing was written.")

    # ── Fetch metadata and filter ─────────────────────────────────────────
    print(f"\nChecking {len(candidate_ids)} candidates (serial; the API blocks parallel access)…")
    paintings, fetch_failures = [], 0
    t0 = time.perf_counter()
    for n, obj_id in enumerate(candidate_ids, 1):
        try:
            meta = fetch_object(obj_id)
        except Exception as e:
            fetch_failures += 1
            meta = None
            if fetch_failures <= 5:
                print(f"\n  ! object {obj_id}: {e}")
        if meta and meta["score"] >= args.min_score:
            paintings.append(meta)
        if n % 25 == 0 or n == len(candidate_ids):
            rate = n / max(time.perf_counter() - t0, 0.01)
            eta = (len(candidate_ids) - n) / max(rate, 0.01)
            print(f"  {n}/{len(candidate_ids)} checked · {len(paintings)} kept, "
                  f"{fetch_failures} failed · ETA {eta/60:.1f} min   ", end="\r")
        time.sleep(DELAY)

    print(f"\n\n  {len(paintings)} paintings passed the filter "
          f"({time.perf_counter() - t0:.0f}s, {fetch_failures} fetch errors, "
          f"{search_failures} search errors)")

    if not paintings:
        raise SystemExit(
            "Nothing passed the filter. With this many errors that means the API blocked us, "
            "not that no paintings exist; wait a few minutes and re-run. Nothing was written."
        )

    # Crowded scenes first, so a partial run still gets the good ones.
    paintings.sort(key=lambda p: -p["score"])
    top = paintings[:args.target]
    crowded = sum(1 for p in top if p["score"] >= 4)
    print(f"  {crowded} of {len(top)} score ≥ 4 (multi-figure)\n")

    if args.dry_run:
        print("Ranking (dry run; nothing downloaded):\n")
        for i, p in enumerate(top, 1):
            print(f"  {i:>3}. [{p['score']:>2}] {p['title'][:50]:52} {', '.join(p['tags'][:6])}")
        return

    # ── Download ──────────────────────────────────────────────────────────
    downloaded = len(existing_ids)
    skipped = 0
    for p in paintings:
        if downloaded >= args.target:
            break
        if str(p["id"]) in existing_ids:
            skipped += 1
            continue

        dest = CATALOG_DIR / safe_filename(p["title"], p["id"])
        if dest.exists():
            skipped += 1
            continue

        print(f"  [{downloaded + 1:>3}/{args.target}] [{p['score']:>2}] "
              f"{p['title'][:46]:48} ({p['artist'][:24]})")
        if download_image(p["url"], dest):
            downloaded += 1

    print(f"\nDone: {downloaded} paintings in catalog/  ({skipped} already present)")
    print("Next step: python download_masterpieces.py   (the famous ones)")
    print("Then:      python iterate_degrade.py         (generate the sequences)")


if __name__ == "__main__":
    main()
