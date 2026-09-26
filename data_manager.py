import csv
import json
import math
import urllib.request
from pathlib import Path

from config import DATA_DIR, MAP_FILE, MAP_URL, USERS_FILE


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def download_map_if_needed():
    ensure_data_dir()
    if MAP_FILE.exists():
        return

    try:
        print("Downloading Tamil Nadu GeoJSON...")
        urllib.request.urlretrieve(MAP_URL, MAP_FILE)
        print(f"Saved map to {MAP_FILE}")
    except Exception as exc:
        raise RuntimeError(
            "Could not download the Tamil Nadu GeoJSON. "
            "Check your internet connection and run again."
        ) from exc


def load_geojson():
    download_map_if_needed()
    with open(MAP_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_property(feature, *names):
    props = feature.get("properties", {})
    for name in names:
        value = props.get(name)
        if value not in (None, "", "null"):
            return str(value)
    return "Prototype Zone"


def geometry_rings(geometry):
    if not geometry:
        return []
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates", [])
    if kind == "Polygon":
        return [coordinates]
    if kind == "MultiPolygon":
        return coordinates
    return []


def geometry_centroid(geometry):
    """Simple vertex-average centroid; sufficient for API lookup in prototype."""
    points = []
    for polygon in geometry_rings(geometry):
        for ring in polygon:
            points.extend(ring)

    if not points:
        return 0.0, 0.0

    lon = sum(p[0] for p in points) / len(points)
    lat = sum(p[1] for p in points) / len(points)
    return lat, lon


def load_census_profiles():
    """
    Loads the bundled Census 2011 prototype population file.

    The official Census of India exposes population/age/sex indicators at
    district, sub-district, town, village and ward levels. This bundled CSV
    currently uses district-level 2011 population so the prototype can show
    a real demographic exposure field immediately.
    """
    path = DATA_DIR / "census_tn_2011.csv"
    if not path.exists():
        return {}

    result = {}
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row["district"].strip()
            result[name.lower()] = {
                "population": int(row["population"]),
                "male": int(row.get("male", 0) or 0),
                "female": int(row.get("female", 0) or 0),
                "source_year": 2011,
                "source": row.get("source", "Census of India 2011"),
            }
    return result


# Districts created after Census 2011 → the 2011 district they were carved from.
POST_2011_DISTRICTS = {
    "chengalpattu": "Kancheepuram",
    "kallakurichi": "Viluppuram",
    "ranipet": "Vellore",
    "tirupathur": "Vellore",
    "tenkasi": "Tirunelveli",
    "mayiladuthurai": "Nagapattinam",
}

CENSUS_ALIASES = {
    "nilgiris": "the nilgiris",
    "kanyakumari": "kanniyakumari",
    "thoothukudi": "thoothukkudi",
    "tuticorin": "thoothukkudi",
    "tiruvallur": "thiruvallur",
    "villupuram": "viluppuram",
    "tiruvarur": "thiruvarur",
    "trichy": "tiruchirappalli",
    "kanchipuram": "kancheepuram",
}


def match_census_profile(name, profiles):
    """Find the Census 2011 row for a map district name (handles spelling variants)."""
    normalized = name.lower().strip()
    key = CENSUS_ALIASES.get(normalized, normalized)
    if key in profiles:
        return profiles[key]

    parent = POST_2011_DISTRICTS.get(normalized)
    if parent:
        return {
            "population": 0, "male": 0, "female": 0, "source_year": 2011,
            "source": "Census 2011",
            "note": f"Formed after 2011 from {parent}; its 2011 population is counted under {parent}.",
        }

    for candidate, profile in profiles.items():
        if len(normalized) > 4 and (candidate in normalized or normalized in candidate):
            return profile

    return {
        "population": 0, "male": 0, "female": 0, "source_year": 2011,
        "source": "No matched Census row", "note": "No Census 2011 row matched this area.",
    }


def load_response_capacity():
    """
    Optional: data/response_capacity.csv with columns district,capacity_index
    (0 = very low preparedness / response capacity, 100 = very high), e.g.
    derived from hospital beds, PHCs, cooling centres, ambulances.
    Returns {} if the file is not present.
    """
    from config import CAPACITY_FILE
    if not CAPACITY_FILE.exists():
        return {}
    result = {}
    try:
        with open(CAPACITY_FILE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    result[row["district"].strip().lower()] = max(0.0, min(100.0, float(row["capacity_index"])))
                except (KeyError, ValueError):
                    continue
    except Exception:
        return {}
    return result


def format_population(value):
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 100_000:
        return f"{value / 100_000:.2f}L"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def average_demographic_text(profile):
    pop = profile.get("population", 0)
    female = profile.get("female", 0)
    male = profile.get("male", 0)

    if not pop:
        return "Not available"
    if male + female:
        female_pct = female / (male + female) * 100
        return f"{format_population(pop)} people • Female {female_pct:.1f}%"
    return f"{format_population(pop)} people"
