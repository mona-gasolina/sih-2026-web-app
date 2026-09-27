"""
One full recompute for every district – shared by the desktop app (main.py)
and the web API (api.py), so both always show the same numbers.

No UI code here: weather → thermal stress → IMD heat-wave code → metrics.
"""
from data_manager import (
    geometry_centroid, get_property, load_census_profiles, load_geojson, load_response_capacity,
    match_census_profile,
)
from pipeline import compute_zone
from weather import get_tmax_normals, get_weather

NAME_KEYS = ("district", "District", "DISTRICT", "NAME_2", "name", "NAME")


def load_areas():
    """
    Returns (locations, demographics, capacities):
      locations    – [(district, lat, lon)] from the GeoJSON
      demographics – {district: Census 2011 profile}
      capacities   – {district lower-case: 0-100} from data/response_capacity.csv (optional)
    """
    profiles = load_census_profiles()
    locations, demographics = [], {}
    for feature in load_geojson().get("features", []):
        name = get_property(feature, *NAME_KEYS)
        lat, lon = geometry_centroid(feature.get("geometry"))
        locations.append((name, lat, lon))
        demographics[name] = match_census_profile(name, profiles)
    return locations, demographics, load_response_capacity()


def compute_all(locations, demographics, capacities, force=False, replay=None):
    """
    Weather for all districts (one batched request, cached 1 h) → metrics per district.
    Returns ({district: metrics}, info) – info as from weather.get_weather, plus
    "normals" (districts with Tmax normals) and "zone_errors" if any district failed.
    """
    data, info = get_weather(locations, force=force, replay=replay)
    normals = get_tmax_normals(locations)
    info["normals"] = len(normals)
    results = {}
    for name, _, _ in locations:
        if name in data:
            try:
                results[name] = compute_zone(
                    name, data[name], demographics.get(name, {}),
                    capacities.get(name.lower()), normals.get(name), replay,
                )
            except Exception as exc:          # one bad district must not break the rest
                info.setdefault("zone_errors", {})[name] = str(exc)
    return results, info
