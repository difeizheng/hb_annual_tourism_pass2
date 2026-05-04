"""Check seasonal availability of spots and suggest alternatives."""
from __future__ import annotations

from src.seasonal_recommender import MONTH_TO_SEASON, calculate_seasonal_score


def check_seasonal_availability(
    spots: list[dict],
    travel_month: int,
) -> list[dict]:
    """Check selected spots for seasonal availability issues.

    Args:
        spots: list of spot dicts with category, sub_category, name, tags
        travel_month: month number (1-12)

    Returns:
        List of warnings for spots with score 0 or low seasonal relevance:
        [{
            "spot_name": str,
            "seasonal_score": int,  # 0-5
            "reason": str,
            "severity": "danger" | "warning" | "ok",
            "alternatives": list[str],  # suggested same-category alternatives
        }]
    """
    season = MONTH_TO_SEASON.get(travel_month, "spring")
    warnings = []

    for spot in spots:
        score, reason = calculate_seasonal_score(spot, season)

        severity = "ok"
        if score == 0:
            severity = "danger"
        elif score <= 1:
            severity = "warning"

        # Find alternatives from same category with higher seasonal score
        alternatives = _find_alternatives(
            spot, season, score, travel_month
        ) if severity in ("danger", "warning") else []

        warnings.append({
            "spot_name": spot.get("name", ""),
            "seasonal_score": score,
            "seasonal_reason": reason,
            "severity": severity,
            "alternatives": alternatives,
        })

    return warnings


def _find_alternatives(
    spot: dict,
    season: str,
    current_score: int,
    travel_month: int,
    all_spots: list[dict] | None = None,
) -> list[str]:
    """Suggest alternative spots with better seasonal scores."""
    # This will be called with the full spots list from the UI
    # For now return empty — alternatives populated at UI level
    return []
