"""Play duration estimation by category, sub_category, and level."""
from __future__ import annotations

# Hours per sub_category (most specific, takes priority)
SUB_CATEGORY_DURATION: dict[str, float] = {
    "漂流": 2.5,
    "水上乐园": 3.5,
    "滑雪": 4.0,
    "温泉": 3.0,
    "溶洞": 2.0,
    "动物园": 3.5,
    "植物园": 2.5,
    "游乐园": 4.0,
    "博物馆": 3.0,
    "剧场": 1.5,
    "古镇": 3.0,
    "寺庙": 1.5,
}

# Default hours per category (fallback when sub_category unknown)
CATEGORY_DURATION: dict[str, float] = {
    "自然景观": 4.0,
    "人文历史": 2.5,
    "主题乐园": 4.0,
    "温泉康养": 3.0,
    "户外运动": 3.0,
    "演艺演出": 1.5,
    "休闲农业": 2.5,
    "城市娱乐": 2.0,
}

# Level bonus: 5A/4A sites tend to be larger, add extra time
LEVEL_BONUS: dict[str, float] = {
    "A5": 2.0,
    "A4": 1.0,
    "A3": 0.5,
}

# Opening hours template (open, close) by category
OPENING_HOURS: dict[str, tuple[int, int]] = {
    "自然景观": (8, 18),
    "人文历史": (9, 17),
    "主题乐园": (9, 18),
    "温泉康养": (10, 21),
    "户外运动": (8, 17),
    "演艺演出": (10, 20),
    "休闲农业": (9, 17),
    "城市娱乐": (10, 21),
}


def estimate_play_duration(
    category: str = "",
    sub_category: str = "",
    level: str = "",
    price: float = 0,
) -> float:
    """Estimate play duration in hours for a spot.

    Priority: sub_category > category > default(2h).
    Adds level bonus for 5A/4A/3A sites.
    High-price spots (>100) get +0.5h assuming more to explore.
    """
    # Start with sub_category if available
    if sub_category and sub_category in SUB_CATEGORY_DURATION:
        base = SUB_CATEGORY_DURATION[sub_category]
    elif category and category in CATEGORY_DURATION:
        base = CATEGORY_DURATION[category]
    else:
        base = 2.0

    # Level bonus
    bonus = LEVEL_BONUS.get(level or "", 0)

    # Price bonus: expensive spots tend to have more to see
    price_bonus = 0.5 if price > 100 else 0

    return round(base + bonus + price_bonus, 1)


def get_opening_hours(category: str = "") -> tuple[int, int]:
    """Return (open_hour, close_hour) for a category."""
    return OPENING_HOURS.get(category, (9, 18))
