"""LLM-powered spot recommendation and price value scoring."""
from __future__ import annotations

import json
from dataclasses import dataclass

import requests


LEVEL_SCORES = {"A5": 8.0, "A4": 6.0, "A3": 4.0, "A2": 2.0, "A1": 1.0, "A0": 0.5}

LEVEL_TAGS = {"A5": "5A", "A4": "4A", "A3": "3A", "A2": "2A", "A1": "A级"}


@dataclass
class SpotRecommendation:
    rating: float
    summary: str
    pros: list[str]
    cons: list[str]
    tags: list[str]
    price_value_score: float


def compute_price_value_score(price: float, level: str) -> float:
    """0-10 score based on price vs level. Higher level + lower price = higher score."""
    base = LEVEL_SCORES.get(level, 3.0)
    penalty = min(price / 20.0, 5.0)
    return round(max(0, min(10, base - penalty)), 1)


def generate_spot_recommendation(spot: dict, secrets: dict | None = None) -> SpotRecommendation:
    """Generate recommendation. Tries LLM first, falls back to rule-based."""
    name = spot.get("name", "")
    city = spot.get("city", "")
    category = spot.get("category", "")
    level = spot.get("level", "")
    price = spot.get("price", 0)
    notes = spot.get("notes", "")
    tags = spot.get("tags", [])
    area = spot.get("area", "")

    # Try LLM if configured
    llm_cfg = _get_llm_config(secrets)
    if llm_cfg:
        try:
            return _llm_recommendation(name, city, category, level, price, notes, tags, area, llm_cfg)
        except Exception:
            pass

    return get_fallback_recommendation(name, city, category, level, price, notes, tags, area)


def _get_llm_config(secrets: dict | None) -> dict | None:
    """Extract LLM config from secrets. Returns None if incomplete."""
    if not secrets:
        return None
    base = secrets.get("llm_api_base", "")
    key = secrets.get("llm_api_key", "")
    model = secrets.get("llm_model", "")
    if base and key and model:
        return {"base": base.rstrip("/"), "key": key, "model": model}
    return None


def _llm_recommendation(
    name, city, category, level, price, notes, tags, area, cfg: dict
) -> SpotRecommendation:
    """Call OpenAI-compatible API for recommendation."""
    system_msg = (
        "你是一个专业的中国旅游顾问。根据提供的景点信息生成简明评价。\n"
        "要求：\n"
        "1. rating: 1-5分（保留1位小数），基于等级、知名度、性价比\n"
        "2. summary: 50-100字，客观描述特色\n"
        "3. pros: 2-4条优点\n"
        "4. cons: 1-3条缺点\n"
        "5. tags: 从[必打卡,亲子友好,情侣适宜,摄影胜地,性价比高,历史文化,自然风光,美食推荐,季节限定]中选择2-4个\n"
        "仅输出JSON，无额外文字。"
    )
    user_msg = json.dumps({
        "name": name, "city": city, "area": area, "category": category,
        "level": level, "price": price, "notes": notes, "tags": tags,
    }, ensure_ascii=False)

    resp = requests.post(
        f"{cfg['base']}/chat/completions",
        headers={"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"},
        json={
            "model": cfg["model"],
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": 300,
            "temperature": 0.3,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"].strip()

    # Try to extract JSON from markdown code blocks
    if "```" in content:
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    parsed = json.loads(content)
    pv_score = compute_price_value_score(float(price or 0), level)
    return SpotRecommendation(
        rating=float(parsed.get("rating", 3.5)),
        summary=parsed.get("summary", ""),
        pros=parsed.get("pros", []),
        cons=parsed.get("cons", []),
        tags=parsed.get("tags", []),
        price_value_score=pv_score,
    )


def get_fallback_recommendation(name, city, category, level, price, notes, tags, area):
    """Rule-based fallback when LLM is unavailable."""
    pv_score = compute_price_value_score(float(price or 0), level)

    # Rating from level
    rating_map = {"A5": 4.8, "A4": 4.2, "A3": 3.8, "A2": 3.2, "A1": 2.5}
    rating = rating_map.get(level, 3.5)
    if float(price or 0) > 100:
        rating = max(1.0, rating - 0.3)

    # Tags
    result_tags = []
    level_tag = LEVEL_TAGS.get(level)
    if level_tag:
        result_tags.append(level_tag)
    if rating >= 4.5:
        result_tags.append("推荐")
    if category == "自然景观":
        result_tags.append("自然风光")
    elif category == "人文历史":
        result_tags.append("历史文化")
    elif category == "主题乐园":
        result_tags.append("亲子友好")
    elif category == "温泉康养":
        result_tags.append("休闲放松")
    if pv_score >= 6:
        result_tags.append("性价比高")
    for t in (tags or []):
        if t not in result_tags:
            result_tags.append(t)

    # Summary
    price_str = f"门票{price}元" if price else "免费参观"
    level_str = f"{level}级景区" if level else ""
    parts = [p for p in [name, level_str, category, city, price_str] if p]
    summary = f"{name}位于{city}{' ' + area if area else ''}，属于{category}类型，{price_str}。"
    if notes:
        summary += f" 提示：{notes}"

    # Pros/cons from level and price
    pros = []
    if level in ("A5", "A4"):
        pros.append(f"{level_str}，品质有保证")
    if float(price or 0) <= 50:
        pros.append("门票实惠，性价比高")
    elif float(price or 0) == 0:
        pros.append("免费景点，值得参观")
    if category == "自然景观":
        pros.append("自然风光优美")
    elif category == "人文历史":
        pros.append("历史文化底蕴深厚")
    elif category == "主题乐园":
        pros.append("适合亲子游玩")
    if not pros:
        pros.append(f"{category}类景点，适合休闲游玩")

    cons = []
    if float(price or 0) > 100:
        cons.append("门票偏贵")
    if float(price or 0) > 150:
        cons.append("节假日可能拥挤")
    if not cons:
        if level == "A5":
            cons.append("节假日人流较大")
        else:
            cons.append("建议提前了解开放时间")

    return SpotRecommendation(
        rating=round(rating, 1),
        summary=summary,
        pros=pros,
        cons=cons,
        tags=result_tags[:6],
        price_value_score=pv_score,
    )
