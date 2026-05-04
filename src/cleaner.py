"""Data cleaner: normalize spot records from all passes."""

import re

from .parser import parse_spot_rules

# Level normalization map
LEVEL_MAP = {
    "5A": "A5",
    "AAAAA": "A5",
    "4A": "A4",
    "AAAA": "A4",
    "3A": "A3",
    "AAA": "A3",
    "2A": "A2",
    "AA": "A2",
    "1A": "A1",
    "A": "A1",
    "非A": "A0",
}


def normalize_level(level: str | None) -> str | None:
    """Normalize attraction level to standard format (A1-A5, A0, None)."""
    if not level:
        return None
    level_stripped = level.strip()
    return LEVEL_MAP.get(level_stripped, level_stripped)


def strip_area_from_name(name: str) -> tuple[str, str]:
    """Remove area suffix from spot name.

    Returns (cleaned_name, area_from_name).
    E.g. "木兰天池（黄陂）" -> ("木兰天池", "黄陂")
    """
    if not name:
        return name, ""

    # Match Chinese parentheses: （xxx）
    match = re.search(r"（([^）]+)）", name)
    if match:
        area_tag = match.group(1)
        cleaned = name[: match.start()] + name[match.end() :]
        return cleaned.strip(), area_tag

    # Match square brackets: [xxx]
    match = re.search(r"\[([^\]]+)\]", name)
    if match:
        area_tag = match.group(1)
        cleaned = name[: match.start()] + name[match.end() :]
        return cleaned.strip(), area_tag

    return name.strip(), ""


def clean_spot_name(name: str) -> str:
    """Clean spot name to canonical form."""
    if not name:
        return ""

    cleaned, _ = strip_area_from_name(name)

    # Remove leading/trailing dashes (used in summary rows)
    if cleaned.startswith("——") or cleaned.startswith("—"):
        return ""

    # Remove trailing whitespace
    cleaned = cleaned.strip()

    return cleaned


def extract_pass_info(pass_name: str) -> dict:
    """Extract pass metadata from filename.

    E.g. "大武汉景区旅游年卡_200元" -> {"name": "大武汉景区旅游年卡", "price": 200}
    """
    match = re.match(r"(.+?)_(\d+)元", pass_name)
    if match:
        return {"name": match.group(1), "price": int(match.group(2))}
    return {"name": pass_name, "price": None}


def clean_spot_record(record: dict) -> dict:
    """Clean and normalize a single spot record."""
    raw_name = record.get("spot_name", "")
    cleaned_name = clean_spot_name(raw_name)
    _, name_area = strip_area_from_name(raw_name)

    # Use the area from record, fallback to extracted area
    area = record.get("area") or name_area or ""
    city = record.get("city") or ""
    level = normalize_level(record.get("level"))
    price = record.get("price")
    pass_name = record.get("pass_name", "")

    rules = parse_spot_rules(record)

    return {
        "spot_name": cleaned_name,
        "raw_name": raw_name,
        "area": area,
        "city": city,
        "level": level,
        "price": price if price is not None else 0,
        "pass_name": pass_name,
        "usage_limit_raw": record.get("usage_limit", ""),
        "notes_raw": record.get("notes", ""),
        "rules": rules,
    }


def clean_all_spots(raw_records: list[dict]) -> list[dict]:
    """Clean all spot records."""
    cleaned = []
    for rec in raw_records:
        spot = clean_spot_record(rec)
        if spot["spot_name"]:  # Skip empty/summary rows
            cleaned.append(spot)
    return cleaned


def get_unique_spots(cleaned: list[dict]) -> list[dict]:
    """Get unique spots by name (before entity alignment)."""
    seen = set()
    unique = []
    for spot in cleaned:
        key = spot["spot_name"]
        if key not in seen:
            seen.add(key)
            unique.append(spot)
    return unique
