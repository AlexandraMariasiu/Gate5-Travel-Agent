import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

import requests

# make "src" importable when the script is run from the repo root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.schemas import HoursStatus, Place, PlaceDataset, Provider  # noqa: E402

# ----------------------------- settings ------------------------------

SOURCE = "openstreetmap"   # "openstreetmap" or "opentripmap"

CITY = "Rome"              # must be the same as PROTOTYPE_CITY in config.py
COUNTRY = "IT"             # two-letter country code of the city
RADIUS_METERS = 5000       # search radius around the city center
MAX_PLACES = 40
MAX_PER_CATEGORY = 10      # for diversity
OUTPUT_FILE = ROOT / "data" / "places.json"
OVERRIDES_FILE = ROOT / "data" / "place_overrides.json"


DATASET_VERSION = date.today().isoformat()

ALLOWED_OVERRIDE_FIELDS = [
    "opening_hours", "hours_status", "est_visit_minutes",
    "indoor", "interest_tags", "category",
]

VISIT_MINUTES = {
    "museums": 90,
    "historic": 45,
    "architecture": 30,
    "religion": 30,
    "natural": 60,
    "cultural": 60,
}
DEFAULT_VISIT_MINUTES = 45

# category -> interest tags
INTEREST_TAGS = {
    "museums": ["museums"],
    "historic": ["history"],
    "architecture": ["architecture"],
    "religion": ["religion"],
    "natural": ["nature"],
    "cultural": ["culture"],
}

INDOOR = {
    "museums": True,
    "natural": False,
}

# --- OpenStreetMap settings
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = [                      # public servers, tried in this order
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]
OVERPASS_ROUNDS = 3                    # how many times to go through the list
OVERPASS_TIMEOUT = (15, 90)            # (connect, read) seconds: fail fast, try the next server

CACHE_DIR = ROOT / "data" / "cache"
USE_CACHE = True
USER_AGENT = "Gate5-student-project/0.1 (university project)"  # Nominatim asks for this

# --- OpenTripMap settings
OTM_URL = "https://api.opentripmap.com/0.1/en"
OTM_MIN_RATE = "2"
OTM_KIND_TO_CATEGORY = {
    "museums": "museums", "historic": "historic", "architecture": "architecture",
    "religion": "religion", "natural": "natural", "cultural": "cultural",
}

PAUSE_SECONDS = 1.0        # be polite to the free services


# helpers

def place_key(provider, provider_id):
    """Key used in the overrides file, e.g. 'opentripmap:W123'."""
    return f"{provider}:{provider_id}"


def load_overrides():
    """Read data/place_overrides.json (empty settings if it does not exist)."""
    if not OVERRIDES_FILE.exists():
        return {"overrides": {}, "exclude": [], "include": []}
    with open(OVERRIDES_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return {
        "overrides": data.get("overrides", {}),
        "exclude": data.get("exclude", []),
        "include": data.get("include", []),
    }


def make_place(provider, provider_id, name, category, lat, lon,
               source_url, opening_hours=None):
    """Build a validated Place. Hours are 'known' only if we have the text."""
    if opening_hours:
        hours_status = HoursStatus.KNOWN
    else:
        hours_status = HoursStatus.UNKNOWN
        opening_hours = None
    return Place(
        provider=provider,
        provider_id=provider_id,
        name=name,
        city=CITY,
        category=category,
        interest_tags=INTEREST_TAGS.get(category, []),
        indoor=INDOOR.get(category),
        lat=lat,
        lon=lon,
        source_url=source_url,
        opening_hours=opening_hours,
        hours_status=hours_status,
        est_visit_minutes=VISIT_MINUTES.get(category, DEFAULT_VISIT_MINUTES),
        retrieved_at=date.today(),
    )


def apply_overrides(places, overrides):
    """Apply the manual changes and validate the result with the schema."""
    by_key = {place_key(p.provider.value, p.provider_id): p for p in places}

    for key in overrides:
        if key not in by_key:
            print("WARNING: override for", key, "ignored - place not in the dataset")

    result = []
    for key, place in by_key.items():
        changes = overrides.get(key, {})
        allowed = {k: v for k, v in changes.items() if k in ALLOWED_OVERRIDE_FIELDS}
        # rebuilding the Place runs the schema checks again
        result.append(Place(**{**place.model_dump(), **allowed}))
    return result


def print_summary(places):
    print("Places:", len(places))
    print("By category:", dict(Counter(p.category for p in places)))
    unknown = sum(1 for p in places if p.hours_status == HoursStatus.UNKNOWN)
    print("Opening hours unknown:", unknown, "of", len(places))


def choose_places(candidates, forced, exclude, provider):
    """
    candidates: list of (score, Place), forced: list of Place.
    Keeps the best places, with a limit per category and no duplicate names.
    """
    chosen = list(forced)
    names = {p.name.lower() for p in chosen}
    per_category = Counter(p.category for p in chosen)

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    for score, place in candidates:
        if len(chosen) >= MAX_PLACES:
            break
        if place_key(provider, place.provider_id) in exclude:
            continue
        if place.name.lower() in names:
            continue
        if per_category[place.category] >= MAX_PER_CATEGORY:
            continue
        chosen.append(place)
        names.add(place.name.lower())
        per_category[place.category] += 1
    return chosen


# ------------------------- OpenStreetMap source ----------------------

def geocode_city(city, country):
    """Return (lat, lon) of the city using Nominatim."""
    params = {"q": city, "countrycodes": country.lower(), "format": "json", "limit": 1}
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    time.sleep(PAUSE_SECONDS)
    results = response.json()
    if not results:
        raise SystemExit("Nominatim could not find the city: " + city)
    return float(results[0]["lat"]), float(results[0]["lon"])


def overpass_query(query):
    cache_file = CACHE_DIR / ("overpass_" + hashlib.sha1(query.encode("utf-8")).hexdigest()[:12] + ".json")
    if USE_CACHE and cache_file.exists():
        print("Using cached answer:", cache_file.name)
        with open(cache_file, encoding="utf-8") as f:
            return json.load(f)

    headers = {"User-Agent": USER_AGENT}
    last_error = None
    for attempt in range(OVERPASS_ROUNDS):
        for url in OVERPASS_URLS:
            try:
                response = requests.post(url, data={"data": query},
                                         headers=headers, timeout=OVERPASS_TIMEOUT)
                response.raise_for_status()
                elements = response.json()["elements"]
                time.sleep(PAUSE_SECONDS)
                if USE_CACHE:
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(elements, f, ensure_ascii=False)
                return elements
            except (requests.RequestException, ValueError, KeyError) as error:
                last_error = error
                print("Overpass failed on", url, "->", error)
        wait = 15 * (attempt + 1)
        print("All servers failed, waiting", wait, "seconds and retrying...")
        time.sleep(wait)
    raise SystemExit("Overpass is not available right now: " + str(last_error))


def build_overpass_query(lat, lon):
    """Named tourist places near the city center (nodes, ways and relations)."""
    around = f"(around:{RADIUS_METERS},{lat},{lon})"
    return f"""[out:json][timeout:90];
(
  nwr["tourism"~"^(attraction|museum|gallery|viewpoint)$"]["name"]{around};
  nwr["historic"~"^(monument|castle|ruins|archaeological_site|memorial|fort|city_gate|building)$"]["name"]{around};
  nwr["amenity"="place_of_worship"]["wikidata"]["name"]{around};
  nwr["leisure"="park"]["wikidata"]["name"]{around};
);
out center tags 500;"""


def element_coords(element):
    """Ways and relations have a 'center', nodes have lat/lon directly."""
    if "center" in element:
        return element["center"]["lat"], element["center"]["lon"]
    if "lat" in element:
        return element["lat"], element["lon"]
    return None


def osm_category(tags):
    if tags.get("tourism") in ("museum", "gallery"):
        return "museums"
    if tags.get("amenity") == "place_of_worship":
        return "religion"
    if tags.get("leisure") == "park":
        return "natural"
    if "historic" in tags:
        return "historic"
    return "cultural"


def osm_score(tags):
    """OSM has no ratings. Places with Wikipedia/Wikidata links are notable."""
    score = 0
    if "wikipedia" in tags:
        score += 2
    if "wikidata" in tags:
        score += 1
    if "tourism" in tags:
        score += 1
    return score


def osm_to_place(element):
    """Convert an OSM element to a Place (or None if it is not usable)."""
    tags = element.get("tags", {})
    coords = element_coords(element)
    name = tags.get("name:en") or tags.get("name")
    if not name or coords is None:
        return None
    osm_type = element["type"]
    osm_id = element["id"]
    return make_place(
        provider=Provider.OPENSTREETMAP,
        provider_id=f"{osm_type}/{osm_id}",
        name=name,
        category=osm_category(tags),
        lat=coords[0],
        lon=coords[1],
        source_url=f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
        opening_hours=tags.get("opening_hours"),
    )


def load_forced_places(include_keys):
    """Load all included places with one Overpass query."""
    keys = [k for k in dict.fromkeys(include_keys) if k.startswith("openstreetmap:")]
    if not keys:
        return []

    parts = ""
    for key in keys:
        osm_type, osm_id = key.split(":", 1)[1].split("/")
        parts += f"{osm_type}({osm_id});"
    elements = overpass_query(f"[out:json][timeout:60];({parts});out center tags;")

    by_key = {f"openstreetmap:{e['type']}/{e['id']}": e for e in elements}
    forced = []
    for key in keys:
        place = osm_to_place(by_key[key]) if key in by_key else None
        if place:
            forced.append(place)
        else:
            print("WARNING: could not load forced place", key)
    return forced


def collect_osm(settings):
    """Collect places from OpenStreetMap."""
    lat, lon = geocode_city(CITY, COUNTRY)
    print("City center:", lat, lon)

    forced = load_forced_places(settings["include"])

    elements = overpass_query(build_overpass_query(lat, lon))
    print("OSM elements found:", len(elements))

    candidates = []
    for element in elements:
        tags = element.get("tags", {})
        if "wikidata" not in tags and "wikipedia" not in tags:
            continue                      # keep only notable places
        place = osm_to_place(element)
        if place:
            candidates.append((osm_score(tags), place))

    return choose_places(candidates, forced, settings["exclude"], "openstreetmap")


# ------------------------- OpenTripMap source ------------------------

def otm_get(path, params):
    """Send one GET request to OpenTripMap and return the JSON answer."""
    api_key = os.environ.get("OPENTRIPMAP_API_KEY")
    if not api_key:
        raise SystemExit("Set the OPENTRIPMAP_API_KEY environment variable first.")
    params = dict(params)
    params["apikey"] = api_key
    response = requests.get(OTM_URL + path, params=params, timeout=30)
    response.raise_for_status()
    time.sleep(PAUSE_SECONDS)
    return response.json()


def otm_category(kinds_text):
    """Choose one simple category from the comma-separated kinds."""
    for kind in kinds_text.split(","):
        if kind in OTM_KIND_TO_CATEGORY:
            return OTM_KIND_TO_CATEGORY[kind]
    return "other"


def otm_to_place(detail):
    """Convert an OpenTripMap record to a Place (or None if not usable)."""
    if not (detail.get("xid") and detail.get("name") and "point" in detail):
        return None
    xid = detail["xid"]
    return make_place(
        provider=Provider.OPENTRIPMAP,
        provider_id=xid,
        name=detail["name"],
        category=otm_category(detail.get("kinds", "")),
        lat=detail["point"]["lat"],
        lon=detail["point"]["lon"],
        source_url=detail.get("otm") or "https://opentripmap.com/en/card/" + xid,
    )


def collect_otm(settings):
    """Collect places from OpenTripMap."""
    geo = otm_get("/places/geoname", {"name": CITY, "country": COUNTRY})
    print("City center:", geo["lat"], geo["lon"])

    forced = []
    for key in settings["include"]:
        if key.startswith("opentripmap:"):
            place = otm_to_place(otm_get("/places/xid/" + key.split(":", 1)[1], {}))
            if place:
                forced.append(place)

    params = {"radius": RADIUS_METERS, "lat": geo["lat"], "lon": geo["lon"],
              "kinds": "interesting_places", "rate": OTM_MIN_RATE,
              "format": "json", "limit": 200}
    short_records = [r for r in otm_get("/places/radius", params) if r.get("name")]
    short_records.sort(key=lambda r: r.get("rate", 0), reverse=True)
    print("Candidates found:", len(short_records))

    # fetch details only for the best ones (one request per place)
    candidates = []
    for record in short_records[: MAX_PLACES * 2]:
        place = otm_to_place(otm_get("/places/xid/" + record["xid"], {}))
        if place:
            candidates.append((record.get("rate", 0), place))
    return choose_places(candidates, forced, settings["exclude"], "opentripmap")


# ----------------------------- main ----------------------------------

def main():
    settings = load_overrides()

    if SOURCE == "openstreetmap":
        places = collect_osm(settings)
    elif SOURCE == "opentripmap":
        places = collect_otm(settings)
    else:
        raise SystemExit("SOURCE must be 'openstreetmap' or 'opentripmap'")

    places = apply_overrides(places, settings["overrides"])

    dataset = PlaceDataset(city=CITY, version=DATASET_VERSION, places=places)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dataset.model_dump(mode="json"), f, indent=2, ensure_ascii=False)

    print_summary(places)
    print("Saved to", OUTPUT_FILE)


if __name__ == "__main__":
    main()