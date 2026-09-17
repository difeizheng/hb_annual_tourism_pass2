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
                          side_effect=lambda n, k=None, **_: poi if n == "神秘新景点" else None):
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
        """Unified v2 contract: source/schema/origin instead of legacy trip_type."""
        days = [{"day_num": 1, "stops": [{"name": "A"}, {"name": "B"}]}]
        with patch("src.trip_planner.plan_manager.save_plan") as sp:
            sp.return_value = "TP-TEST"
            pid = ii.save_imported_itinerary(days, "我的12天", "武汉")
        assert pid == "TP-TEST"
        saved = sp.call_args[0][0]
        assert saved["source"] == "import"
        assert saved["schema_version"] == 2
        assert saved["num_days"] == 1
        assert saved["total_spots"] == 2
        assert saved["origin"]["city"] == "武汉"


class TestGeoGuards:
    """Deterministic guards against wild POI matches."""

    def test_city_in_name_uses_city_coord(self):
        days = [{"day_num": 1, "stops": [{"name": "武汉出发"},
                                         {"name": "利川休整"}]}]
        calls = []

        def fake_poi(name, key, anchor=None):
            calls.append((name, anchor))
            return {"lng": 1.0, "lat": 2.0, "source": "poi"}

        with patch.object(ii, "_poi_search", side_effect=fake_poi):
            coords = ii.resolve_stop_coords(days, [], "key")
        assert coords["武汉出发"]["source"] == "city"
        assert coords["利川休整"]["source"] == "city"
        # no POI calls at all for city names
        assert calls == []

    def test_poi_search_gets_anchor_bias(self):
        days = [{"day_num": 1, "stops": [{"name": "博物馆"}]}]
        seen = {}

        def fake_poi(name, key, anchor=None):
            seen["anchor"] = anchor
            return {"lng": 111.3, "lat": 30.7, "source": "poi"}

        with patch.object(ii, "_poi_search", side_effect=fake_poi):
            coords = ii.resolve_stop_coords(
                days, [], "key",
                prev_days=[{"day_num": 0,
                            "stops": [{"name": "前站",
                                       "lng": 111.286, "lat": 30.692}]}])
        assert seen["anchor"] == {"lng": 111.286, "lat": 30.692}
        assert coords["博物馆"]["source"] == "poi"


class TestSaveWithCoords:
    def test_coords_merged_into_stops_without_mutating_input(self):
        days = [{"day_num": 1, "stops": [{"name": "A"}, {"name": "B"}]}]
        coords = {"A": {"lng": 111.0, "lat": 30.0, "source": "poi"}}
        with patch("src.trip_planner.plan_manager.save_plan") as sp:
            sp.return_value = "TP-XY"
            ii.save_imported_itinerary(days, "n", "武汉", coords=coords)
        saved_days = sp.call_args[0][0]["days"]
        assert saved_days[0]["stops"][0]["lng"] == 111.0
        assert saved_days[0]["stops"][0]["coord_source"] == "poi"
        assert saved_days[0]["stops"][1]["lng"] is None  # B unresolved
        # original days NOT mutated (deepcopy)
        assert "lng" not in days[0]["stops"][0]

    def test_plan_id_enables_overwrite(self):
        days = [{"day_num": 1, "stops": [{"name": "A"}]}]
        with patch("src.trip_planner.plan_manager.save_plan") as sp:
            sp.return_value = "TP-OLD"
            ii.save_imported_itinerary(days, "n", "武汉", plan_id="TP-OLD")
        assert sp.call_args[0][0]["id"] == "TP-OLD"

    def test_no_coords_keeps_days_asis(self):
        """Without coords, stop content survives normalization unchanged."""
        days = [{"day_num": 1, "stops": [{"name": "A", "arrive": "09:00"}]}]
        with patch("src.trip_planner.plan_manager.save_plan") as sp:
            sp.return_value = "TP-1"
            ii.save_imported_itinerary(days, "n", "武汉")
        saved = sp.call_args[0][0]
        assert "id" not in saved
        stop = saved["days"][0]["stops"][0]
        assert stop["name"] == "A" and stop["arrive"] == "09:00"
        assert stop["lng"] is None


class TestResolveSingle:
    def test_pass_pool_hit(self):
        pool = [{"name": "三峡大瀑布", "lng": 111.4, "lat": 30.8}]
        c = ii.resolve_single_stop("三峡大瀑布", pool, "key")
        assert c["source"] == "pass" and c["lng"] == 111.4

    def test_city_filler_uses_city_coord_without_poi(self):
        with patch.object(ii, "_poi_search", side_effect=AssertionError("must not call POI")):
            c = ii.resolve_single_stop("利川休整", [], "key")
        assert c["source"] == "city"
        assert c["lng"] == ii.COUNTY_COORDS["利川"][0]

    def test_city_name_poi_first_then_city_fallback(self):
        with patch.object(ii, "_poi_search", return_value=None):
            c = ii.resolve_single_stop("荆州古城墙", [], "key")
        assert c["source"] == "city"
        with patch.object(ii, "_poi_search",
                          return_value={"lng": 112.1, "lat": 30.3, "source": "poi"}):
            c2 = ii.resolve_single_stop("荆州古城墙", [], "key")
        assert c2["source"] == "poi"

    def test_plain_name_poi_and_unresolved(self):
        with patch.object(ii, "_poi_search",
                          return_value={"lng": 1.0, "lat": 2.0, "source": "poi"}) as m:
            c = ii.resolve_single_stop("某小景点", [], "key",
                                       anchor={"lng": 9.0, "lat": 9.0})
        assert c["source"] == "poi"
        assert m.call_args[1]["anchor"] == {"lng": 9.0, "lat": 9.0}
        with patch.object(ii, "_poi_search", return_value=None):
            assert ii.resolve_single_stop("某小景点", [], "key") is None
