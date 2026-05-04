"""Tests for parser, classifier, loader, and analyzer modules."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.parser import parse_usage_limit, parse_notes, parse_spot_rules
from src.classifier import classify_spot


# ============================================================
# Parser tests
# ============================================================

class TestParseUsageLimit:
    def test_free_n_times(self):
        result = parse_usage_limit("免6次")
        assert result["type"] == "free"
        assert result["count"] == 6

    def test_unlimited(self):
        assert parse_usage_limit("不限次")["type"] == "unlimited"
        assert parse_usage_limit("不限")["type"] == "unlimited"
        assert parse_usage_limit("免费入园不限次数")["type"] == "unlimited"

    def test_free_1_time(self):
        result = parse_usage_limit("免1次")
        assert result["type"] == "free"
        assert result["count"] == 1

    def test_supplement_yuan_per_time(self):
        result = parse_usage_limit("25元/次")
        assert result["type"] == "supplement"
        assert result["supplement_amount"] == 25.0

    def test_appointment_required(self):
        result = parse_usage_limit("需预约共限6次")
        assert result["requires_appointment"] is True
        assert result["type"] == "free"

    def test_null(self):
        result = parse_usage_limit(None)
        assert result["type"] == "unknown"

    def test_empty(self):
        result = parse_usage_limit("")
        assert result["type"] == "unknown"

    def test_free_appointment(self):
        result = parse_usage_limit("免费预约")
        assert result["type"] == "free"

    def test_supplement_bu(self):
        result = parse_usage_limit("补39即可")
        assert result["type"] == "supplement"
        assert result["supplement_amount"] == 39.0

    def test_date_range(self):
        result = parse_usage_limit("2026年共免6次")
        assert result["type"] == "free"
        assert result["count"] == 6


class TestParseNotes:
    def test_child_height_free(self):
        result = parse_notes("1.2米以下儿童免费")
        assert "child_free_height" in result

    def test_child_must_pay(self):
        result = parse_notes("儿童达1米需购票")
        assert "child_must_pay_height" in result

    def test_holiday_restriction(self):
        result = parse_notes("大型节假日不接待年卡用户")
        assert result["holiday_restriction"] == "blocked"

    def test_advance_booking(self):
        result = parse_notes("大型节假日需提前1天预约")
        assert result["holiday_restriction"] == "advance_booking"

    def test_appointment_days(self):
        result = parse_notes("需至少提前1天预约")
        assert result["appointment_days"] == 1

    def test_night_session(self):
        result = parse_notes("玩夜场需要16:00之前入园")
        assert result["night_entry_hour"] == 16

    def test_null(self):
        assert parse_notes(None) == {}


# ============================================================
# Classifier tests
# ============================================================

class TestClassifySpot:
    def test_natural_scenery(self):
        result = classify_spot("木兰天池")
        assert result["category"] == "自然景观"

    def test_cultural_historical(self):
        result = classify_spot("黄鹤楼")
        assert result["category"] == "人文历史"

    def test_theme_park(self):
        result = classify_spot("九峰森林动物园")
        assert result["category"] == "主题乐园"

    def test_hot_spring(self):
        result = classify_spot("山湖温泉")
        assert result["category"] == "温泉康养"

    def test_outdoor(self):
        result = classify_spot("桃花冲漂流")
        assert result["category"] == "户外运动"

    def test_agriculture(self):
        result = classify_spot("金卉庄园")
        assert result["category"] == "休闲农业"

    def test_tags(self):
        result = classify_spot("黄鹤楼5A", "夜场")
        assert "5A" in result["tags"]
        assert "夜场" in result["tags"]

    def test_sub_category(self):
        result = classify_spot("桃花冲漂流")
        assert result["sub_category"] == "漂流"


# ============================================================
# Analyzer tests
# ============================================================

class TestAnalyzer:
    def test_price_analysis(self):
        from src.analyzer import price_analysis
        spots = [
            {"price": 100, "notes_raw": ""},
            {"price": 50, "notes_raw": ""},
            {"price": 0, "notes_raw": "季节性"},
        ]
        result = price_analysis(spots)
        assert result["min"] == 50
        assert result["max"] == 100
        assert result["count"] == 2
        assert result["free_count"] == 1

    def test_seasonal_analysis(self):
        from src.analyzer import seasonal_analysis
        spots = [
            {
                "spot_name": "桃花冲漂流",
                "city": "黄冈",
                "notes_raw": "季节性景区，6月14日开漂",
                "_classification": {"category": "户外运动"},
            },
            {
                "spot_name": "木兰天池",
                "city": "武汉",
                "notes_raw": "",
                "_classification": {"category": "自然景观"},
            },
        ]
        result = seasonal_analysis(spots)
        assert result["count"] == 1
        assert result["spots"][0]["name"] == "桃花冲漂流"
