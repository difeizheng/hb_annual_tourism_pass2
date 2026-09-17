# -*- coding: utf-8 -*-
"""单日路线页 — 自定义站点 + 真实驾车路线 + 时间轴 + 地图。

站点来源：年卡景点 / POI 搜索入库的自定义站点 / 手动坐标。
渲染复用 app.map_html（自包含模块；页面代码禁止 import app.main）。
"""
from __future__ import annotations

import streamlit as st

from app.map_html import _build_trip_map_html, _save_map_html
from src.trip_planner import day_route_planner as drp
from src.trip_planner.plan_manager import save_days_plan


def _render_day_route_map(route, stops):
    """Build + save map HTML via map_html, return map_server URL."""
    day_spots = [{**s, "day_num": 1} for s in stops]
    html = _build_trip_map_html(
        selected_spots=day_spots,
        route_polyline=route.ordered_polyline,
        day_plan={"days": [{"day_num": 1, "city": "当日路线",
                            "spots": day_spots}]},
    )
    return _save_map_html(html)


def _poi_search(query, web_key):
    """AMap text search -> [{name, lng, lat, category, address}]."""
    import requests
    try:
        resp = requests.get(
            "https://restapi.amap.com/v3/place/text",
            params={"key": web_key, "keywords": query,
                    "output": "json", "pagesize": 6},
            timeout=10,
        )
        data = resp.json()
    except Exception:
        return []
    if data.get("status") != "1":
        return []
    out = []
    for p in data.get("pois", [])[:6]:
        loc = p.get("location", "0,0").split(",")
        if len(loc) != 2:
            continue
        out.append({
            "name": p.get("name", ""),
            "lng": float(loc[0]), "lat": float(loc[1]),
            "category": p.get("type", ""),
            "address": p.get("address", "") or "",
        })
    return out


def render_day_route_page(spots_with_coords, graph_data, cleaned):
    ss = st.session_state
    st.title("🧭 单日路线")
    st.caption("挑选今天的站点 → 真实驾车路线 + 时间轴 + 地图。支持年卡景点、POI 搜索、手动坐标。")

    # --- session init ---
    if "dr_stops" not in ss:
        ss.dr_stops = []
    if "dr_route" not in ss:
        ss.dr_route = None
    if "dr_timeline" not in ss:
        ss.dr_timeline = None
    if "dr_map_url" not in ss:
        ss.dr_map_url = None

    web_key = st.secrets.get("amap_web_key", "") if hasattr(st, "secrets") else ""

    # =====================================================
    # 侧栏：出发点 + 添加站点
    # =====================================================
    with st.sidebar:
        st.subheader("出发点")
        all_cities = sorted(set(s["city"] for s in spots_with_coords if s.get("city")))
        origin_name = st.selectbox("出发地", all_cities, key="dr_origin_city")
        from app.map_html import CITY_COORDS
        oc = CITY_COORDS.get(origin_name, [114.305, 30.593])
        origin = {"name": origin_name, "lng": oc[0], "lat": oc[1]}

        st.divider()
        st.subheader("添加站点")

        tabs = st.tabs(["年卡景点", "POI 搜索", "手动坐标"])

        with tabs[0]:
            q = st.text_input("筛选", key="dr_pass_filter", placeholder="输入名称关键字")
            pool = spots_with_coords
            if q:
                pool = [s for s in pool if q in s.get("name", "")]
            names = [s["name"] for s in pool[:50]]
            pick = st.selectbox("选择景点", names, key="dr_pass_pick") if names else None
            if pick and st.button("➕ 加入", key="dr_pass_add"):
                s = next(s for s in pool if s["name"] == pick)
                ss.dr_stops.append({
                    "name": s["name"], "lng": s["lng"], "lat": s["lat"],
                    "category": s.get("category", ""), "play_hours": s.get("play_hours") or 2.0,
                    "price": s.get("price", 0) or 0, "_custom": False,
                })
                st.rerun()

        with tabs[1]:
            if not web_key:
                st.caption("未配置 amap_web_key，POI 搜索不可用")
            kw = st.text_input("关键字", key="dr_poi_kw", placeholder="如：三峡大瀑布")
            if kw and web_key and st.button("🔍 搜索", key="dr_poi_search"):
                ss.dr_poi_results = _poi_search(kw, web_key)
            for p in ss.get("dr_poi_results", []):
                label = f"{p['name']}（{p['address'][:12]}）"
                if st.button(f"➕ {label}", key=f"dr_poi_add_{p['lng']}_{p['lat']}"):
                    drp.upsert_custom_stop(
                        p["name"], p["lng"], p["lat"], category=p["category"],
                        play_hours=drp.estimate_custom_play_hours(p["category"]),
                        address=p["address"],
                    )
                    ss.dr_stops.append({**p, "play_hours": drp.estimate_custom_play_hours(p["category"]),
                                        "price": 0, "_custom": True})
                    st.rerun()

        with tabs[2]:
            mname = st.text_input("名称", key="dr_man_name")
            c1, c2 = st.columns(2)
            with c1:
                mlng = st.number_input("经度", 73.0, 135.0, 111.0, 0.0001, key="dr_man_lng")
            with c2:
                mlat = st.number_input("纬度", 3.0, 53.0, 30.0, 0.0001, key="dr_man_lat")
            if mname and st.button("➕ 加入", key="dr_man_add"):
                ss.dr_stops.append({
                    "name": mname, "lng": float(mlng), "lat": float(mlat),
                    "category": "自定义", "play_hours": 2.0, "price": 0, "_custom": True,
                })
                st.rerun()

        st.divider()
        if ss.dr_stops:
            st.subheader(f"今日站点（{len(ss.dr_stops)}）")
            for i, s in enumerate(ss.dr_stops):
                tag = "⭐" if s.get("_custom") else "🎫"
                st.markdown(f"{i+1}. {tag} {s['name']}（{s.get('play_hours', 2)}h）")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("↑", key=f"dr_mv_up_{i}") and i > 0:
                        ss.dr_stops[i-1], ss.dr_stops[i] = ss.dr_stops[i], ss.dr_stops[i-1]
                        st.rerun()
                with c2:
                    if st.button("✕", key=f"dr_del_{i}"):
                        ss.dr_stops.pop(i)
                        st.rerun()

    # =====================================================
    # 主区：生成 + 展示
    # =====================================================
    col1, col2 = st.columns([3, 1])
    with col1:
        c1, c2, c3 = st.columns(3)
        with c1:
            depart = st.number_input("出发时间（时）", 5, 12, 8, key="dr_depart")
        with c2:
            optimize = st.checkbox("自动排序（就近优先）", value=len(ss.dr_stops) >= 3, key="dr_opt")
        with c3:
            go = st.button("🚗 生成路线", type="primary", key="dr_go")
    with col2:
        if st.button("🗑 清空全部", key="dr_clear"):
            ss.dr_stops, ss.dr_route, ss.dr_timeline, ss.dr_map_url = [], None, None, None
            st.rerun()

    if go:
        if not ss.dr_stops:
            st.warning("先从左侧添加站点")
        elif not web_key:
            st.error("未配置 amap_web_key（secrets.toml），无法获取驾车路线")
        else:
            with st.spinner("规划中…"):
                ordered = drp.optimize_stop_order(origin, ss.dr_stops, optimize=optimize)
                route = drp.build_day_route(origin, ordered, web_key)
                ss.dr_route = route
                ss.dr_timeline = drp.build_day_timeline(route, depart_hour=int(depart))
                ss.dr_map_url = _render_day_route_map(route, ordered)
            st.rerun()

    # --- 结果展示 ---
    route, tl = ss.dr_route, ss.dr_timeline
    if not route:
        st.info("添加站点后点「🚗 生成路线」")
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("总里程", f"{route.total_distance_km} km")
    m2.metric("总车程", f"{route.total_duration_min // 60}h{route.total_duration_min % 60:02d}")
    m3.metric("游玩时长", f"{tl['total_play_hours']}h")
    m4.metric("预计返回", tl["end_time"])

    left, right = st.columns([2, 3])
    with left:
        st.subheader("⏱ 时间轴")
        icons = {"drive": "🚗", "play": "🎯", "lunch": "🍜"}
        for it in tl["items"]:
            st.markdown(f"**{it['start']}–{it['end']}** {icons.get(it['kind'],'')} "
                        f"{it['name']}" + (f"　`{it['note']}`" if it.get("note") else ""))
    with right:
        st.subheader("🗺 地图")
        if ss.dr_map_url:
            st.components.v1.iframe(ss.dr_map_url, height=560)

    # --- save as unified plan ---
    st.divider()
    dr_name = st.text_input("行程名称", key="dr_save_name",
                            value="单日路线·" + "-".join(
                                s["name"] for s in ss.dr_stops[:3]))
    if st.button("💾 保存到我的行程", key="dr_save_btn", type="primary"):
        pid = save_days_plan(
            [{"day_num": 1, "city": origin_name,
              "stops": [dict(s) for s in ss.dr_stops],
              "route": {"polyline": route.ordered_polyline,
                        "km": route.total_distance_km,
                        "min": route.total_duration_min,
                        "from": origin_name}}],
            dr_name, "day_route",
            origin_city=origin_name,
            origin_lng=origin["lng"], origin_lat=origin["lat"],
            meta={"timeline": tl})
        st.success(f"已保存（ID: {pid}）。到「🧳 我的行程」查看/编辑")
