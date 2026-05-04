"""Seasonal recommendation engine with multi-tier scoring."""
from __future__ import annotations

MONTH_TO_SEASON = {
    1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "autumn", 10: "autumn", 11: "autumn", 12: "winter",
}
SEASON_NAMES = {"spring": "春季", "summer": "夏季", "autumn": "秋季", "winter": "冬季"}
SEASON_EMOJI = {"spring": "🌸", "summer": "☀️", "autumn": "🍂", "winter": "❄️"}

CLIMATE_INFO = {
    "spring": {
        "temp_range": "10-25°C",
        "desc": "春暖花开，户外游玩最佳，赏花踏青好时节",
        "tips": "推荐赏花、登山、古镇游览",
    },
    "summer": {
        "temp_range": "25-35°C",
        "desc": "炎热夏季，水上活动最佳，避暑纳凉好去处",
        "tips": "推荐漂流、水上乐园、溶洞避暑",
    },
    "autumn": {
        "temp_range": "10-25°C",
        "desc": "秋高气爽，户外登山最佳，赏红叶好时节",
        "tips": "推荐登山、赏秋、古镇游览",
    },
    "winter": {
        "temp_range": "0-10°C",
        "desc": "寒冷冬季，室内温泉最佳，滑雪运动好时节",
        "tips": "推荐温泉、滑雪、博物馆、人文历史",
    },
}

SUB_CATEGORY_SCORES: dict[str, dict[str, int]] = {
    "漂流":     {"spring": 2, "summer": 5, "autumn": 2, "winter": 0},
    "水上乐园": {"spring": 2, "summer": 5, "autumn": 1, "winter": 0},
    "滑雪":     {"spring": 2, "summer": 1, "autumn": 2, "winter": 5},
    "温泉":     {"spring": 3, "summer": 2, "autumn": 4, "winter": 5},
    "溶洞":     {"spring": 3, "summer": 4, "autumn": 3, "winter": 3},
    "动物园":   {"spring": 4, "summer": 3, "autumn": 4, "winter": 2},
    "植物园":   {"spring": 5, "summer": 3, "autumn": 4, "winter": 2},
    "游乐园":   {"spring": 3, "summer": 3, "autumn": 3, "winter": 2},
    "博物馆":   {"spring": 3, "summer": 3, "autumn": 3, "winter": 4},
    "剧场":     {"spring": 2, "summer": 2, "autumn": 2, "winter": 3},
    "古镇":     {"spring": 4, "summer": 2, "autumn": 4, "winter": 3},
    "寺庙":     {"spring": 3, "summer": 2, "autumn": 3, "winter": 3},
}

CATEGORY_SCORES: dict[str, dict[str, int]] = {
    "自然景观": {"spring": 4, "summer": 3, "autumn": 5, "winter": 2},
    "人文历史": {"spring": 3, "summer": 2, "autumn": 3, "winter": 4},
    "主题乐园": {"spring": 3, "summer": 3, "autumn": 3, "winter": 2},
    "温泉康养": {"spring": 3, "summer": 2, "autumn": 4, "winter": 5},
    "户外运动": {"spring": 3, "summer": 4, "autumn": 3, "winter": 1},
    "演艺演出": {"spring": 2, "summer": 2, "autumn": 2, "winter": 2},
    "休闲农业": {"spring": 5, "summer": 3, "autumn": 4, "winter": 1},
    "城市娱乐": {"spring": 2, "summer": 2, "autumn": 2, "winter": 2},
    "其他":     {"spring": 1, "summer": 1, "autumn": 1, "winter": 1},
}

NAME_KEYWORDS = {
    "spring": [
        "樱花", "桃花", "梅园", "牡丹", "郁金香", "杜鹃", "油菜",
        "花卉", "花园", "花海", "春游", "踏青", "生态园", "植物园",
    ],
    "summer": [
        "漂流", "水上", "水世界", "游泳池", "避暑", "峡谷",
        "瀑布", "溪流", "玻璃桥", "玻璃滑道",
    ],
    "autumn": [
        "红叶", "赏秋", "登山", "枫叶", "银杏", "秋景", "秋色", "金秋",
    ],
    "winter": [
        "滑雪", "温泉", "汤泉", "汤池", "冰雪",
    ],
}

REASON_TEMPLATES = {
    "漂流":     {"summer": "漂流项目，夏季水上活动最佳"},
    "水上乐园": {"summer": "水上乐园，夏季避暑纳凉首选"},
    "滑雪":     {"winter": "滑雪场，冬季冰雪运动专属体验"},
    "温泉":     {"winter": "温泉康养，冬季泡汤驱寒最佳时节"},
    "溶洞":     {"summer": "溶洞恒温凉爽，夏季避暑好去处"},
    "动物园":   {"spring": "春暖花开，动物园亲子踏青舒适宜人"},
    "植物园":   {"spring": "植物园花季正盛，春季赏花绝佳"},
    "游乐园":   {"spring": "主题乐园，春秋气候舒适适合游玩"},
    "博物馆":   {"winter": "室内博物馆，冬季避寒学习历史文化"},
    "剧场":     {"winter": "室内演出，冬季文化娱乐好选择"},
    "古镇":     {"spring": "古镇春色宜人，春秋漫步最佳"},
    "寺庙":     {"spring": "古刹清幽，四季皆宜"},
}

CATEGORY_REASONS = {
    "spring": {
        "自然景观": "春季自然景观，赏花登山正当时",
        "人文历史": "春日访古，人文景观舒适宜人",
        "主题乐园": "春秋气候舒适，主题乐园游玩体验佳",
        "温泉康养": "春季温泉，舒缓身心好去处",
        "户外运动": "春季户外运动，天气适宜",
        "休闲农业": "春季农事体验，踏青赏花正当时",
    },
    "summer": {
        "自然景观": "夏季自然景观，避暑纳凉好去处",
        "人文历史": "夏季人文景观，室内清凉避暑",
        "户外运动": "夏季户外运动，亲近自然活力十足",
        "休闲农业": "夏日田园，夏季采摘避暑",
    },
    "autumn": {
        "自然景观": "秋季自然景观，赏红叶秋景最佳",
        "人文历史": "秋日访古，秋高气爽宜出行",
        "户外运动": "秋季户外运动，温度适宜体力充沛",
        "休闲农业": "秋日丰收季，采摘赏秋好时节",
    },
    "winter": {
        "自然景观": "冬季自然景观，静谧清幽别有情调",
        "人文历史": "冬季人文历史，室内参观不受天气影响",
        "主题乐园": "冬日主题乐园，避开人流高峰",
        "温泉康养": "冬季温泉康养，驱寒暖身最佳选择",
        "演艺演出": "冬季室内演出，文化娱乐好选择",
    },
}


def calculate_seasonal_score(spot: dict, season: str) -> tuple[int, str]:
    """Calculate seasonal relevance score (0-5) and reason string."""
    sub = spot.get("sub_category", "") or ""
    cat = spot.get("category", "") or "其他"
    name = spot.get("name", "") or ""
    tags = spot.get("tags", []) or []

    # Priority 1: sub_category explicit seasonal score
    if sub in SUB_CATEGORY_SCORES:
        score = SUB_CATEGORY_SCORES[sub].get(season, 1)
        reason = REASON_TEMPLATES.get(sub, {}).get(season, f"{sub}，四季皆可游玩")
        return score, reason

    # Priority 2: name keyword match (Tier 5)
    for kw in NAME_KEYWORDS.get(season, []):
        if kw in name:
            return 5, f"「{kw}」为主题，{SEASON_NAMES[season]}特色景点"

    # Priority 3: category-level score
    cat_scores = CATEGORY_SCORES.get(cat, CATEGORY_SCORES["其他"])
    score = cat_scores.get(season, 1)

    # Adjustments
    if "5A" in tags or "4A" in tags:
        score = min(score + 1, 5)
    if "季节性" in tags:
        score = min(score + 1, 5)

    reason = CATEGORY_REASONS.get(season, {}).get(cat, f"{cat}，四季皆可")
    return score, reason


def get_seasonal_recommendations(
    spots: list[dict],
    month: int,
    city_filter: list[str] | None = None,
) -> dict:
    """Generate tiered seasonal recommendations.

    Returns dict with season info, climate context, and three tiers of spots.
    """
    season = MONTH_TO_SEASON.get(month, "spring")
    climate = CLIMATE_INFO[season]

    must_visit: list[tuple[dict, str, int]] = []
    recommended: list[tuple[dict, str, int]] = []
    optional: list[tuple[dict, str, int]] = []

    for spot in spots:
        if city_filter and spot.get("city", "") not in city_filter:
            continue

        score, reason = calculate_seasonal_score(spot, season)
        if score == 0:
            continue

        entry = (spot, reason, score)
        if score >= 4:
            must_visit.append(entry)
        elif score >= 3:
            recommended.append(entry)
        else:
            optional.append(entry)

    # Sort each tier by score desc, then by price desc (value sorting)
    for tier in (must_visit, recommended, optional):
        tier.sort(key=lambda x: (-x[2], -x[0].get("price", 0)))

    return {
        "season": SEASON_NAMES[season],
        "season_key": season,
        "emoji": SEASON_EMOJI[season],
        "month": month,
        "climate": climate,
        "must_visit": must_visit,
        "recommended": recommended,
        "optional": optional,
        "total_count": len(must_visit) + len(recommended) + len(optional),
    }
