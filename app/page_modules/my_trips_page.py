# -*- coding: utf-8 -*-
"""🧳 我的行程 — draft (当前草稿) + UNIFIED plan repository (行程仓库).

Draft section was moved from app/main.py mostly verbatim (namespace injected
via globals().update(ctx)). The repository replaces the old per-trip_type
lists: every saved plan — manual/chat/import/day_route/weekend — is listed
with map + day details + ✏️ 编辑 (opens the planning hub's editor) + 🗑 删除.
"""

import os
import json

import pandas as pd
import streamlit as st

from src.trip_planner.plan_manager import (list_plans, load_plan, delete_plan,
                                           save_plan, save_days_plan)
from src.trip_planner.plan_schema import plan_to_editor_days
from app.map_html import CITY_COORDS, _build_trip_map_html, _save_map_html

_SOURCE_LABEL = {"manual": "📝 表单", "chat": "💬 对话", "import": "📥 导入",
                 "day_route": "🧭 单日", "weekend": "🚗 周末", "unknown": "📦"}


def render_my_trips_page(ctx):
    globals().update(ctx)
    st.title("我的行程")

    trip_origin = st.session_state.trip_origin
    all_cities_for_dep = sorted(set(s["city"] for s in spots_with_coords if s["city"]))

    # ---------------- Sidebar: draft settings + actions ----------------
    with st.sidebar:
        st.subheader("行程设置")
        trip_origin = st.selectbox(
            "出发城市", all_cities_for_dep,
            index=all_cities_for_dep.index(st.session_state.trip_origin)
                if st.session_state.trip_origin in all_cities_for_dep else 0,
        )
        st.session_state.trip_origin = trip_origin

        # Save current draft as a unified single-day plan
        if st.session_state.selected_trip_spots:
            plan_name = st.text_input(
                "行程名称",
                value=f"我的行程-{len(st.session_state.selected_trip_spots)}个景点")
            if st.button("保存草稿为行程", type="primary", use_container_width=True):
                _save_draft_as_plan(plan_name, trip_origin)
        if st.button("清空行程", type="secondary", use_container_width=True):
            st.session_state.selected_trip_spots = []
            st.session_state.route_options = []
            st.session_state.selected_route_idx = 0
            st.session_state.trip_nearby = {"hotels": [], "restaurants": []}
            st.rerun()

    # ---------------- Draft: spot list + map ----------------
    st.subheader("🧺 当前草稿（未保存）")
    col_list, col_map = st.columns([1, 2])

    with col_list:
        st.caption(f"已选景点 ({len(st.session_state.selected_trip_spots)})")

        if not st.session_state.selected_trip_spots:
            st.info("在「🗺️ 地图探索」点景点弹窗中的「添加到行程」，或在各规划页「加入行程」。")
        else:
            # 主区域一键转存（侧边栏也有完整版：可自定义名称）
            if st.button("💾 存为正式行程", key="mt_draft_quick_save",
                         use_container_width=True):
                _save_draft_as_plan(
                    f"我的行程-{len(st.session_state.selected_trip_spots)}个景点",
                    trip_origin)
            for i, spot in enumerate(st.session_state.selected_trip_spots):
                with st.container(border=True):
                    st.markdown(f"**{i+1}. {spot['name']}**")
                    st.caption(f"{spot['city']} {spot.get('area', '')} · {spot['category']} · ¥{spot['price']}")
                    if st.button("移除", key=f"remove_spot_{spot['name']}"):
                        st.session_state.selected_trip_spots.pop(i)
                        st.session_state.route_options = []
                        st.session_state.selected_route_idx = 0
                        st.rerun()

            st.divider()

            # Route optimization
            if len(st.session_state.selected_trip_spots) >= 2:
                if st.button("优化路线", type="primary", use_container_width=True):
                    valid_spots = [s for s in st.session_state.selected_trip_spots
                                   if s.get("lng") and s.get("lat")]
                    dep_coord = CITY_COORDS.get(trip_origin, [114.305, 30.593])
                    departure = {"name": trip_origin, "lng": dep_coord[0], "lat": dep_coord[1]}

                    with st.spinner("正在生成多套路线方案..."):
                        web_key = st.secrets.get("amap_web_key", "")
                        options = generate_route_options(departure, valid_spots, web_key)
                        st.session_state.route_options = options
                        st.session_state.selected_route_idx = 0
                    st.rerun()

            # Nearby search
            if st.session_state.selected_trip_spots:
                st.subheader("周边搜索")
                if st.button("搜索附近酒店"):
                    with st.spinner("搜索中..."):
                        hotels = []
                        for spot in st.session_state.selected_trip_spots[:3]:
                            if spot.get("lng") and spot.get("lat"):
                                h = search_nearby_hotels(
                                    spot["lng"], spot["lat"],
                                    st.secrets.get("amap_web_key", ""),
                                    radius=3000, max_results=5,
                                )
                                hotels.extend(h)
                        seen = set()
                        unique_hotels = []
                        for h in hotels:
                            if h["name"] not in seen:
                                seen.add(h["name"])
                                unique_hotels.append(h)
                        st.session_state.trip_nearby["hotels"] = unique_hotels[:15]
                        st.rerun()

                if st.button("搜索附近餐厅"):
                    with st.spinner("搜索中..."):
                        restaurants = []
                        for spot in st.session_state.selected_trip_spots[:3]:
                            if spot.get("lng") and spot.get("lat"):
                                r = search_nearby_restaurants(
                                    spot["lng"], spot["lat"],
                                    st.secrets.get("amap_web_key", ""),
                                    radius=2000, max_results=5,
                                )
                                restaurants.append(r)
                        seen = set()
                        unique_rest = []
                        for r in restaurants:
                            if r["name"] not in seen:
                                seen.add(r["name"])
                                unique_rest.append(r)
                        st.session_state.trip_nearby["restaurants"] = unique_rest[:15]
                        st.rerun()

                # Show cached nearby results
                if st.session_state.trip_nearby.get("hotels"):
                    st.write("**附近酒店**")
                    hotel_df = pd.DataFrame([
                        {"酒店": h["name"], "地址": h.get("address", ""), "距离(m)": h.get("distance", 0)}
                        for h in st.session_state.trip_nearby["hotels"][:10]
                    ])
                    st.dataframe(hotel_df, use_container_width=True, hide_index=True)

                if st.session_state.trip_nearby.get("restaurants"):
                    st.write("**附近餐厅**")
                    rest_df = pd.DataFrame([
                        {"餐厅": r["name"], "地址": r.get("address", ""), "距离(m)": r.get("distance", 0)}
                        for r in st.session_state.trip_nearby["restaurants"][:10]
                    ])
                    st.dataframe(rest_df, use_container_width=True, hide_index=True)

            # Route options selector
            if st.session_state.route_options:
                st.divider()
                options = st.session_state.route_options
                idx = st.session_state.selected_route_idx

                labels = [f"方案{i+1}: {opt['name']}" for i, opt in enumerate(options)]
                safe_idx = min(idx, len(labels) - 1)
                if safe_idx != idx:
                    st.session_state.selected_route_idx = safe_idx
                selected_label = st.radio("选择方案", labels, index=safe_idx, horizontal=True)
                new_idx = labels.index(selected_label)
                if new_idx != idx:
                    st.session_state.selected_route_idx = new_idx
                    st.rerun()

                chosen = options[new_idx]
                st.subheader(f"路线概览 — {chosen['name']}")
                c1, c2 = st.columns(2)
                c1.metric("总距离", f"{chosen['total_distance_km']:.1f} km")
                c2.metric("预计驾驶", f"{chosen['total_duration_min']} 分钟")

                col_p, col_c = st.columns(2)
                with col_p:
                    st.markdown("**优点**")
                    for pro in chosen["pros"]:
                        st.markdown(f"- {pro}")
                with col_c:
                    st.markdown("**缺点**")
                    for con in chosen["cons"]:
                        st.markdown(f"- {con}")

                st.write("**推荐游览顺序:**")
                for i, s in enumerate(chosen["ordered_spots"]):
                    st.write(f"{i+1}. {s['name']} ({s['city']})")
                st.write(f"起点: {trip_origin}")

    with col_map:
        if not st.session_state.selected_trip_spots:
            st.info("请先添加景点到行程")
        else:
            hotels = st.session_state.trip_nearby.get("hotels", [])
            restaurants = st.session_state.trip_nearby.get("restaurants", [])
            route_polyline = ""
            map_spots = st.session_state.selected_trip_spots
            if st.session_state.route_options:
                idx = min(st.session_state.selected_route_idx, len(st.session_state.route_options) - 1)
                chosen = st.session_state.route_options[idx]
                route_polyline = chosen.get("ordered_polyline", "")
                map_spots = chosen.get("ordered_spots", map_spots)

            trip_map_html = _build_trip_map_html(
                selected_spots=map_spots,
                route_polyline=route_polyline,
                hotels=hotels,
                restaurants=restaurants,
                height="650px",
            )
            trip_map_url = _save_map_html(trip_map_html)
            st.components.v1.iframe(trip_map_url, height=660)

            # Check for removal flag from map server (triggers on each rerun)
            _REMOVE_FLAG = os.path.join(DATA_DIR, "_remove_spot_flag.json")
            if os.path.exists(_REMOVE_FLAG):
                try:
                    with open(_REMOVE_FLAG, "r", encoding="utf-8") as _f:
                        _flag_data = json.load(_f)
                    _remove_name = _flag_data.get("name")
                    if _remove_name:
                        st.session_state.selected_trip_spots = [
                            s for s in st.session_state.selected_trip_spots
                            if s.get("name") != _remove_name
                        ]
                        st.session_state.route_options = []
                        st.session_state.selected_route_idx = 0
                    os.remove(_REMOVE_FLAG)
                    st.rerun()
                except (json.JSONDecodeError, OSError):
                    try:
                        os.remove(_REMOVE_FLAG)
                    except OSError:
                        pass

    # ---------------- Unified repository ----------------
    st.divider()
    st.subheader("💾 行程仓库")
    plans = list_plans()
    if not plans:
        st.caption("暂无保存的行程。在「🗓️ 规划中心」用任意方式生成后保存，都会出现在这里。")
        return

    # Repository filters (source + name keyword)
    fc1, fc2 = st.columns([1, 2])
    _sources = sorted({p.get("source") or "unknown" for p in plans})
    sel_src = fc1.selectbox(
        "来源筛选", ["全部"] + _sources,
        format_func=lambda x: "全部" if x == "全部" else _SOURCE_LABEL.get(x, x),
        key="mt_repo_src")
    kw = fc2.text_input("按名称搜索", "", key="mt_repo_kw",
                        placeholder="输入行程名关键字")
    if sel_src != "全部":
        plans = [p for p in plans if (p.get("source") or "unknown") == sel_src]
    if kw.strip():
        plans = [p for p in plans if kw.strip() in p.get("name", "")]
    if not plans:
        st.caption("没有匹配的行程")
        return

    for p in plans:
        full = load_plan(p["id"])  # auto-migrates legacy formats
        if not full:
            continue
        src_lbl = _SOURCE_LABEL.get(full.get("source") or "unknown", "📦")
        date_str = (full.get("updated_at") or "")[:10]
        title = (f"{src_lbl} **{full.get('name', '未命名')}** · "
                 f"{full.get('num_days', 0)}天 · {full.get('total_spots', 0)}站 · {date_str}")
        with st.expander(title):
            _render_plan_detail(full)
            missing = _days_missing_route(full)
            if missing and st.button(
                    f"🔁 重新生成路线（{len(missing)} 天缺驾车路线，调高德）",
                    key=f"mt_regen_{p['id']}"):
                n = _regen_routes(full)
                if n:
                    st.success(f"已补齐 {n} 天路线并覆盖保存")
                    st.rerun()
            bc1, bc2 = st.columns(2)
            if bc1.button("✏️ 编辑", key=f"mt_edit_{p['id']}"):
                _open_in_editor(full)
            _del_flag = f"mt_delconfirm_{p['id']}"
            if st.session_state.get(_del_flag):
                bc2.warning("确认删除？此操作不可恢复")
                cc1, cc2 = st.columns(2)
                if cc1.button("✅ 确认删除", key=f"mt_delok_{p['id']}"):
                    delete_plan(p["id"])
                    st.session_state.pop(_del_flag, None)
                    st.rerun()
                if cc2.button("❎ 取消", key=f"mt_delno_{p['id']}"):
                    st.session_state.pop(_del_flag, None)
                    st.rerun()
            elif bc2.button("🗑 删除", key=f"mt_del_{p['id']}"):
                st.session_state[_del_flag] = True
                st.rerun()


def _render_day(d, extras):
    """Render one day block (header + stops + hotel) of a plan detail."""
    rt = d.get("route") or {}
    if rt.get("km") or rt.get("min"):
        mins = int(rt.get("min", 0))
        rt_txt = "🚗 {:.0f}km / {}h{:02d}m".format(rt.get("km", 0),
                                                   mins // 60, mins % 60)
        if rt.get("from"):
            rt_txt += " 自 " + rt["from"]
    else:
        rt_txt = ""
    ex = extras.get(str(d.get("day_num"))) or {}
    label = d.get("city") or ex.get("label") or ""
    tag = " 🚗转场" if d.get("is_transfer_day") else ""
    head = "**D{} · {}**{}　{}".format(d.get("day_num", ""), label, tag, rt_txt)
    st.markdown(head)
    for s in d.get("stops", []):
        line = "• " + s.get("name", "")
        if s.get("arrive"):
            line += "　" + s["arrive"]
        if s.get("hours"):
            line += "（{:g}h）".format(s["hours"])
        if s.get("note"):
            line += "　备注：" + s["note"]
        st.markdown("　" + line)
    if ex.get("hotel"):
        st.caption("　🏨 " + ex["hotel"])


def _save_draft_as_plan(plan_name, trip_origin):
    """Persist the flat draft list as a unified single-day plan."""
    route = {}
    if st.session_state.route_options:
        idx = min(st.session_state.selected_route_idx,
                  len(st.session_state.route_options) - 1)
        chosen = st.session_state.route_options[idx]
        route = {"polyline": chosen.get("ordered_polyline", ""),
                 "km": chosen.get("total_distance_km", 0),
                 "min": chosen.get("total_duration_min", 0)}
    dep = CITY_COORDS.get(trip_origin, [114.305, 30.593])
    pid = save_days_plan(
        [{"day_num": 1, "city": trip_origin,
          "stops": [dict(s) for s in st.session_state.selected_trip_spots],
          "route": route}],
        plan_name, "manual",
        origin_city=trip_origin, origin_lng=dep[0], origin_lat=dep[1])
    st.success(f"已保存！ID: {pid}（下方行程仓库可查看/编辑）")


def _open_in_editor(plan):
    """Load a unified plan into the planning hub's ✏️ 编辑器 mode."""
    days, coords = plan_to_editor_days(plan)
    ss = st.session_state
    ss.ed_days = days
    ss.ed_coords = coords or None
    ss.ed_edit_plan_id = plan["id"]
    ss.ed_edit_name = plan.get("name", "")
    ss.ed_source = plan.get("source") or "manual"
    ss.ed_meta = {k: v for k, v in (plan.get("meta") or {}).items()
                  if k != "day_extras"}
    ss.ed_travel_month = plan.get("travel_month")
    ss.ed_origin = (plan.get("origin") or {}).get("city") or "武汉"
    ss.ed_dirty = False
    ss.ed_edit_open = None
    ss.ed_add_open = None
    ss.ph_mode = "✏️ 编辑器"
    ss._nav_pending = "🗓️ 规划中心"
    st.rerun()


def _days_missing_route(plan):
    """Indices of days that have coord stops but no driving polyline."""
    out = []
    for i, d in enumerate(plan.get("days", [])):
        if (d.get("route") or {}).get("polyline"):
            continue
        if any(s.get("lng") is not None and s.get("lat") is not None
               for s in d.get("stops", [])):
            out.append(i)
    return out


def _regen_routes(plan):
    """Recompute driving polylines for days missing them, overwrite same plan id."""
    from src.trip_planner.route_optimizer import compute_route

    web_key = st.secrets.get("amap_web_key", "")
    if not web_key:
        st.error("未配置 amap_web_key，无法生成驾车路线")
        return 0
    days = plan.get("days", [])
    origin = plan.get("origin") or {}

    def _day_origin(i):
        if origin.get("lng") is not None and origin.get("lat") is not None:
            return {"name": origin.get("city") or origin.get("address") or "出发地",
                    "lng": origin["lng"], "lat": origin["lat"]}
        cc = CITY_COORDS.get(origin.get("city") or "")
        if cc:
            return {"name": origin["city"], "lng": cc[0], "lat": cc[1]}
        prev = [s for dd in days[:i] for s in dd.get("stops", [])
                if s.get("lng") is not None and s.get("lat") is not None]
        if prev:
            return {"name": prev[-1]["name"], "lng": prev[-1]["lng"], "lat": prev[-1]["lat"]}
        return None

    fixed = 0
    for i in _days_missing_route(plan):
        d = days[i]
        stops = [s for s in d.get("stops", [])
                 if s.get("lng") is not None and s.get("lat") is not None]
        o = _day_origin(i)
        if o is None:
            o = {"name": stops[0]["name"], "lng": stops[0]["lng"], "lat": stops[0]["lat"]}
        route = compute_route(o, stops, web_key)
        d["route"] = {"polyline": route.ordered_polyline,
                      "km": round(route.total_distance_km, 1),
                      "min": int(route.total_duration_min),
                      "from": o["name"]}
        d["travel_km"] = round(route.total_distance_km, 1)
        fixed += 1
    if fixed:
        save_plan(plan)  # plan['id'] preserved -> overwrite in place
    return fixed


def _render_plan_detail(plan):
    """Day-by-day markdown + map rebuilt from stored coords (zero API calls).
    Long plans show only the first 3 days until expanded (expander-in-expander
    is illegal in Streamlit, so a toggle gates the rest)."""
    extras = (plan.get("meta") or {}).get("day_extras", {})
    days = plan.get("days", [])
    head_days = days if len(days) <= 4 else days[:3]
    for d in head_days:
        _render_day(d, extras)
    if len(days) > 4:
        if st.toggle(f"展开剩余 {len(days) - 3} 天",
                     key=f"mt_days_{plan.get('id', 'x')}"):
            for d in days[3:]:
                _render_day(d, extras)

    # map
    map_spots, day_routes, dp_days = [], {}, []
    for d in plan.get("days", []):
        ds = []
        for s in d.get("stops", []):
            if s.get("lng") is None or s.get("lat") is None:
                continue
            ms = dict(s)
            ms["day_num"] = d.get("day_num")
            ms["noRemove"] = True
            map_spots.append(ms)
            ds.append(ms)
        day_routes[str(d.get("day_num"))] = (d.get("route") or {}).get("polyline", "")
        ex = extras.get(str(d.get("day_num"))) or {}
        dp_days.append({"day_num": d.get("day_num"),
                        "city": d.get("city") or ex.get("label") or ex.get("hotel", ""),
                        "spots": ds})
    if map_spots:
        url = _save_map_html(_build_trip_map_html(
            map_spots, height="430px",
            day_plan={"days": dp_days}, day_routes=day_routes))
        st.components.v1.iframe(url, height=450)
    else:
        st.caption("此行程无坐标，无法上图；点「✏️ 编辑」重新定位后即可看地图")
