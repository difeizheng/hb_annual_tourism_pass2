# -*- coding: utf-8 -*-
"""Itinerary import page: paste text, LLM-parse, geocode, per-day routes.

Flow: paste box -> parse button (LLM structure only) -> geocode + routes
(deterministic) -> map with per-day polylines -> day details -> save.
"""
from __future__ import annotations

import streamlit as st

from app.map_html import CITY_COORDS, _build_trip_map_html, _save_map_html
from src.trip_planner import itinerary_importer as ii


def _unresolved_names(days):
    out = []
    for d in days:
        for s in d.get("stops", []):
            if s.get("_unresolved"):
                out.append(s["name"])
    return out


def render_itinerary_import_page(spots_with_coords, graph_data, cleaned):
    """Entry point wired in main.py."""
    ss = st.session_state
    try:
        web_key = st.secrets["amap_web_key"]
    except (KeyError, FileNotFoundError):
        web_key = ""

    if "ii_days" not in ss:
        ss.ii_days = None
    if "ii_coords" not in ss:
        ss.ii_coords = None
    if "ii_error" not in ss:
        ss.ii_error = ""

    st.header("📥 行程导入")
    st.caption("粘贴你的行程文本：LLM 只做结构化（不新增、不重排、不改时间），"
               "坐标解析与驾车路线全部走确定性算法。")

    text = st.text_area(
        "行程文本", height=280, key="ii_text",
        placeholder="D1（9/25 周五）：7:00武汉出发 → 11:30三峡大瀑布（溯溪约2.5h，带雨衣）→ ...\n"
                    "D2（9/26 周六）：两坝一峡全天（7:30–17:00）→ ...",
        help="每行一天，顺序即行程顺序；时间与备注原样保留")

    col_btn, col_clear, col_origin = st.columns([1, 1, 2])
    parse_disabled = not text.strip()
    if col_btn.button("🔍 解析行程", type="primary",
                      key="ii_parse_btn", disabled=parse_disabled):
        with st.spinner("LLM 解析中（约 10-60s）..."):
            try:
                ss.ii_days = ii.parse_itinerary_text(text)
                ss.ii_coords = None
                ss.ii_error = ""
            except ValueError as e:
                ss.ii_error = str(e)
    if col_clear.button("🧹 清除", key="ii_clear_btn"):
        ss.ii_days = None
        ss.ii_coords = None
        ss.ii_error = ""
        st.rerun()
    city_names = list(CITY_COORDS.keys())
    origin_name = col_origin.selectbox(
        "D1 出发城市", city_names,
        index=city_names.index("武汉") if "武汉" in city_names else 0,
        key="ii_origin")

    if ss.ii_error:
        st.error("解析失败：" + ss.ii_error)
        return
    days = ss.ii_days
    if not days:
        st.info("粘贴行程文本后点「🔍 解析行程」")
        return

    n_stops = sum(len(d.get("stops", [])) for d in days)
    st.success("解析成功：{} 天 / {} 个站点".format(len(days), n_stops))

    # ---------- geocode + per-day routes (deterministic) ----------
    if ss.ii_coords is None:
        pool = []
        for s in spots_with_coords:
            if isinstance(s, dict) and s.get("lng") and s.get("lat"):
                pool.append({"name": s.get("name", ""),
                             "lng": s["lng"], "lat": s["lat"]})
        origin = {"name": origin_name,
                  "lng": CITY_COORDS[origin_name][0],
                  "lat": CITY_COORDS[origin_name][1]}
        with st.spinner("坐标解析 + 驾车路线计算中..."):
            coords = ii.resolve_stop_coords(days, pool, web_key)
            days = ii.attach_day_routes(days, coords, origin, web_key)
        ss.ii_days = days
        ss.ii_coords = coords

    coords = ss.ii_coords
    days = ss.ii_days

    unresolved = _unresolved_names(days)
    if unresolved:
        st.warning("⚠️ 以下站点未能定位（保留在行程里但不上图，可手动核对名称）："
                   + "、".join(unresolved))

    # ---------- map ----------
    map_spots = []
    day_routes = {}
    day_plan_days = []
    for d in days:
        day_spots = []
        for s in d.get("stops", []):
            c = coords.get(s.get("name", ""))
            if not c:
                continue
            ms = dict(s)
            ms.update(c)
            ms["day_num"] = d["day_num"]
            map_spots.append(ms)
            day_spots.append(ms)
        rt = d.get("route") or {}
        day_routes[str(d["day_num"])] = rt.get("polyline", "")
        day_plan_days.append({
            "day_num": d["day_num"],
            "city": d.get("label") or d.get("hotel") or "",
            "spots": day_spots,
        })
    html = _build_trip_map_html(
        map_spots, height="640px",
        day_plan={"days": day_plan_days},
        day_routes=day_routes)
    url = _save_map_html(html)
    st.components.v1.iframe(url, height=660)

    # ---------- day details ----------
    st.subheader("逐日明细")
    for d in days:
        rt = d.get("route")
        if rt:
            hh, mm = divmod(int(rt.get("min", 0)), 60)
            route_txt = "🚗 {:.0f}km / {}h{:02d}（自 {}）".format(
                rt.get("km", 0), hh, mm, rt.get("from", ""))
        else:
            route_txt = "（当日无可定位站点）"
        head = "D{}  {}  {}　|　{}".format(
            d.get("day_num", ""), d.get("date", ""),
            d.get("label", ""), route_txt)
        with st.expander(head):
            if d.get("transport"):
                st.caption("交通：" + d["transport"])
            if d.get("hotel"):
                st.caption("住宿：" + d["hotel"])
            for s in d.get("stops", []):
                flag = "⚠️未定位 " if s.get("_unresolved") else ""
                arrive = s.get("arrive") or ""
                hours = s.get("hours") or 0
                note = s.get("note") or ""
                line = flag + "• " + s.get("name", "")
                if arrive:
                    line += "　" + arrive
                if hours:
                    line += "（{:g}h）".format(hours)
                if note:
                    line += "　备注：" + note
                st.markdown(line)

    # ---------- save ----------
    st.subheader("保存")
    name = st.text_input("行程名称", value="导入的行程", key="ii_name")
    if st.button("💾 保存到我的行程", key="ii_save_btn", type="primary"):
        pid = ii.save_imported_itinerary(days, name or "导入的行程", origin_name)
        st.success("已保存（ID: {}），可在「🧳 我的行程」页查看".format(pid))
