# -*- coding: utf-8 -*-
"""Shared plan editor component — map + per-day stop editor + unified save.

Used by:
  - app/itinerary_import.py (📥 行程导入, prefixes ii_/imp_)
  - app/planning_hub.py    (✏️ 编辑器 mode, prefixes ed_/ed_)   [Stage E]

Operates on session-state day dicts (stops mutable in place) plus a
{name: {lng, lat, source}} coord map. Saves through the UNIFIED plan
schema (plan_schema.build_plan) via plan_manager.save_days_plan.
"""

import streamlit as st

import src.trip_planner.itinerary_importer as ii
from src.trip_planner.plan_manager import save_days_plan
from app.map_html import _build_trip_map_html, _save_map_html


def anchor_for(days, coords, day_num, idx):
    """Nearest resolved coord before stop (day_num, idx): same-day earlier
    stops first, then previous days' last stops. Used to bias POI search."""
    for d in days:
        if d.get("day_num") == day_num:
            for s in reversed(d.get("stops", [])[:idx]):
                c = coords.get(s.get("name", ""))
                if c:
                    return c
    prev = None
    for d in days:
        if (d.get("day_num") or 0) < day_num:
            prev = d
    if prev:
        for s in reversed(prev.get("stops", [])):
            c = coords.get(s.get("name", ""))
            if c:
                return c
    return None


def _move_cb(dn, idx, key, days_key, state_prefix):
    """selectbox on_change: move stop (dn, idx) to the chosen day."""
    target = st.session_state.get(key)
    if not target or target == "移至…":
        return
    try:
        tdn = int(str(target)[1:])
    except ValueError:
        return
    days_ = st.session_state.get(days_key) or []
    src_d = next((x for x in days_ if x.get("day_num") == dn), None)
    dst_d = next((x for x in days_ if x.get("day_num") == tdn), None)
    if not src_d or not dst_d or idx >= len(src_d.get("stops", [])):
        return
    stop = src_d["stops"].pop(idx)
    dst_d["stops"].append(stop)
    st.session_state["{}_dirty".format(state_prefix)] = True
    st.session_state.pop(key, None)


def init_editor_state(ss, sp):
    """Idempotent init of the editor's UI state keys."""
    ss.setdefault("{}_dirty".format(sp), False)
    ss.setdefault("{}_edit_plan_id".format(sp), None)
    ss.setdefault("{}_edit_name".format(sp), "")
    ss.setdefault("{}_edit_open".format(sp), None)
    ss.setdefault("{}_add_open".format(sp), None)


def reset_editor_state(ss, sp):
    """Clear editor UI state (e.g. after parse/clear on the import page)."""
    ss["{}_coords".format(sp)] = None
    ss["{}_error".format(sp)] = ""
    ss["{}_dirty".format(sp)] = False
    ss["{}_edit_plan_id".format(sp)] = None
    ss["{}_edit_name".format(sp)] = ""
    ss["{}_edit_open".format(sp)] = None
    ss["{}_add_open".format(sp)] = None
    ss.pop("{}_name".format(sp), None)


def render_plan_editor(*, days_key, coords_key, pool, web_key, origin_name,
                       origin_coord, state_prefix, widget_prefix, source,
                       default_name="我的行程", meta=None, travel_month=None):
    """Map + per-day editor + save for the day dicts at ss[days_key].

    days:  [{day_num, stops: [{name, arrive, hours, note, ...}], route, ...}]
    coords: ss[coords_key] = {name: {lng, lat, source}}
    """
    ss = st.session_state
    sp, wp = state_prefix, widget_prefix
    init_editor_state(ss, sp)

    days = ss.get(days_key)
    coords = ss.get(coords_key) or {}
    if not days:
        st.caption("没有可编辑的行程")
        return

    # ---- recompute routes after structural edits ----
    if ss["{}_dirty".format(sp)]:
        if web_key:
            with st.spinner("行程有改动，重算驾车路线..."):
                days = ii.attach_day_routes(days, coords, origin_coord, web_key)
            ss[days_key] = days
            ss["{}_dirty".format(sp)] = False
        else:
            st.warning("未配置 amap_web_key：结构改动已生效，但驾车路线暂不更新")

    # ---- map: per-day polylines switch with the day buttons ----
    st.markdown("#### 🗺️ 地图（按天切换：只亮当天的景点与红色路线）")
    map_spots = []
    day_routes = {}
    dp_days = []
    for d in days:
        day_spots = []
        for s in d.get("stops", []):
            c = coords.get(s["name"]) or (
                {"lng": s["lng"], "lat": s["lat"]}
                if s.get("lng") is not None and s.get("lat") is not None else None)
            if not c:
                continue
            ms = dict(s)
            ms["day_num"] = d["day_num"]
            ms["noRemove"] = True
            ms.update({k: v for k, v in c.items() if k != "name"})
            map_spots.append(ms)
            day_spots.append(ms)
        route = d.get("route") or {}
        day_routes[str(d["day_num"])] = route.get("polyline", "")
        dp_days.append({"day_num": d["day_num"],
                        "city": d.get("label") or d.get("city") or d.get("hotel", ""),
                        "spots": day_spots})
    if map_spots:
        html = _build_trip_map_html(map_spots, height="640px",
                                    day_plan={"days": dp_days},
                                    day_routes=day_routes)
        url = _save_map_html(html)
        st.components.v1.iframe(url, height=660)
    else:
        st.caption("没有可上图的站点")

    # ---- per-day details: THE EDITOR ----
    st.markdown("#### 📋 逐日明细（点站点行内按钮编辑；改动后自动重算路线）")
    for d in days:
        dn = d.get("day_num")
        route = d.get("route")
        head = "D{}".format(dn)
        if d.get("date"):
            head += "（{}）".format(d["date"])
        if d.get("label"):
            head += " " + d["label"]
        elif d.get("city"):
            head += " " + str(d["city"])
        if route and (route.get("km") or route.get("min")):
            head += " · {}km / {:.0f}min".format(route.get("km", 0),
                                                 route.get("min", 0))
        with st.expander(head):
            if d.get("transport"):
                st.caption("🚆 交通：" + d["transport"])
            if d.get("hotel"):
                st.caption("🏨 住宿：" + d["hotel"])
            stops = d.get("stops", [])
            for idx, s in enumerate(stops):
                if ss["{}_edit_open".format(sp)] == (dn, idx):
                    _render_edit_form(ss, sp, wp, d, dn, idx, s, days, coords,
                                      pool, web_key)
                    continue

                # ---- view row + actions ----
                rc = st.columns([5.6, 0.7, 0.7, 0.7, 0.7, 2.6])
                flag = "⚠️未定位 " if s.get("_unresolved") else ""
                line = flag + "**" + s.get("name", "") + "**"
                if s.get("arrive"):
                    line += "　到达" + s["arrive"]
                if s.get("hours"):
                    line += "（{:g}h）".format(s["hours"])
                if s.get("note"):
                    line += "　备注：" + s["note"]
                rc[0].markdown(line)
                if rc[1].button("⬆️", key="{}_up_{}_{}".format(wp, dn, idx),
                                help="上移", disabled=(idx == 0)):
                    stops[idx - 1], stops[idx] = stops[idx], stops[idx - 1]
                    ss["{}_dirty".format(sp)] = True
                    st.rerun()
                if rc[2].button("⬇️", key="{}_dn_{}_{}".format(wp, dn, idx),
                                help="下移", disabled=(idx == len(stops) - 1)):
                    stops[idx + 1], stops[idx] = stops[idx], stops[idx + 1]
                    ss["{}_dirty".format(sp)] = True
                    st.rerun()
                if rc[3].button("✏️", key="{}_edit_{}_{}".format(wp, dn, idx),
                                help="编辑站点"):
                    for k in ("{}_e_name_{}_{}".format(wp, dn, idx),
                              "{}_e_arr_{}_{}".format(wp, dn, idx),
                              "{}_e_hrs_{}_{}".format(wp, dn, idx),
                              "{}_e_note_{}_{}".format(wp, dn, idx)):
                        ss.pop(k, None)
                    ss["{}_edit_open".format(sp)] = (dn, idx)
                    st.rerun()
                if rc[4].button("🗑", key="{}_del_{}_{}".format(wp, dn, idx),
                                help="删除站点"):
                    stops.pop(idx)
                    ss["{}_dirty".format(sp)] = True
                    st.rerun()
                other_days = [x.get("day_num") for x in days
                              if x.get("day_num") != dn]
                if other_days and rc[5].selectbox(
                        "移至", ["移至…"] + ["D{}".format(x) for x in other_days],
                        key="{}_mv_{}_{}".format(wp, dn, idx),
                        label_visibility="collapsed",
                        on_change=_move_cb,
                        args=(dn, idx, "{}_mv_{}_{}".format(wp, dn, idx),
                              days_key, sp)):
                    pass  # mutation happens in the on_change callback

            _render_add_stop(ss, sp, wp, dn, days, stops, coords, pool, web_key)

    # ---- save (unified schema) ----
    st.markdown("#### 💾 保存")
    name = st.text_input("行程名称",
                         value=ss.get("{}_edit_name".format(sp)) or default_name,
                         key="{}_name".format(sp))
    edit_plan_id = ss.get("{}_edit_plan_id".format(sp))
    if edit_plan_id:
        sc1, sc2 = st.columns(2)
        if sc1.button("💾 覆盖保存原行程", type="primary",
                      key="{}_save_overwrite".format(wp)):
            pid = save_days_plan(days, name or default_name, source,
                                 origin_city=origin_name, coords=coords,
                                 plan_id=edit_plan_id, meta=meta,
                                 travel_month=travel_month)
            ss["{}_edit_name".format(sp)] = name or default_name
            st.success("已覆盖保存（ID: {}，含坐标与路线）。「🧳 我的行程」可直接看地图".format(pid))
        if sc2.button("📄 另存为新行程", key="{}_save_as".format(wp)):
            pid = save_days_plan(days, name or default_name, source,
                                 origin_city=origin_name, coords=coords,
                                 meta=meta, travel_month=travel_month)
            ss["{}_edit_plan_id".format(sp)] = pid
            ss["{}_edit_name".format(sp)] = name or default_name
            st.success("已另存为新行程（ID: {}）".format(pid))
    else:
        if st.button("💾 保存到我的行程", type="primary",
                     key="{}_save_btn".format(wp)):
            pid = save_days_plan(days, name or default_name, source,
                                 origin_city=origin_name, coords=coords,
                                 meta=meta, travel_month=travel_month)
            ss["{}_edit_plan_id".format(sp)] = pid
            ss["{}_edit_name".format(sp)] = name or default_name
            st.success("已保存（ID: {}，含坐标与路线）。到「🧳 我的行程」查看（含地图）".format(pid))


def _render_edit_form(ss, sp, wp, d, dn, idx, s, days, coords, pool, web_key):
    st.markdown("　✏️ **编辑站点**")
    ec1, ec2, ec3, ec4 = st.columns([2.2, 1, 1, 2.2])
    e_name = ec1.text_input("名称", value=s.get("name", ""),
                            key="{}_e_name_{}_{}".format(wp, dn, idx))
    e_arr = ec2.text_input("到达", value=s.get("arrive", "") or "",
                           key="{}_e_arr_{}_{}".format(wp, dn, idx),
                           placeholder="09:30")
    e_hrs = ec3.number_input("游玩h", value=float(s.get("hours") or 0),
                             min_value=0.0, step=0.5,
                             key="{}_e_hrs_{}_{}".format(wp, dn, idx))
    e_note = ec4.text_input("备注", value=s.get("note", "") or "",
                            key="{}_e_note_{}_{}".format(wp, dn, idx))
    eb1, eb2, _sp = st.columns([1, 1, 4])
    if eb1.button("✅ 保存修改", type="primary",
                  key="{}_e_ok_{}_{}".format(wp, dn, idx)):
        old_name = s.get("name", "")
        new_name = (e_name or "").strip() or old_name
        s["name"] = new_name
        s["arrive"] = (e_arr or "").strip()
        s["hours"] = float(e_hrs)
        s["note"] = (e_note or "").strip()
        if new_name != old_name:
            s.pop("_unresolved", None)
            if new_name not in coords:
                with st.spinner("定位「{}」...".format(new_name)):
                    c = ii.resolve_single_stop(
                        new_name, pool, web_key,
                        anchor=anchor_for(days, coords, dn, idx))
                if c:
                    coords[new_name] = c
                else:
                    s["_unresolved"] = True
            ss["{}_dirty".format(sp)] = True
        ss["{}_edit_open".format(sp)] = None
        st.rerun()
    if eb2.button("取消", key="{}_e_cancel_{}_{}".format(wp, dn, idx)):
        ss["{}_edit_open".format(sp)] = None
        for k in ("{}_e_name_{}_{}".format(wp, dn, idx),
                  "{}_e_arr_{}_{}".format(wp, dn, idx),
                  "{}_e_hrs_{}_{}".format(wp, dn, idx),
                  "{}_e_note_{}_{}".format(wp, dn, idx)):
            ss.pop(k, None)
        st.rerun()


def _render_add_stop(ss, sp, wp, dn, days, stops, coords, pool, web_key):
    if ss["{}_add_open".format(sp)] == dn:
        st.markdown("　➕ **添加站点到 D{}**".format(dn))
        ac1, ac2, ac3, ac4 = st.columns([2.2, 1, 1, 2.2])
        a_name = ac1.text_input("景点/地点名", key="{}_a_name_{}".format(wp, dn),
                                placeholder="如：恩施大峡谷")
        a_arr = ac2.text_input("到达", key="{}_a_arr_{}".format(wp, dn),
                               placeholder="09:30")
        a_hrs = ac3.number_input("游玩h", value=2.0, min_value=0.0,
                                 step=0.5, key="{}_a_hrs_{}".format(wp, dn))
        a_note = ac4.text_input("备注", key="{}_a_note_{}".format(wp, dn))
        ab1, ab2, _sp2 = st.columns([1, 1, 4])
        if ab1.button("✅ 定位并添加", type="primary",
                      key="{}_a_ok_{}".format(wp, dn)):
            nm = (a_name or "").strip()
            if not nm:
                st.warning("名称不能为空")
            else:
                new_s = {"name": nm, "arrive": (a_arr or "").strip(),
                         "hours": float(a_hrs),
                         "note": (a_note or "").strip()}
                if nm not in coords:
                    if not web_key:
                        st.warning("未配置 amap_web_key：站点已加入但无法定位")
                        new_s["_unresolved"] = True
                    else:
                        with st.spinner("定位「{}」...".format(nm)):
                            c = ii.resolve_single_stop(
                                nm, pool, web_key,
                                anchor=anchor_for(days, coords, dn, len(stops)))
                        if c:
                            coords[nm] = c
                        else:
                            new_s["_unresolved"] = True
                stops.append(new_s)
                ss["{}_dirty".format(sp)] = True
                ss["{}_add_open".format(sp)] = None
                for k in ("{}_a_name_{}".format(wp, dn),
                          "{}_a_arr_{}".format(wp, dn),
                          "{}_a_hrs_{}".format(wp, dn),
                          "{}_a_note_{}".format(wp, dn)):
                    ss.pop(k, None)
                st.rerun()
        if ab2.button("取消", key="{}_a_cancel_{}".format(wp, dn)):
            ss["{}_add_open".format(sp)] = None
            for k in ("{}_a_name_{}".format(wp, dn),
                      "{}_a_arr_{}".format(wp, dn),
                      "{}_a_hrs_{}".format(wp, dn),
                      "{}_a_note_{}".format(wp, dn)):
                ss.pop(k, None)
            st.rerun()
    else:
        if st.button("➕ 添加站点", key="{}_add_{}".format(wp, dn)):
            ss["{}_add_open".format(sp)] = dn
            for k in ("{}_a_name_{}".format(wp, dn),
                      "{}_a_arr_{}".format(wp, dn),
                      "{}_a_hrs_{}".format(wp, dn),
                      "{}_a_note_{}".format(wp, dn)):
                ss.pop(k, None)
            st.rerun()
