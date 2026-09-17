# -*- coding: utf-8 -*-
"""🗓️ 规划中心 — one entry for all trip-creation modes + the shared editor.

Mode dispatch via radio (NOT st.tabs): only the active mode renders, so a
heavy mode never computes in the background. All modes save through the
UNIFIED plan schema; saved plans are viewed/managed in 🧳 我的行程 and can
be reopened here in ✏️ 编辑器 mode.
"""

import streamlit as st

from app.map_html import CITY_COORDS
from app.plan_editor import render_plan_editor

MODES = ["📝 表单规划", "💬 对话规划", "🚗 周末出发", "🧭 单日路线",
         "📥 粘贴导入", "✏️ 编辑器"]


def render_planning_hub(ctx):
    ss = st.session_state
    st.title("🗓️ 规划中心")
    st.caption("选择一种方式生成行程 → 统一保存到「🧳 我的行程」→ 随时回这里的 ✏️ 编辑器修改")
    ss.setdefault("ph_mode", MODES[0])
    mode = st.radio("规划方式", MODES, horizontal=True,
                    key="ph_mode", label_visibility="collapsed")
    st.divider()

    if mode == "📝 表单规划":
        from app.pages.trip_planner_page import render_trip_planner_page
        render_trip_planner_page(ctx)
    elif mode == "💬 对话规划":
        from app.chat_planner import render_chat_planner_page
        dep_coords = {
            name: {"name": name, "lng": ll[0], "lat": ll[1]}
            for name, ll in CITY_COORDS.items()
        }
        render_chat_planner_page(ctx["spots_with_coords"], ctx["graph_data"],
                                 ctx["cleaned"], dep_coords)
    elif mode == "🚗 周末出发":
        from app.pages.weekend_page import render_weekend_page
        render_weekend_page(ctx)
    elif mode == "🧭 单日路线":
        from app.day_route import render_day_route_page
        render_day_route_page(ctx["spots_with_coords"], ctx["graph_data"],
                              ctx["cleaned"])
    elif mode == "📥 粘贴导入":
        from app.itinerary_import import render_itinerary_import_page
        render_itinerary_import_page(ctx["spots_with_coords"],
                                     ctx["graph_data"], ctx["cleaned"])
    elif mode == "✏️ 编辑器":
        _render_editor_mode(ctx, ss)


def _render_editor_mode(ctx, ss):
    """Shared editor bound to ed_* session keys (set by 我的行程's ✏️ 编辑)."""
    if not ss.get("ed_days"):
        st.info("在「🧳 我的行程」点某个行程的 **✏️ 编辑**，或先用其他方式生成/导入行程")
        return
    try:
        web_key = str(st.secrets.get("amap_web_key", "")).strip()
    except Exception:
        web_key = ""
    pool = [s for s in (ctx.get("spots_with_coords") or [])
            if s.get("lng") and s.get("lat")]
    origin_name = ss.get("ed_origin") or "武汉"
    oc = CITY_COORDS.get(origin_name, [114.305, 30.593])
    origin_coord = {"name": origin_name, "lng": oc[0], "lat": oc[1]}
    if ss.get("ed_edit_plan_id"):
        st.info("✏️ 正在编辑已保存行程「{}」（ID: {}）——保存时可选择**覆盖原行程**或**另存为新行程**".format(
            ss.get("ed_edit_name") or "未命名", ss["ed_edit_plan_id"]))
    render_plan_editor(
        days_key="ed_days", coords_key="ed_coords",
        pool=pool, web_key=web_key,
        origin_name=origin_name, origin_coord=origin_coord,
        state_prefix="ed", widget_prefix="ed",
        source=ss.get("ed_source") or "manual",
        default_name=ss.get("ed_edit_name") or "我的行程",
        meta=ss.get("ed_meta"), travel_month=ss.get("ed_travel_month"))
