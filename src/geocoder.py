"""AMap geocoding: convert spot names to coordinates."""

import json
import os
import time

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COORD_FILE = os.path.join(PROJECT_ROOT, "data", "spot_coordinates.json")


def load_coordinates() -> dict:
    """Load cached coordinates."""
    if os.path.exists(COORD_FILE):
        with open(COORD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_coordinates(coords: dict):
    """Save coordinates to cache."""
    os.makedirs(os.path.dirname(COORD_FILE), exist_ok=True)
    with open(COORD_FILE, "w", encoding="utf-8") as f:
        json.dump(coords, f, ensure_ascii=False, indent=2)


def geocode_one(address: str, api_key: str) -> dict | None:
    """Geocode a single address via AMap REST API."""
    url = "https://restapi.amap.com/v3/geocode/geo"
    params = {
        "key": api_key,
        "address": address,
        "output": "json",
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("status") == "1" and data.get("geocodes"):
            loc = data["geocodes"][0]["location"]
            lng, lat = loc.split(",")
            return {"lng": float(lng), "lat": float(lat)}
    except Exception:
        pass
    return None


def batch_geocode(
    spots: list[dict],
    api_key: str,
    existing: dict | None = None,
    delay: float = 0.15,
) -> tuple[dict, int, int]:
    """Geocode multiple spots in batches.

    Args:
        spots: list of {spot_name, city, area}
        api_key: AMap Web Service API key
        existing: previously cached coordinates
        delay: seconds between requests

    Returns:
        (all_coords, success_count, fail_count)
    """
    existing = existing or {}
    all_coords = dict(existing)

    # Build unique addresses to geocode
    to_geocode = []
    for s in spots:
        name = s.get("spot_name") or s.get("name")
        if not name:
            continue
        if name in all_coords:
            continue
        city = s.get("city", "")
        area = s.get("area", "")
        address = f"{city}{area}{name}"
        to_geocode.append({"name": name, "address": address})

    if not to_geocode:
        return all_coords, 0, 0

    print(f"Geocoding {len(to_geocode)} spots...")
    success = 0
    failed = 0

    # Batch requests (max 10 per request)
    batch_size = 10
    for i in range(0, len(to_geocode), batch_size):
        batch = to_geocode[i : i + batch_size]
        addresses = "|".join(b["address"] for b in batch)

        url = "https://restapi.amap.com/v3/geocode/geo"
        params = {"key": api_key, "address": addresses, "batch": "true", "output": "json"}

        try:
            resp = requests.get(url, params=params, timeout=15)
            data = resp.json()
            if data.get("status") == "1" and data.get("geocodes"):
                for idx, geo in enumerate(data["geocodes"]):
                    if idx < len(batch) and geo.get("location"):
                        lng, lat = geo["location"].split(",")
                        all_coords[batch[idx]["name"]] = {
                            "lng": float(lng),
                            "lat": float(lat),
                        }
                        success += 1
                    else:
                        failed += 1
            else:
                failed += len(batch)
        except Exception:
            failed += len(batch)

        if i + batch_size < len(to_geocode):
            time.sleep(delay)

        progress = min(i + batch_size, len(to_geocode))
        print(f"  {progress}/{len(to_geocode)} done ({success} ok, {failed} fail)")

    return all_coords, success, failed
