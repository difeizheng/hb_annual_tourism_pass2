"""Tests for loader, analyzer, recommender, and pipeline modules."""

import json
import os
import sys
import tempfile

import pytest
import networkx as nx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_graph():
    """Create a small test graph."""
    G = nx.MultiDiGraph()
    G.add_node("spot:黄鹤楼", type="spot", name="黄鹤楼", city="武汉", level="A5", price=80, category="人文历史", area="武昌", tags=["5A"], sub_category="古迹")
    G.add_node("spot:木兰天池", type="spot", name="木兰天池", city="武汉", level="A4", price=60, category="自然景观", area="黄陂", tags=[], sub_category=None)
    G.add_node("spot:东湖温泉", type="spot", name="东湖温泉", city="武汉", level="A3", price=120, category="温泉康养", area="东湖", tags=["季节性"], sub_category="温泉")
    G.add_node("spot:桃花冲漂流", type="spot", name="桃花冲漂流", city="黄冈", level=None, price=0, category="户外运动", area="英山", tags=[], sub_category="漂流")
    G.add_node("pass:大武汉_200元", type="pass", name="大武汉_200元")
    G.add_node("pass:湖北_300元", type="pass", name="湖北_300元")
    G.add_edge("spot:黄鹤楼", "pass:大武汉_200元", type="INCLUDED_IN", price=80)
    G.add_edge("spot:木兰天池", "pass:大武汉_200元", type="INCLUDED_IN", price=60)
    G.add_edge("spot:黄鹤楼", "pass:湖北_300元", type="INCLUDED_IN", price=80)
    G.add_edge("spot:东湖温泉", "pass:湖北_300元", type="INCLUDED_IN", price=120)
    G.add_edge("spot:桃花冲漂流", "pass:湖北_300元", type="INCLUDED_IN", price=0)
    return G


# ============================================================
# Loader tests
# ============================================================

class TestLoader:
    def test_load_json(self):
        from src.loader import load_json
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump([{"spot_name": "test", "seq": 1}], f)
            path = f.name
        try:
            result = load_json(path)
            assert len(result) == 1
            assert result[0]["spot_name"] == "test"
        finally:
            os.unlink(path)

    def test_load_all_passes_skips_summary(self):
        from src.loader import load_all_passes
        with tempfile.TemporaryDirectory() as tmpdir:
            data = [
                {"spot_name": "Spot A", "seq": 1, "area": "武昌", "city": "武汉", "level": "5A", "price": 100, "usage_limit": "不限次", "notes": ""},
                {"spot_name": "——总计——", "seq": -1, "area": "", "city": "", "level": "", "price": 0, "usage_limit": "", "notes": ""},
            ]
            with open(os.path.join(tmpdir, "test_pass_200元.json"), "w", encoding="utf-8") as f:
                json.dump(data, f)
            result = load_all_passes(tmpdir)
            assert len(result) == 1
            assert result[0]["pass_name"] == "test_pass_200元"

    def test_get_pass_names(self):
        from src.loader import get_pass_names
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["pass1_100元", "pass2_200元"]:
                with open(os.path.join(tmpdir, f"{name}.json"), "w", encoding="utf-8") as f:
                    json.dump([], f)
            names = get_pass_names(tmpdir)
            assert names == ["pass1_100元", "pass2_200元"]


# ============================================================
# Analyzer tests (graph-based functions)
# ============================================================

class TestAnalyzerGraph:
    def test_global_stats(self):
        from src.analyzer import global_stats
        G = _make_graph()
        result = global_stats(G)
        assert result["total_nodes"] == 6
        assert result["total_edges"] == 5
        assert result["node_types"]["spot"] == 4
        assert result["node_types"]["pass"] == 2

    def test_city_distribution(self):
        from src.analyzer import city_distribution
        G = _make_graph()
        result = city_distribution(G)
        assert result["武汉"] == 3
        assert result["黄冈"] == 1

    def test_level_distribution(self):
        from src.analyzer import level_distribution
        G = _make_graph()
        result = level_distribution(G)
        assert result["A5"] == 1
        assert result["A4"] == 1
        assert result["A3"] == 1

    def test_category_distribution(self):
        from src.analyzer import category_distribution
        G = _make_graph()
        result = category_distribution(G)
        assert "人文历史" in result
        assert "自然景观" in result
        assert "温泉康养" in result

    def test_pass_analysis(self):
        from src.analyzer import pass_analysis
        G = _make_graph()
        result = pass_analysis(G)
        assert len(result) == 2
        assert result[0]["name"] == "大武汉_200元"  # 140/200 = 0.7 > 200/300 = 0.67

    def test_pass_overlap(self):
        from src.analyzer import pass_overlap
        G = _make_graph()
        result = pass_overlap(G, "大武汉_200元", "湖北_300元")
        assert result["overlap_count"] == 1  # 黄鹤楼
        assert result["only_pass1"] == 1  # 木兰天池
        assert result["only_pass2"] == 2  # 东湖温泉, 桃花冲漂流

    def test_top_value_spots(self):
        from src.analyzer import top_value_spots
        G = _make_graph()
        result = top_value_spots(G, top_n=2)
        assert len(result) == 2
        assert result[0]["name"] == "东湖温泉"  # price=120
        assert result[1]["name"] == "黄鹤楼"  # price=80


# ============================================================
# Analyzer tests (list-based functions)
# ============================================================

class TestAnalyzerLists:
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
            {"spot_name": "桃花冲漂流", "city": "黄冈", "notes_raw": "季节性景区，6月14日开漂", "_classification": {"category": "户外运动"}},
            {"spot_name": "木兰天池", "city": "武汉", "notes_raw": "", "_classification": {"category": "自然景观"}},
        ]
        result = seasonal_analysis(spots)
        assert result["count"] == 1
        assert result["spots"][0]["name"] == "桃花冲漂流"


# ============================================================
# Recommender tests
# ============================================================

class TestRecommender:
    def test_filter_by_city(self):
        from src.recommender import filter_spots
        G = _make_graph()
        result = filter_spots(G, city="武汉")
        assert len(result) == 3

    def test_filter_by_level(self):
        from src.recommender import filter_spots
        G = _make_graph()
        result = filter_spots(G, level="A5")
        assert len(result) == 1
        assert result[0]["name"] == "黄鹤楼"

    def test_filter_by_category(self):
        from src.recommender import filter_spots
        G = _make_graph()
        result = filter_spots(G, category="自然景观")
        assert len(result) == 1
        assert result[0]["name"] == "木兰天池"

    def test_filter_by_price_range(self):
        from src.recommender import filter_spots
        G = _make_graph()
        result = filter_spots(G, min_price=70, max_price=100)
        assert len(result) == 1
        assert result[0]["name"] == "黄鹤楼"

    def test_filter_combined(self):
        from src.recommender import filter_spots
        G = _make_graph()
        result = filter_spots(G, city="黄冈", requires_appointment=None)
        assert len(result) == 1

    def test_recommender_family(self):
        from src.recommender import recommend_passes
        G = _make_graph()
        spots = []
        result = recommend_passes(G, spots, {"family": True, "cities": ["武汉"]})
        assert len(result) >= 1
        assert "score" in result[0]

    def test_recommender_outdoor(self):
        from src.recommender import recommend_passes
        G = _make_graph()
        spots = []
        result = recommend_passes(G, spots, {"outdoor": True, "budget": 300})
        assert isinstance(result, list)

    def test_recommender_budget_filter(self):
        from src.recommender import recommend_passes
        G = _make_graph()
        spots = []
        result = recommend_passes(G, spots, {"budget": 50})
        # Both passes are >50元, should be filtered out
        assert len(result) == 0

    def test_recommend_by_season_summer(self):
        from src.recommender import recommend_by_season
        G = _make_graph()
        result = recommend_by_season(G, month=7)
        assert result["season"] == "summer"

    def test_recommend_by_season_winter(self):
        from src.recommender import recommend_by_season
        G = _make_graph()
        result = recommend_by_season(G, month=1)
        assert result["season"] == "winter"
        # Should include 温泉 spots
        assert len(result["spots"]) >= 1

    def test_recommend_by_season_spring(self):
        from src.recommender import recommend_by_season
        G = _make_graph()
        result = recommend_by_season(G, month=4)
        assert result["season"] == "spring"

    def test_query_natural_language_5a(self):
        from src.recommender import query_natural_language
        G = _make_graph()
        result = query_natural_language(G, "武汉5A景点")
        assert len(result) >= 1
        assert result[0]["level"] == "A5"

    def test_query_natural_language_hot_spring(self):
        from src.recommender import query_natural_language
        G = _make_graph()
        result = query_natural_language(G, "温泉")
        assert len(result) >= 1

    def test_query_natural_language_drift(self):
        from src.recommender import query_natural_language
        G = _make_graph()
        result = query_natural_language(G, "漂流")
        assert len(result) >= 1
        assert result[0]["category"] == "户外运动"


# ============================================================
# Pipeline tests
# ============================================================

class TestPipeline:
    def test_pipeline_runs(self):
        from src.pipeline import run_pipeline
        with tempfile.TemporaryDirectory() as tmpdir:
            data = [
                {"spot_name": "黄鹤楼", "seq": 1, "area": "武昌", "city": "武汉", "level": "5A", "price": 80, "usage_limit": "不限次", "notes": ""},
                {"spot_name": "木兰天池", "seq": 2, "area": "黄陂", "city": "武汉", "level": "4A", "price": 60, "usage_limit": "免6次", "notes": "1.2米以下儿童免费"},
            ]
            with open(os.path.join(tmpdir, "test_pass_200元.json"), "w", encoding="utf-8") as f:
                json.dump(data, f)

            output_dir = tempfile.mkdtemp()
            result = run_pipeline(tmpdir, output_dir)

            assert result["record_count"] == 2
            assert result["graph_nodes"] > 0
            assert result["graph_edges"] > 0

            # Verify output files exist
            assert os.path.exists(os.path.join(output_dir, "cleaned_spots.json"))
            assert os.path.exists(os.path.join(output_dir, "knowledge_graph.json"))
