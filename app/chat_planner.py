"""Chat-based trip planner page (Streamlit UI layer).

Logic lives in src/trip_planner/chat_planner_core.py; this file only handles
chat UI + orchestration calls + rendering (incl. day-toggle map).
"""
from __future__ import annotations

import json
from datetime import date

import streamlit as st

from src.trip_planner.chat_planner_core import (
    parse_intent,
    resolve_holiday_dates,
    build_trip_from_intent,
    validate_intent_against_pool,
)
from src.trip_planner.amenity_planner import (
    find_city_hotel,
    plan_meals_for_day,
    find_parking_for_spot,
)
from src.trip_planner.plan_manager import save_plan


def render_chat_planner_page(spots_with_coords, graph_data, cleaned, departure_city_coords):
    """Main entry for the 💬 对话规划 page.

    Args:
        spots_with_coords: all unique spots with lng/lat
        graph_data: knowledge graph JSON
        cleaned: cleaned spot records
        departure_city_coords: {city_name: {lng, lat}} mapping
    """
    st.title("💬 对话式行程规划")
    st.caption("用一句话描述出行计划，例如：中秋+国庆+请假3天，准备出行10天，我有武汉惠游年票，从武汉出发走宜昌+恩施，帮我规划")

    # --- session state ---
    ss = st.session_state
    defaults = {
        "chat_messages": [],          # [{"role": "user"|"assistant", "content": str}]
        "chat_stage": "intake",       # intake → clarify → plan_ready
        "chat_intent": None,          # parsed intent dict
        "chat_trip": None,            # built trip (plan_multi_city result)
        "chat_hotels": [],
        "chat_restaurants": [],       # [{...lunch/dinner merged, day_num}]
        "chat_parkings": [],
        "clarify_rounds": 0,
        "clarify_pending": None,      # current critical field being asked
    }
    for k, v in defaults.items():
        if k not in ss:
            ss[k] = v

    # --- chat history ---
    for msg in ss.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # --- user input ---
    if prompt := st.chat_input("描述你的出行计划…"):
        ss.chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            _handle_user_message(
                prompt, ss, spots_with_coords, graph_data, cleaned,
                departure_city_coords,
            )

    # --- action buttons when plan is ready ---
    if ss.chat_stage == "plan_ready" and ss.chat_trip:
        _render_trip_result(ss, departure_city_coords)


def _handle_user_message(prompt, ss, spots_with_coords, graph_data, cleaned, city_coords):
    """State machine: intake → (clarify)×N → build plan."""
    secrets = st.secrets if hasattr(st, "secrets") else {}

    # If we're waiting for a clarify answer, merge it into intent
    if ss.chat_stage == "clarify" and ss.clarify_pending and ss.chat_intent:
        field, question = ss.clarify_pending
        merged = f"{json.dumps(ss.chat_intent, ensure_ascii=False)}\n补充信息：{prompt}"
        intent = parse_intent(merged, secrets) or ss.chat_intent
        intent.setdefault("num_days", None)
        ss.chat_intent = intent
        ss.clarify_pending = None
        missing = _critical_missing(intent)
        if missing:
            ss.clarify_rounds += 1
            if ss.clarify_rounds > 3:
                _finalize_intent_defaults(intent)
                _build_and_reply(intent, ss, spots_with_coords, graph_data, cleaned, city_coords)
                return
            ss.clarify_pending = (missing[0], _clarify_question(missing[0]))
            st.markdown(ss.clarify_pending[1])
            return
        _build_and_reply(intent, ss, spots_with_coords, graph_data, cleaned, city_coords)
        return

    # Fresh intake
    intent = parse_intent(prompt, secrets)
    if intent is None:
        st.markdown(
            "⚠️ LLM 服务不可用（未配置 `llm_api_base/llm_api_key/llm_model` 于 secrets）。"
            "请检查配置后重试，或使用 📝 行程规划 页手动规划。"
        )
        return

    ss.chat_intent = intent
    ss.clarify_rounds = 0

    missing = _critical_missing(intent)
    if missing:
        ss.chat_stage = "clarify"
        ss.clarify_pending = (missing[0], _clarify_question(missing[0]))
        st.markdown(ss.clarify_pending[1])
        return

    _build_and_reply(intent, ss, spots_with_coords, graph_data, cleaned, city_coords)


def _critical_missing(intent: dict) -> list[str]:
    missing = []
    for f in ("transport", "travel_style", "companions"):
        if not intent.get(f):
            missing.append(f)
    return missing


def _clarify_question(field: str) -> str:
    return {
        "transport": "🚗 出行方式是自驾还是公共交通？（自驾 / 高铁+当地交通）",
        "travel_style": "💰 预算偏好：经济型 / 舒适型 / 高档型？",
        "companions": "👨‍👩‍👧 同行人数？（如：2大1小 / 夫妻二人 / 单人）",
    }[field]


def _finalize_intent_defaults(intent: dict):
    intent.setdefault("transport", "drive")
    intent.setdefault("travel_style", "midrange")
    intent.setdefault("companions", "1人")


def _build_and_reply(intent, ss, spots_with_coords, graph_data, cleaned, city_coords):
    from src.trip_planner.smart_selector import import_pass_spots

    # 1. Resolve holiday dates → num_days
    holiday = resolve_holiday_dates(
        intent.get("holiday_phrase"), intent.get("leave_days")
    )
    if holiday and not intent.get("num_days"):
        intent["num_days"] = holiday["days"]
    if holiday:
        intent["_holiday_resolved"] = holiday
    if not intent.get("num_days"):
        intent["num_days"] = 3
        st.markdown("ℹ️ 未识别天数，默认按 3 天规划。")

    # travel month from resolved dates (for seasonal filter)
    if holiday:
        intent["_travel_month"] = date.fromisoformat(holiday["start"]).month
    else:
        intent["_travel_month"] = date.today().month

    # 2. Pass spots pool (deterministic closed-set resolution, not LLM)
    from src.trip_planner.chat_planner_core import resolve_pass_name
    pass_canon = resolve_pass_name(intent.get("pass_name"))
    pool = []
    if pass_canon:
        pool = import_pass_spots(pass_canon, graph_data, cleaned)
    if not pool:
        pool = spots_with_coords
        st.markdown(
            f"ℹ️ 未识别年卡「{intent.get('pass_name') or ''}」，使用全部景点库。"
        )
    else:
        st.markdown(f"🎫 已识别年卡：**{pass_canon}**（{len(pool)} 个景点）")

    # 3. Validate city coverage
    warnings = validate_intent_against_pool(intent, pool)
    for w in warnings:
        st.markdown(f"⚠️ {w}")

    # 4. Departure coord
    dep_city = intent.get("departure_city") or "武汉"
    dep = city_coords.get(dep_city) or {"name": dep_city, "lng": 114.30, "lat": 30.59}

    # 5. Build (coords from spot_coordinates.json — import_pass_spots lacks them)
    # NOTE: app/chat_planner.py → parent.parent = project root; dirname×3 lands
    # ABOVE the root and silently yields coords={} → pool loses all coordinates
    # → plan_multi_city assigns 0 days (found via headless UI smoke).
    import os
    coords_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "spot_coordinates.json",
    )
    coords = {}
    try:
        with open(coords_path, encoding="utf-8") as f:
            coords = json.load(f)
    except Exception:
        pass
    trip = build_trip_from_intent(intent, pool, dep, coords=coords, all_spots=spots_with_coords)
    ss.chat_trip = trip
    ss.chat_stage = "plan_ready"

    # 6. Reply with summary
    meta = trip["intent_meta"]
    lines = ["✅ 行程已生成！", ""]
    if meta.get("uncovered_cities"):
        lines.append(
            f"⚠️ 年卡不覆盖「{'、'.join(meta['uncovered_cities'])}」，"
            f"已从全库选取该城景点（需自费购票）。"
        )
    if holiday:
        lines.append(f"📅 **{holiday['note']}**")
    lines.append(f"🏠 出发：{meta['departure_city']} → {' → '.join(trip['city_order'])}")
    lines.append(f"🗓 共 {len(trip['days'])} 天，{sum(len(d['spots']) for d in trip['days'])} 个景点")
    if trip.get("seasonal_warnings"):
        lines.append(f"⚠️ {len(trip['seasonal_warnings'])} 个景点当季不可玩，已自动排除")
    lines.append("")
    lines.append("下方可查看行程详情与地图 👇")
    st.markdown("\n".join(lines))


def _render_trip_result(ss, city_coords):
    trip = ss.chat_trip
    from src.trip_planner.cost_estimator import estimate_trip_cost
    from src.trip_planner.pass_coverage import compute_pass_coverage

    # --- Day-by-day overview ---
    with st.expander("📅 每日行程", expanded=True):
        for d in trip["days"]:
            tag = " 🚗转场" if d.get("is_transfer_day") else ""
            st.markdown(f"**D{d['day_num']} · {d['city']}**{tag}（{d['play_hours']}h / {d['travel_km']}km）")
            names = " → ".join(s["name"] for s in d["spots"])
            st.markdown(f"　{names or '（空闲日，可用于休整）'}")

    # --- Amenities (hotel/meal/parking) ---
    with st.expander("🏨 酒店与餐饮（生成中需调用高德 API）"):
        if st.button("生成酒店/餐厅/停车场方案", key="chat_gen_amenities"):
            _generate_amenities(ss)

        if ss.chat_trip and ss.chat_trip.get("amenities"):
            am = ss.chat_trip["amenities"]
            st.markdown("**酒店（城市连住）**")
            for h in am.get("hotels", []):
                st.markdown(f"- 🏨 {h['name']}（{h.get('city','')}，{h.get('nights',0)} 晚）— {h.get('selection_reason','')}")
            st.markdown("**每日餐饮**")
            for m in am.get("meals", []):
                lunch = (m.get("lunch") or {}).get("name", "—")
                dinner = (m.get("dinner") or {}).get("name", "—")
                st.markdown(f"- D{m['day_num']}：午餐 {lunch} · 晚餐 {dinner}")
            st.markdown("**停车场（自驾）**")
            for p in am.get("parkings", []):
                st.markdown(f"- {p.get('spot_name','')} → 🅿️ {p['name']}（{p['distance']}m）")

    # --- Map ---
    with st.expander("🗺️ 行程地图（按天切换）", expanded=True):
        web_key = st.secrets.get("amap_web_key", "") if hasattr(st, "secrets") else ""
        if st.button("渲染行程地图", key="chat_gen_map"):
            _render_map(ss)

        if ss.chat_trip and ss.chat_trip.get("map_url"):
            st.components.v1.html(
                open(ss.chat_trip["map_url"], encoding="utf-8").read(),
                height=620,
            )

    # --- Cost & save ---
    col1, col2 = st.columns(2)
    with col1:
        if st.button("💰 估算费用", key="chat_est_cost"):
            trip_km = sum(d.get("travel_km", 0) for d in trip["days"])
            ticket = sum(float(s.get("price", 0)) for d in trip["days"] for s in d["spots"])
            style = trip["intent_meta"].get("travel_style", "midrange")
            cost = estimate_trip_cost(trip_km, len(trip["days"]), ticket, 0, style)
            ss.chat_trip["cost_estimate"] = cost
            st.rerun()
    with col2:
        if st.button("💾 保存到我的行程", key="chat_save_plan", type="primary"):
            plan_data = {
                "name": f"对话规划·{trip['intent_meta'].get('departure_city','')}→{'-'.join(trip['city_order'])}",
                "trip_type": "chat_planner_v1",
                "cart": [s for d in trip["days"] for s in d["spots"]],
                "assignment": {"days": trip["days"]},
                "city_order": trip["city_order"],
                "intent_meta": trip["intent_meta"],
                "departure_city": trip["intent_meta"].get("departure_city", "武汉"),
                "num_days": len(trip["days"]),
                "travel_month": trip["intent_meta"].get("_travel_month", 10),
                "total_spots": sum(len(d["spots"]) for d in trip["days"]),
            }
            plan_id = save_plan(plan_data)
            st.success(f"已保存！行程 ID: {plan_id}（可在 🧳 我的行程 查看/导入到行程规划页精调）")


def _generate_amenities(ss):
    import time
    trip = ss.chat_trip
    web_key = st.secrets.get("amap_web_key", "") if hasattr(st, "secrets") else ""
    if not web_key:
        st.error("未配置 amap_web_key，无法搜索 POI。")
        return
    style = trip["intent_meta"].get("travel_style", "midrange")
    transport = trip["intent_meta"].get("transport", "drive")

    hotels, meals, parkings = [], [], []
    with st.spinner("搜索酒店/餐厅/停车场…"):
        # hotels: one per city block
        city_blocks = {}
        for d in trip["days"]:
            city_blocks.setdefault(d["city"], []).append(d)
        for city, days in city_blocks.items():
            city_spots = [s for d in days for s in d["spots"]]
            if not city_spots:
                continue
            h = find_city_hotel(city, city_spots, web_key, travel_style=style)
            if h:
                h["nights"] = len(days) - 1 or 1
                h["day_num"] = days[0]["day_num"]
                hotels.append(h)

        # meals per day
        hotel_by_day = {}
        for h in hotels:
            for d in trip["days"]:
                if d["city"] == h["city"]:
                    hotel_by_day[d["day_num"]] = h
        for d in trip["days"]:
            m = plan_meals_for_day(d, hotel_by_day.get(d["day_num"]), web_key)
            m["day_num"] = d["day_num"]
            meals.append(m)

        # parking per spot (drive only)
        if transport == "drive":
            for d in trip["days"]:
                for s in d["spots"]:
                    p = find_parking_for_spot(s, web_key)
                    if p:
                        p["day_num"] = d["day_num"]
                        p["spot_name"] = s["name"]
                        parkings.append(p)

    ss.chat_trip["amenities"] = {"hotels": hotels, "meals": meals, "parkings": parkings}
    st.rerun()


def _render_map(ss):
    """Build day-toggle map HTML via _build_trip_map_html and stash URL."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.main import _build_trip_map_html, _save_map_html

    trip = ss.chat_trip
    all_spots = [s for d in trip["days"] for s in d["spots"]]
    # enrich spots with coords (spots in days already carry lng/lat via pool)
    am = trip.get("amenities") or {}
    hotels = [{**h, "day_num": h.get("day_num", 0)} for h in am.get("hotels", [])]
    restaurants = []
    for m in am.get("meals", []):
        for meal_key in ("lunch", "dinner"):
            if m.get(meal_key):
                restaurants.append({**m[meal_key], "day_num": m["day_num"]})
    parkings = am.get("parkings", [])

    html = _build_trip_map_html(
        selected_spots=all_spots,
        route_polyline="",
        hotels=hotels,
        restaurants=restaurants,
        parkings=parkings,
        day_plan={"days": trip["days"]},
    )
    ss.chat_trip["map_url"] = _save_map_html(html)
    st.rerun()
