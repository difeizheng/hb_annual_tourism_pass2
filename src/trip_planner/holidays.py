"""Static China holiday tables for 2025-2026 (no API dependency).

Used by chat_planner to parse phrases like "中秋+国庆+请假2天" into real
date ranges. Extend HOLIDAYS when new year arrives — keep it static data,
never fetch at runtime.
"""

from datetime import date, timedelta

# {date: label}  official public holidays; make-up workdays in WORKDAY_WEEKENDS
HOLIDAYS = {
    # ---- 2025 ----
    date(2025, 1, 1): "元旦",
    date(2025, 1, 28): "春节", date(2025, 1, 29): "春节", date(2025, 1, 30): "春节",
    date(2025, 1, 31): "春节", date(2025, 2, 1): "春节", date(2025, 2, 2): "春节",
    date(2025, 2, 3): "春节", date(2025, 2, 4): "春节",
    date(2025, 4, 4): "清明", date(2025, 4, 5): "清明", date(2025, 4, 6): "清明",
    date(2025, 5, 1): "劳动节", date(2025, 5, 2): "劳动节", date(2025, 5, 3): "劳动节",
    date(2025, 5, 4): "劳动节", date(2025, 5, 5): "劳动节",
    date(2025, 5, 31): "端午", date(2025, 6, 1): "端午", date(2025, 6, 2): "端午",
    # 2025 中秋(10月6日)与国庆连休，不单列
    date(2025, 10, 1): "国庆", date(2025, 10, 2): "国庆", date(2025, 10, 3): "国庆",
    date(2025, 10, 4): "国庆", date(2025, 10, 5): "国庆", date(2025, 10, 6): "国庆(中秋)",
    date(2025, 10, 7): "国庆", date(2025, 10, 8): "国庆",
    # ---- 2026 (国务院 2025-11 发布版) ----
    date(2026, 1, 1): "元旦", date(2026, 1, 2): "元旦", date(2026, 1, 3): "元旦",
    date(2026, 2, 15): "春节(除夕)", date(2026, 2, 16): "春节", date(2026, 2, 17): "春节",
    date(2026, 2, 18): "春节", date(2026, 2, 19): "春节", date(2026, 2, 20): "春节",
    date(2026, 2, 21): "春节", date(2026, 2, 22): "春节", date(2026, 2, 23): "春节",
    date(2026, 4, 4): "清明", date(2026, 4, 5): "清明", date(2026, 4, 6): "清明",
    date(2026, 5, 1): "劳动节", date(2026, 5, 2): "劳动节", date(2026, 5, 3): "劳动节",
    date(2026, 5, 4): "劳动节", date(2026, 5, 5): "劳动节",
    date(2026, 6, 19): "端午", date(2026, 6, 20): "端午", date(2026, 6, 21): "端午",
    date(2026, 9, 25): "中秋", date(2026, 9, 26): "中秋", date(2026, 9, 27): "中秋",
    date(2026, 10, 1): "国庆", date(2026, 10, 2): "国庆", date(2026, 10, 3): "国庆",
    date(2026, 10, 4): "国庆", date(2026, 10, 5): "国庆", date(2026, 10, 6): "国庆",
    date(2026, 10, 7): "国庆", date(2026, 10, 8): "国庆",
}

# 调休上班的周末（官方安排，影响"周末+请假拼假"计算）
WORKDAY_WEEKENDS = {
    # 2025
    date(2025, 1, 26), date(2025, 2, 8),
    date(2025, 4, 27), date(2025, 9, 28), date(2025, 10, 11),
    # 2026
    date(2026, 2, 14), date(2026, 2, 28),
    date(2026, 4, 11), date(2026, 9, 26), date(2026, 10, 10),
}


def is_off_day(d: date) -> bool:
    """True if d is a rest day: statutory holiday OR normal weekend (not a make-up workday)."""
    if d in HOLIDAYS:
        return True
    if d.weekday() >= 5:  # Sat/Sun
        return d not in WORKDAY_WEEKENDS
    return False


def merge_off_blocks(
    start: date, end: date, leave_days: set[date] | None = None
) -> list[tuple[date, date]]:
    """Merge consecutive off-days within [start, end] into contiguous blocks.

    leave_days: user's personal leave dates, treated as off-days so that
    "中秋+国庆+请假" can form one contiguous travel window.
    """
    leave = leave_days or set()
    blocks: list[tuple[date, date]] = []
    cur_start = None
    d = start
    while d <= end:
        if is_off_day(d) or d in leave:
            if cur_start is None:
                cur_start = d
        else:
            if cur_start is not None:
                blocks.append((cur_start, d - timedelta(days=1)))
                cur_start = None
        d += timedelta(days=1)
    if cur_start is not None:
        blocks.append((cur_start, end))
    return blocks


def find_holiday_by_name(name: str, year: int) -> list[tuple[date, date]]:
    """All contiguous blocks of a named holiday in the year, e.g. name='国庆'."""
    wanted = [d for d, label in HOLIDAYS.items() if name in label and d.year == year]
    if not wanted:
        return []
    wanted.sort()
    blocks: list[tuple[date, date]] = []
    s = e = wanted[0]
    for d in wanted[1:]:
        if (d - e).days == 1:
            e = d
        else:
            blocks.append((s, e))
            s = e = d
    blocks.append((s, e))
    return blocks
