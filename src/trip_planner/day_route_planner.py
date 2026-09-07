"""Single-day route planner core — pure functions, no Streamlit dependencies.

Turns a user-picked sequence of stops (annual-pass spots and/or custom POIs
from AMap text search) into:
  1. an ordered route with real driving polyline via AMap directions API
  2. a time-slotted timeline (departure time + play duration + drive legs)
"""
from __future__ import annotations

import json
import os

from src.trip_planner.route_optimizer import (
    DayRoute,
    compute_route,
    haversine_distance,
    nearest_neighbor_optimize,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

# Custom (non-pass) stops persist here — user-built via POI search,
# reusable across sessions. Shape: {name: stop_dict}.
CUSTOM_STOPS_FILE = os.path.join(DATA_DIR, "custom_stops.json")

# AMap POI category → rough play duration (hours), for custom stops.
# Pass spots carry their own estimates from the knowledge graph.
CATEGORY_DEFAULT_HOURS = {
    "风景名胜": 2.5,
    "自然景观": 2.5,
    "公园广场": 1.5,
    "博物馆": 2.0,
    "科教文化场所": 2.0,
    "旅游景点": 2.5,
    "宗教场所": 1.5,
    "游乐园": 3.0,
    "度假场所": 3.0,
}


def _stop_to_dict(name: str, lng: float, lat: float, category: str = "",
                  play_hours: float = 2.0, price: float = 0.0,
                  custom: bool = True, address: str = "") -> dict:
    return {
        "name": name,
        "lng": float(lng),
        "lat": float(lat),
        "category": category or "旅游景点",
        "play_hours": float(play_hours),
        "price": float(price),
        "address": address,
        "_custom": custom,
    }


# ---------------------------------------------------------------
# Custom stops CRUD (data/custom_stops.json)
# ---------------------------------------------------------------
def load_custom_stops() -> dict:
    """Return {name: stop dict}."""
    if not os.path.exists(CUSTOM_STOPS_FILE):
        return {}
    try:
        with open(CUSTOM_STOPS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_custom_stops(stops: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CUSTOM_STOPS_FILE, "w", encoding="utf-8") as f:
        json.dump(stops, f, ensure_ascii=False, indent=2)


def upsert_custom_stop(name: str, lng: float, lat: float, category: str = "",
                       play_hours: float = 2.0, price: float = 0.0,
                       address: str = "") -> dict:
    """Insert or update a custom stop. Returns the stored dict."""
    stops = load_custom_stops()
    stop = _stop_to_dict(name, lng, lat, category, play_hours, price,
                         custom=True, address=address)
    stops[name] = stop
    save_custom_stops(stops)
    return stop


def delete_custom_stop(name: str) -> bool:
    stops = load_custom_stops()
    if name in stops:
        del stops[name]
        save_custom_stops(stops)
        return True
    return False


def estimate_custom_play_hours(category: str) -> float:
    """Rough play duration for a custom stop from its AMap type string."""
    for key, hours in CATEGORY_DEFAULT_HOURS.items():
        if key in (category or ""):
            return hours
    return 2.0


# ---------------------------------------------------------------
# Route build
# ---------------------------------------------------------------
def optimize_stop_order(origin: dict, stops: list[dict], optimize: bool = True) -> list[dict]:
    """Return stops in visit order. optimize=True runs nearest-neighbor from
    origin; False keeps user's manual order."""
    valid = [s for s in stops if s.get("lng") and s.get("lat")]
    if optimize and len(valid) >= 2:
        return nearest_neighbor_optimize(origin, valid)
    return valid


def build_day_route(origin: dict, ordered_stops: list[dict],
                    api_key: str) -> DayRoute:
    """Real driving route (polyline/distance/duration) through ordered stops.
    Falls back to straight-line segments if the API fails."""
    return compute_route(origin, ordered_stops, api_key)


def build_day_timeline(route: DayRoute, depart_hour: int = 8, depart_min: int = 0,
                       lunch_start: float = 12.0, lunch_hours: float = 1.0) -> dict:
    """Interleave play durations and real drive legs into a timed schedule.

    Returns {
      "items": [{kind: play|drive|lunch, name, start: "HH:MM", end,
                 hours, note}],
      "end_time": "HH:MM",
      "total_play_hours": float,
      "warnings": [...],
    }
    """
    items: list[dict] = []
    warnings: list[str] = []
    t = depart_hour + depart_min / 60.0

    def _fmt(x: float) -> str:
        h = int(x) % 24
        m = int(round((x - int(x)) * 60))
        if m == 60:
            h, m = h + 1, 0
        return f"{h:02d}:{m:02d}"

    lunch_done = False
    total_play = 0.0

    # Leg to first stop uses route.segments[0]; segment i goes stop i-1 → i.
    # compute_route returns segments per AMap step (not per stop), so we use
    # per-stop drive estimates from the matched path when available; simpler:
    # distribute total duration proportionally to straight-line legs.
    stops = route.ordered_spots
    n = len(stops)

    # Per-leg drive minutes: if AMap succeeded, route.total_duration_min is
    # road-accurate for the whole chain; allocate by haversine share.
    legs = []
    prev = {"lng": route.origin.get("lng"), "lat": route.origin.get("lat")}
    raw = []
    for s in stops:
        km = haversine_distance(prev["lng"], prev["lat"], s["lng"], s["lat"])
        raw.append(km)
        prev = {"lng": s["lng"], "lat": s["lat"]}
    total_km_hav = sum(raw) or 1.0
    if route.total_duration_min > 0:
        # road factor ~1.35x haversine is baked into AMap total already
        for km in raw:
            legs.append(max(10, int(route.total_duration_min * km / total_km_hav)))
    else:
        for km in raw:
            legs.append(max(10, int(km / 60 * 60 * 1.35)))  # ~45 km/h urban

    for i, s in enumerate(stops):
        # drive leg
        drive_min = legs[i]
        t_end = t + drive_min / 60.0
        items.append({
            "kind": "drive", "name": s["name"],
            "start": _fmt(t), "end": _fmt(t_end),
            "hours": round(drive_min / 60, 2),
            "note": f"车程约 {drive_min} 分钟",
        })
        t = t_end

        # lunch insert before the stop that brackets 12:00
        if not lunch_done and t >= lunch_start:
            items.append({
                "kind": "lunch", "name": "午餐",
                "start": _fmt(t), "end": _fmt(t + lunch_hours),
                "hours": lunch_hours, "note": "",
            })
            t += lunch_hours
            lunch_done = True

        play = float(s.get("play_hours") or 2.0)
        t_end = t + play
        items.append({
            "kind": "play", "name": s["name"],
            "start": _fmt(t), "end": _fmt(t_end),
            "hours": play,
            "note": f"门票 ¥{s.get('price', 0):.0f}" if s.get("price") else "门票免费/含年卡",
        })
        total_play += play
        t = t_end

    return {
        "items": items,
        "end_time": _fmt(t),
        "total_play_hours": round(total_play, 1),
        "warnings": warnings,
    }
