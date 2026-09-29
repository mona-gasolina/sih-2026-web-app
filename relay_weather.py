"""
Downloads the forecast for every district and saves it as one JSON file, in the
same format as data/weather_cache.json.

Run hourly by GitHub Actions (.github/workflows/weather.yml), which publishes the
file on the weather-data branch. The hosted server reads it from there
(HEAT_WEATHER_URL in render.yaml) instead of calling Open-Meteo itself: on shared
hosting the free Open-Meteo daily limit is used up by other apps on the same
internet address.

    python relay_weather.py out/weather.json
"""
import json
import sys
import time
from pathlib import Path

from data_manager import geometry_centroid, get_property, load_geojson
from weather import CACHE_VERSION, _fetch_with_retry

NAME_KEYS = ("district", "District", "DISTRICT", "NAME_2", "name", "NAME")   # as service.py


def main(out_path):
    locations = []
    for feature in load_geojson().get("features", []):
        lat, lon = geometry_centroid(feature.get("geometry"))
        locations.append((get_property(feature, *NAME_KEYS), lat, lon))
    payloads = _fetch_with_retry(locations)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"fetched_at": time.time(), "version": CACHE_VERSION,
                               "names": list(payloads), "payloads": payloads}), encoding="utf-8")
    models = sum(1 for p in payloads.values() if p.get("models_daily"))
    print(f"Saved {len(payloads)} districts ({models} with the other weather models) to {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out/weather.json")
