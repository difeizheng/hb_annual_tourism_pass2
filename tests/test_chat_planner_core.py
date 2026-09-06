"""Tests for chat_planner_core (offline: no LLM, no AMap calls)."""

import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.trip_planner.chat_planner_core import (
    resolve_holiday_dates, build_trip_from_intent, validate_intent_against_pool,
)


def _spot(name, city, lng, lat, hours=3.0):
    return {"name": name, "city": city, "lng": lng, "lat": lat,
            "category": "自然风光", "level": "4A", "price": 60, "_play_hours": hours}


WUHAN = {"name": "武汉", "lng": 114.30, "lat": 30.59}


class TestResolveHolidayDates:
    def test_midautumn_national_leave_bridge(self):
        # 2026: 中秋 9/25-27, 国庆 10/1-8, gap 9/28-30 (3 workdays)
        r = resolve_holiday_dates("中秋+国庆+请假3天", leave_days=3, today=date(2026, 9, 1))
        assert r is not None
        assert r["start"] == "2026-09-25"
        assert r["end"] == "2026-10-08"
        assert r["days"] == 14

    def test_national_only_no_leave(self):
        r = resolve_holiday_dates("国庆", leave_days=0, today=date(2026, 9, 1))
        assert r["start"] == "2026-10-01"
        assert r["days"] == 8

    def test_unknown_phrase_returns_none(self):
        assert resolve_holiday_dates("随便玩玩", None) is None

    def test_none_phrase(self):
        assert resolve_holiday_dates(None, None) is None


class TestBuildTripFromIntent:
    def test_full_pipeline_yichang_enshi(self):
        intent = {
            "departure_city": "武汉", "cities": ["宜昌", "恩施"],
            "num_days": 10, "pass_name": "惠游",
            "travel_style": "midrange", "transport": "drive",
            "companions": "2大1小", "budget": 6000,
        }
        spots = (
            [_spot(f"宜昌{i}", "宜昌", 111.28 + i * 0.02, 30.69, 4.0) for i in range(12)]
            + [_spot(f"恩施{i}", "恩施", 109.49 + i * 0.02, 30.27, 4.0) for i in range(8)]
        )
        result = build_trip_from_intent(intent, spots, WUHAN)
        assert len(result["days"]) == 10
        cities_seq = [d["city"] for d in result["days"]]
        assert cities_seq[: cities_seq.index("恩施")] == ["宜昌"] * cities_seq.index("恩施")
        assert result["intent_meta"]["travel_style"] == "midrange"
        assert result["intent_meta"]["budget"] == 6000

    def test_city_filter_fallback_when_empty(self):
        # Cities requested have no coverage → fall back to all spots
        intent = {"cities": ["拉萨"], "num_days": 3}
        spots = [_spot("A", "宜昌", 111.3, 30.7)]
        result = build_trip_from_intent(intent, spots, WUHAN)
        assert len(result["days"]) == 3  # didn't crash, used fallback pool


class TestValidateIntent:
    def test_uncovered_city_warning(self):
        spots = [_spot("A", "宜昌", 111.3, 30.7)]
        w = validate_intent_against_pool({"cities": ["宜昌", "拉萨"]}, spots)
        assert len(w) == 1 and "拉萨" in w[0]

    def test_all_covered(self):
        spots = [_spot("A", "宜昌", 111.3, 30.7)]
        assert validate_intent_against_pool({"cities": ["宜昌"]}, spots) == []


class TestDedupeVariants:
    def test_name_variants_merged(self):
        from src.trip_planner.chat_planner_core import _dedupe_spots
        spots = [
            {"name": "恩施大峡谷", "city": "恩施", "lng": 109.5, "lat": 30.3},
            {"name": "恩施大峡谷·七星寨", "city": "恩施", "lng": 109.51, "lat": 30.31},
            {"name": "三峡大瀑布", "city": "宜昌", "lng": 111.3, "lat": 30.7},
            {"name": "三峡大瀑布(夷陵区)", "city": "宜昌", "lng": 111.31, "lat": 30.71},
            {"name": "腾龙洞", "city": "恩施", "lng": 109.4, "lat": 30.3},
        ]
        uniq, dropped = _dedupe_spots(spots)
        assert len(uniq) == 3
        assert len(dropped) == 2
        assert any("七星寨" in d for d in dropped)

    def test_dedupe_in_full_pipeline(self):
        # same attraction under two names must NOT occupy two days
        intent = {"cities": ["恩施"], "num_days": 4}
        spots = (
            [_spot(f"恩施大峡谷{'·七星寨' if i else ''}", "恩施", 109.5, 30.3, 6.5) for i in range(2)]
            + [_spot("腾龙洞", "恩施", 109.4, 30.3, 6.0)]
        )
        result = build_trip_from_intent(intent, spots, WUHAN)
        names = [s["name"] for d in result["days"] for s in d["spots"]]
        # variant should appear at most once
        from src.trip_planner.chat_planner_core import _normalize_name
        norm = [_normalize_name(n) for n in names]
        assert len(norm) == len(set(norm))

    def test_normalize_name(self):
        from src.trip_planner.chat_planner_core import _normalize_name
        assert _normalize_name("三峡大瀑布（夷陵区）") == "三峡大瀑布"
        assert _normalize_name("恩施大峡谷·七星寨") == "恩施大峡谷"
        assert _normalize_name("黄鹤楼公园") == "黄鹤楼公园"


class TestDedupeKeySuffix:
    def test_suffix_words_stripped(self):
        from src.trip_planner.chat_planner_core import _dedupe_key
        assert _dedupe_key("腾龙洞景区") == _dedupe_key("腾龙洞")
        # 1-char fuzzy variants (神龙溪 vs 神农溪) are NOT auto-merged — too risky
        # (清江方山 vs 清江画廊 also differ by 1 char but are distinct spots).
        # The chat UI lets the user drop duplicates interactively instead.
        assert _dedupe_key("黄鹤楼公园") == _dedupe_key("黄鹤楼")


class TestPassResolution:
    def test_wuhan_huimin_maps_to_province_card(self):
        # 用户说"武汉惠民卡"指的常是湖北旅游惠民卡（地名前缀误导）
        from src.trip_planner.chat_planner_core import resolve_pass_name
        assert resolve_pass_name("武汉惠民卡") == "湖北旅游惠民卡_300元"
        assert resolve_pass_name("惠民") == "湖北旅游惠民卡_300元"
        assert resolve_pass_name("畅玩") == "湖北文旅畅玩卡_200元"
        assert resolve_pass_name("江城卡") == "武汉文旅江城卡_150元"

    def test_exact_canonical_name(self):
        from src.trip_planner.chat_planner_core import resolve_pass_name
        assert resolve_pass_name("湖北旅游年卡_300元") == "湖北旅游年卡_300元"

    def test_unknown_returns_none(self):
        from src.trip_planner.chat_planner_core import resolve_pass_name
        assert resolve_pass_name("不存在的卡") is None
        assert resolve_pass_name(None) is None
