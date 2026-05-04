"""Tests for the graph builder module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.graph_builder import build_graph, graph_to_json, save_graph, load_graph


class TestBuildGraph:
    def test_basic_graph(self):
        cleaned = [
            {
                "spot_name": "黄鹤楼",
                "area": "武昌",
                "city": "武汉",
                "level": "A5",
                "price": 70,
                "pass_name": "test_pass",
                "usage_limit_raw": "",
                "notes_raw": "",
                "_classification": {"category": "人文历史", "sub_category": None, "tags": ["5A"]},
            }
        ]
        alignment = {"alignment_pairs": [], "canonical_spots": [], "stats": {}}
        G = build_graph(cleaned, alignment)

        assert G.number_of_nodes() >= 4  # spot, pass, city, area, category
        assert G.number_of_edges() >= 3  # INCLUDED_IN, LOCATED_IN, HAS_CATEGORY

    def test_graph_has_correct_types(self):
        cleaned = [
            {
                "spot_name": "东湖游船",
                "area": "东湖",
                "city": "武汉",
                "level": None,
                "price": 100,
                "pass_name": "test_pass",
                "usage_limit_raw": "免6次",
                "notes_raw": "",
                "_classification": {"category": "自然景观", "sub_category": None, "tags": []},
            }
        ]
        alignment = {"alignment_pairs": [], "canonical_spots": [], "stats": {}}
        G = build_graph(cleaned, alignment)

        # Check spot node exists
        spot_found = False
        for _, attrs in G.nodes(data=True):
            if attrs.get("type") == "spot":
                spot_found = True
                assert attrs.get("name") == "东湖游船"
                assert attrs.get("price") == 100
        assert spot_found


class TestGraphJsonConversion:
    def test_roundtrip(self):
        cleaned = [
            {
                "spot_name": "木兰天池",
                "area": "黄陂",
                "city": "武汉",
                "level": "A5",
                "price": 70,
                "pass_name": "test_pass",
                "usage_limit_raw": "",
                "notes_raw": "",
                "_classification": {"category": "自然景观", "sub_category": None, "tags": []},
            }
        ]
        alignment = {"alignment_pairs": [], "canonical_spots": [], "stats": {}}
        G = build_graph(cleaned, alignment)

        data = graph_to_json(G)
        assert "nodes" in data
        assert "edges" in data
        assert "stats" in data
        assert data["stats"]["node_count"] == G.number_of_nodes()


class TestSaveLoadGraph:
    def test_save_and_load(self, tmp_path):
        import networkx as nx
        G = nx.MultiDiGraph()
        G.add_node("test:1", type="spot", name="Test Spot")
        G.add_edge("test:1", "test:2", relation="TEST")

        output_path = str(tmp_path / "test_graph.json")
        save_graph(G, output_path)

        loaded = load_graph(output_path)
        assert loaded.number_of_nodes() == 2
        assert loaded.number_of_edges() == 1
