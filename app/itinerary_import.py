# -*- coding: utf-8 -*-
'''📥 行程导入 — paste a multi-day itinerary, structure it, map it, EDIT it.

Boundary: the LLM ONLY parses pasted text into structured days (no
reordering, no invented stops, no re-timing). Geocoding and per-day driving
routes reuse the deterministic importer pipeline.

The map + editor + save block lives in the shared component
app/plan_editor.py (also used by the planning hub's ✏️ 编辑器 mode).
'''

import streamlit as st

import src.trip_planner.itinerary_importer as ii
from app.map_html import CITY_COORDS
from app.plan_editor import render_plan_editor, init_editor_state, reset_editor_state

_SAMPLE = """第1天：武汉出发，前往宜昌，游览三峡大瀑布，宿宜昌
第2天：两坝一峡游船（需提前预约），宿宜昌
第3天：上午恩施大峡谷（带雨衣），下午休整，宿利川"""


def render_itinerary_import_page(spots_with_coords, graph_data, cleaned):
    ss = st.session_state
    ss.setdefault("ii_days", None)
    ss.setdefault("ii_coords", None)
    ss.setdefault("ii_error", "")
    init_editor_state(ss, "ii")

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
                reset_editor_state(ss, "ii")
            except ValueError as e:
                ss.ii_error = "解析失败：{}".format(e)
            except Exception:
                ss.ii_error = "解析失败：LLM 服务异常"
    if c2.button("清空行程", key="ii_clear_btn"):
        ss.ii_days = None
        reset_editor_state(ss, "ii")
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

    # ---- shared editor: map + per-day editing + unified save ----
    render_plan_editor(
        days_key="ii_days", coords_key="ii_coords",
        pool=pool, web_key=web_key,
        origin_name=origin_name, origin_coord=origin_coord,
        state_prefix="ii", widget_prefix="imp",
        source="import", default_name="导入的行程")
