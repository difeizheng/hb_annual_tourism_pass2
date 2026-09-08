# -*- coding: utf-8 -*-
'''📥 行程导入 — paste a multi-day itinerary, structure it, map it, EDIT it.

Boundary: the LLM ONLY parses pasted text into structured days (no
reordering, no invented stops, no re-timing). Geocoding and per-day driving
routes reuse the deterministic importer pipeline.

Editor: reorder/delete/edit stops in-day, move stops across days, add stops;
routes recompute automatically. Saved plans (with coordinates) can be loaded
back here from 「🧳 我的行程」 and overwrite-saved.
'''

import streamlit as st

import src.trip_planner.itinerary_importer as ii
from app.map_html import CITY_COORDS, _build_trip_map_html, _save_map_html

_SAMPLE = """第1天：武汉出发，前往宜昌，游览三峡大瀑布，宿宜昌
第2天：两坝一峡游船（需提前预约），宿宜昌
第3天：上午恩施大峡谷（带雨衣），下午休整，宿利川"""


def _anchor_for(days, coords, day_num, idx):
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


def _move_cb(dn, idx, key):
    """selectbox on_change: move stop (dn, idx) to the chosen day."""
    target = st.session_state.get(key)
    if not target or target == "移至…":
        return
    try:
        tdn = int(str(target)[1:])
    except ValueError:
        return
    days_ = st.session_state.ii_days or []
    src_d = next((x for x in days_ if x.get("day_num") == dn), None)
    dst_d = next((x for x in days_ if x.get("day_num") == tdn), None)
    if not src_d or not dst_d or idx >= len(src_d.get("stops", [])):
        return
    stop = src_d["stops"].pop(idx)
    dst_d["stops"].append(stop)
    st.session_state.ii_dirty = True
    st.session_state.pop(key, None)


def _reset_editor_state(ss):
    ss.ii_coords = None
    ss.ii_error = ""
    ss.ii_dirty = False
    ss.ii_edit_plan_id = None
    ss.ii_edit_name = ""
    ss.ii_edit_open = None
    ss.ii_add_open = None
    ss.pop("ii_name", None)


def render_itinerary_import_page(spots_with_coords, graph_data, cleaned):
    ss = st.session_state
    ss.setdefault("ii_days", None)
    ss.setdefault("ii_coords", None)
    ss.setdefault("ii_error", "")
    ss.setdefault("ii_dirty", False)
    ss.setdefault("ii_edit_plan_id", None)
    ss.setdefault("ii_edit_name", "")
    ss.setdefault("ii_edit_open", None)
    ss.setdefault("ii_add_open", None)

    try:
        web_key = str(st.secrets.get("amap_web_key", "")).strip()
    except Exception:
        web_key = ""

    st.subheader("📥 行程导入")
    st.caption(
        "粘贴多日行程文本（小红书/朋友圈/群聊格式都行）→ 只解析不改动：按天结构化、"
        "确定性定位、每日驾车路线上图。解析后可直接编辑：调序、删除、修改、跨天移动、加站点。"
    )

    if ss.ii_edit_plan_id:
        st.info("✏️ 正在编辑已保存行程「{}」（ID: {}）——保存时可选择**覆盖原行程**或**另存为新行程**".format(
            ss.ii_edit_name or "未命名", ss.ii_edit_plan_id))

    text = st.text_area(
        "行程文本", height=220,
        placeholder=_SAMPLE,
        help="每行一天或自由格式均可；LLM 只做结构化，不会重排你的行程",
    )
    c1, c2 = st.columns([1, 5])
    if c1.button("🔍 解析行程", type="primary", key="ii_parse_btn"):
        if not text.strip():
            ss.ii_error = "请先粘贴行程文本"
        else:
            try:
                with st.spinner("解析中（约 10-30 秒）..."):
                    ss.ii_days = ii.parse_itinerary_text(text)
                _reset_editor_state(ss)
            except ValueError as e:
                ss.ii_error = "解析失败：{}".format(e)
            except Exception:
                ss.ii_error = "解析失败：LLM 服务异常"
    if c2.button("清空行程", key="ii_clear_btn"):
        ss.ii_days = None
        _reset_editor_state(ss)
        st.rerun()

    # 出发城市（D1 路线起点；编辑装载时可能已预设）
    city_names = list(CITY_COORDS.keys())
    if "ii_origin" not in ss:
        ss.ii_origin = "武汉"
    origin = st.sidebar.selectbox(
        "出发城市", city_names,
        index=city_names.index(ss.ii_origin) if ss.ii_origin in city_names else 0,
        key="ii_origin_sel", help="第 1 天驾车路线从这里起算")
    origin_name = origin
    origin_coord = {"name": origin, "lng": CITY_COORDS[origin][0],
                    "lat": CITY_COORDS[origin][1]}

    if ss.ii_error:
        st.error(ss.ii_error)
    days = ss.ii_days
    if not days:
        st.caption("解析成功后这里会显示：定位统计 → 地图（每日路线）→ 逐日明细（可编辑）→ 保存")
        return

    pool = [s for s in (spots_with_coords or [])
            if s.get("lng") and s.get("lat")]

    st.success("解析出 {} 天 · 共 {} 个站点".format(
        len(days), sum(len(d.get("stops", [])) for d in days)))

    # ---- geocode (first run after parse, or loaded plan without coords) ----
    coords = ss.ii_coords
    if coords is None:
        if not web_key:
            ss.ii_error = "未配置 amap_web_key（app/.streamlit/secrets.toml），无法定位"
            st.error(ss.ii_error)
            return
        with st.spinner("定位站点坐标（年卡库→自定义→POI+地名守卫）..."):
            coords = ii.resolve_stop_coords(days, pool, web_key)
        ss.ii_coords = coords
        with st.spinner("计算每日驾车路线..."):
            days = ii.attach_day_routes(days, coords, origin_coord, web_key)
        ss.ii_days = days

    # ---- recompute routes after structural edits ----
    if ss.ii_dirty:
        if web_key:
            with st.spinner("行程有改动，重算驾车路线..."):
                days = ii.attach_day_routes(days, coords, origin_coord, web_key)
            ss.ii_days = days
            ss.ii_dirty = False
        else:
            st.warning("未配置 amap_web_key：结构改动已生效，但驾车路线暂不更新")

    n_unres = sum(1 for d in days for s in d.get("stops", []) if s.get("_unresolved"))
    m1, m2 = st.columns(2)
    m1.metric("已定位", "{} / {}".format(
        sum(len(d.get("stops", [])) for d in days) - n_unres,
        sum(len(d.get("stops", [])) for d in days)))
    m2.metric("未定位", n_unres)
    if n_unres:
        st.warning("有 {} 个站点未能定位（地图上跳过、文字仍保留）：{}".format(
            n_unres,
            "、".join(s["name"] for d in days for s in d.get("stops", [])
                      if s.get("_unresolved"))))

    # ---- map: per-day polylines switch with the day buttons ----
    st.markdown("#### 🗺️ 地图（按天切换：只亮当天的景点与红色路线）")
    map_spots = []
    day_routes = {}
    dp_days = []
    for d in days:
        day_spots = []
        for s in d.get("stops", []):
            c = coords.get(s["name"])
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
        dp_days.append({"day_num": d["day_num"], "city": d.get("hotel", ""),
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
        if route:
            head += " · {}km / {:.0f}min".format(route.get("km", 0),
                                                 route.get("min", 0))
        with st.expander(head):
            if d.get("transport"):
                st.caption("🚆 交通：" + d["transport"])
            if d.get("hotel"):
                st.caption("🏨 住宿：" + d["hotel"])
            stops = d.get("stops", [])
            for idx, s in enumerate(stops):
                if ss.ii_edit_open == (dn, idx):
                    # ---- inline edit form ----
                    st.markdown("　✏️ **编辑站点**")
                    ec1, ec2, ec3, ec4 = st.columns([2.2, 1, 1, 2.2])
                    e_name = ec1.text_input("名称", value=s.get("name", ""),
                                            key="imp_e_name_{}_{}".format(dn, idx))
                    e_arr = ec2.text_input("到达", value=s.get("arrive", "") or "",
                                           key="imp_e_arr_{}_{}".format(dn, idx),
                                           placeholder="09:30")
                    e_hrs = ec3.number_input("游玩h", value=float(s.get("hours") or 0),
                                             min_value=0.0, step=0.5,
                                             key="imp_e_hrs_{}_{}".format(dn, idx))
                    e_note = ec4.text_input("备注", value=s.get("note", "") or "",
                                            key="imp_e_note_{}_{}".format(dn, idx))
                    eb1, eb2, _sp = st.columns([1, 1, 4])
                    if eb1.button("✅ 保存修改", type="primary",
                                  key="imp_e_ok_{}_{}".format(dn, idx)):
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
                                        anchor=_anchor_for(days, coords, dn, idx))
                                if c:
                                    coords[new_name] = c
                                else:
                                    s["_unresolved"] = True
                            ss.ii_dirty = True
                        ss.ii_edit_open = None
                        st.rerun()
                    if eb2.button("取消", key="imp_e_cancel_{}_{}".format(dn, idx)):
                        ss.ii_edit_open = None
                        for k in ("imp_e_name_{}_{}".format(dn, idx),
                                  "imp_e_arr_{}_{}".format(dn, idx),
                                  "imp_e_hrs_{}_{}".format(dn, idx),
                                  "imp_e_note_{}_{}".format(dn, idx)):
                            ss.pop(k, None)
                        st.rerun()
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
                if rc[1].button("⬆️", key="imp_up_{}_{}".format(dn, idx),
                                help="上移", disabled=(idx == 0)):
                    stops[idx - 1], stops[idx] = stops[idx], stops[idx - 1]
                    ss.ii_dirty = True
                    st.rerun()
                if rc[2].button("⬇️", key="imp_dn_{}_{}".format(dn, idx),
                                help="下移", disabled=(idx == len(stops) - 1)):
                    stops[idx + 1], stops[idx] = stops[idx], stops[idx + 1]
                    ss.ii_dirty = True
                    st.rerun()
                if rc[3].button("✏️", key="imp_edit_{}_{}".format(dn, idx),
                                help="编辑站点"):
                    for k in ("imp_e_name_{}_{}".format(dn, idx),
                              "imp_e_arr_{}_{}".format(dn, idx),
                              "imp_e_hrs_{}_{}".format(dn, idx),
                              "imp_e_note_{}_{}".format(dn, idx)):
                        ss.pop(k, None)
                    ss.ii_edit_open = (dn, idx)
                    st.rerun()
                if rc[4].button("🗑", key="imp_del_{}_{}".format(dn, idx),
                                help="删除站点"):
                    stops.pop(idx)
                    ss.ii_dirty = True
                    st.rerun()
                other_days = [x.get("day_num") for x in days
                              if x.get("day_num") != dn]
                if other_days and rc[5].selectbox(
                        "移至", ["移至…"] + ["D{}".format(x) for x in other_days],
                        key="imp_mv_{}_{}".format(dn, idx),
                        label_visibility="collapsed",
                        on_change=_move_cb,
                        args=(dn, idx, "imp_mv_{}_{}".format(dn, idx))):
                    pass  # mutation happens in the on_change callback

            # ---- add stop ----
            if ss.ii_add_open == dn:
                st.markdown("　➕ **添加站点到 D{}**".format(dn))
                ac1, ac2, ac3, ac4 = st.columns([2.2, 1, 1, 2.2])
                a_name = ac1.text_input("景点/地点名", key="imp_a_name_{}".format(dn),
                                        placeholder="如：恩施大峡谷")
                a_arr = ac2.text_input("到达", key="imp_a_arr_{}".format(dn),
                                       placeholder="09:30")
                a_hrs = ac3.number_input("游玩h", value=2.0, min_value=0.0,
                                         step=0.5, key="imp_a_hrs_{}".format(dn))
                a_note = ac4.text_input("备注", key="imp_a_note_{}".format(dn))
                ab1, ab2, _sp2 = st.columns([1, 1, 4])
                if ab1.button("✅ 定位并添加", type="primary",
                              key="imp_a_ok_{}".format(dn)):
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
                                        anchor=_anchor_for(days, coords, dn,
                                                           len(stops)))
                                if c:
                                    coords[nm] = c
                                else:
                                    new_s["_unresolved"] = True
                        stops.append(new_s)
                        ss.ii_dirty = True
                        ss.ii_add_open = None
                        for k in ("imp_a_name_{}".format(dn),
                                  "imp_a_arr_{}".format(dn),
                                  "imp_a_hrs_{}".format(dn),
                                  "imp_a_note_{}".format(dn)):
                            ss.pop(k, None)
                        st.rerun()
                if ab2.button("取消", key="imp_a_cancel_{}".format(dn)):
                    ss.ii_add_open = None
                    for k in ("imp_a_name_{}".format(dn),
                              "imp_a_arr_{}".format(dn),
                              "imp_a_hrs_{}".format(dn),
                              "imp_a_note_{}".format(dn)):
                        ss.pop(k, None)
                    st.rerun()
            else:
                if st.button("➕ 添加站点", key="imp_add_{}".format(dn)):
                    ss.ii_add_open = dn
                    for k in ("imp_a_name_{}".format(dn),
                              "imp_a_arr_{}".format(dn),
                              "imp_a_hrs_{}".format(dn),
                              "imp_a_note_{}".format(dn)):
                        ss.pop(k, None)
                    st.rerun()

    # ---- save ----
    st.markdown("#### 💾 保存")
    name = st.text_input("行程名称",
                         value=ss.get("ii_edit_name") or "导入的行程",
                         key="ii_name")
    if ss.ii_edit_plan_id:
        sc1, sc2 = st.columns(2)
        if sc1.button("💾 覆盖保存原行程", type="primary", key="ii_save_overwrite"):
            pid = ii.save_imported_itinerary(
                days, name or "导入的行程", origin_name,
                coords=coords, plan_id=ss.ii_edit_plan_id)
            ss.ii_edit_name = name or "导入的行程"
            st.success("已覆盖保存（ID: {}，含坐标与路线）。「🧳 我的行程」→「保存的行程」可直接看地图".format(pid))
        if sc2.button("📄 另存为新行程", key="ii_save_as"):
            pid = ii.save_imported_itinerary(
                days, name or "导入的行程", origin_name, coords=coords)
            ss.ii_edit_plan_id = pid
            ss.ii_edit_name = name or "导入的行程"
            st.success("已另存为新行程（ID: {}）".format(pid))
    else:
        if st.button("💾 保存到我的行程", type="primary", key="ii_save_btn"):
            pid = ii.save_imported_itinerary(
                days, name or "导入的行程", origin_name, coords=coords)
            ss.ii_edit_plan_id = pid
            ss.ii_edit_name = name or "导入的行程"
            st.success("已保存（ID: {}，含坐标与路线）。到「🧳 我的行程」页，主区域底部「保存的行程 → 📥 导入的行程」查看（含地图）".format(pid))
