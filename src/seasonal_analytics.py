"""Seasonal analytics: 12-month overview, pass ranking, category distribution, exclusive spots."""
from __future__ import annotations

import pandas as pd

from src.seasonal_recommender import (
    MONTH_TO_SEASON,
    SEASON_NAMES,
    calculate_seasonal_score,
)


def compute_12_month_overview(
    spots: list[dict],
    city_filter: list[str] | None = None,
) -> pd.DataFrame:
    """Compute stats for all 12 months: recommended count, avg price, 5A count.

    Returns DataFrame with columns: month, season, recommended, avg_price, a5_count
    """
    rows = []
    for month in range(1, 13):
        season = MONTH_TO_SEASON[month]
        recommended = 0
        total_price = 0
        a5_count = 0

        for spot in spots:
            if city_filter and spot.get("city", "") not in city_filter:
                continue
            score, _ = calculate_seasonal_score(spot, season)
            if score >= 3:
                recommended += 1
                total_price += spot.get("price", 0)
                if spot.get("level") == "A5":
                    a5_count += 1

        avg_price = total_price / recommended if recommended > 0 else 0
        rows.append({
            "month": month,
            "season": season,
            "recommended": recommended,
            "avg_price": round(avg_price, 0),
            "a5_count": a5_count,
        })

    return pd.DataFrame(rows)


def compute_seasonal_pass_ranking(
    pass_info: dict[str, dict],
    spots: list[dict],
    month: int,
    city_filter: list[str] | None = None,
) -> list[dict]:
    """Rank passes by seasonal value: sum of ticket prices for spots with seasonal score >= 3.

    Returns list sorted by seasonal_savings desc:
        [{pass_id, display, card_price, seasonal_value, seasonal_savings, seasonal_spots}]
    """
    season = MONTH_TO_SEASON[month]

    # Build spot name -> seasonal score map
    spot_scores: dict[str, int] = {}
    for spot in spots:
        if city_filter and spot.get("city", "") not in city_filter:
            continue
        score, _ = calculate_seasonal_score(spot, season)
        spot_scores[spot["name"]] = score

    result = []
    for pid, pi in pass_info.items():
        seasonal_value = 0
        seasonal_spots = 0
        for s in pi["spots_detail"]:
            if spot_scores.get(s["name"], 0) >= 3:
                seasonal_value += s["price"]
                seasonal_spots += 1

        card_price = pi["price"]
        seasonal_savings = seasonal_value - card_price

        result.append({
            "pass_id": pid,
            "display": pi["display"],
            "card_price": card_price,
            "seasonal_value": seasonal_value,
            "seasonal_savings": seasonal_savings,
            "seasonal_spots": seasonal_spots,
        })

    result.sort(key=lambda x: -x["seasonal_savings"])
    return result


def compute_category_distribution(recs: dict) -> dict[str, int]:
    """Category distribution of recommended spots (must_visit + recommended only).

    Returns {category: count} sorted by count desc.
    """
    dist: dict[str, int] = {}

    for tier in (recs.get("must_visit", []), recs.get("recommended", [])):
        for spot, _, _ in tier:
            cat = spot.get("category", "其他")
            dist[cat] = dist.get(cat, 0) + 1

    return dict(sorted(dist.items(), key=lambda x: -x[1]))


def find_seasonal_exclusive_spots(
    spots: list[dict],
    month: int,
    pass_info: dict[str, dict] | None = None,
) -> list[dict]:
    """Find spots that are seasonally exclusive or strongly associated with current season.

    Detection (3 tiers):
    1. Explicit: notes/usage_limit contain "仅夏季"/"仅冬季"/"开漂" — exact match
    2. Tagged: tags contain "季节性" — seasonal flag
    3. Sub-category association: 漂流/水上乐园→夏季, 滑雪→冬季, 温泉→冬季

    Returns [{name, city, category, sub_category, price, level, exclusive_type,
              detection_type, passes_covering, coverage_status}]
    """
    season = MONTH_TO_SEASON[month]

    # Keywords mapping: season -> explicit keywords
    season_kw = {
        "summer": ["仅夏季", "开漂", "夏季", "夏天", "6-8月", "7-8月", "7、8月"],
        "winter": ["仅冬季", "冬季", "雪季", "12-2月", "11-2月", "12月-次年2月"],
        "spring": ["仅春季", "春季", "3-5月", "踏青"],
        "autumn": ["仅秋季", "秋季", "9-11月", "金秋"],
    }

    # Sub-categories that are inherently seasonal
    sub_cat_season = {
        "漂流": "summer",
        "水上乐园": "summer",
        "滑雪": "winter",
        "温泉": "winter",
    }

    target_kws = season_kw.get(season, [])

    # Build spot name -> list of pass_ids
    spot_to_passes: dict[str, list[str]] = {}
    if pass_info:
        for pid, pi in pass_info.items():
            for s in pi["spots_detail"]:
                spot_to_passes.setdefault(s["name"], []).append(pid)

    def _coverage_status(passes: list[str]) -> str:
        if not passes:
            return "无覆盖"
        return "全卡覆盖" if len(passes) >= len(pass_info or {}) * 0.5 else "部分覆盖"

    result = []
    seen_names: set[str] = set()

    for spot in spots:
        name = spot["name"]
        notes = (spot.get("notes") or "") + (spot.get("usage_limit") or "")
        tags = spot.get("tags", []) or []
        sub_cat = spot.get("sub_category", "") or ""
        entry = None

        # Tier 1: explicit keyword match
        for kw in target_kws:
            if kw in notes:
                entry = {
                    "name": name, "city": spot.get("city", ""),
                    "category": spot.get("category", ""),
                    "sub_category": sub_cat, "price": spot.get("price", 0),
                    "level": spot.get("level", ""),
                    "exclusive_type": kw,
                    "detection_type": "明确标注",
                    "passes_covering": spot_to_passes.get(name, []),
                }
                break

        # Tier 2: seasonal tag
        if entry is None and "季节性" in tags:
            # Check if any keyword matches
            matched = False
            for kw in target_kws:
                if kw in notes:
                    matched = True
                    break
            if matched or any(sk in notes for sk in ["季节"]):
                entry = {
                    "name": name, "city": spot.get("city", ""),
                    "category": spot.get("category", ""),
                    "sub_category": sub_cat, "price": spot.get("price", 0),
                    "level": spot.get("level", ""),
                    "exclusive_type": f"季节性({season})",
                    "detection_type": "季节标签",
                    "passes_covering": spot_to_passes.get(name, []),
                }

        # Tier 3: sub-category inherent season
        if entry is None and sub_cat in sub_cat_season:
            if sub_cat_season[sub_cat] == season:
                entry = {
                    "name": name, "city": spot.get("city", ""),
                    "category": spot.get("category", ""),
                    "sub_category": sub_cat, "price": spot.get("price", 0),
                    "level": spot.get("level", ""),
                    "exclusive_type": f"{sub_cat}({SEASON_NAMES[season]})",
                    "detection_type": "子分类关联",
                    "passes_covering": spot_to_passes.get(name, []),
                }

        if entry and name not in seen_names:
            seen_names.add(name)
            entry["coverage_status"] = _coverage_status(entry["passes_covering"])
            result.append(entry)

    result.sort(key=lambda x: -x["price"])
    return result


def compute_seasonal_calendar(
    spots: list[dict],
    pass_info: dict[str, dict] | None = None,
) -> pd.DataFrame:
    """12-month x sub-category heatmap data: count of seasonal-exclusive spots.

    Returns DataFrame: rows=sub_category, cols=months 1-12, values=count.
    """
    # Sub-categories that are inherently seasonal
    sub_cat_season = {
        "漂流": "summer", "水上乐园": "summer",
        "滑雪": "winter", "温泉": "winter",
    }

    # Build spot -> passes map
    spot_to_passes: dict[str, list[str]] = {}
    if pass_info:
        for pid, pi in pass_info.items():
            for s in pi["spots_detail"]:
                spot_to_passes.setdefault(s["name"], []).append(pid)

    calendar: dict[str, dict[int, int]] = {}

    for spot in spots:
        notes = (spot.get("notes") or "") + (spot.get("usage_limit") or "")
        tags = spot.get("tags", []) or []
        sub_cat = spot.get("sub_category", "") or ""

        # Determine season for this spot
        spot_season = None
        if sub_cat in sub_cat_season:
            spot_season = sub_cat_season[sub_cat]
        elif "仅夏季" in notes or "开漂" in notes:
            spot_season = "summer"
        elif "仅冬季" in notes:
            spot_season = "winter"
        elif "季节性" in tags:
            # Try to find explicit month/season hint
            if any(kw in notes for kw in ["夏季", "夏天", "漂"]):
                spot_season = "summer"
            elif any(kw in notes for kw in ["冬季", "雪"]):
                spot_season = "winter"

        if not spot_season:
            continue

        season_months = {
            "spring": [3, 4, 5], "summer": [6, 7, 8, 9],
            "autumn": [10, 11], "winter": [12, 1, 2],
        }

        if not sub_cat:
            sub_cat = spot.get("category", "其他")

        if sub_cat not in calendar:
            calendar[sub_cat] = {m: 0 for m in range(1, 13)}

        for m in season_months.get(spot_season, []):
            calendar[sub_cat][m] += 1

    df = pd.DataFrame(calendar).T.fillna(0).astype(int)
    # Add row totals
    df["_total"] = df.sum(axis=1)
    df = df.sort_values("_total", ascending=False).drop(columns=["_total"])
    return df
