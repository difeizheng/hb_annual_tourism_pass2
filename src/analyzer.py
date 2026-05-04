"""Analyzer: statistical analysis of the knowledge graph and pass data."""

from collections import Counter, defaultdict

import networkx as nx


def global_stats(G: nx.MultiDiGraph) -> dict:
    """Calculate global graph statistics."""
    node_types = Counter()
    for _, attrs in G.nodes(data=True):
        node_types[attrs.get("type", "unknown")] += 1

    edge_types = Counter()
    for _, _, _, attrs in G.edges(data=True, keys=True):
        edge_types[attrs.get("relation", "unknown")] += 1

    return {
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "node_types": dict(node_types),
        "edge_types": dict(edge_types),
    }


def city_distribution(G: nx.MultiDiGraph) -> dict:
    """Count spots per city."""
    city_spots = defaultdict(int)
    for node_id, attrs in G.nodes(data=True):
        if attrs.get("type") == "spot":
            city_spots[attrs.get("city", "unknown")] += 1
    return dict(sorted(city_spots.items(), key=lambda x: -x[1]))


def level_distribution(G: nx.MultiDiGraph) -> dict:
    """Count spots by level."""
    level_counts = Counter()
    for _, attrs in G.nodes(data=True):
        if attrs.get("type") == "spot":
            level = attrs.get("level", "未评级")
            level_counts[level or "未评级"] += 1
    return dict(level_counts.most_common())


def category_distribution(G: nx.MultiDiGraph) -> dict:
    """Count spots by category."""
    cat_counts = Counter()
    for _, attrs in G.nodes(data=True):
        if attrs.get("type") == "spot":
            cat = attrs.get("category", "其他")
            cat_counts[cat] += 1
    return dict(cat_counts.most_common())


def pass_analysis(G: nx.MultiDiGraph) -> list[dict]:
    """Analyze each pass: spot count, total price, value ratio."""
    passes = []
    for node_id, attrs in G.nodes(data=True):
        if attrs.get("type") != "pass":
            continue

        incoming = list(G.in_edges(node_id, data=True, keys=True))
        spot_count = len(incoming)
        total_price = sum(e[3].get("price", 0) for e in incoming)

        # Extract pass price from name
        import re
        name = attrs.get("name", "")
        price_match = re.search(r"(\d+)元", name)
        pass_price = int(price_match.group(1)) if price_match else 0

        value_ratio = total_price / pass_price if pass_price > 0 else 0

        passes.append({
            "name": name,
            "price": pass_price,
            "spot_count": spot_count,
            "total_price": total_price,
            "value_ratio": round(value_ratio, 1),
        })

    return sorted(passes, key=lambda x: -x["value_ratio"])


def pass_overlap(G: nx.MultiDiGraph, pass1: str, pass2: str) -> dict:
    """Analyze overlap between two passes."""
    spots1 = set()
    spots2 = set()

    for u, v, _key, _data in G.in_edges(f"pass:{pass1}", data=True, keys=True):
        spots1.add(u)
    for u, v, _key, _data in G.in_edges(f"pass:{pass2}", data=True, keys=True):
        spots2.add(u)

    overlap = spots1 & spots2
    only_1 = spots1 - spots2
    only_2 = spots2 - spots1

    return {
        "pass1": pass1,
        "pass2": pass2,
        "pass1_count": len(spots1),
        "pass2_count": len(spots2),
        "overlap_count": len(overlap),
        "only_pass1": len(only_1),
        "only_pass2": len(only_2),
        "overlap_spots": list(overlap),
        "only_pass1_spots": list(only_1),
        "only_pass2_spots": list(only_2),
    }


def price_analysis(cleaned_spots: list[dict]) -> dict:
    """Analyze price distribution."""
    prices = [s["price"] for s in cleaned_spots if s.get("price", 0) > 0]
    if not prices:
        return {}

    return {
        "min": min(prices),
        "max": max(prices),
        "mean": round(sum(prices) / len(prices), 1),
        "median": sorted(prices)[len(prices) // 2],
        "total": sum(prices),
        "count": len(prices),
        "free_count": len(cleaned_spots) - len(prices),
    }


def seasonal_analysis(cleaned_spots: list[dict]) -> dict:
    """Analyze seasonal spots."""
    seasonal = []
    for spot in cleaned_spots:
        notes = (spot.get("notes_raw") or "") + (spot.get("usage_limit_raw") or "")
        if "季节性" in notes or "仅夏季" in notes or "仅冬季" in notes or "开漂" in notes:
            seasonal.append({
                "name": spot["spot_name"],
                "city": spot["city"],
                "category": spot.get("_classification", {}).get("category", "其他"),
                "notes": notes,
            })
    return {
        "count": len(seasonal),
        "spots": seasonal,
    }


def top_value_spots(G: nx.MultiDiGraph, top_n: int = 20) -> list[dict]:
    """Find spots with highest individual ticket prices."""
    spots = []
    for node_id, attrs in G.nodes(data=True):
        if attrs.get("type") == "spot":
            spots.append({
                "name": attrs.get("name", ""),
                "price": attrs.get("price", 0),
                "level": attrs.get("level", ""),
                "city": attrs.get("city", ""),
                "category": attrs.get("category", ""),
            })

    spots.sort(key=lambda x: -x["price"])
    return spots[:top_n]
