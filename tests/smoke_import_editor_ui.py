# -*- coding: utf-8 -*-
"""Headless UI smoke for the shared plan editor via the import page.

Pattern per knowledge base: containers must be REAL stubs — button returns
False, selectbox returns business value, text_input returns "". MagicMock
column elements make buttons truthy and both branches fire in one frame.
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

    def setdefault(self, k, v=None):
        return super().setdefault(k, v)


class Col(MagicMock):
    """Column element stub: every widget returns a safe business value."""

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
st.expander = lambda *a, **k: MagicMock(
    __enter__=lambda s: MagicMock(), __exit__=lambda s, *x: False)
st.columns = lambda spec, **k: [Col() for _ in range(
    spec if isinstance(spec, int) else len(spec))]
st.rerun = lambda *a, **k: None
st.secrets = {"amap_web_key": "", "amap_js_key": ""}
st.sidebar = MagicMock()
st.sidebar.selectbox = lambda *a, **k: "武汉"
st.components = MagicMock()
st.components.v1 = MagicMock()
st.components.v1.iframe = Recorder("iframe")

# ---------------------------------------------------------------- run
from app.itinerary_import import render_itinerary_import_page  # noqa: E402

ss = SS()
st.session_state = ss
ss.ii_days = [
    {"day_num": 1, "label": "武汉", "stops": [
        {"name": "黄鹤楼", "arrive": "09:00", "hours": 2.0, "note": ""},
        {"name": "东湖", "arrive": "14:00", "hours": 2.5, "note": "骑车"}],
     "route": {"polyline": "p1", "km": 12, "min": 30}},
    {"day_num": 2, "label": "宜昌", "stops": [
        {"name": "三峡大瀑布", "arrive": "10:00", "hours": 3.0, "note": ""}],
     "route": {"polyline": "p2", "km": 45, "min": 70}},
]
ss.ii_coords = {
    "黄鹤楼": {"lng": 114.30, "lat": 30.54, "source": "pool"},
    "东湖": {"lng": 114.36, "lat": 30.55, "source": "pool"},
    "三峡大瀑布": {"lng": 111.40, "lat": 30.80, "source": "pool"},
}
ss.ii_origin = "武汉"

pool = [{"name": n, "lng": c["lng"], "lat": c["lat"]}
        for n, c in ss.ii_coords.items()]

render_itinerary_import_page(pool, {}, [])

names = [c[0] for c in calls]
args_blob = " ".join(c[1] for c in calls)
assert "iframe" in names, "map iframe not rendered"
assert "逐日明细" in args_blob, "editor section missing"
assert "保存" in args_blob, "save section missing"
assert "解析出" in args_blob, "parse summary missing"
assert ss.ii_days[0]["stops"][0]["name"] == "黄鹤楼", "stops mutated by render!"
print("smoke_import_editor_ui: PASS ({} recorder calls)".format(len(calls)))
