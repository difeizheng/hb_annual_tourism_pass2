"""Recommender: query, filter, and recommend passes based on preferences."""

import networkx as nx


def filter_spots(
    G: nx.MultiDiGraph,
    city: str | None = None,
    level: str | None = None,
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    requires_appointment: bool | None = None,
) -> list[dict]:
    """Filter spots by criteria."""
    results = []
    for node_id, attrs in G.nodes(data=True):
        if attrs.get("type") != "spot":
            continue

        # Apply filters
        if city and attrs.get("city") != city:
            continue
        if level and attrs.get("level") != level:
            continue
        if category and attrs.get("category") != category:
            continue
        if min_price is not None and attrs.get("price", 0) < min_price:
            continue
        if max_price is not None and attrs.get("price", 0) > max_price:
            continue

        results.append({
            "name": attrs.get("name", ""),
            "city": attrs.get("city", ""),
            "area": attrs.get("area", ""),
            "level": attrs.get("level", ""),
            "price": attrs.get("price", 0),
            "category": attrs.get("category", ""),
            "sub_category": attrs.get("sub_category"),
            "tags": attrs.get("tags", []),
        })

    return results


def recommend_passes(
    G: nx.MultiDiGraph,
    cleaned_spots: list[dict],
    preferences: dict,
) -> list[dict]:
    """Recommend best passes based on user preferences.

    preferences: {
        "cities": [str],        # preferred cities
        "categories": [str],    # preferred categories
        "budget": int,          # max pass price
        "min_spots": int,       # minimum spots wanted
        "family": bool,         # traveling with children
        "outdoor": bool,        # outdoor activities
    }
    """
    # Score each pass
    scored = []
    for node_id, attrs in G.nodes(data=True):
        if attrs.get("type") != "pass":
            continue

        import re
        name = attrs.get("name", "")
        price_match = re.search(r"(\d+)元", name)
        pass_price = int(price_match.group(1)) if price_match else 0

        # Get spots in this pass
        incoming = list(G.in_edges(node_id, data=True, keys=True))
        spots_in_pass = []
        for u, v, _key, data in incoming:
            spot_attrs = dict(G.nodes[u])
            spots_in_pass.append(spot_attrs)

        if preferences.get("budget") and pass_price > preferences["budget"]:
            continue

        if preferences.get("min_spots") and len(spots_in_pass) < preferences["min_spots"]:
            continue

        score = 0

        # City preference
        if preferences.get("cities"):
            city_matches = sum(
                1 for s in spots_in_pass
                if s.get("city") in preferences["cities"]
            )
            score += city_matches * 2

        # Category preference
        if preferences.get("categories"):
            cat_matches = sum(
                1 for s in spots_in_pass
                if s.get("category") in preferences["categories"]
            )
            score += cat_matches * 3

        # Family-friendly (parks, zoos, etc.)
        if preferences.get("family"):
            family_cats = ["主题乐园", "休闲农业"]
            family_matches = sum(
                1 for s in spots_in_pass
                if s.get("category") in family_cats
            )
            score += family_matches * 2

        # Outdoor activities
        if preferences.get("outdoor"):
            outdoor_cats = ["户外运动", "自然景观"]
            outdoor_matches = sum(
                1 for s in spots_in_pass
                if s.get("category") in outdoor_cats
            )
            score += outdoor_matches * 2

        # Value ratio bonus
        total_price = sum(s.get("price", 0) for s in spots_in_pass)
        if pass_price > 0:
            ratio = total_price / pass_price
            score += ratio

        scored.append({
            "name": name,
            "price": pass_price,
            "spot_count": len(spots_in_pass),
            "total_price": total_price,
            "score": round(score, 1),
        })

    scored.sort(key=lambda x: -x["score"])
    return scored


def recommend_by_season(G: nx.MultiDiGraph, month: int | None = None) -> dict:
    """Recommend spots available in current season."""
    if month is None:
        import datetime
        month = datetime.datetime.now().month

    # Seasonal spots by month
    seasonal_spots = {
        "summer": {"months": [6, 7, 8, 9], "keywords": ["漂流", "水上", "水世界", "游泳池", "仅夏季"]},
        "winter": {"months": [12, 1, 2], "keywords": ["滑雪", "温泉", "仅冬季"]},
        "spring": {"months": [3, 4, 5], "keywords": ["樱花园", "桃花", "牡丹", "郁金香", "梅园"]},
        "autumn": {"months": [10, 11], "keywords": ["红叶", "赏秋", "登山"]},
    }

    current_season = None
    season_keywords = []
    for season, data in seasonal_spots.items():
        if month in data["months"]:
            current_season = season
            season_keywords = data["keywords"]
            break

    results = {"season": current_season, "month": month, "spots": []}

    for node_id, attrs in G.nodes(data=True):
        if attrs.get("type") != "spot":
            continue

        name = attrs.get("name", "")
        tags = attrs.get("tags", [])
        category = attrs.get("category", "")

        # Check if spot matches season keywords
        for kw in season_keywords:
            if kw in name or kw in category:
                results["spots"].append({
                    "name": name,
                    "city": attrs.get("city", ""),
                    "price": attrs.get("price", 0),
                    "category": category,
                    "reason": kw,
                })
                break

    return results


def query_natural_language(G: nx.MultiDiGraph, query: str) -> list[dict]:
    """Simple natural language query handler.

    Supports patterns like:
    - "武汉有哪些5A景点"
    - "哪些年卡包含黄鹤楼"
    - "武汉的温泉有哪些"
    - "5A景点"
    - "免费景点"
    """
    results = []

    # Extract city
    cities_in_query = []
    for _, attrs in G.nodes(data=True):
        if attrs.get("type") == "city":
            city_name = attrs.get("name", "")
            if city_name in query:
                cities_in_query.append(city_name)

    # Extract level
    level = None
    if "5A" in query or "AAAAA" in query:
        level = "A5"
    elif "4A" in query or "AAAA" in query:
        level = "A4"
    elif "3A" in query or "AAA" in query:
        level = "A3"

    # Extract category
    category = None
    if "温泉" in query:
        category = "自然景观"  # Closest match for hot springs
    elif "漂流" in query:
        category = "户外运动"
    elif "乐园" in query:
        category = "主题乐园"
    elif "古" in query:
        category = "人文历史"

    return filter_spots(
        G,
        city=cities_in_query[0] if cities_in_query else None,
        level=level,
        category=category,
    )
