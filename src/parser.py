"""Rule parser: extract structured rules from usage_limit and notes fields."""

import re


def parse_usage_limit(text: str | None) -> dict:
    """Parse usage_limit field into structured data.

    Examples:
        "免6次" -> {"type": "free", "count": 6}
        "不限次" -> {"type": "unlimited"}
        "免1次" -> {"type": "free", "count": 1}
        "25元/次" -> {"type": "supplement", "amount": 25}
        "需预约共限6次" -> {"type": "free", "count": 6, "requires_appointment": True}
    """
    if not text:
        return {"type": "unknown", "raw": text}

    result: dict = {"raw": text, "requires_appointment": False}

    # Check for appointment requirement
    if "预约" in text:
        result["requires_appointment"] = True

    # Unlimited
    if any(kw in text for kw in ["不限次", "不限", "免费入园不限次数", "免费入园不限次", "无限次"]):
        result["type"] = "unlimited"
        return result

    # Supplement per use
    match = re.search(r"(\d+(?:\.\d+)?)元[/／每]次", text)
    if match:
        result["type"] = "supplement"
        result["supplement_amount"] = float(match.group(1))
        return result

    match = re.search(r"补(\d+(?:\.\d+)?)", text)
    if match and "免" not in text:
        result["type"] = "supplement"
        result["supplement_amount"] = float(match.group(1))
        return result

    # Free N times
    match = re.search(r"免(\d+)次", text)
    if match:
        result["type"] = "free"
        result["count"] = int(match.group(1))
        return result

    # Limited N times (without "免")
    match = re.search(r"限(\d+)次", text)
    if match:
        result["type"] = "free"
        result["count"] = int(match.group(1))
        return result

    # "共免6次" / "合计免6次" / "共免5次"
    match = re.search(r"共?免(\d+)次", text)
    if match:
        result["type"] = "free"
        result["count"] = int(match.group(1))
        return result

    # "免费入园限6次" / "免费入园免6次" / "免费入园限N次"
    match = re.search(r"免费入园(?:免|限)(\d+)次", text)
    if match:
        result["type"] = "free"
        result["count"] = int(match.group(1))
        return result

    # "首次免费后20/次限6次"
    match = re.search(r"首次免费.*?限(\d+)次", text)
    if match:
        result["type"] = "free_then_supplement"
        result["count"] = int(match.group(1))
        return result

    # "免费预约"
    if "免费预约" in text:
        result["type"] = "free"
        result["count"] = None
        return result

    # "补XX即可"
    match = re.search(r"补(\d+(?:\.\d+)?)即可", text)
    if match:
        result["type"] = "supplement"
        result["supplement_amount"] = float(match.group(1))
        return result

    # Date range restrictions like "2026年共免6次"
    match = re.search(r"\d{4}年共?免(\d+)次", text)
    if match:
        result["type"] = "free"
        result["count"] = int(match.group(1))
        return result

    # "可约当天"
    if "可约当天" in text:
        result["type"] = "free"
        result["count"] = None
        return result

    result["type"] = "unknown"
    return result


def parse_notes(text: str | None) -> dict:
    """Parse notes field into structured rules.

    Extracts:
        - child_policy: children admission rules
        - holiday_restriction: holiday usage restrictions
        - seasonal: seasonal availability
        - appointment_detail: appointment requirements
        - supplement_detail: supplement details
        - night_field: night session rules
        - other: anything else
    """
    if not text:
        return {}

    result: dict = {"raw": text}

    # Child policy
    child_patterns = [
        (r"(\d+(?:\.\d+)?)米以下儿童(?:免[费票])", "child_free_height"),
        (r"儿童达?(\d+(?:\.\d+)?)米需购票", "child_must_pay_height"),
        (r"(\d+)岁以下儿童免费", "child_free_age"),
        (r"(\d+)岁以下(?:不)?建议.*?体验", "child_min_age"),
        (r"(\d+)CM以上", "child_min_height_cm"),
    ]
    for pattern, key in child_patterns:
        match = re.search(pattern, text)
        if match:
            if key not in result:
                result[key] = []
            result[key].append(match.group(1))

    # Holiday restriction
    if "大型节假日" in text or "劳动节" in text or "国庆节" in text or "五一" in text or "十一" in text or "春节" in text or "暑假" in text or "周末" in text:
        if "不接待" in text or "不接待年卡" in text:
            result["holiday_restriction"] = "blocked"
        elif "需提前" in text or "提前" in text:
            result["holiday_restriction"] = "advance_booking"
        else:
            result["holiday_restriction"] = "notice"

    # Seasonal
    seasonal_kw = ["季节性", "仅夏季", "仅冬季", "开漂", "闭园", "营业"]
    for kw in seasonal_kw:
        if kw in text:
            result.setdefault("seasonal_notes", []).append(kw)

    # Appointment details
    appt_patterns = [
        r"提前(\d+)天",
        r"至少提前(\d+)天",
        r"需至少提前(\d+)天",
    ]
    for pattern in appt_patterns:
        match = re.search(pattern, text)
        if match:
            result["appointment_days"] = int(match.group(1))

    # Supplement details
    supp_matches = re.findall(r"补(?:差)?(\d+(?:\.\d+)?)", text)
    if supp_matches:
        result["supplement_amounts"] = [float(x) for x in supp_matches]

    # Night session rules
    if "夜场" in text or "夜游" in text:
        # Match "16:00之前" or "16点之前"
        night_match = re.search(r"(\d{1,2})[:：]\d{2}之前", text)
        if not night_match:
            night_match = re.search(r"(\d{1,2})[:：]?点之前", text)
        if night_match:
            result["night_entry_hour"] = int(night_match.group(1))
        else:
            result["has_night_session"] = True

    # Specific date restrictions
    date_match = re.search(r"(\d+月\d+日[至-]\d+月\d+日)", text)
    if date_match:
        result["date_restriction"] = date_match.group(1)

    return result


def parse_spot_rules(record: dict) -> dict:
    """Parse all rules from a spot record."""
    usage = parse_usage_limit(record.get("usage_limit"))
    notes = parse_notes(record.get("notes"))
    return {
        "usage_limit": usage,
        "notes": notes,
    }
