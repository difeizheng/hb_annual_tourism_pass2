"""Time-aware day assignment considering play duration and seasonal availability."""
from __future__ import annotations

from src.trip_planner.play_duration import estimate_play_duration, get_opening_hours
from src.trip_planner.route_optimizer import haversine_distance
from src.seasonal_recommender import MONTH_TO_SEASON, calculate_seasonal_score

# Default daily activity capacity in hours
DEFAULT_DAILY_CAPACITY = 8.0
# Travel time estimate: minutes per km of straight-line distance
TRAVEL_MIN_PER_KM = 2.0


def assign_spots_with_duration(
    spots: list[dict],
    departure: dict,
    num_days: int,
    travel_month: int = 6,
    daily_capacity: float = DEFAULT_DAILY_CAPACITY,
) -> dict:
    """Assign spots to days respecting play duration and seasonal availability.

    Algorithm:
    1. Filter out seasonally unavailable spots (score=0)
    2. Group by city
    3. Sort city groups by distance from departure
    4. Greedy fill into day buckets up to daily_capacity hours
    5. Sort each day's spots by proximity

    Returns:
        {
            "days": [{spots, play_hours, city, travel_km}],
            "seasonal_warnings": [{spot, score, reason}],
            "unassigned": [spot_names],
        }
    """
    if num_days <= 0:
        num_days = 1

    season = MONTH_TO_SEASON.get(travel_month, "spring")

    # Step 1: Seasonal filter + duration estimation
    active_spots = []
    seasonal_warnings = []

    for spot in spots:
        score, reason = calculate_seasonal_score(spot, season)

        play_hours = estimate_play_duration(
            category=spot.get("category", ""),
            sub_category=spot.get("sub_category", ""),
            level=spot.get("level", ""),
            price=spot.get("price", 0),
        )

        spot_with_meta = {**spot, "_play_hours": play_hours, "_seasonal_score": score}

        if score == 0:
            seasonal_warnings.append({
                "spot_name": spot.get("name", ""),
                "score": score,
                "reason": reason,
            })
            continue

        active_spots.append(spot_with_meta)

    # Step 2: Group by city
    by_city: dict[str, list[dict]] = {}
    for s in active_spots:
        city = s.get("city", "其他")
        by_city.setdefault(city, []).append(s)

    # Step 3: Sort city groups by distance from departure
    dep_lng = float(departure.get("lng", 0))
    dep_lat = float(departure.get("lat", 0))

    def city_dist(city_spots: list[dict]) -> float:
        if not city_spots:
            return 999
        avg_lng = sum(float(s.get("lng", 0)) for s in city_spots) / len(city_spots)
        avg_lat = sum(float(s.get("lat", 0)) for s in city_spots) / len(city_spots)
        return haversine_distance(dep_lng, dep_lat, avg_lng, avg_lat)

    city_groups = sorted(by_city.values(), key=city_dist)

    # Step 4: Sort spots within each city by play duration (longest first)
    for group in city_groups:
        group.sort(key=lambda s: -s["_play_hours"])

    # Step 5: Greedy fill into day buckets
    days: list[list[dict]] = [[] for _ in range(num_days)]
    day_hours: list[float] = [0.0] * num_days

    for group in city_groups:
        for spot in group:
            hours = spot["_play_hours"]
            # Find day with most remaining capacity that can fit this spot
            best_day = None
            best_remaining = -1
            for d in range(num_days):
                remaining = daily_capacity - day_hours[d]
                if remaining >= hours and remaining > best_remaining:
                    best_day = d
                    best_remaining = remaining

            if best_day is not None:
                days[best_day].append(spot)
                day_hours[best_day] += hours
            else:
                # No day has enough capacity — put in the day with most remaining
                best_day = day_hours.index(min(day_hours))
                days[best_day].append(spot)
                day_hours[best_day] += hours

    # Step 6: Sort each day's spots by proximity (nearest-neighbor from departure)
    for i, day_spots in enumerate(days):
        prev_point = departure
        ordered = []
        remaining = list(day_spots)
        while remaining:
            nearest = min(
                remaining,
                key=lambda s: haversine_distance(
                    float(prev_point.get("lng", 0)),
                    float(prev_point.get("lat", 0)),
                    float(s.get("lng", 0)),
                    float(s.get("lat", 0)),
                ),
            )
            ordered.append(nearest)
            remaining.remove(nearest)
            prev_point = nearest
        days[i] = ordered

    # Build result
    result_days = []
    unassigned = []

    for i, day_spots in enumerate(days):
        # Compute intra-day travel distance
        travel_km = 0
        prev = departure
        for s in day_spots:
            d = haversine_distance(
                float(prev.get("lng", 0)), float(prev.get("lat", 0)),
                float(s.get("lng", 0)), float(s.get("lat", 0)),
            )
            travel_km += d
            prev = s

        primary_city = day_spots[0].get("city", "") if day_spots else ""

        result_days.append({
            "day_num": i + 1,
            "spots": day_spots,
            "play_hours": round(day_hours[i], 1),
            "travel_km": round(travel_km, 1),
            "primary_city": primary_city,
        })

    return {
        "days": result_days,
        "seasonal_warnings": seasonal_warnings,
        "unassigned": unassigned,
    }
