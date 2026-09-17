"""Tests for unified plan schema + legacy migrations (Stage A)."""
import json
import os

import pytest

from src.trip_planner.plan_schema import (
    PLAN_SCHEMA_VERSION, build_plan, migrate_plan, normalize_stop,
    plan_summary, all_stops, validate_plan,
)

PLAN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "trip_plans")


# ---------------------------------------------------------------- build
def test_build_plan_normalizes_days_and_stops():
    plan = build_plan(
        "测试", [{"day_num": 1, "city": "武汉",
                  "stops": [{"name": "黄鹤楼", "lng": 114.3, "lat": 30.5,
                             "price": 70, "_play_hours": 2.5}]}],
        "manual", origin={"city": "武汉"})
    assert plan["schema_version"] == PLAN_SCHEMA_VERSION
    assert plan["num_days"] == 1
    assert plan["total_spots"] == 1
    s = plan["days"][0]["stops"][0]
    assert s["hours"] == 2.5 and s["price"] == 70
    assert set(s.keys()) == {"name", "lng", "lat", "arrive", "hours", "note",
                             "price", "category", "level", "city", "passes",
                             "coord_source"}


def test_build_plan_rejects_unknown_source():
    with pytest.raises(AssertionError):
        build_plan("x", [], "bogus")


def test_validate_plan_flags_missing_coords():
    plan = build_plan("x", [{"stops": [{"name": "A"}]}], "manual")
    issues = validate_plan(plan)
    assert any("无坐标" in i for i in issues)


# ------------------------------------------------------- legacy migrate
def test_migrate_imported_keeps_stops_and_route():
    raw = {
        "trip_type": "imported_itinerary", "id": "p1", "name": "导入",
        "departure_city": "武汉",
        "days": [{"day_num": 1, "label": "D1", "hotel": "如家",
                  "stops": [{"name": "黄鹤楼", "arrive": "09:00", "hours": 2,
                             "note": "n", "lng": 114.3, "lat": 30.5,
                             "source": "pool"}],
                  "route": {"from": "武汉", "km": 5, "min": 15, "polyline": "abc"}}],
    }
    plan = migrate_plan(raw)
    assert plan["schema_version"] == PLAN_SCHEMA_VERSION
    assert plan["source"] == "import"
    assert plan["id"] == "p1"
    d = plan["days"][0]
    assert d["route"]["polyline"] == "abc" and d["route"]["km"] == 5
    assert d["stops"][0]["coord_source"] == "pool"
    assert d["stops"][0]["arrive"] == "09:00"
    assert plan["meta"]["day_extras"]["1"]["hotel"] == "如家"


def test_migrate_v2_assignment_spots_become_stops():
    raw = {
        "trip_type": "trip_planner_v2", "name": "v2", "departure_city": "武汉",
        "travel_month": 10,
        "cart": [{"name": "黄鹤楼", "lng": 114.3, "lat": 30.5, "price": 70}],
        "assignment": {"days": [
            {"day_num": 1, "primary_city": "武汉", "travel_km": 12.0,
             "play_hours": 5.0,
             "spots": [{"name": "黄鹤楼", "lng": 114.3, "lat": 30.5,
                        "price": 70, "category": "人文", "level": "5A",
                        "_play_hours": 3.0}]}],
            "seasonal_warnings": ["w1"]},
    }
    plan = migrate_plan(raw)
    assert plan["source"] == "manual"
    assert plan["travel_month"] == 10
    d = plan["days"][0]
    assert d["city"] == "武汉" and d["travel_km"] == 12.0
    s = d["stops"][0]
    assert s["lng"] == 114.3 and s["hours"] == 3.0 and s["level"] == "5A"
    assert plan["meta"]["seasonal_warnings"] == ["w1"]


def test_migrate_chat_v1_source_and_meta():
    raw = {
        "trip_type": "chat_planner_v1", "name": "chat", "departure_city": "武汉",
        "assignment": {"days": [{"day_num": 1, "primary_city": "宜昌",
                                 "spots": [{"name": "三峡大坝", "lng": 111.0,
                                            "lat": 30.8}]}]},
        "intent_meta": {"num_days": 1}, "city_order": ["宜昌"],
    }
    plan = migrate_plan(raw)
    assert plan["source"] == "chat"
    assert plan["meta"]["intent_meta"] == {"num_days": 1}
    assert plan["meta"]["city_order"] == ["宜昌"]


def test_migrate_quick_trip_single_day():
    raw = {
        "trip_type": "quick_trip", "name": "q",
        "origin": {"city": "武汉"},
        "selected_trip_spots": [
            {"name": "东湖", "lng": 114.4, "lat": 30.55, "price": 0}],
        "route_options": [{"polyline": "xyz", "km": 8, "min": 20}],
        "selected_route_idx": 0,
    }
    plan = migrate_plan(raw)
    assert plan["num_days"] == 1
    assert plan["days"][0]["route"]["polyline"] == "xyz"
    assert plan["days"][0]["stops"][0]["name"] == "东湖"


def test_migrate_unknown_best_effort():
    plan = migrate_plan({"name": "weird", "trip_type": "alien"})
    assert plan["schema_version"] == PLAN_SCHEMA_VERSION
    assert plan["name"] == "weird"


def test_migrate_is_idempotent_for_v2():
    plan = build_plan("x", [{"stops": [{"name": "A", "lng": 1, "lat": 2}]}], "manual")
    assert migrate_plan(plan) is plan


# -------------------------------------------------- on-disk legacy files
@pytest.mark.skipif(not os.path.isdir(PLAN_DIR), reason="no plans dir")
def test_real_legacy_files_migrate():
    """Every plan file currently on disk must migrate without exceptions
    and produce a valid unified plan."""
    files = [f for f in os.listdir(PLAN_DIR) if f.endswith(".json")]
    assert files, "expected at least one real plan file"
    for f in files:
        raw = json.load(open(os.path.join(PLAN_DIR, f), encoding="utf-8"))
        plan = migrate_plan(raw)
        assert plan["schema_version"] == PLAN_SCHEMA_VERSION
        assert plan["source"] in ("manual", "chat", "import", "day_route", "weekend")
        # stops with coords must survive migration
        for s in all_stops(plan):
            assert isinstance(s["lng"], (int, float))
            assert isinstance(s["lat"], (int, float))


def test_summary_and_all_stops():
    plan = build_plan("s", [
        {"day_num": 1, "city": "武汉", "stops": [{"name": "A", "lng": 1, "lat": 2}]},
        {"day_num": 2, "city": "宜昌", "stops": [{"name": "B"}]},
    ], "chat")
    sm = plan_summary(plan)
    assert sm["source"] == "chat" and sm["num_days"] == 2 and sm["total_spots"] == 2
    assert sm["cities"] == ["武汉", "宜昌"]
    stops = all_stops(plan)
    assert len(stops) == 1 and stops[0]["day_num"] == 1  # B has no coords
