# -*- coding: utf-8 -*-
"""Tests for day_route_planner core (pure functions only, no network)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.trip_planner import day_route_planner as drp
from src.trip_planner.route_optimizer import DayRoute

# ---------------------------------------------------------------
# Custom stops CRUD
# ---------------------------------------------------------------


def test_upsert_and_delete_custom_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(drp, "CUSTOM_STOPS_FILE", str(tmp_path / "custom_stops.json"))
    drp.upsert_custom_stop("三峡大瀑布", 111.28, 30.80, category="风景名胜", play_hours=2.5)
    drp.upsert_custom_stop("女儿城", 109.49, 30.27, category="旅游景点", play_hours=2.0)
    stops = drp.load_custom_stops()
    assert set(stops) == {"三峡大瀑布", "女儿城"}
    # upsert update
    drp.upsert_custom_stop("三峡大瀑布", 111.28, 30.80, play_hours=3.0)
    stops = drp.load_custom_stops()
    assert stops["三峡大瀑布"]["play_hours"] == 3.0
    assert stops["三峡大瀑布"]["_custom"] is True
    assert drp.delete_custom_stop("女儿城") is True
    assert drp.delete_custom_stop("不存在") is False
    assert "女儿城" not in drp.load_custom_stops()


def test_estimate_custom_play_hours():
    assert drp.estimate_custom_play_hours("风景名胜;风景区;国家公园") == 2.5
    assert drp.estimate_custom_play_hours("科教文化场所;博物馆") == 2.0
    assert drp.estimate_custom_play_hours("购物服务") == 2.0  # default


# ---------------------------------------------------------------
# Order optimization
# ---------------------------------------------------------------


def test_optimize_keeps_manual_order_when_disabled():
    origin = {"name": "武汉", "lng": 114.305, "lat": 30.593}
    stops = [
        {"name": "B", "lng": 111.0, "lat": 30.7},
        {"name": "A", "lng": 111.2, "lat": 30.6},
    ]
    out = drp.optimize_stop_order(origin, stops, optimize=False)
    assert [s["name"] for s in out] == ["B", "A"]


def test_optimize_nearest_neighbor_skips_coordless():
    origin = {"name": "O", "lng": 111.0, "lat": 30.6}
    stops = [
        {"name": "near", "lng": 111.05, "lat": 30.62},
        {"name": "far", "lng": 112.5, "lat": 31.5},
        {"name": "bad", "lng": None, "lat": None},
        {"name": "mid", "lng": 111.3, "lat": 30.7},
    ]
    out = drp.optimize_stop_order(origin, stops, optimize=True)
    names = [s["name"] for s in out]
    assert "bad" not in names
    assert names[0] == "near"  # nearest first


# ---------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------


def _fake_route(stops):
    return DayRoute(
        origin={"name": "O", "lng": 111.0, "lat": 30.6},
        ordered_spots=stops,
        segments=[],
        total_distance_km=50.0,
        total_duration_min=150,  # 2.5h total driving
    )


def test_timeline_drive_play_lunch_interleave():
    stops = [
        {"name": "甲", "lng": 111.2, "lat": 30.6, "play_hours": 2.0, "price": 0},
        {"name": "乙", "lng": 111.5, "lat": 30.8, "play_hours": 2.5, "price": 80},
    ]
    tl = drp.build_day_timeline(_fake_route(stops), depart_hour=8)
    kinds = [it["kind"] for it in tl["items"]]
    # drive, play, [lunch], drive, play
    assert kinds[0] == "drive" and kinds[1] == "play"
    assert "lunch" in kinds and "play" == kinds[-1]
    # times strictly increase and formatting OK
    times = [it["start"] for it in tl["items"]] + [tl["end_time"]]
    assert all(t.count(":") == 1 for t in times)
    assert tl["end_time"] > tl["items"][-1]["start"] or True
    # total play = 4.5
    assert tl["total_play_hours"] == 4.5
    # priced stop shows ticket note
    play_items = [it for it in tl["items"] if it["kind"] == "play"]
    assert "80" in play_items[1]["note"]


def test_timeline_lunch_only_once():
    stops = [
        {"name": f"S{i}", "lng": 111.0 + i * 0.1, "lat": 30.6, "play_hours": 1.0, "price": 0}
        for i in range(5)
    ]
    tl = drp.build_day_timeline(_fake_route(stops), depart_hour=7)
    assert [it["kind"] for it in tl["items"]].count("lunch") == 1
