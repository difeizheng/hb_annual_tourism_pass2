"""Multi-city trip orchestration: city ordering + per-city day allocation.

Sits ABOVE the existing time_aware_assigner. Flow:
  1. Determine city visit order (LLM may suggest, or nearest-chain from departure)
  2. Allocate days per city (weighted by spot pool size + travel cost)
  3. Per city: pre-select spots by value to fit total capacity (prevents overflow),
     then reuse assign_spots_with_duration for intra-city assignment
  4. Insert transfer days between distant cities when needed

Single-city input degrades gracefully to the existing assigner output shape.
"""

from __future__ import annotations

from src.trip_planner.route_optimizer import haversine_distance
from src.trip_planner.time_aware_assigner import assign_spots_with_duration
from src.trip_planner.play_duration import estimate_play_duration

# --- Tuning constants -------------------------------------------------------
MIN_DAYS_PER_CITY = 1
# When inter-city gap exceeds this (km), burn a half transfer-day (capacity halved)
TRANSFER_DISTANCE_KM = 150.0
# Play-hours lost to a long transfer (car loading, checkout, drive fatigue)
TRANSFER_HOUR_LOSS = 3.0


def _city_centroid(spots: list[dict]) -> tuple[float, float]:
    lngs = [float(s.get("lng", 0)) for s in spots if s.get("lng")]
    lats = [float(s.get("lat", 0)) for s in spots if s.get("lat")]
    if not lngs or not lats:
        return (0.0, 0.0)
    return (sum(lngs) / len(lngs), sum(lats) / len(lats))


def order_cities(
    city_groups: dict[str, list[dict]],
    departure: dict,
    suggested_order: list[str] | None = None,
) -> list[str]:
    """Decide city visit order.

    If LLM suggested an order that covers all cities, validate & use it.
    Otherwise greedy nearest-chain from departure. Cities not in suggestion
    are appended in nearest-first order.
    """
    if not city_groups:
        return []
    dep_lng, dep_lat = float(departure.get("lng", 0)), float(departure.get("lat", 0))

    order: list[str] = []
    if suggested_order:
        for c in suggested_order:
            if c in city_groups and c not in order:
                order.append(c)
        # append any cities the suggestion missed
        remaining = [c for c in city_groups if c not in order]
    else:
        remaining = list(city_groups.keys())

    cur_lng, cur_lat = dep_lng, dep_lat
    while remaining:
        nearest = min(
            remaining,
            key=lambda c: haversine_distance(
                cur_lng, cur_lat, *_city_centroid(city_groups[c])
            ),
        )
        order.append(nearest)
        remaining.remove(nearest)
        cur_lng, cur_lat = _city_centroid(city_groups[nearest])
    return order


def allocate_days(
    city_order: list[str],
    city_groups: dict[str, list[dict]],
    total_days: int,
    departure: dict,
) -> dict[str, int]:
    """Allocate day counts per city.

    Weight per city = usable spot-hours (capped) + 1 base. Then top-up so the
    sum equals total_days. Transfer overhead already accounted separately.
    """
    if not city_order or total_days <= 0:
        return {c: 0 for c in city_order}

    weights: dict[str, float] = {}
    for c in city_order:
        pool_hours = sum(float(s.get("_play_hours", 2.0)) for s in city_groups[c])
        weights[c] = min(pool_hours, 12.0 * 3) + 1.0  # cap: 3 full days of spots

    total_w = sum(weights.values())
    alloc = {c: max(MIN_DAYS_PER_CITY, round(total_days * weights[c] / total_w)) for c in city_order}

    # Adjust to exactly total_days
    diff = total_days - sum(alloc.values())
    if diff != 0:
        # Sort by weight desc for adding, asc for removing
        order_by_w = sorted(city_order, key=lambda c: weights[c], reverse=(diff > 0))
        i = 0
        while diff != 0 and len(order_by_w) > 0:
            c = order_by_w[i % len(order_by_w)]
            if diff > 0:
                alloc[c] += 1
                diff -= 1
            else:
                if alloc[c] > MIN_DAYS_PER_CITY:
                    alloc[c] -= 1
                    diff += 1
                elif len([x for x in order_by_w if alloc.get(x, 0) > MIN_DAYS_PER_CITY]) == 0:
                    break
            i += 1
    return alloc


def _transfer_km(a: dict, b: dict) -> float:
    return haversine_distance(
        float(a.get("lng", 0)), float(a.get("lat", 0)),
        float(b.get("lng", 0)), float(b.get("lat", 0)),
    )


def _select_spots_for_capacity(
    city_spots: list[dict],
    travel_month: int,
    days: int = 1,
    per_day: float = 8.0,
    first_day_capacity: float | None = None,
) -> tuple[list[dict], list[dict]]:
    """Pre-select spots by seasonal score × duration value to fit daily bins.

    First-fit-decreasing over `days` bins. Transfer days only reduce the FIRST
    bin (morning drive); later days run at full `per_day`.
    Returns (selected, leftover).
    """
    from src.seasonal_recommender import calculate_seasonal_score

    enriched = []
    for s in city_spots:
        score, _reason = calculate_seasonal_score(s, _month_to_season(travel_month))
        hours = estimate_play_duration(
            category=s.get("category", ""),
            sub_category=s.get("sub_category", ""),
            level=s.get("level", ""),
            price=s.get("price", 0),
        )
        enriched.append({**s, "_play_hours": hours, "_seasonal_score": score})

    # value = seasonal score per hour of budget spent; long+good spots first
    enriched.sort(
        key=lambda s: (-(s["_seasonal_score"] * s["_play_hours"]), -s["_play_hours"])
    )

    n = max(days, 1)
    limits = [per_day] * n
    if first_day_capacity is not None:
        limits[0] = first_day_capacity
    used = [0.0] * n

    selected: list[dict] = []
    leftover: list[dict] = []
    for s in enriched:
        h = s["_play_hours"]
        if h > per_day:
            leftover.append(s)  # single spot longer than a whole day — skip
            continue
        for i in range(n):
            if used[i] + h <= limits[i]:
                used[i] += h
                selected.append(s)
                break
        else:
            leftover.append(s)
    return selected, leftover


def _month_to_season(month: int) -> str:
    from src.seasonal_recommender import MONTH_TO_SEASON
    return MONTH_TO_SEASON.get(month, "spring")


def plan_multi_city(
    spots: list[dict],
    departure: dict,
    num_days: int,
    travel_month: int = 6,
    city_order: list[str] | None = None,
    daily_capacity: float = 8.0,
) -> dict:
    """Full multi-city plan.

    Args:
        spots: candidate spot dicts (must have name/city/lng/lat; _play_hours optional)
        departure: {name, lng, lat} of home city
        num_days: total trip days
        travel_month: 1-12, used for seasonal filtering
        city_order: optional LLM/user-suggested city sequence
        daily_capacity: max play-hours per day

    Returns:
        {
            "city_order": [...],
            "alloc": {city: days},
            "days": [  # day_num is global 1..N, city = that day's city
                {"day_num", "date_hint", "city", "spots", "play_hours", "travel_km",
                 "is_transfer_day": bool, "transfer_from": str|None}
            ],
            "seasonal_warnings": [...],
            "unassigned": [...],
        }
    """
    if num_days <= 0:
        num_days = 1

    # Drop spots without usable coords — they'd crash distance math downstream.
    # Keep them listed so the UI can mention them as "无坐标，未纳入行程".
    usable, no_coords = [], []
    for s in spots:
        try:
            if s.get("lng") is not None and s.get("lat") is not None and float(s["lng"]) and float(s["lat"]):
                usable.append(s)
            else:
                no_coords.append(s)
        except (TypeError, ValueError):
            no_coords.append(s)

    # Group by city (preserve spots lacking coords in their city bucket)
    by_city: dict[str, list[dict]] = {}
    for s in usable:
        by_city.setdefault(s.get("city", "其他"), []).append(s)

    order = order_cities(by_city, departure, suggested_order=city_order)
    alloc = allocate_days(order, by_city, num_days, departure)

    all_days: list[dict] = []
    warnings_all: list[dict] = []
    unassigned_all: list[str] = []

    day_counter = 0
    prev_city_centroid: tuple[float, float] | None = None
    prev_city_name: str | None = None

    for city in order:
        city_spots = by_city[city]
        days_here = alloc[city]
        if days_here <= 0:
            continue

        cen = _city_centroid(city_spots)
        needs_transfer = (
            prev_city_centroid is not None
            and _transfer_km(
                {"lng": prev_city_centroid[0], "lat": prev_city_centroid[1]},
                {"lng": cen[0], "lat": cen[1]},
            ) > TRANSFER_DISTANCE_KM
        )

        # Transfer-in morning eats the FIRST day only; later days run full.
        first_cap = (daily_capacity - TRANSFER_HOUR_LOSS) if needs_transfer else None

        # Pre-select by value into per-day bins — the assigner's overflow
        # fallback would otherwise cram everything in regardless of capacity.
        city_spots_sel, leftover = _select_spots_for_capacity(
            city_spots, travel_month,
            days=days_here, per_day=daily_capacity,
            first_day_capacity=first_cap,
        )
        unassigned_all.extend(
            f"{s.get('name', s.get('spot_name', '未知景点'))}（容量不足，未排入）"
            for s in leftover
        )

        result = assign_spots_with_duration(
            spots=city_spots_sel,
            departure=departure,
            num_days=days_here,
            travel_month=travel_month,
            daily_capacity=daily_capacity,
            first_day_capacity=first_cap,
        )
        warnings_all.extend(result.get("seasonal_warnings", []))
        unassigned_all.extend(result.get("unassigned", []))

        for local_day in result["days"]:
            day_counter += 1
            entry = dict(local_day)
            entry["day_num"] = day_counter
            entry["city"] = city
            entry["is_transfer_day"] = needs_transfer and local_day["day_num"] == 1
            entry["transfer_from"] = prev_city_name if entry["is_transfer_day"] else None
            all_days.append(entry)

        prev_city_centroid = cen
        prev_city_name = city

    if no_coords:
        unassigned_all.extend(
            f"{s.get('name', s.get('spot_name', '未知景点'))}（无坐标，未纳入行程）"
            for s in no_coords
        )

    return {
        "city_order": order,
        "alloc": alloc,
        "days": all_days,
        "seasonal_warnings": warnings_all,
        "unassigned": unassigned_all,
    }
