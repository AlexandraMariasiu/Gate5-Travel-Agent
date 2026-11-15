'''
Helper to get the OSM link direclty to the place you want
'''

import sys
import time

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "Gate5-student-project/0.1 (university project)"


def search(query):
    """Return the first 3 Nominatim matches for a query."""
    params = {"q": query, "format": "json", "limit": 3}
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def main():
    queries = sys.argv[1:]
    if not queries:
        raise SystemExit('Give at least one name, e.g. "Colosseum, Rome"')

    for query in queries:
        print("\n" + query)
        results = search(query)
        if not results:
            print("  no result - try a different spelling")
        for r in results:
            if r.get("osm_type") not in ("node", "way", "relation"):
                continue
            key = f"openstreetmap:{r['osm_type']}/{r['osm_id']}"
            print("  ", key)
            print("     ", r["display_name"][:90])
            print("      type:", r.get("class"), "/", r.get("type"),
                  "| https://www.openstreetmap.org/" + f"{r['osm_type']}/{r['osm_id']}")
        time.sleep(1.1)        # Nominatim allows 1 request per second


if __name__ == "__main__":
    main()