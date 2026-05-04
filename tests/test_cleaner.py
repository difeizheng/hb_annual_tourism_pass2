"""Tests for the cleaner module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cleaner import (
    normalize_level, strip_area_from_name, clean_spot_name,
    extract_pass_info, clean_spot_record, clean_all_spots,
)


class TestNormalizeLevel:
    def test_5a_variants(self):
        assert normalize_level("5A") == "A5"
        assert normalize_level("AAAAA") == "A5"

    def test_4a_variants(self):
        assert normalize_level("4A") == "A4"
        assert normalize_level("AAAA") == "A4"

    def test_3a_variants(self):
        assert normalize_level("3A") == "A3"
        assert normalize_level("AAA") == "A3"

    def test_non_a(self):
        assert normalize_level("非A") == "A0"

    def test_empty(self):
        assert normalize_level("") is None
        assert normalize_level(None) is None

    def test_unknown(self):
        assert normalize_level("2A") == "A2"


class TestStripAreaFromName:
    def test_with_chinese_parens(self):
        name, area = strip_area_from_name("木兰天池（黄陂）")
        assert name == "木兰天池"
        assert area == "黄陂"

    def test_with_brackets(self):
        name, area = strip_area_from_name("东湖湖心岛动物博物馆[东湖]")
        assert name == "东湖湖心岛动物博物馆"
        assert area == "东湖"

    def test_no_area(self):
        name, area = strip_area_from_name("黄鹤楼")
        assert name == "黄鹤楼"
        assert area == ""

    def test_empty(self):
        name, area = strip_area_from_name("")
        assert name == ""
        assert area == ""


class TestCleanSpotName:
    def test_removes_area(self):
        assert clean_spot_name("木兰天池（黄陂）") == "木兰天池"

    def test_removes_summary_row(self):
        assert clean_spot_name("——免票金额合计——") == ""

    def test_whitespace(self):
        assert clean_spot_name("  黄鹤楼  ") == "黄鹤楼"


class TestExtractPassInfo:
    def test_standard_name(self):
        info = extract_pass_info("大武汉景区旅游年卡_200元")
        assert info["name"] == "大武汉景区旅游年卡"
        assert info["price"] == 200

    def test_no_price(self):
        info = extract_pass_info("UnknownPass")
        assert info["name"] == "UnknownPass"
        assert info["price"] is None


class TestCleanSpotRecord:
    def test_basic_cleaning(self):
        record = {
            "spot_name": "黄鹤楼（武昌）",
            "area": "武昌",
            "city": "武汉",
            "level": "AAAAA",
            "price": 70,
            "usage_limit": "免6次",
            "notes": "可约当天",
            "pass_name": "test_pass_200元",
        }
        result = clean_spot_record(record)
        assert result["spot_name"] == "黄鹤楼"
        assert result["level"] == "A5"
        assert result["price"] == 70
        assert result["city"] == "武汉"

    def test_empty_name_skipped(self):
        record = {
            "spot_name": "——票价总计——",
            "price": 4420,
            "pass_name": "test_200元",
        }
        result = clean_spot_record(record)
        assert result["spot_name"] == ""
