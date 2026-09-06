"""Amenity planning: hotels (city-stay), meals, parking per multi-city day plan.

Design decisions (from grilling session):
- Hotels: one hotel per city block, near that city's spot centroid (not last spot)
- Meals: lunch near last morning spot, dinner near hotel; breakfast = hotel-included
- Parking: nearest parking lot POI per spot (self-drive scenario)
- Hotel tier follows travel_style from cost_estimator
"""

from __future__ import annotations

from src.trip_planner.nearby_search import (
    geocode_address,
    search_nearby,
    search_nearby_hotels,
    search_nearby_restaurants,
)

# AMap POI type codes
PARKING_TYPE = "150900"      # 停车场
HOTEL_TYPE = "050100"
RESTAURANT_TYPE = "050101"

# Hotel keyword hints per travel style (AMap keywords filter)
HOTEL_KEYWORDS = {
    "economy": "经济型",
    "midrange": "舒适型",
    "luxury": "高档",
}

# How far from centroid/day-route to search
HOTEL_RADIUS = 3000
MEAL_RADIUS = 1500
PARKING_RADIUS = 1000


def find_city_hotel(
    city: str,
    city_spots: list[dict],
    api_key: str,
    travel_style: str = "midrange",
    max_results: int = 8,
) -> dict | None:
    """Pick ONE hotel for a whole city block, near the spot centroid."""
    pts = [(float(s.get("lng", 0)), float(s.get("lat", 0))) for s in city_spots if s.get("lng")]
    if not pts or not api_key:
        return None
    lng = sum(p[0] for p in pts) / len(pts)
    lat = sum(p[1] for p in pts) / len(pts)

    kw = HOTEL_KEYWORDS.get(travel_style, "")
    candidates = search_nearby(
        lng, lat, api_key,
        poi_type=HOTEL_TYPE, keywords=kw,
        radius=HOTEL_RADIUS, max_results=max_results,
    )
    # Fallback: no keyword hit → plain hotel search
    if not candidates:
        candidates = search_nearby(
            lng, lat, api_key,
            poi_type=HOTEL_TYPE, radius=HOTEL_RADIUS, max_results=max_results,
        )
    if not candidates:
        return None

    best = candidates[0]
    return {
        **best,
        "city": city,
        "nights": 0,  # filled by caller
        "selection_reason": f"该城 {len(city_spots)} 个景点质心 {best['distance']}m 处，{kw or '综合'}首选",
    }


def plan_meals_for_day(
    day: dict,
    hotel: dict | None,
    api_key: str,
) -> dict:
    """Lunch near day's midpoint spot; dinner near hotel (or last spot)."""
    spots = day.get("spots", [])
    lunch = None
    dinner = None

    if spots:
        mid = spots[len(spots) // 2]
        lunch_cands = search_nearby_restaurants(
            float(mid.get("lng", 0)), float(mid.get("lat", 0)),
            api_key, radius=MEAL_RADIUS, max_results=5,
        )
        if lunch_cands:
            lunch = {**lunch_cands[0], "near": mid.get("name", "")}

    dinner_anchor = hotel or (spots[-1] if spots else None)
    if dinner_anchor and dinner_anchor.get("lng"):
        dinner_cands = search_nearby_restaurants(
            float(dinner_anchor.get("lng", 0)), float(dinner_anchor.get("lat", 0)),
            api_key, radius=MEAL_RADIUS, max_results=5,
        )
        if dinner_cands:
            dinner = {**dinner_cands[0], "near": dinner_anchor.get("name", "")}

    return {"lunch": lunch, "dinner": dinner}


def find_parking_for_spot(spot: dict, api_key: str) -> dict | None:
    """Nearest parking lot POI for a spot."""
    if not spot.get("lng") or not api_key:
        return None
    results = search_nearby(
        float(spot["lng"]), float(spot["lat"]), api_key,
        poi_type=PARKING_TYPE, radius=PARKING_RADIUS, max_results=3,
    )
    if not results:
        return None
    return results[0]
