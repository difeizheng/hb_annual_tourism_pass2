"""Unit tests for the shared plan editor helpers + unified save path."""
import json
import os
from unittest.mock import MagicMock, patch

import pytest

import src.trip_planner.plan_manager as pm
from src.trip_planner.plan_manager import save_days_plan, load_plan
from src.trip_planner.plan_schema import PLAN_SCHEMA_VERSION
from app.plan_editor import anchor_for, _move_cb


# ---------------------------------------------------------------- anchor
def test_anchor_prefers_same_day_earlier_stop():
    days = [{"day_num": 1, "stops": [{"name": "A"}, {"name": "B"}, {"name": "C"}]},
            {"day_num": 2, "stops": [{"name": "D"}]}]
    coords = {"A": {"lng": 1, "lat": 1}, "D": {"lng": 9, "lat": 9}}
    a = anchor_for(days, coords, 1, 2)   # before C: nearest earlier = A
    assert a == {"lng": 1, "lat": 1}


def test_anchor_falls_back_to_prev_day_last_stop():
    days = [{"day_num": 1, "stops": [{"name": "A"}, {"name": "B"}]},
            {"day_num": 2, "stops": [{"name": "C"}]}]
    coords = {"B": {"lng": 2, "lat": 2}}
    a = anchor_for(days, coords, 2, 0)   # C first in day → prev day's B
    assert a == {"lng": 2, "lat": 2}


def test_anchor_none_when_nothing_resolved():
    assert anchor_for([{"day_num": 1, "stops": [{"name": "X"}]}], {}, 1, 0) is None


# --------------------------------------------------------------- move_cb
class _SS(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)

    def __setattr__(self, k, v):
        self[k] = v


def _fake_st(ss):
    m = MagicMock()
    m.session_state = ss
    return m


def test_move_cb_moves_stop_across_days():
    ss = _SS()
    ss["ii_days"] = [
        {"day_num": 1, "stops": [{"name": "A"}, {"name": "B"}]},
        {"day_num": 2, "stops": [{"name": "C"}]},
    ]
    ss["mv_key"] = "D2"
    with patch("app.plan_editor.st", _fake_st(ss)):
        _move_cb(1, 0, "mv_key", "ii_days", "ii")
    assert [s["name"] for s in ss["ii_days"][0]["stops"]] == ["B"]
    assert [s["name"] for s in ss["ii_days"][1]["stops"]] == ["C", "A"]
    assert ss["ii_dirty"] is True
    assert "mv_key" not in ss


def test_move_cb_ignores_placeholder():
    ss = _SS()
    ss["ii_days"] = [{"day_num": 1, "stops": [{"name": "A"}]}]
    ss["mv_key"] = "移至…"
    with patch("app.plan_editor.st", _fake_st(ss)):
        _move_cb(1, 0, "mv_key", "ii_days", "ii")
    assert len(ss["ii_days"][0]["stops"]) == 1
    assert not ss.get("ii_dirty")


# ------------------------------------------------------- save_days_plan
def test_save_days_plan_unified_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "PLAN_DIR", str(tmp_path))
    days = [
        {"day_num": 1, "label": "武汉", "hotel": "如家",
         "stops": [{"name": "黄鹤楼", "arrive": "09:00", "hours": 2.0}],
         "route": {"polyline": "abc", "km": 5, "min": 15}},
    ]
    coords = {"黄鹤楼": {"lng": 114.3, "lat": 30.5, "source": "pool"}}
    pid = save_days_plan(days, "测试行程", "weekend", origin_city="武汉",
                         coords=coords, meta={"budget": {"total": 500}})

    raw = json.load(open(os.path.join(str(tmp_path), pid + ".json"),
                         encoding="utf-8"))
    assert raw["schema_version"] == PLAN_SCHEMA_VERSION
    assert raw["source"] == "weekend"
    assert raw["origin"]["city"] == "武汉"
    assert raw["meta"]["budget"] == {"total": 500}
    assert raw["meta"]["day_extras"]["1"]["hotel"] == "如家"
    stop = raw["days"][0]["stops"][0]
    assert stop["lng"] == 114.3 and stop["coord_source"] == "pool"
    assert raw["days"][0]["route"]["polyline"] == "abc"
    assert raw["total_spots"] == 1

    loaded = load_plan(pid)          # already v2 → passes through unchanged
    assert loaded is not None and loaded["schema_version"] == PLAN_SCHEMA_VERSION
    assert loaded["days"][0]["stops"][0]["name"] == "黄鹤楼"


def test_save_days_plan_overwrite_keeps_id(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "PLAN_DIR", str(tmp_path))
    days = [{"day_num": 1, "stops": [{"name": "A"}]}]
    pid1 = save_days_plan(days, "v1", "manual")
    pid2 = save_days_plan(days, "v2", "manual", plan_id=pid1)
    assert pid1 == pid2
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert load_plan(pid1)["name"] == "v2"
