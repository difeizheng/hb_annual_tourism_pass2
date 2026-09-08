# -*- coding: utf-8 -*-
"""Tests for itinerary_importer: normalization, geocode fallback chain,
per-day route attach, and save contract. LLM and AMap are mocked."""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.trip_planner import itinerary_importer as ii
from src.trip_planner import llm_client
from src.trip_planner.route_optimizer import DayRoute, RouteSegment


SAMPLE_JSON = (
    '[{"day_num":1,"date":"9/25","label":"武汉-宜昌","transport":"自驾",'
    '"stops":[{"name":"三峡大瀑布","arrive":"11:30","hours":2.5,'
    '"note":"带雨衣"}],"hotel":"宜昌市区"},'
    '{"day_num":2,"date":"9/26","label":"两坝一峡","transport":"船去车回",'
    '"stops":[{"name":"宜昌博物馆","arrive":"15:00","hours":2}],'
    '"hotel":"宜昌市区"}]'
)


def _fake_llm_resp(content):
    return {"choices": [{"message": {"content": content}}]}


class TestNormalize:
    def test_parse_normalizes_fields(self):
        fake = _fake_llm_resp(SAMPLE_JSON)
        with patch.object(llm_client, "chat_completion", return_value=fake), \
             patch.object(llm_client, "_get_llm_config",
                          return_value={"base": "http://x", "key": "k",
                                        "model": "m"}):
            days = ii.parse_itinerary_text("随便什么文本")
        assert len(days) == 2
        d1 = days[0]
        assert d1["day_num"] == 1 and d1["date"] == "9/25"
        assert d1["stops"][0]["name"] == "三峡大瀑布"
        assert d1["stops"][0]["hours"] == 2.5
        assert d1["stops"][0]["note"] == "带雨衣"
        assert d1["hotel"] == "宜昌市区"
        # stop dicts carry no unresolved flag yet
        assert "_unresolved" not in d1["stops"][0]

    def test_parse_strips_fences(self):
        fake = _fake_llm_resp("```json\n" + SAMPLE_JSON + "\n```")
        with patch.object(llm_client, "chat_completion", return_value=fake), \
             patch.object(llm_client, "_get_llm_config",
                          return_value={"base": "http://x", "key": "k",
                                        "model": "m"}):
            days = ii.parse_itinerary_text("text")
        assert len(days) == 2

    def test_parse_bad_json_raises_valueerror(self):
        fake = _fake_llm_resp("我不是 JSON")
        with patch.object(llm_client, "chat_completion", return_value=fake), \
             patch.object(llm_client, "_get_llm_config",
                          return_value={"base": "http://x", "key": "k",
                                        "model": "m"}):
            try:
                ii.parse_itinerary_text("text")
                assert False, "should raise"
            except ValueError:
                pass

    def test_parse_no_config_raises(self):
        from src.trip_planner import llm_client
        with patch.object(llm_client, "_get_llm_config", return_value=None):
            try:
                ii.parse_itinerary_text("text")
                assert False, "should raise"
            except ValueError:
                pass


class TestResolve:
    def _days(self):
        return [
            {"day_num": 1, "stops": [{"name": "三峡大瀑布"},
                                     {"name": "神秘新景点"}]},
        ]

    def test_pass_pool_hit(self):
        pool = [{"name": "三峡大瀑布", "lng": 111.16, "lat": 30.84}]
        days = self._days()
        with patch.object(ii, "_poi_search", return_value=None):
            coords = ii.resolve_stop_coords(days, pool, "key")
        assert coords["三峡大瀑布"]["source"] == "pass"
        # stops[1] 神秘新景点：pool miss + poi None → flagged
        assert days[0]["stops"][1].get("_unresolved") is True

    def test_poi_fallback_and_flag(self):
        pool = []
        days = self._days()
        poi = {"lng": 111.5, "lat": 30.9, "source": "poi"}
        with patch.object(ii, "_poi_search",
                          side_effect=lambda n, k: poi if n == "神秘新景点" else None):
            coords = ii.resolve_stop_coords(days, pool, "key")
        assert coords["神秘新景点"]["source"] == "poi"
        assert days[0]["stops"][1].get("_unresolved") is not True

    def test_unresolved_flagged_not_dropped(self):
        pool = []
        days = self._days()
        with patch.object(ii, "_poi_search", return_value=None):
            coords = ii.resolve_stop_coords(days, pool, "key")
        assert "神秘新景点" not in coords
        assert days[0]["stops"][1]["_unresolved"] is True
        # stop stays in the day list
        assert len(days[0]["stops"]) == 2


class TestRoutes:
    def test_attach_routes_and_chaining(self):
        days = [
            {"day_num": 1, "stops": [
                {"name": "A"}, {"name": "B"}]},
            {"day_num": 2, "stops": [
                {"name": "C"}, {"name": "D"}]},
        ]
        coords = {n: {"lng": 111.0 + i, "lat": 30.0 + i, "source": "poi"}
                  for i, n in enumerate("ABCD")}
        origin = {"name": "O", "lng": 110.5, "lat": 29.8}

        def fake_compute(origin_arg, pts, key):
            return DayRoute(origin=origin_arg, ordered_spots=pts,
                            segments=[],
                            total_distance_km=42.0, total_duration_min=60,
                            ordered_polyline="111.0,30.0;111.1,30.1")

        with patch("src.trip_planner.route_optimizer.compute_route",
                   side_effect=fake_compute):
            out = ii.attach_day_routes(days, coords, origin, "key")
        r1, r2 = out[0]["route"], out[1]["route"]
        assert r1["from"] == "O"
        assert r2["from"] == ""  # coords dicts have no name key -> ""
        assert r1["km"] == 42.0 and r1["min"] == 60
        # chain: day2 starts where day1 ended
        assert out[1]["stops"][0]["name"] == "C"

    def test_day_without_resolved_stops_gets_none(self):
        days = [{"day_num": 1, "stops": [{"name": "X", "_unresolved": True}]}]
        out = ii.attach_day_routes(days, {}, None, "key")
        assert out[0]["route"] is None


class TestSave:
    def test_save_contract(self):
        days = [{"day_num": 1, "stops": [{"name": "A"}, {"name": "B"}]}]
        with patch("src.trip_planner.plan_manager.save_plan") as sp:
            sp.return_value = "TP-TEST"
            pid = ii.save_imported_itinerary(days, "我的12天", "武汉")
        assert pid == "TP-TEST"
        saved = sp.call_args[0][0]
        assert saved["trip_type"] == "imported_itinerary"
        assert saved["num_days"] == 1
        assert saved["total_spots"] == 2
        assert saved["departure_city"] == "武汉"
