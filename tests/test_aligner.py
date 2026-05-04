"""Tests for the aligner module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.aligner import normalize_name, compute_similarity, align_spots


class TestNormalizeName:
    def test_removes_suffix(self):
        assert normalize_name("木兰天池景区") == "木兰天池"

    def test_no_suffix(self):
        assert normalize_name("黄鹤楼") == "黄鹤楼"


class TestComputeSimilarity:
    def test_exact_match(self):
        assert compute_similarity("黄鹤楼", "黄鹤楼") == 100.0

    def test_normalized_match(self):
        assert compute_similarity("木兰天池景区", "木兰天池") == 100.0

    def test_substring(self):
        score = compute_similarity("黄鹤楼", "夜上黄鹤楼")
        assert score > 50

    def test_different(self):
        score = compute_similarity("木兰天池", "东湖游船")
        assert score < 70


class TestAlignSpots:
    def test_basic_alignment(self):
        spots = [
            {"spot_name": "黄鹤楼", "city": "武汉", "area": "武昌", "pass_name": "pass1"},
            {"spot_name": "黄鹤楼", "city": "武汉", "area": "武昌", "pass_name": "pass2"},
        ]
        result = align_spots(spots, threshold=80.0)
        assert result["stats"]["unique_spots"] == 1
        assert result["stats"]["aligned_pairs"] == 1

    def test_different_spots(self):
        spots = [
            {"spot_name": "黄鹤楼", "city": "武汉", "area": "武昌", "pass_name": "pass1"},
            {"spot_name": "东湖游船", "city": "武汉", "area": "东湖", "pass_name": "pass1"},
        ]
        result = align_spots(spots, threshold=80.0)
        assert result["stats"]["unique_spots"] == 2
        assert result["stats"]["aligned_pairs"] == 0

    def test_alias_collection(self):
        # Aligner expects already-cleaned names
        spots = [
            {"spot_name": "黄鹤楼", "city": "武汉", "area": "武昌", "pass_name": "pass1"},
            {"spot_name": "黄鹤楼 ", "city": "武汉", "area": "武昌", "pass_name": "pass2"},
        ]
        result = align_spots(spots, threshold=80.0)
        assert result["stats"]["unique_spots"] == 1
