"""Build day-by-day timeline with estimated time slots."""
from __future__ import annotations

from src.trip_planner.play_duration import estimate_play_duration, get_opening_hours


def build_day_timeline(
    day_spots: list[dict],
    start_hour: int = 9,
    start_min: int = 0,
) -> dict:
    """Generate estimated timeline for a day's spots.

    Inserts lunch break around 12:00 and estimates travel time between spots
    based on category defaults (rough estimate: 30 min per transition).

    Args:
        day_spots: list of spot dicts (ordered) with play_hours field
        start_hour, start_min: day start time

    Returns:
        {
            "slots": [{spot, start, end, play_hours}],
            "lunch": {start, end} or None,
            "end_time": str,
            "warnings": list[str],
        }
    """
    if not day_spots:
        return {"slots": [], "lunch": None, "end_time": "", "warnings": ["无景点"]}

    slots = []
    warnings = []
    current_hour = start_hour
    current_min = start_min
    lunch_inserted = False
    lunch_break_start = None
    lunch_break_end = None
    travel_min = 30  # Default between-spot travel time

    for spot in day_spots:
        play_hours = spot.get("_play_hours", 2.0)

        # Check if we need lunch break
        if not lunch_inserted and current_hour >= 11 and current_min >= 30:
            lunch_break_start = _format_time(current_hour, current_min)
            current_hour += 1  # 1-hour lunch
            lunch_break_end = _format_time(current_hour, current_min)
            lunch_inserted = True

        # Check closing hours
        category = spot.get("category", "")
        open_h, close_h = get_opening_hours(category)
        estimated_end = current_hour + play_hours

        if estimated_end > close_h:
            warnings.append(
                f"{spot.get('name', '')} 可能在 {close_h}:00 关闭，建议调整到上午"
            )

        start_str = _format_time(current_hour, current_min)
        end_hour = current_hour + int(play_hours)
        end_min = current_min + int((play_hours % 1) * 60)
        if end_min >= 60:
            end_hour += 1
            end_min -= 60
        end_str = _format_time(end_hour, end_min)

        slots.append({
            "spot_name": spot.get("name", ""),
            "city": spot.get("city", ""),
            "category": category,
            "play_hours": play_hours,
            "start": start_str,
            "end": end_str,
        })

        # Add travel time to next spot
        current_hour = end_hour
        current_min = end_min + travel_min
        if current_min >= 60:
            current_hour += 1
            current_min -= 60

    # Add lunch break at end if never inserted
    if not lunch_inserted:
        # Insert at closest point to 12:00
        if len(slots) >= 2:
            mid = len(slots) // 2
            slots.insert(mid, {
                "spot_name": "午餐",
                "city": "",
                "category": "餐饮",
                "play_hours": 1.0,
                "start": "12:00",
                "end": "13:00",
            })

    return {
        "slots": slots,
        "lunch": {"start": lunch_break_start, "end": lunch_break_end} if lunch_inserted else None,
        "end_time": _format_time(current_hour, current_min),
        "warnings": warnings,
    }


def _format_time(hour: int, minute: int) -> str:
    """Format hour and minute as HH:MM string."""
    return f"{hour:02d}:{minute:02d}"
