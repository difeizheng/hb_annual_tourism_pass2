"""Smart spot selection: pass import, seasonal recommendations, persona picks."""
from __future__ import annotations

import re
from collections import defaultdict

from src.seasonal_recommender import get_seasonal_recommendations

PERSONA_PROFILES = {
    "family": {
        "label": "家庭亲子",
        "bonus_cats": ["主题乐园", "休闲农业"],
        "min_spots": 5,
    },
    "adventure": {
        "label": "户外探险",
        "bonus_cats": ["户外运动", "自然景观"],
        "min_spots": 3,
    },
    "culture": {
        "label": "人文历史",
        "bonus_cats": ["人文历史"],
        "min_spots": 4,
    },
    "relax": {
        "label": "休闲放松",
        "bonus_cats": ["温泉康养", "自然景观"],
        "min_spots": 3,
    },
}


def import_pass_spots(
    pass_name: str,
    graph_data: dict,
    cleaned_spots: list[dict],
) -> list[dict]:
    """Import all spots from a given annual pass.

    Args:
        pass_name: display name of the pass
        graph_data: knowledge graph JSON
        cleaned_spots: list of all cleaned spot data

    Returns:
        List of spot dicts with full metadata
    """
    # Find pass node ID by name
    pass_id = None
    for node in graph_data.get("nodes", []):
        if node.get("type") == "pass" and pass_name in node.get("name", ""):
            pass_id = node["id"]
            break

    if not pass_id:
        return []

    # Find spot node IDs that point to this pass
    spot_ids = set()
    for edge in graph_data.get("edges", []):
        if edge.get("target") == pass_id:
            spot_ids.add(edge["source"])

    # Map spot node IDs to node data
    node_map = {}
    for node in graph_data.get("nodes", []):
        if node["id"] in spot_ids:
            node_map[node["id"]] = node

    # Find matching cleaned spots by name
    spot_name_to_cleaned = {}
    for s in cleaned_spots:
        spot_name_to_cleaned[s.get("spot_name", "")] = s

    result = []
    for spot_id, node in node_map.items():
        name = node.get("name", "")
        cleaned = spot_name_to_cleaned.get(name, {})

        result.append({
            "name": name,
            "city": node.get("city", cleaned.get("city", "")),
            "category": node.get("category", cleaned.get("category", "")),
            "sub_category": cleaned.get("_classification", {}).get("sub_category", ""),
            "level": node.get("level", cleaned.get("level", "")),
            "price": node.get("price", cleaned.get("price", 0)),
            "lng": node.get("lng", cleaned.get("lng")),
            "lat": node.get("lat", cleaned.get("lat")),
            "tags": node.get("tags", []),
            "notes": cleaned.get("notes_raw", ""),
        })

    return result


def get_all_passes_info(graph_data: dict) -> list[dict]:
    """Get summary info for all passes (name, spot count, price, etc)."""
    passes = []
    for node in graph_data.get("nodes", []):
        if node.get("type") != "pass":
            continue
        name = node.get("name", "")
        price_match = re.search(r"(\d+)元", name)
        pass_price = int(price_match.group(1)) if price_match else 0

        # Count spots
        spot_count = 0
        total_value = 0
        for edge in graph_data.get("edges", []):
            if edge.get("target") == node["id"]:
                spot_count += 1
                total_value += edge.get("price", 0)

        passes.append({
            "id": node["id"],
            "name": name,
            "price": pass_price,
            "spot_count": spot_count,
            "total_value": total_value,
            "value_ratio": round(total_value / pass_price, 1) if pass_price > 0 else 0,
        })

    passes.sort(key=lambda x: -x["value_ratio"])
    return passes


def get_persona_recommendations(
    persona_key: str,
    month: int,
    spots: list[dict],
) -> list[dict]:
    """Get persona-filtered seasonal recommendations.

    Args:
        persona_key: one of PERSONA_PROFILES keys
        month: travel month (1-12)
        spots: all available spots

    Returns:
        List of (spot, score, reason) tuples ranked by relevance
    """
    profile = PERSONA_PROFILES.get(persona_key, PERSONA_PROFILES["family"])

    # Get seasonal recommendations first
    recs = get_seasonal_recommendations(spots, month)

    # Bonus for persona-preferring categories
    bonus_cats = profile.get("bonus_cats", [])
    scored: list[tuple[dict, int, str, int]] = []  # (spot, score, reason, bonus)

    for tier in (recs["must_visit"], recs["recommended"], recs["optional"]):
        for spot, reason, score in tier:
            bonus = 0
            if spot.get("category") in bonus_cats:
                bonus = 1
            scored.append((spot, score, reason, bonus))

    # Sort by score desc, then bonus desc, then price desc
    scored.sort(key=lambda x: (-x[1], -x[3], -x[0].get("price", 0)))

    return scored
