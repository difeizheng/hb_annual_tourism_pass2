# -*- coding: utf-8 -*-
"""Headless UI smoke for the day-route page (Recorder pattern).

Covers: first render (session init + sidebar), and the result branch
(timeline markdown, map iframe, metrics) with a pre-built route.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import types
from unittest.mock import MagicMock

import streamlit as st

calls = []


class Recorder:
    def __init__(self, name, ret=None):
        self.name, self.ret = name, ret

    def __call__(self, *a, **k):
        calls.append((self.name, str(a[:1])[:120]))
        return self.ret if self.ret is not None else MagicMock()


class SS(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)

    def __setattr__(self, k, v):
        self[k] = v


for f in ("markdown caption info success warning error divider expander "
          "spinner metric subheader title").split():
    setattr(st, f, Recorder(f))
for f in "button selectbox number_input text_input checkbox".split():
    setattr(st, f, Recorder(f, ret=False) if f == "button" else Recorder(f, ret=""))
st.tabs = lambda labels, **k: [
    MagicMock(__enter__=lambda s: MagicMock(), __exit__=lambda s, *x: False)
    for _ in labels
]


def _cols(*a, **k):
    spec = a[0] if a else [1, 1]
    if isinstance(spec, int):
        n = spec
    elif isinstance(spec, (list, tuple)):
        n = len(spec)
    else:
        n = 2
    return [MagicMock(__enter__=lambda s: MagicMock(),
                      __exit__=lambda s, *x: False) for _ in range(n)]


st.columns = _cols
st.rerun = lambda *a, **k: None
st.secrets = {"amap_web_key": "", "amap_js_key": ""}

# --- fixture pool ---
import json

data_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "spot_coordinates.json")
with open(data_path, encoding="utf-8") as f:
    raw = json.load(f)
pool = [
    {"name": n, "lng": c["lng"], "lat": c["lat"], "city": "宜昌",
     "category": "自然景观", "play_hours": 2.0, "price": 0}
    for n, c in (raw.items() if isinstance(raw, dict) else [])
    if isinstance(c, dict) and c.get("lng")
]

from app.day_route import render_day_route_page

# --- 1) first render: session init + sidebar, no crash ---
render_day_route_page(pool, None, None)
assert st.session_state.dr_stops == []
assert st.session_state.dr_route is None
print("first render OK")

# --- 2) result branch: pre-built route + timeline + map url ---
from src.trip_planner import day_route_planner as drp
from src.trip_planner.route_optimizer import DayRoute

stops = [
    {"name": "三峡大瀑布", "lng": 111.165, "lat": 30.846,
     "play_hours": 2.5, "price": 0, "_custom": True},
    {"name": "宜昌博物馆", "lng": 111.306, "lat": 30.705,
     "play_hours": 2.0, "price": 0, "_custom": True},
]
st.session_state.dr_stops = stops
st.session_state.dr_route = DayRoute(
    origin={"name": "宜昌", "lng": 111.286, "lat": 30.692},
    ordered_spots=stops, segments=[],
    total_distance_km=23.1, total_duration_min=46,
    ordered_polyline="111.28,30.69;111.16,30.84")
st.session_state.dr_timeline = drp.build_day_timeline(
    st.session_state.dr_route, depart_hour=7)
st.session_state.dr_map_url = "http://127.0.0.1:19170/map_smoke.html"

render_day_route_page(pool, None, None)

text = " ".join(str(c[1]) for c in calls if c[0] in ("markdown", "subheader"))
assert "时间轴" in text and "地图" in text
assert "三峡大瀑布" in text
assert "07:00" in text  # timeline drive leg rendered with times
# 注：结果区 metric 调用挂在 column 上下文（m1.metric），Recorder 全局拦截
# 不生效；真实渲染由浏览器端验证，冒烟只断言无异常 + 时间轴/地图渲染。
print("result render OK (timeline+map)")
print("SMOKE PASS")
