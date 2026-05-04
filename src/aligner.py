"""Entity aligner: match same spots across different passes using fuzzy matching."""

from rapidfuzz import fuzz, process


def normalize_name(name: str) -> str:
    """Normalize name for comparison."""
    # Remove common suffixes that don't affect identity
    suffixes = ["景区", "风景区", "旅游区", "生态旅游区", "生态旅游景区",
                "文化旅游区", "旅游度假区", "国家森林公园", "国家地质公园",
                "游览区", "公园", "旅游区", "旅游"]
    cleaned = name
    for sfx in suffixes:
        if cleaned.endswith(sfx):
            cleaned = cleaned[: -len(sfx)]
            break
    return cleaned.strip()


def compute_similarity(name1: str, name2: str) -> float:
    """Compute similarity score between two spot names.

    Uses multiple strategies and returns the best score.
    """
    n1 = normalize_name(name1)
    n2 = normalize_name(name2)

    # Exact match after normalization
    if n1 == n2:
        return 100.0

    # One is substring of the other
    if n1 in n2 or n2 in n1:
        shorter = min(len(n1), len(n2))
        longer = max(len(n1), len(n2))
        return (shorter / longer) * 100.0

    # Fuzzy matching
    token_sort = fuzz.token_sort_ratio(n1, n2)
    partial = fuzz.partial_ratio(n1, n2)
    wratio = fuzz.WRatio(n1, n2)

    return max(token_sort, partial, wratio)


def align_spots(
    cleaned_spots: list[dict],
    threshold: float = 70.0,
) -> dict:
    """Align spots across passes.

    Returns:
        {
            "canonical_spots": [{"canonical_name": str, "aliases": [str], "passes": [str], "best_record": dict}],
            "alignment_pairs": [{"spot1": str, "spot2": str, "score": float, "confirmed": bool}],
            "stats": {"total_records": int, "unique_spots": int, "aligned_pairs": int},
        }
    """
    # Group by (city, area) first to reduce search space
    groups: dict[str, list[dict]] = {}
    for spot in cleaned_spots:
        key = f"{spot['city']}|{spot['area']}"
        groups.setdefault(key, []).append(spot)

    # Track canonical names and their aliases
    canonical_map: dict[str, dict] = {}  # canonical_name -> {aliases, passes, records}
    alignment_pairs = []

    for key, group in groups.items():
        # Get unique names in this group
        names_seen: list[dict] = []  # (name, record)

        for spot in group:
            name = spot["spot_name"]
            matched = None

            for seen_name, seen_record in names_seen:
                score = compute_similarity(name, seen_name)
                if score >= threshold:
                    matched = seen_name
                    alignment_pairs.append({
                        "spot1": seen_name,
                        "spot2": name,
                        "score": round(score, 1),
                        "confirmed": score >= 85.0,
                        "city": spot["city"],
                        "area": spot["area"],
                    })
                    break

            if matched:
                # Add as alias to existing canonical
                canonical_map[matched]["aliases"].append(name)
                canonical_map[matched]["passes"].append(spot["pass_name"])
                canonical_map[matched]["records"].append(spot)
            else:
                # New canonical spot
                names_seen.append((name, spot))
                canonical_map[name] = {
                    "canonical_name": name,
                    "aliases": [],
                    "passes": [spot["pass_name"]],
                    "records": [spot],
                }

    # Build result
    canonical_spots = []
    for name, data in sorted(canonical_map.items()):
        # Pick best record (prefer one with level)
        best = None
        for rec in data["records"]:
            if rec.get("level"):
                best = rec
                break
        if best is None:
            best = data["records"][0]

        canonical_spots.append({
            "canonical_name": name,
            "aliases": sorted(set(data["aliases"])),
            "passes": sorted(set(data["passes"])),
            "best_record": best,
            "record_count": len(data["records"]),
        })

    return {
        "canonical_spots": canonical_spots,
        "alignment_pairs": alignment_pairs,
        "stats": {
            "total_records": len(cleaned_spots),
            "unique_spots": len(canonical_spots),
            "aligned_pairs": len(alignment_pairs),
        },
    }
