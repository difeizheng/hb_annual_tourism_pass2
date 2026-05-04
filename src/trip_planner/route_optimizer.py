"""Route optimization using nearest-neighbor algorithm and AMap driving API."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class RouteSegment:
    from_name: str
    to_name: str
    distance_km: float
    duration_min: int
    polyline: str = ""


@dataclass
class DayRoute:
    origin: dict
    ordered_spots: list[dict]
    segments: list[RouteSegment]
    total_distance_km: float
    total_duration_min: int
    ordered_polyline: str = ""


def haversine_distance(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """Haversine formula, returns km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def nearest_neighbor_optimize(origin: dict, spots: list[dict]) -> list[dict]:
    """Greedy nearest-neighbor TSP approximation. O(n^2), fine for n<20."""
    valid = [s for s in spots if s.get("lng") and s.get("lat")]
    if not valid:
        return []
    ordered = []
    remaining = list(valid)
    cur_lng = float(origin.get("lng", 0))
    cur_lat = float(origin.get("lat", 0))
    while remaining:
        nearest = min(
            remaining,
            key=lambda s: haversine_distance(cur_lng, cur_lat, float(s["lng"]), float(s["lat"])),
        )
        ordered.append(nearest)
        remaining.remove(nearest)
        cur_lng = float(nearest["lng"])
        cur_lat = float(nearest["lat"])
    return ordered


def compute_route(origin: dict, ordered_spots: list[dict], api_key: str) -> DayRoute:
    """Call AMap driving API to get actual road distances and polyline."""
    if not ordered_spots:
        return DayRoute(
            origin=origin,
            ordered_spots=[],
            segments=[],
            total_distance_km=0,
            total_duration_min=0,
        )

    origin_coord = f"{origin['lng']},{origin['lat']}"
    dest = ordered_spots[-1]
    dest_coord = f"{dest['lng']},{dest['lat']}"
    waypoints = ";".join(
        f"{s['lng']},{s['lat']}" for s in ordered_spots[:-1]
    )

    import requests
    url = "https://restapi.amap.com/v3/direction/driving"
    params = {
        "key": api_key,
        "origin": origin_coord,
        "destination": dest_coord,
        "extensions": "all",
        "output": "json",
    }
    if waypoints:
        params["waypoints"] = waypoints

    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
    except Exception:
        data = {}

    if data.get("status") != "1" or not data.get("route", {}).get("paths"):
        # Fallback: compute straight-line distances
        return _fallback_route(origin, ordered_spots)

    path = data["route"]["paths"][0]
    segments = []
    points_list = [origin] + list(ordered_spots)

    steps = path.get("steps", [])
    for step in steps:
        polyline = step.get("polyline", "")
        dist_m = int(step.get("distance", 0))
        dur_s = int(step.get("duration", 0))

        from_name = step.get("instruction", "")[:20] or "路段"
        to_name = ""

        segments.append(RouteSegment(
            from_name=from_name,
            to_name=to_name,
            distance_km=round(dist_m / 1000, 2),
            duration_min=round(dur_s / 60),
            polyline=polyline,
        ))

    total_dist_m = int(path.get("distance", 0))
    total_dur_s = int(path.get("duration", 0))
    ordered_polyline = path.get("polyline", "")

    return DayRoute(
        origin=origin,
        ordered_spots=ordered_spots,
        segments=segments,
        total_distance_km=round(total_dist_m / 1000, 2),
        total_duration_min=round(total_dur_s / 60),
        ordered_polyline=ordered_polyline,
    )


def _fallback_route(origin: dict, ordered_spots: list[dict]) -> DayRoute:
    """Compute straight-line distances when API fails."""
    segments = []
    total_dist = 0.0
    total_dur = 0
    points = [origin] + list(ordered_spots)
    polyline_parts = []
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        d = haversine_distance(float(a.get("lng", 0)), float(a.get("lat", 0)),
                                float(b.get("lng", 0)), float(b.get("lat", 0)))
        segments.append(RouteSegment(
            from_name=a.get("name", "起点"),
            to_name=b.get("name", "终点"),
            distance_km=round(d, 2),
            duration_min=round(d * 2),  # Rough estimate: 30km/h
        ))
        total_dist += d
        total_dur += round(d * 2)
        polyline_parts.append(f"{a.get('lng', 0)},{a.get('lat', 0)}")
    # Add final point to polyline
    if ordered_spots:
        last = ordered_spots[-1]
        polyline_parts.append(f"{last.get('lng', 0)},{last.get('lat', 0)}")

    return DayRoute(
        origin=origin,
        ordered_spots=ordered_spots,
        segments=segments,
        total_distance_km=round(total_dist, 2),
        total_duration_min=total_dur,
        ordered_polyline=";".join(polyline_parts),
    )


def _farthest_first_optimize(origin: dict, spots: list[dict]) -> list[dict]:
    """Sort by farthest-first then nearest-neighbor within clusters.
    Picks the farthest spot first, then greedily visits nearest from remaining.
    Tends to reduce backtracking.
    """
    valid = [s for s in spots if s.get("lng") and s.get("lat")]
    if not valid:
        return []
    # Start from the farthest spot from origin
    ordered = []
    remaining = list(valid)
    cur_lng = float(origin.get("lng", 0))
    cur_lat = float(origin.get("lat", 0))

    # First: pick farthest spot
    farthest = max(
        remaining,
        key=lambda s: haversine_distance(cur_lng, cur_lat, float(s["lng"]), float(s["lat"])),
    )
    ordered.append(farthest)
    remaining.remove(farthest)
    cur_lng = float(farthest["lng"])
    cur_lat = float(farthest["lat"])

    # Then nearest-neighbor for the rest
    while remaining:
        nearest = min(
            remaining,
            key=lambda s: haversine_distance(cur_lng, cur_lat, float(s["lng"]), float(s["lat"])),
        )
        ordered.append(nearest)
        remaining.remove(nearest)
        cur_lng = float(nearest["lng"])
        cur_lat = float(nearest["lat"])
    return ordered


def _clustered_optimize(origin: dict, spots: list[dict]) -> list[dict]:
    """Cluster spots by direction from origin, then visit clusters in arc order.
    Reduces zigzag by grouping nearby spots and visiting groups in geographic order.
    """
    import math as _math
    valid = [s for s in spots if s.get("lng") and s.get("lat")]
    if not valid:
        return []
    o_lng = float(origin.get("lng", 0))
    o_lat = float(origin.get("lat", 0))

    # Compute bearing from origin to each spot, sort by angle
    def bearing(s):
        dlng = _math.radians(float(s["lng"]) - o_lng)
        lat1 = _math.radians(o_lat)
        lat2 = _math.radians(float(s["lat"]))
        x = _math.sin(dlng) * _math.cos(lat2)
        y = _math.cos(lat1) * _math.sin(lat2) - _math.sin(lat1) * _math.cos(lat2) * _math.cos(dlng)
        return (_math.degrees(_math.atan2(x, y)) + 360) % 360

    sorted_by_angle = sorted(valid, key=bearing)

    # Within each angular cluster, sort by distance
    clusters = []
    current_cluster = [sorted_by_angle[0]]
    prev_angle = bearing(sorted_by_angle[0])
    for s in sorted_by_angle[1:]:
        angle = bearing(s)
        if abs(angle - prev_angle) > 45:
            clusters.append(current_cluster)
            current_cluster = [s]
            prev_angle = angle
        else:
            current_cluster.append(s)
            prev_angle = angle
    if current_cluster:
        clusters.append(current_cluster)

    # Sort each cluster by distance from origin (near first)
    for cluster in clusters:
        cluster.sort(key=lambda s: haversine_distance(o_lng, o_lat, float(s["lng"]), float(s["lat"])))

    # Flatten: visit clusters in angular order, nearest-first within each
    ordered = []
    for cluster in clusters:
        ordered.extend(cluster)
    return ordered


def generate_route_options(
    origin: dict,
    spots: list[dict],
    api_key: str,
) -> list[dict]:
    """Generate 3 route options with different ordering strategies.

    Returns list of dicts with: name, ordered_spots, total_distance_km,
    total_duration_min, ordered_polyline, pros, cons.
    """
    strategies = [
        {
            "name": "最短距离",
            "order_fn": nearest_neighbor_optimize,
            "pros": ["总驾驶里程最短", "适合时间充裕、慢慢玩的行程"],
            "cons": ["可能先跑远路去偏远景点"],
        },
        {
            "name": "最少驾驶时间",
            "order_fn": lambda o, s: _farthest_first_optimize(o, s),
            "pros": ["先远后近，减少回头路", "驾驶总时间最少"],
            "cons": ["第一天可能驾驶较长"],
        },
        {
            "name": "最顺路",
            "order_fn": lambda o, s: _clustered_optimize(o, s),
            "pros": ["按地理方向顺路游览", "不走回头路，节奏均匀"],
            "cons": ["总距离可能略长于最短方案"],
        },
    ]

    options = []
    for strat in strategies:
        ordered = strat["order_fn"](origin, spots)
        route = compute_route(origin, ordered, api_key)
        options.append({
            "name": strat["name"],
            "ordered_spots": ordered,
            "total_distance_km": route.total_distance_km,
            "total_duration_min": route.total_duration_min,
            "ordered_polyline": route.ordered_polyline,
            "pros": strat["pros"],
            "cons": strat["cons"],
        })

    return options
