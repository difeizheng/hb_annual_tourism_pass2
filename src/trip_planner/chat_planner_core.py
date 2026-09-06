"""Chat-based trip planner: LLM intent parsing + deterministic orchestration.

Pipeline (per grilling consensus):
  1. parse_intent        — LLM extracts structured params from natural language
  2. clarify loop        — ask for critical missing fields (one at a time, ≤3 rounds)
  3. build_trip          — multi_city_planner + amenity_planner + timeline
  4. save to plan_manager + render day-toggle map

LLM NEVER picks spots or assigns days — closed-set selection stays in
deterministic code to prevent hallucinated spots/prices.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

import requests

from src.trip_planner.holidays import find_holiday_by_name, merge_off_blocks
from src.trip_planner.multi_city_planner import plan_multi_city

# ---------------------------------------------------------------------------
# LLM intent parsing
# ---------------------------------------------------------------------------

INTENT_SYSTEM_PROMPT = """你是旅游行程规划的意图解析器。从用户输入中抽取以下字段，仅输出 JSON：

{
  "departure_city": "出发城市，如'武汉'。未提及则为 null",
  "cities": ["想去的城市列表，按用户暗示的顺序"],
  "num_days": 总天数(整数)或 null,
  "pass_name": "年卡名称关键词，如'惠游'/'江城'/'畅玩'。未提及为 null",
  "holiday_phrase": "假期描述原文，如'中秋+国庆+请假'。未提及为 null",
  "leave_days": 请假天数(整数)或 null,
  "travel_style": "economy|midrange|luxury 之一，未提及默认 midrange",
  "transport": "drive|transit 之一，未提及默认 drive",
  "companions": "同行人描述，如'2大1小'。未提及为 null",
  "budget": 预算数字(元)或 null,
  "missing_critical": ["transport", ...]
}

规则：
- critical 字段 = transport, travel_style, companions（错则行程白排）
- 用户原文蕴含但未明说的（如'自驾'→drive），抽取出来就不要列入 missing_critical
- 仅输出 JSON，无其他文字"""


def parse_intent(user_text: str, secrets: dict | None) -> dict | None:
    """Call LLM to extract trip params. Returns None if LLM unavailable/fails."""
    base = secrets.get("llm_api_base", "") if secrets else ""
    key = secrets.get("llm_api_key", "") if secrets else ""
    model = secrets.get("llm_model", "") if secrets else ""
    if not (base and key and model):
        return None
    try:
        resp = requests.post(
            f"{base.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_text},
                ],
                "max_tokens": 400,
                "temperature": 0.1,
            },
            timeout=20,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# Holiday phrase → concrete date range
# ---------------------------------------------------------------------------

_HOLIDAY_KEYWORDS = ["国庆", "中秋", "春节", "清明", "端午", "劳动节", "五一", "元旦"]


def resolve_holiday_dates(
    holiday_phrase: str | None,
    leave_days: int | None,
    today: date | None = None,
) -> dict | None:
    """Resolve '中秋+国庆+请假3天' into {start, end, days, note}.

    Strategy: find the named holidays in current/next year, take the widest
    block, extend by leave_days on both ends if it connects more off-days.
    """
    if not holiday_phrase:
        return None
    today = today or date.today()
    phrases = [h for h in _HOLIDAY_KEYWORDS if h in holiday_phrase]
    if not phrases:
        return None

    leave = max(int(leave_days or 0), 0)

    for year in (today.year, today.year + 1):
        # Collect all off blocks of the named holidays in this year
        blocks = []
        for h in phrases:
            blocks.extend(find_holiday_by_name(h, year))
        if not blocks:
            continue
        blocks.sort()

        # Merge blocks separated by ≤ leave days (leave bridges them)
        merged = [list(blocks[0])]
        for s, e in blocks[1:]:
            gap = (s - merged[-1][1]).days - 1
            if 0 < gap <= leave:
                merged[-1][1] = e
                leave -= gap
            else:
                merged.append([s, e])
        # Pick the longest merged block
        start, end = max(merged, key=lambda b: (b[1] - b[0]).days)

        # Extend by remaining leave on both ends (attach adjacent off-days)
        # e.g. leave before block if the previous day is a weekend
        if leave > 0:
            lead = merge_off_blocks(end + timedelta(days=1),
                                    end + timedelta(days=leave))
            if lead:
                end = lead[0][1]
            else:
                # just extend linearly
                end = end + timedelta(days=leave)
        days = (end - start).days + 1
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": days,
            "note": f"{'、'.join(phrases)} + 请假{leave_days}天 → {start}~{end}（{days}天）",
        }
    return None


# ---------------------------------------------------------------------------
# Trip orchestration
# ---------------------------------------------------------------------------

def build_trip_from_intent(
    intent: dict,
    pass_spots: list[dict],
    departure: dict,
) -> dict:
    """Run the deterministic pipeline from parsed intent.

    Args:
        intent: parse_intent output (validated)
        pass_spots: spots covered by the user's pass (import_pass_spots result)
        departure: {name, lng, lat}

    Returns:
        plan_multi_city result + meta (dates, style, etc.)
    """
    cities = intent.get("cities") or []
    num_days = int(intent.get("num_days") or 3)

    # Filter pass spots to requested cities when specified
    if cities:
        pool = [s for s in pass_spots if s.get("city") in cities]
        # keep spots whose city is in list OR unlisted-but-nearby; fall back to all
        if not pool:
            pool = pass_spots
    else:
        pool = pass_spots

    result = plan_multi_city(
        spots=pool,
        departure=departure,
        num_days=num_days,
        travel_month=intent.get("_travel_month", 10),
        city_order=cities or None,
        daily_capacity=8.0,
    )
    result["intent_meta"] = {
        "departure_city": intent.get("departure_city") or departure.get("name", ""),
        "cities": cities,
        "num_days": num_days,
        "pass_name": intent.get("pass_name"),
        "travel_style": intent.get("travel_style") or "midrange",
        "transport": intent.get("transport") or "drive",
        "companions": intent.get("companions"),
        "budget": intent.get("budget"),
        "holiday": intent.get("_holiday_resolved"),
    }
    return result


def validate_intent_against_pool(intent: dict, pass_spots: list[dict]) -> list[str]:
    """Check requested cities actually have pass coverage. Returns warnings."""
    warnings = []
    cities = intent.get("cities") or []
    if cities:
        covered = {s.get("city", "") for s in pass_spots}
        for c in cities:
            if c not in covered:
                warnings.append(f"年卡不覆盖「{c}」或无坐标数据")
    return warnings
