"""Tests for multi_city_planner and holidays."""

import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.trip_planner.holidays import (
    HOLIDAYS, WORKDAY_WEEKENDS, is_off_day, merge_off_blocks, find_holiday_by_name,
)
from src.trip_planner.multi_city_planner import (
    order_cities, allocate_days, plan_multi_city,
)


def _spot(name, city, lng, lat, hours=3.0):
    return {
        "name": name, "city": city, "lng": lng, "lat": lat,
        "category": "自然风光", "level": "4A", "price": 60,
        "_play_hours": hours,
    }


WUHAN = {"name": "武汉", "lng": 114.30, "lat": 30.59}


class TestHolidays:
    def test_national_day_2025_block(self):
        blocks = find_holiday_by_name("国庆", 2025)
        assert (date(2025, 10, 1), date(2025, 10, 8)) in blocks

    def test_makeup_workday_is_not_off(self):
        # 2025-09-28 (Sunday) is a make-up workday
        assert not is_off_day(date(2025, 9, 28))

    def test_normal_weekend_is_off(self):
        assert not is_off_day(date(2025, 10, 11))  # makeup workday
        assert is_off_day(date(2025, 11, 15))  # regular Saturday

    def test_merge_off_blocks_spans_holiday_plus_weekend(self):
        # 2025-09-29/30 are workdays; Oct 1-8 holiday. With leave on 9/29-30,
        # merge_off_blocks over Sep29-Oct8 yields one contiguous block.
        blocks = merge_off_blocks(
            date(2025, 9, 29), date(2025, 10, 8),
            leave_days={date(2025, 9, 29), date(2025, 9, 30)},
        )
        assert blocks == [(date(2025, 9, 29), date(2025, 10, 8))]

    def test_holiday_name_lookup_2026_midautumn_national_merge(self):
        # 2026: 中秋 9/25-27 (Fri-Sun), 国庆 10/1-8. Leave on 9/28-30
        # stitches everything into one 14-day window.
        blocks = merge_off_blocks(
            date(2026, 9, 25), date(2026, 10, 8),
            leave_days={date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30)},
        )
        assert blocks == [(date(2026, 9, 25), date(2026, 10, 8))]

        # Without leave: two separate blocks
        blocks2 = merge_off_blocks(date(2026, 9, 25), date(2026, 10, 8))
        assert blocks2 == [
            (date(2026, 9, 25), date(2026, 9, 27)),
            (date(2026, 10, 1), date(2026, 10, 8)),
        ]


class TestOrderCities:
    def test_suggested_order_respected(self):
        groups = {"恩施": [_spot("a", "恩施", 109.5, 30.2)],
                  "宜昌": [_spot("b", "宜昌", 111.3, 30.7)]}
        order = order_cities(groups, WUHAN, suggested_order=["恩施", "宜昌"])
        assert order == ["恩施", "宜昌"]

    def test_nearest_chain_from_departure(self):
        groups = {"恩施": [_spot("a", "恩施", 109.5, 30.2)],
                  "宜昌": [_spot("b", "宜昌", 111.3, 30.7)]}
        order = order_cities(groups, WUHAN)
        assert order == ["宜昌", "恩施"]  # 宜昌 closer to 武汉

    def test_invalid_suggestion_falls_back(self):
        groups = {"宜昌": [_spot("b", "宜昌", 111.3, 30.7)]}
        order = order_cities(groups, WUHAN, suggested_order=["北京", "上海"])
        assert order == ["宜昌"]


class TestAllocateDays:
    def test_allocation_sums_to_total(self):
        groups = {
            "宜昌": [_spot(f"s{i}", "宜昌", 111.3, 30.7) for i in range(10)],
            "恩施": [_spot(f"t{i}", "恩施", 109.5, 30.2) for i in range(6)],
        }
        alloc = allocate_days(["宜昌", "恩施"], groups, 10, WUHAN)
        assert sum(alloc.values()) == 10
        assert alloc["宜昌"] >= alloc["恩施"]

    def test_min_days_floor(self):
        groups = {
            "宜昌": [_spot("s", "宜昌", 111.3, 30.7)],
            "恩施": [_spot(f"t{i}", "恩施", 109.5, 30.2) for i in range(12)],
        }
        alloc = allocate_days(["宜昌", "恩施"], groups, 2, WUHAN)
        assert alloc["宜昌"] >= 1 and alloc["恩施"] >= 1
        assert sum(alloc.values()) == 2


class TestPlanMultiCity:
    def test_ten_day_yichang_enshi(self):
        spots = (
            [_spot(f"宜昌{i}", "宜昌", 111.28 + i * 0.02, 30.69 + i * 0.01, hours=4.0) for i in range(12)]
            + [_spot(f"恩施{i}", "恩施", 109.49 + i * 0.02, 30.27 + i * 0.01, hours=4.0) for i in range(8)]
        )
        result = plan_multi_city(spots, WUHAN, num_days=10, travel_month=10)
        assert len(result["days"]) == 10
        assert sum(len(d["spots"]) for d in result["days"]) == 20
        # City blocks must be contiguous: all 宜昌 days before all 恩施 days
        cities_seq = [d["city"] for d in result["days"]]
        first_eshi = cities_seq.index("恩施")
        assert all(c == "宜昌" for c in cities_seq[:first_eshi])
        assert all(c == "恩施" for c in cities_seq[first_eshi:])
        # 恩施 first day after 宜昌 is a transfer day (distance > 150km)
        eshi_days = [d for d in result["days"] if d["city"] == "恩施"]
        assert eshi_days[0]["is_transfer_day"] is True
        assert eshi_days[0]["transfer_from"] == "宜昌"

    def test_single_city_degrades_gracefully(self):
        spots = [_spot(f"武汉{i}", "武汉", 114.30 + i * 0.01, 30.59, hours=3.0) for i in range(6)]
        result = plan_multi_city(spots, WUHAN, num_days=2, travel_month=5)
        assert len(result["days"]) == 2
        assert result["days"][0]["city"] == "武汉"
        assert all(not d["is_transfer_day"] for d in result["days"])

    def test_empty_input(self):
        result = plan_multi_city([], WUHAN, num_days=3)
        assert result["days"] == []
        assert result["city_order"] == []
