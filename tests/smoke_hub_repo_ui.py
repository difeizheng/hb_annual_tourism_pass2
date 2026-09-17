# -*- coding: utf-8 -*-
"""Headless UI smoke: planning hub dispatch + 我的行程 repository render.

Same Recorder/Col stub pattern as smoke_import_editor_ui.py. Repository is
rendered against the REAL data/trip_plans dir (read-only, no button clicks),
so this also exercises load_plan auto-migration on whatever plans exist.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


class Col(MagicMock):
    def button(self, *a, **k):
        return False

    def selectbox(self, *a, **k):
        return "移至…"

    def text_input(self, *a, **k):
        return ""

    def number_input(self, *a, **k):
        return 2.0


for f in ("markdown caption info success warning error divider spinner "
          "metric subheader title write").split():
    setattr(st, f, Recorder(f))
st.button = Recorder("button", ret=False)
st.text_input = Recorder("text_input", ret="")
st.text_area = Recorder("text_area", ret="")
st.number_input = Recorder("number_input", ret=2.0)
st.selectbox = Recorder("selectbox", ret="武汉")
st.radio = Recorder("radio", ret="✏️ 编辑器")
st.expander = lambda *a, **k: MagicMock(
    __enter__=lambda s: MagicMock(), __exit__=lambda s, *x: False)
st.container = lambda *a, **k: MagicMock(
    __enter__=lambda s: MagicMock(), __exit__=lambda s, *x: False)
st.columns = lambda spec, **k: [Col() for _ in range(
    spec if isinstance(spec, int) else len(spec))]
st.rerun = lambda *a, **k: None
st.secrets = {"amap_web_key": "", "amap_js_key": ""}
st.sidebar = MagicMock()
st.sidebar.selectbox = lambda *a, **k: "武汉"
st.sidebar.button = lambda *a, **k: False
st.components = MagicMock()
st.components.v1 = MagicMock()
st.components.v1.iframe = Recorder("iframe")

# ---------------------------------------------------------------- hub
from app import planning_hub  # noqa: E402

ss = SS()
st.session_state = ss

# editor mode with nothing loaded -> info hint, no crash
planning_hub.render_planning_hub({"spots_with_coords": [], "graph_data": {},
                                  "cleaned": []})

# editor mode with a real plan loaded
from src.trip_planner.plan_manager import list_plans, load_plan  # noqa: E402
from src.trip_planner.plan_schema import plan_to_editor_days  # noqa: E402

plans = list_plans()
assert plans, "expected at least one saved plan on disk for this smoke"
full = load_plan(plans[0]["id"])
assert full and full.get("days"), "plan load/migration failed"
days, coords = plan_to_editor_days(full)
ss.ed_days = days
ss.ed_coords = coords or None
ss.ed_edit_plan_id = full["id"]
ss.ed_edit_name = full.get("name", "")
ss.ed_source = full.get("source")
ss.ed_meta = full.get("meta")
ss.ed_travel_month = full.get("travel_month")
ss.ed_origin = (full.get("origin") or {}).get("city") or "武汉"
planning_hub.render_planning_hub({"spots_with_coords": [], "graph_data": {},
                                  "cleaned": []})
print("hub editor mode OK (plan: {})".format(full.get("name")))

# ------------------------------------------------------- my trips page
import app.pages.my_trips_page as mt  # noqa: E402

mt._build_trip_map_html = lambda *a, **k: "<html></html>"
mt._save_map_html = lambda *a, **k: "http://127.0.0.1/x.html"

ss2 = SS()
ss2.trip_origin = "武汉"
ss2.selected_trip_spots = []
ss2.route_options = []
ss2.selected_route_idx = 0
ss2.trip_nearby = {"hotels": [], "restaurants": []}
ss2.nav_page = "🧳 我的行程"
st.session_state = ss2
mt.render_my_trips_page({"spots_with_coords": [], "DATA_DIR": "data"})
print("my_trips repository OK ({} plans rendered)".format(len(plans)))
print("SMOKE PASS ({} recorder calls)".format(len(calls)))
