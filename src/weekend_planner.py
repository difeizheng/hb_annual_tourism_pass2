"""Weekend getaway planner: generate 1-2 day trips from a departure city."""
from __future__ import annotations

from src.seasonal_recommender import (
    MONTH_TO_SEASON,
    calculate_seasonal_score,
)
from src.trip_planner.play_duration import estimate_play_duration
from src.trip_planner.route_optimizer import haversine_distance
from src.trip_planner.cost_estimator import estimate_trip_cost, FUEL_RATE_PER_KM, TOLL_RATE_PER_KM

# Style preferences: categories and sub-categories that match each style
STYLE_PREFS = {
    "休闲": {
        "categories": ["温泉康养", "休闲农业", "城市娱乐"],
        "sub_categories": ["温泉", "古镇", "博物馆", "寺庙", "剧场"],
    },
    "户外": {
        "categories": ["自然景观", "户外运动"],
        "sub_categories": ["漂流", "水上乐园", "登山", "溶洞", "植物园"],
    },
    "亲子": {
        "categories": ["主题乐园", "休闲农业", "城市娱乐"],
        "sub_categories": ["动物园", "游乐园", "水上乐园", "植物园"],
    },
    "文化": {
        "categories": ["人文历史"],
        "sub_categories": ["古镇", "博物馆", "寺庙", "剧场"],
    },
}


def plan_weekend(
    spots: list[dict],
    pass_info: dict[str, dict],
    home: dict,
    num_days: int,
    travel_month: int,
    style: str,
    max_spots_per_day: int = 4,
    owned_pass_id: str | None = None,
) -> dict:
    """Generate a weekend getaway plan.

    Args:
        spots: list of spot dicts with name/city/category/sub_category/price/level/lng/lat
        pass_info: pass info from build_pass_info
        home: {name, lng, lat} — departure point & return destination
        num_days: 1 or 2
        travel_month: 1-12
        style: "休闲"|"户外"|"亲子"|"文化"
        max_spots_per_day: max spots per day
        owned_pass_id: if set, prioritize spots covered by this pass

    Returns:
        Plan dict with days, budget, highlights, seasonal_tips, home_return_km
    """
    season = MONTH_TO_SEASON[travel_month]
    prefs = STYLE_PREFS.get(style, STYLE_PREFS["休闲"])

    # Build owned pass spot set
    owned_pass_spot_names: set[str] = set()
    if owned_pass_id and owned_pass_id in pass_info:
        owned_pass_spot_names = {s["name"] for s in pass_info[owned_pass_id]["spots_detail"]}

    # Score and filter spots
    scored = []
    for spot in spots:
        if not spot.get("lng") or not spot.get("lat"):
            continue
        score, reason = calculate_seasonal_score(spot, season)
        if score == 0:
            continue

        # Style bonus
        bonus = 0
        if spot.get("category") in prefs["categories"]:
            bonus += 2
        if spot.get("sub_category") in prefs["sub_categories"]:
            bonus += 3
        # Keyword match in name
        for kw in prefs["sub_categories"]:
            if kw in spot.get("name", ""):
                bonus += 2
                break

        # Owned pass bonus: big boost for spots covered by user's pass
        is_covered = spot["name"] in owned_pass_spot_names
        if is_covered:
            bonus += 10  # strong priority

        final_score = score + bonus
        dist = haversine_distance(home["lng"], home["lat"], spot["lng"], spot["lat"])

        # Prefer closer spots (distance penalty)
        dist_penalty = dist / 100.0  # -1 per 100km
        adjusted = max(final_score - dist_penalty, 0)

        play_hours = estimate_play_duration(
            spot.get("category", ""),
            spot.get("sub_category", ""),
            spot.get("level", ""),
            spot.get("price", 0),
        )

        scored.append({
            **spot,
            "_seasonal_score": score,
            "_adjusted_score": adjusted,
            "_play_hours": play_hours,
            "_dist_km": dist,
            "_reason": reason,
            "_owned_pass_covered": is_covered,
        })

    if not scored:
        return {"days": [], "budget": {}, "highlights": [], "seasonal_tips": "当前季节无推荐景点"}

    # Sort by adjusted score desc
    scored.sort(key=lambda x: -x["_adjusted_score"])

    # Select spots per day
    days = []
    used_names: set[str] = set()
    daily_hours = 7.0  # max play hours per day
    avg_speed = 50.0  # km/h average for door-to-door inter-city driving

    for day_num in range(1, num_days + 1):
        day_spots = []
        day_hours = 0.0
        day_km = 0.0
        day_drive_min = 0.0
        # First point of day is home (or hotel on Day 2+ for multi-day)
        if day_num == 1:
            prev_point = {"lng": home["lng"], "lat": home["lat"]}
        else:
            # Use last spot of previous day as approximate morning start
            prev_point = {"lng": days[-1]["spots"][-1]["lng"], "lat": days[-1]["spots"][-1]["lat"]}

        for spot in scored:
            if spot["name"] in used_names:
                continue
            if day_hours + spot["_play_hours"] > daily_hours:
                continue
            if len(day_spots) >= max_spots_per_day:
                break

            seg_dist = haversine_distance(prev_point["lng"], prev_point["lat"], spot["lng"], spot["lat"])
            spot = {**spot, "_drive_time_min": round(seg_dist / avg_speed * 60)}
            day_drive_min += spot["_drive_time_min"]

            day_spots.append(spot)
            day_hours += spot["_play_hours"]
            day_km += spot["_dist_km"]
            used_names.add(spot["name"])
            prev_point = {"lng": spot["lng"], "lat": spot["lat"]}

        if day_spots:
            # Compute return home / to hotel distance
            if num_days == 1:
                return_dest = home
            elif day_num < num_days:
                # Day 1: find nearest hotel zone to last spot
                return_dest = day_spots[-1]  # hotel search near last spot
            else:
                # Last day: return home
                return_dest = home

            return_km = haversine_distance(day_spots[-1]["lng"], day_spots[-1]["lat"],
                                           return_dest["lng"], return_dest["lat"])
            return_drive_min = round(return_km / avg_speed * 60)

            days.append({
                "day_num": day_num,
                "spots": day_spots,
                "play_hours": round(day_hours, 1),
                "travel_km": round(day_km, 0),
                "drive_min": round(day_drive_min, 0),
                "theme": style,
                # End-of-day info
                "end_point": {"lng": day_spots[-1]["lng"], "lat": day_spots[-1]["lat"]},
                "return_km": round(return_km, 0),
                "return_drive_min": return_drive_min,
                "is_overnight": (day_num < num_days),  # need hotel after this day
                "is_final_day": (day_num == num_days),
            })

    # Budget calculation
    all_spots = [s for d in days for s in d["spots"]]
    no_pass_total = sum(s["price"] for s in all_spots)
    total_km = sum(d["travel_km"] for d in days)
    # Add return-home driving
    total_return_km = sum(d.get("return_km", 0) for d in days)

    # If user has owned pass, use it as the reference
    owned_pass_savings = 0
    if owned_pass_id and owned_pass_id in pass_info:
        owned_names = {s["name"] for s in pass_info[owned_pass_id]["spots_detail"]}
        owned_covered_value = sum(s["price"] for s in all_spots if s["name"] in owned_names)
        owned_pass_savings = owned_covered_value - pass_info[owned_pass_id]["price"]

    # Find best pass coverage (for non-owned case)
    best_pass_id = None
    best_savings = 0
    for pid, pi in pass_info.items():
        pi_names = {s["name"] for s in pi["spots_detail"]}
        covered = [s for s in all_spots if s["name"] in pi_names]
        covered_value = sum(s["price"] for s in covered)
        savings = covered_value - pi["price"]
        if savings > best_savings:
            best_savings = savings
            best_pass_id = pid

    # If owned pass is set, override best_pass with it
    if owned_pass_id and owned_pass_id in pass_info:
        best_pass_id = owned_pass_id
        best_savings = owned_pass_savings

    driving_cost = (total_km + total_return_km) * (FUEL_RATE_PER_KM + TOLL_RATE_PER_KM)
    food_cost = 150 * num_days  # per person per day
    accommodation = 400 * max(num_days - 1, 0)  # one night for 2 days

    budget = {
        "no_pass_total": round(no_pass_total, 0),
        "best_pass_id": best_pass_id,
        "best_pass_display": pass_info[best_pass_id]["display"] if best_pass_id else None,
        "best_pass_savings": round(best_savings, 0),
        "driving_cost": round(driving_cost, 0),
        "food_cost": round(food_cost, 0),
        "accommodation": round(accommodation, 0),
        "grand_total_no_pass": round(no_pass_total + driving_cost + food_cost + accommodation, 0),
        "grand_total_with_pass": round(
            max(no_pass_total - best_savings, 0) + driving_cost + food_cost + accommodation +
            (pass_info[best_pass_id]["price"] if best_pass_id else 0), 0
        ),
        "home_return_km": round(total_return_km, 0),
    }

    # Highlights
    highlights = []
    for s in sorted(all_spots, key=lambda x: -x["_adjusted_score"])[:5]:
        highlights.append({
            "name": s["name"],
            "city": s["city"],
            "category": s["category"],
            "price": s["price"],
            "level": s.get("level", ""),
            "reason": s["_reason"],
            "play_hours": s["_play_hours"],
        })

    # Seasonal tips
    season_tips = {
        "spring": "春暖花开，注意早晚温差，带件薄外套",
        "summer": "炎热夏季，注意防晒补水，优先室内/水上活动",
        "autumn": "秋高气爽，适合户外，注意景区人流高峰",
        "winter": "寒冷冬季，注意保暖，温泉/室内景点优先",
    }

    return {
        "days": days,
        "budget": budget,
        "highlights": highlights,
        "seasonal_tips": f"{season_tips.get(season, '')}",
    }
