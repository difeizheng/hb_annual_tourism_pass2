"""Pass comparison and analysis module."""
from __future__ import annotations

import math
import re
from collections import defaultdict
from itertools import combinations

import pandas as pd


def build_pass_info(graph_data: dict, cleaned: list[dict]) -> dict[str, dict]:
    """Build pass info dict from graph data and cleaned spots.

    Returns:
        {pass_id: {name_key, display, price, spots, spots_detail, cities,
                   categories, total_price, levels, spot_count, city_count,
                   value_ratio, a5_count, a4_count}}
    """
    pass_info: dict[str, dict] = {}
    for node in graph_data["nodes"]:
        if node.get("type") == "pass":
            price_m = re.search(r"(\d+)元", node.get("name", ""))
            pass_info[node["id"]] = {
                "name_key": node["name"],
                "display": node["name"].split("_")[0],
                "price": int(price_m.group(1)) if price_m else 0,
                "spots": [],
                "spots_detail": [],
                "cities": set(),
                "categories": set(),
                "total_price": 0,
                "levels": [],
            }

    for edge in graph_data["edges"]:
        target = edge.get("target", "")
        if target in pass_info:
            source = edge.get("source", "")
            for n in graph_data["nodes"]:
                if n.get("id") == source and n.get("type") == "spot":
                    pi = pass_info[target]
                    spot_name = n.get("name", "")
                    spot_price = n.get("price", 0)
                    spot_city = n.get("city", "")
                    spot_level = n.get("level") or ""
                    spot_cat = n.get("category", "")
                    spot_usage = n.get("usage_limit", "")
                    spot_notes = n.get("notes", "")

                    pi["spots"].append(spot_name)
                    pi["spots_detail"].append({
                        "name": spot_name,
                        "price": spot_price,
                        "city": spot_city,
                        "level": spot_level,
                        "category": spot_cat,
                        "usage_limit": spot_usage,
                        "notes": spot_notes,
                    })
                    pi["cities"].add(spot_city)
                    pi["categories"].add(spot_cat)
                    pi["total_price"] += spot_price
                    pi["levels"].append(spot_level)

    for pn, pi in pass_info.items():
        pi["city_count"] = len(pi["cities"])
        pi["spot_count"] = len(pi["spots"])
        pi["value_ratio"] = round(pi["total_price"] / pi["price"], 1) if pi["price"] else 0
        pi["a5_count"] = sum(1 for lv in pi["levels"] if lv == "A5")
        pi["a4_count"] = sum(1 for lv in pi["levels"] if lv == "A4")

    return pass_info


def compute_savings(pass_info: dict[str, dict]) -> dict[str, dict]:
    """Compute savings per pass: total_ticket_value - card_price.

    Returns:
        {pass_id: {"total_value": int, "savings": int, "savings_by_city": {city: value}}}
    """
    result = {}
    for pid, pi in pass_info.items():
        by_city: dict[str, int] = defaultdict(int)
        for s in pi["spots_detail"]:
            by_city[s["city"]] += s["price"]

        total_value = sum(s["price"] for s in pi["spots_detail"])
        savings = total_value - pi["price"]

        result[pid] = {
            "total_value": total_value,
            "savings": savings,
            "savings_by_city": dict(by_city),
        }
    return result


def compute_exclusive_spots(
    pass_info: dict[str, dict],
    selected_ids: list[str],
) -> dict[str, list[dict]]:
    """For each selected pass, find spots that NO other selected pass has.

    Returns:
        {pass_id: [{name, price, city, level, category}, ...]} sorted by price desc
    """
    if len(selected_ids) <= 1:
        return {pid: pass_info[pid]["spots_detail"] for pid in selected_ids}

    # Build spot -> set of pass_ids mapping for selected passes
    spot_to_passes: dict[str, set[str]] = defaultdict(set)
    for pid in selected_ids:
        for s in pass_info[pid]["spots_detail"]:
            spot_to_passes[s["name"]].add(pid)

    result = {}
    for pid in selected_ids:
        exclusive = [
            s for s in pass_info[pid]["spots_detail"]
            if len(spot_to_passes[s["name"]]) == 1
        ]
        exclusive.sort(key=lambda x: -x["price"])
        result[pid] = exclusive
    return result


def compute_complementarity(
    selected_ids: list[str],
    pass_info: dict[str, dict],
) -> list[dict]:
    """For each unselected pass, compute how much it complements the selected ones.

    Returns:
        [{"pass_id", "display", "new_spots_count", "new_spots_value",
           "overlap_pct", "complement_score"}] sorted by complement_score desc
    """
    if not selected_ids:
        return []

    # All spots covered by selected passes
    selected_spots: set[str] = set()
    for pid in selected_ids:
        for s in pass_info[pid]["spots_detail"]:
            selected_spots.add(s["name"])

    result = []
    for pid, pi in pass_info.items():
        if pid in selected_ids:
            continue

        new_spots = [s for s in pi["spots_detail"] if s["name"] not in selected_spots]
        new_count = len(new_spots)
        new_value = sum(s["price"] for s in new_spots)
        overlap_count = pi["spot_count"] - new_count
        overlap_pct = round(overlap_count / pi["spot_count"] * 100, 1) if pi["spot_count"] > 0 else 0

        # Complement score: weighted combo of new spots count + new value
        max_possible_count = max(p["spot_count"] for p in pass_info.values()) or 1
        max_possible_value = max(p["total_price"] for p in pass_info.values()) or 1
        complement_score = round(
            (new_count / max_possible_count * 0.4 + new_value / max_possible_value * 0.6) * 100,
            1,
        )

        result.append({
            "pass_id": pid,
            "display": pi["display"],
            "price": pi["price"],
            "new_spots_count": new_count,
            "new_spots_value": new_value,
            "overlap_count": overlap_count,
            "overlap_pct": overlap_pct,
            "complement_score": complement_score,
        })

    result.sort(key=lambda x: -x["complement_score"])
    return result


def compute_city_pass_heatmap(
    pass_info: dict[str, dict],
    selected_ids: list[str] | None = None,
) -> pd.DataFrame:
    """City x Pass heatmap: rows=cities, cols=passes, values=spot_count.

    Returns DataFrame sorted by total spots desc.
    """
    ids = selected_ids or list(pass_info.keys())
    city_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for pid in ids:
        for s in pass_info[pid]["spots_detail"]:
            city_counts[s["city"]][pid] += 1

    df = pd.DataFrame(city_counts).T.fillna(0).astype(int)
    df["_total"] = df.sum(axis=1)
    df = df.sort_values("_total", ascending=False).drop(columns=["_total"])
    return df


def compute_usage_limits(pass_info: dict[str, dict]) -> list[dict]:
    """Analyze usage limits per pass: unlimited spots, seasonal, appointment needed, etc.

    Returns:
        [{"pass_id", "display", "total", "unlimited", "seasonal",
          "appointment_needed", "holiday_excluded"}]
    """
    result = []
    for pid, pi in pass_info.items():
        unlimited = 0
        seasonal = 0
        appointment_needed = 0
        holiday_excluded = 0

        for s in pi["spots_detail"]:
            usage = (s.get("usage_limit") or "").lower()
            notes = (s.get("notes") or "").lower()
            text = usage + notes

            # No restrictions
            if not usage and not notes:
                unlimited += 1

            if any(kw in text for kw in ["季节", "夏季", "冬季", "仅", "漂", "雪"]):
                seasonal += 1
            if any(kw in text for kw in ["预约", "提前", "电话"]):
                appointment_needed += 1
            if any(kw in text for kw in ["节假日", "法定", "国庆", "春节", "不含"]):
                holiday_excluded += 1

        result.append({
            "pass_id": pid,
            "display": pi["display"],
            "total": pi["spot_count"],
            "unlimited": unlimited,
            "seasonal": seasonal,
            "appointment_needed": appointment_needed,
            "holiday_excluded": holiday_excluded,
        })

    return result


def compute_optimal_combinations(
    pass_info: dict[str, dict],
    max_cards: int = 3,
) -> list[dict]:
    """Find best 2-card and 3-card pass combinations."""
    all_ids = list(pass_info.keys())
    results = []

    for size in range(2, max_cards + 1):
        for combo_ids in combinations(all_ids, size):
            unique_names: set[str] = set()
            total_value = 0
            for pid in combo_ids:
                for s in pass_info[pid]["spots_detail"]:
                    if s["name"] not in unique_names:
                        unique_names.add(s["name"])
                        total_value += s["price"]

            total_price = sum(pass_info[pid]["price"] for pid in combo_ids)
            savings = total_value - total_price
            efficiency = round(savings / total_price, 1) if total_price > 0 else 0

            results.append({
                "passes": [pass_info[pid]["display"] for pid in combo_ids],
                "pass_ids": list(combo_ids),
                "total_price": total_price,
                "unique_spots": len(unique_names),
                "total_value": total_value,
                "savings": savings,
                "efficiency_score": efficiency,
            })

    results.sort(key=lambda x: -x["efficiency_score"])
    return results


def compute_scene_analysis(
    pass_info: dict[str, dict],
    city: str | None = None,
    level: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """Filter passes by city/level/category, show per-pass stats."""
    result = []
    for pid, pi in pass_info.items():
        spots = pi["spots_detail"]
        if city:
            spots = [s for s in spots if s.get("city") == city]
        if level:
            spots = [s for s in spots if s.get("level") == level]
        if category:
            spots = [s for s in spots if s.get("category") == category]
        if not spots:
            continue

        total_value = sum(s["price"] for s in spots)
        a5 = sum(1 for s in spots if s.get("level") == "A5")
        a4 = sum(1 for s in spots if s.get("level") == "A4")

        result.append({
            "pass_id": pid,
            "display": pi["display"],
            "price": pi["price"],
            "spot_count": len(spots),
            "total_value": total_value,
            "savings": total_value - pi["price"],
            "a5_count": a5,
            "a4_count": a4,
        })

    result.sort(key=lambda x: -x["spot_count"])
    return result


def _haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """Haversine distance in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + \
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
        math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def compute_route_feasibility(
    pass_info: dict[str, dict],
    selected_ids: list[str],
    spots_with_coords: list[dict],
) -> dict:
    """Analyze route feasibility: distance span, city spread."""
    selected_spot_names: set[str] = set()
    for pid in selected_ids:
        for s in pass_info[pid]["spots_detail"]:
            selected_spot_names.add(s["name"])

    coords = []
    for s in spots_with_coords:
        if s["name"] in selected_spot_names and s.get("lng") and s.get("lat"):
            coords.append({
                "name": s["name"],
                "city": s.get("city", ""),
                "lng": float(s["lng"]),
                "lat": float(s["lat"]),
            })

    if len(coords) < 2:
        return {
            "max_distance_km": 0, "avg_distance_km": 0,
            "city_span": [], "city_count": 0,
            "farthest_pair": [],
            "recommendation": "景点坐标不足，无法计算距离",
        }

    max_dist = 0
    farthest_pair = ("", "")
    distances = []
    sample_n = min(500, len(coords) * (len(coords) - 1) // 2)
    count = 0
    for i in range(len(coords)):
        for j in range(i + 1, len(coords)):
            d = _haversine_km(coords[i]["lng"], coords[i]["lat"],
                               coords[j]["lng"], coords[j]["lat"])
            distances.append(d)
            if d > max_dist:
                max_dist = d
                farthest_pair = (coords[i]["name"], coords[j]["name"])
            count += 1
            if count >= sample_n:
                break
        if count >= sample_n:
            break

    avg_dist = sum(distances) / len(distances) if distances else 0
    cities = sorted({c["city"] for c in coords if c["city"]})

    if max_dist > 400:
        rec = f"跨度较大（最远 {max_dist:.0f}km），建议搭配住宿分段游玩"
    elif max_dist > 200:
        rec = f"中等跨度（最远 {max_dist:.0f}km），建议2-3天安排"
    else:
        rec = f"跨度合理（最远 {max_dist:.0f}km），可1-2天游玩"

    return {
        "max_distance_km": round(max_dist, 1),
        "avg_distance_km": round(avg_dist, 1),
        "city_span": cities,
        "city_count": len(cities),
        "farthest_pair": farthest_pair,
        "recommendation": rec,
    }


def compute_cost_performance_ranking(pass_info: dict[str, dict]) -> dict[str, list[dict]]:
    """Rank all passes: per-yuan spots, A5 density, city coverage."""
    per_spot_cost = []
    for pid, pi in pass_info.items():
        score = round(pi["spot_count"] / pi["price"] * 100, 1) if pi["price"] > 0 else 0
        per_spot_cost.append({"pass_id": pid, "display": pi["display"], "score": score})
    per_spot_cost.sort(key=lambda x: -x["score"])

    a5_density = []
    for pid, pi in pass_info.items():
        score = round(pi["a5_count"] / pi["spot_count"] * 100, 1) if pi["spot_count"] > 0 else 0
        a5_density.append({"pass_id": pid, "display": pi["display"], "score": score})
    a5_density.sort(key=lambda x: -x["score"])

    max_cities = max(pi["city_count"] for pi in pass_info.values()) or 1
    city_coverage = []
    for pid, pi in pass_info.items():
        score = round(pi["city_count"] / max_cities * 100, 1)
        city_coverage.append({"pass_id": pid, "display": pi["display"], "score": score})
    city_coverage.sort(key=lambda x: -x["score"])

    return {
        "per_spot_cost": per_spot_cost,
        "a5_density": a5_density,
        "city_coverage": city_coverage,
    }


def get_limit_detail(
    pass_info: dict[str, dict],
    selected_ids: list[str],
) -> list[dict]:
    """Detailed limit info: which spots have what restrictions."""
    result = []
    for pid in selected_ids:
        limits = []
        for s in pass_info[pid]["spots_detail"]:
            usage = (s.get("usage_limit") or "").strip()
            notes = (s.get("notes") or "").strip()
            text = usage + " " + notes
            if not text.strip():
                continue

            types_found = []
            if any(kw in text for kw in ["季节", "夏季", "冬季", "仅", "漂", "雪"]):
                types_found.append("季节限制")
            if any(kw in text for kw in ["预约", "提前", "电话"]):
                types_found.append("需预约")
            if any(kw in text for kw in ["节假日", "法定", "国庆", "春节", "不含"]):
                types_found.append("不含节假日")
            if any(kw in text for kw in ["次", "限"]):
                types_found.append("次数限制")

            if types_found:
                limits.append({
                    "spot_name": s["name"],
                    "restriction_types": types_found,
                    "detail": usage or notes,
                })

        result.append({
            "pass_id": pid,
            "display": pass_info[pid]["display"],
            "limits": limits,
        })

    return result
