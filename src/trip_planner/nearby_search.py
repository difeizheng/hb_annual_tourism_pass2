"""AMap nearby POI search for hotels and restaurants."""
from __future__ import annotations

import requests


def search_nearby(
    lng: float,
    lat: float,
    api_key: str,
    poi_type: str = "",
    keywords: str = "",
    radius: int = 2000,
    max_results: int = 10,
) -> list[dict]:
    """Generic nearby POI search via AMap /v3/place/around.

    Args:
        lng, lat: Center point coordinates
        api_key: AMap Web Service API key
        poi_type: AMap type code (050100=hotels, 050101=restaurants)
        keywords: Text keyword filter
        radius: Search radius in meters (max 50000)
        max_results: Max number of results
    Returns:
        List of POI dicts with name, address, lng, lat, distance, type_name
    """
    url = "https://restapi.amap.com/v3/place/around"
    params = {
        "key": api_key,
        "location": f"{lng},{lat}",
        "radius": min(radius, 50000),
        "offset": max_results,
        "output": "json",
    }
    if poi_type:
        params["types"] = poi_type
    if keywords:
        params["keywords"] = keywords

    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
    except Exception:
        return []

    if data.get("status") != "1" or not data.get("pois"):
        return []

    results = []
    for p in data["pois"][:max_results]:
        loc = p.get("location", "0,0").split(",")
        results.append({
            "name": p.get("name", ""),
            "address": p.get("address", ""),
            "lng": float(loc[0]) if loc[0] else 0,
            "lat": float(loc[1]) if loc[1] else 0,
            "distance": int(p.get("distance", 0)),
            "type_name": p.get("type", ""),
            "photos": p.get("photos", []),
        })
    return results


def search_nearby_hotels(
    lng: float, lat: float, api_key: str,
    radius: int = 2000, max_results: int = 10,
) -> list[dict]:
    """Search nearby hotels (type=050100)."""
    return search_nearby(lng, lat, api_key, poi_type="050100", radius=radius, max_results=max_results)


def search_nearby_restaurants(
    lng: float, lat: float, api_key: str,
    radius: int = 2000, max_results: int = 10,
) -> list[dict]:
    """Search nearby restaurants (type=050101)."""
    return search_nearby(lng, lat, api_key, poi_type="050101", radius=radius, max_results=max_results)
