"""Calculate pass coverage and savings for selected spots."""
from __future__ import annotations


def compute_pass_coverage(
    selected_spots: list[dict],
    graph_data: dict,
) -> dict:
    """For each selected spot, find which passes cover it and compute savings.

    Args:
        selected_spots: list of spot dicts with at least "name" and "price"
        graph_data: the knowledge graph JSON with nodes/edges

    Returns:
        {
            "spot_coverages": [{spot_name, passes, best_pass, supplement}],
            "pass_stats": [{pass_name, covered_count, total_value}],
            "best_overall_pass": str,
            "total_ticket_cost": float,
            "total_pass_value": float,
            "total_savings": float,
        }
    """
    # Build pass -> spots mapping from graph edges
    pass_spots: dict[str, list[str]] = {}
    pass_prices: dict[str, float] = {}

    for node in graph_data.get("nodes", []):
        if node.get("type") == "pass":
            node_id = node["id"]
            name = node.get("name", "")
            import re
            price_match = re.search(r"(\d+)元", name)
            pass_prices[node_id] = int(price_match.group(1)) if price_match else 0
            pass_spots[node_id] = []

    for edge in graph_data.get("edges", []):
        target = edge.get("target", "")
        source = edge.get("source", "")
        if target in pass_spots:
            pass_spots[target].append(source)

    # Build spot node name -> spot data mapping
    spot_names: dict[str, dict] = {}
    for node in graph_data.get("nodes", []):
        if node.get("type") == "spot":
            spot_names[node["id"]] = node

    # For each selected spot, find covering passes
    spot_coverages = []
    total_ticket_cost = 0
    total_pass_value = 0

    for spot in selected_spots:
        spot_name = spot.get("name", "")
        spot_price = spot.get("price", 0) or 0
        total_ticket_cost += spot_price

        covering_passes = []
        for pass_id, spots_in_pass in pass_spots.items():
            # Check if this spot is in the pass
            for sp_id in spots_in_pass:
                if sp_id in spot_names and spot_names[sp_id].get("name") == spot_name:
                    covering_passes.append(pass_id)
                    break

        best_pass = covering_passes[0] if covering_passes else None
        supplement = 0  # Could be computed from usage_limit data

        spot_coverages.append({
            "spot_name": spot_name,
            "passes": covering_passes,
            "best_pass": best_pass,
            "supplement": supplement,
            "price": spot_price,
        })

    # Pass statistics
    pass_stats = []
    for pass_id, spots_in_pass in pass_spots.items():
        covered = sum(
            1 for sc in spot_coverages
            if pass_id in sc["passes"]
        )
        if covered > 0:
            total_value = sum(
                sc["price"] for sc in spot_coverages
                if pass_id in sc["passes"]
            )
            pass_stats.append({
                "pass_name": pass_id,
                "covered_count": covered,
                "total_value": total_value,
            })

    pass_stats.sort(key=lambda x: -x["total_value"])

    best_overall = pass_stats[0]["pass_name"] if pass_stats else ""
    total_pass_value = pass_stats[0]["total_value"] if pass_stats else 0

    return {
        "spot_coverages": spot_coverages,
        "pass_stats": pass_stats,
        "best_overall_pass": best_overall,
        "total_ticket_cost": total_ticket_cost,
        "total_pass_value": total_pass_value,
        "total_savings": total_pass_value - total_ticket_cost if total_pass_value > 0 else 0,
    }
