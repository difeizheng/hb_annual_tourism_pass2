"""Auto-assign spots to trip days based on geographic proximity."""
from __future__ import annotations

from src.trip_planner.route_optimizer import haversine_distance


def cluster_by_proximity(spots: list[dict], max_distance_km: float = 30.0) -> list[list[dict]]:
    """Greedy spatial clustering. Spots within max_distance_km of cluster center go together."""
    valid = [s for s in spots if s.get("lng") and s.get("lat")]
    if not valid:
        return []

    # First group by city
    by_city: dict[str, list[dict]] = {}
    for s in valid:
        city = s.get("city", "其他")
        by_city.setdefault(city, []).append(s)

    clusters: list[list[dict]] = []
    for city, city_spots in by_city.items():
        remaining = list(city_spots)
        while remaining:
            seed = remaining.pop(0)
            cluster = [seed]
            c_lng = float(seed["lng"])
            c_lat = float(seed["lat"])
            still_going = True
            while still_going and remaining:
                still_going = False
                for s in list(remaining):
                    d = haversine_distance(c_lng, c_lat, float(s["lng"]), float(s["lat"]))
                    if d <= max_distance_km:
                        cluster.append(s)
                        remaining.remove(s)
                        # Update cluster center
                        n = len(cluster)
                        c_lng = (c_lng * (n - 1) + float(s["lng"])) / n
                        c_lat = (c_lat * (n - 1) + float(s["lat"])) / n
                        still_going = True
            clusters.append(cluster)

    return clusters


def assign_spots_to_days(
    spots: list[dict],
    departure: dict,
    num_days: int,
) -> list[list[dict]]:
    """Assign spots to days based on geographic proximity.

    Strategy:
    1. Cluster by proximity (within-city first)
    2. Distribute clusters across num_days
    3. Sort each day's spots by proximity to departure for first day,
       then by proximity to previous day's last spot
    """
    if num_days <= 0:
        num_days = 1

    clusters = cluster_by_proximity(spots)
    if not clusters:
        return [[] for _ in range(num_days)]

    # Sort clusters by distance from departure (closest first)
    dep_lng = float(departure.get("lng", 0))
    dep_lat = float(departure.get("lat", 0))

    def cluster_center_dist(cluster: list[dict]) -> float:
        if not cluster:
            return 999
        avg_lng = sum(float(s["lng"]) for s in cluster) / len(cluster)
        avg_lat = sum(float(s["lat"]) for s in cluster) / len(cluster)
        return haversine_distance(dep_lng, dep_lat, avg_lng, avg_lat)

    clusters.sort(key=cluster_center_dist)

    # Distribute clusters to days round-robin
    days: list[list[dict]] = [[] for _ in range(num_days)]
    for i, cluster in enumerate(clusters):
        day_idx = i % num_days
        days[day_idx].extend(cluster)

    return days
