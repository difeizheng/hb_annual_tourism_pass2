# -*- coding: utf-8 -*-
"""🚗 周末出发 — extracted VERBATIM from app/main.py.

render(ctx) injects main.py's namespace via globals().update(ctx); the
moved block is unchanged to keep behavior identical. Do NOT import
app.main here (Streamlit re-execution trap).
"""


def render_weekend_page(ctx):
    globals().update(ctx)
    st.title("周末出发")
    st.caption("选出发城市 → 选风格 → 一键生成行程")

    # Preset cards
    presets_w = {
        "武汉周末自驾": {"city": "武汉", "days": 2, "style": "休闲", "label": "武汉 · 2天 · 休闲自驾"},
        "武汉亲子1天": {"city": "武汉", "days": 1, "style": "亲子", "label": "武汉 · 1天 · 亲子游"},
        "武汉户外探险": {"city": "武汉", "days": 2, "style": "户外", "label": "武汉 · 2天 · 户外探险"},
        "武汉文化之旅": {"city": "武汉", "days": 1, "style": "文化", "label": "武汉 · 1天 · 文化之旅"},
        "宜昌周边游": {"city": "宜昌", "days": 1, "style": "户外", "label": "宜昌 · 1天 · 山水户外"},
        "襄阳文化游": {"city": "襄阳", "days": 2, "style": "文化", "label": "襄阳 · 2天 · 三国文化"},
    }

    st.markdown("#### 热门路线")
    preset_cols = st.columns(6)
    for idx, (pk, pv) in enumerate(presets_w.items()):
        with preset_cols[idx]:
            if st.button(pv["label"], key=f"wpreset_{pk}", use_container_width=True, type="primary"):
                st.session_state.weekend_preset = pk
                st.session_state.weekend_dep = pv["city"]
                st.session_state.weekend_days = pv["days"]
                st.session_state.weekend_style = pv["style"]
                st.session_state.weekend_month = 1  # will update from sidebar
                st.session_state.weekend_needs_gen = True

    # Controls
    all_dep_cities = sorted(set(s["city"] for s in spots_with_coords if s["city"]))
    default_dep = st.session_state.get("weekend_dep", "武汉")
    default_days = st.session_state.get("weekend_days", 2)
    default_style = st.session_state.get("weekend_style", "休闲")

    st.markdown("##### 🏠 家的位置")
    home_addr = st.text_input(
        "详细地址（可选）",
        value=st.session_state.get("weekend_home_addr", ""),
        placeholder="如：武汉市洪山区光谷广场，留空使用城市中心",
    )
    home_status = st.session_state.get("weekend_home_coord", None)
    home_coord_display = ""
    if home_status:
        home_coord_display = f"📌 {home_status['formatted_address']} ({home_status['lng']:.4f}, {home_status['lat']:.4f})"

    home_input_row = st.columns([2, 1])
    with home_input_row[0]:
        dep_city = st.selectbox("出发城市", all_dep_cities,
                                index=all_dep_cities.index(default_dep) if default_dep in all_dep_cities else 0)
    with home_input_row[1]:
        web_key_for_geo = st.secrets.get("amap_web_key", "")
        if st.button("📍 定位地址", type="secondary", use_container_width=True):
            if home_addr and web_key_for_geo:
                result = geocode_address(home_addr, web_key_for_geo, city=dep_city)
                if result:
                    st.session_state.weekend_home_coord = result
                    st.rerun()
                else:
                    st.error("未找到该地址，请检查输入")
            elif not home_addr:
                st.warning("请先输入地址")
            else:
                st.warning("请配置高德地图 API Key")

    if home_coord_display:
        st.success(home_coord_display)

    # Trip params
    params_row = st.columns(3)
    with params_row[0]:
        num_days = st.radio("天数", [1, 2], horizontal=True, index=1 if default_days == 2 else 0)
    with params_row[1]:
        style = st.selectbox("风格", ["休闲", "户外", "亲子", "文化"],
                             index=["休闲", "户外", "亲子", "文化"].index(default_style))
    with params_row[2]:
        travel_month_w = st.selectbox("月份", list(range(1, 13)), index=0)

    gen_clicked = st.button("生成行程", type="primary", use_container_width=True)
    needs_gen = gen_clicked or st.session_state.get("weekend_needs_gen", False)
    st.session_state.weekend_needs_gen = False

    if needs_gen:
        # Use geocoded coordinates if available, fallback to city center
        geocoded = st.session_state.get("weekend_home_coord", None)
        if geocoded:
            home = {"name": geocoded["formatted_address"], "lng": geocoded["lng"], "lat": geocoded["lat"]}
        else:
            dep_coord = CITY_COORDS.get(dep_city, [114.305, 30.593])
            home = {"name": dep_city, "lng": dep_coord[0], "lat": dep_coord[1]}
        pi_wk = build_pass_info(graph_data, cleaned)

        with st.spinner("正在规划行程..."):
            weekend_plan = plan_weekend(
                spots=spots_with_coords,
                pass_info=pi_wk,
                home=home,
                num_days=num_days,
                travel_month=travel_month_w,
                style=style,
                owned_pass_id=_owned_pass if _owned_pass != "无" else None,
            )
            st.session_state.weekend_plan = weekend_plan
            st.session_state.weekend_home = home
            st.session_state.weekend_dep_city = dep_city
            st.session_state.weekend_home_addr = home_addr

    # Display saved plan
    if st.session_state.get("weekend_plan"):
        plan = st.session_state.weekend_plan
        home = st.session_state.weekend_home

        if not plan.get("days"):
            st.info("当前季节和风格下暂无推荐行程")
            st.stop()

        all_plan_spots = [s for d in plan["days"] for s in d["spots"]]
        total_km = sum(d["travel_km"] for d in plan["days"])
        total_hours = sum(d["play_hours"] for d in plan["days"])
        home_return = plan["budget"].get("home_return_km", 0)

        # Summary row
        s1, s2, s3, s4, s5 = st.columns(5)
        s1.metric("景点数", len(all_plan_spots))
        s2.metric("游览时长", f"{total_hours:.1f}h")
        s3.metric("游览里程", f"{total_km:.0f}km")
        s4.metric("回家里程", f"{home_return:.0f}km")
        s5.metric("油费+过路费", f"¥{plan['budget'].get('driving_cost', 0):,.0f}")

        st.divider()

        # Seasonal tips
        st.info(f"💡 {plan['seasonal_tips']}")

        # Budget breakdown with progress bar
        st.subheader("预算分解")
        bud = plan["budget"]
        total_budget = bud.get("grand_total_no_pass", 0)
        components = [
            ("门票", bud.get("no_pass_total", 0)),
            ("油费+过路费", bud.get("driving_cost", 0)),
            ("餐饮", bud.get("food_cost", 0)),
            ("住宿", bud.get("accommodation", 0)),
        ]
        if total_budget > 0:
            progress_parts = []
            for label, amount in components:
                pct = round(amount / total_budget * 100, 1) if total_budget > 0 else 0
                if amount > 0:
                    progress_parts.append(f"{label} ¥{amount:,.0f} ({pct}%)")
            st.caption(" | ".join(progress_parts))
            st.caption(f"**总计**: ¥{total_budget:,.0f}（自驾+门票+餐饮+住宿）")

        # Recommended pass
        if bud.get("best_pass_display"):
            st.divider()
            with st.container(border=True):
                st.markdown(f"### 🎫 推荐年卡: **{bud['best_pass_display']}**")
                st.caption(f"覆盖行程中 {plan['budget'].get('best_pass_savings', 0):.0f} 元门票价值")
                b1, b2, b3 = st.columns(3)
                b1.metric("自费总价", f"¥{bud.get('grand_total_no_pass', 0):,.0f}")
                b2.metric("用年卡总价", f"¥{bud.get('grand_total_with_pass', 0):,.0f}")
                b3.metric("节省金额", f"¥{bud.get('best_pass_savings', 0):,.0f}")

        # Day cards with timeline + map + POI
        st.divider()
        web_key_map = st.secrets.get("amap_web_key", "")

        for day in plan["days"]:
            day_spots_list = day["spots"]
            drive_h = day.get("drive_min", 0) / 60
            drive_label = f" · 驾车{day['drive_min']:.0f}min({drive_h:.1f}h)" if day.get("drive_min") else ""
            return_label = f" · 返家{day.get('return_drive_min', 0):.0f}min({day.get('return_km', 0):.0f}km)" if day.get("is_final_day") else ""
            hotel_label = " · 入住酒店" if day.get("is_overnight") else ""
            with st.expander(f"📅 Day {day['day_num']} · {day['play_hours']}h 游览 · {day['travel_km']:.0f}km{drive_label}{hotel_label}{return_label}", expanded=True):
                # Fetch POI: restaurants + hotels
                day_restaurants = st.session_state.get(f"_wk_rest_{day['day_num']}", None)
                day_hotels = st.session_state.get(f"_wk_hot_{day['day_num']}", None)

                if day_restaurants is None and web_key_map:
                    # Fetch restaurants near midday spot (lunch) and last spot (dinner)
                    lunch_restaurants = []
                    dinner_restaurants = []
                    n = len(day_spots_list)
                    if n > 0:
                        mid = day_spots_list[n // 2]
                        last = day_spots_list[-1]
                        if mid.get("lng") and mid.get("lat"):
                            from src.trip_planner.nearby_search import search_nearby_restaurants as _sr
                            lunch_restaurants = _sr(mid["lng"], mid["lat"], web_key_map, radius=2000, max_results=5)
                        if last.get("lng") and last.get("lat"):
                            from src.trip_planner.nearby_search import search_nearby_restaurants as _sr
                            dinner_restaurants = _sr(last["lng"], last["lat"], web_key_map, radius=2000, max_results=5)
                    # Dedup
                    seen_r = set()
                    all_lunch = []
                    for r in lunch_restaurants:
                        if r["name"] not in seen_r:
                            seen_r.add(r["name"])
                            all_lunch.append(r)
                    seen_d = set()
                    all_dinner = []
                    for r in dinner_restaurants:
                        if r["name"] not in seen_d:
                            seen_d.add(r["name"])
                            all_dinner.append(r)
                    st.session_state[f"_wk_rest_{day['day_num']}"] = {"lunch": all_lunch, "dinner": all_dinner}
                    day_restaurants = {"lunch": all_lunch, "dinner": all_dinner}

                if day_hotels is None and web_key_map and day.get("is_overnight"):
                    from src.trip_planner.nearby_search import search_nearby_hotels as _sh
                    last_spot = day_spots_list[-1]
                    if last_spot.get("lng") and last_spot.get("lat"):
                        raw_hotels = _sh(last_spot["lng"], last_spot["lat"], web_key_map, radius=3000, max_results=8)
                        seen_h = set()
                        unique_hotels = []
                        for h in raw_hotels:
                            if h["name"] not in seen_h:
                                seen_h.add(h["name"])
                                unique_hotels.append(h)
                        st.session_state[f"_wk_hot_{day['day_num']}"] = unique_hotels
                        day_hotels = unique_hotels

                # Time timeline with actual driving times
                timeline = _build_weekend_timeline(day_spots_list, start_hour=9, start_min=0)
                st.markdown("**时间安排**")
                for slot in timeline.get("slots", []):
                    is_lunch = slot.get("spot_name") == "午餐"
                    if is_lunch:
                        st.markdown(f"🍽️ **{slot['start']} - {slot['end']}** 午餐休息")
                    else:
                        play_h = slot.get("play_hours", 0)
                        drive = slot.get("drive_min", 0)
                        drive_str = f" | 驾车{drive:.0f}min" if drive > 0 else ""
                        st.markdown(f"**{slot['start']} - {slot['end']}** {slot['spot_name']}（{play_h}h{drive_str}）")

                if timeline.get("end_time"):
                    st.caption(f"预计结束: {timeline['end_time']}")
                    if timeline.get("warnings"):
                        for w in timeline["warnings"]:
                            st.warning(w)

                st.divider()

                # Restaurant recommendations
                if day_restaurants:
                    st.markdown("##### 🍴 周边美食推荐")
                    # Lunch
                    if day_restaurants.get("lunch"):
                        st.markdown("**午餐推荐**（距中午景点约 1-2km）")
                        lunch_cols = st.columns(min(len(day_restaurants["lunch"]), 3))
                        for ri, rest in enumerate(day_restaurants["lunch"][:3]):
                            with lunch_cols[ri]:
                                with st.container(border=True):
                                    st.markdown(f"**{rest['name']}**")
                                    if rest.get("address"):
                                        st.caption(f"📍 {rest['address']}")
                                    if rest.get("distance"):
                                        st.caption(f"距离: {rest['distance']}m")

                    # Dinner
                    if day_restaurants.get("dinner"):
                        st.markdown("**晚餐推荐**（距最后一站约 1-2km）")
                        dinner_cols = st.columns(min(len(day_restaurants["dinner"]), 3))
                        for ri, rest in enumerate(day_restaurants["dinner"][:3]):
                            with dinner_cols[ri]:
                                with st.container(border=True):
                                    st.markdown(f"**{rest['name']}**")
                                    if rest.get("address"):
                                        st.caption(f"📍 {rest['address']}")
                                    if rest.get("distance"):
                                        st.caption(f"距离: {rest['distance']}m")

                    st.divider()

                # Hotel recommendations (for overnight days)
                if day_hotels and day.get("is_overnight"):
                    st.markdown("##### 🏨 住宿推荐（当晚入住）")
                    hotel_cols = st.columns(min(len(day_hotels), 4))
                    for hi, hotel in enumerate(day_hotels[:4]):
                        with hotel_cols[hi]:
                            with st.container(border=True):
                                st.markdown(f"**{hotel['name']}**")
                                if hotel.get("address"):
                                    st.caption(f"📍 {hotel['address']}")
                                if hotel.get("distance"):
                                    st.caption(f"距离: {hotel['distance']}m")

                    st.divider()

                # Return home (for final day)
                if day.get("is_final_day"):
                    return_km = day.get("return_km", 0)
                    return_drive = day.get("return_drive_min", 0)
                    with st.container(border=True):
                        st.markdown(f"🏠 **返程回家** → 距离 {return_km:.0f}km · 驾车约 {return_drive:.0f}min")

                st.divider()

                # Map with route
                valid_day_spots = [s for s in day_spots_list if s.get("lng") and s.get("lat")]
                if valid_day_spots and web_key_map:
                    try:
                        with st.spinner("生成路线图..."):
                            from src.trip_planner.route_optimizer import generate_route_options as gen_route
                            dep_for_day = home
                            route_options = gen_route(dep_for_day, valid_day_spots, web_key_map)
                            if route_options:
                                best_route = route_options[0]  # shortest distance
                                ordered_spots_for_map = best_route.get("ordered_spots", valid_day_spots)
                                # Build POI lists for map
                                map_hotels = day_hotels[:3] if day_hotels else []
                                map_restaurants = []
                                if day_restaurants:
                                    map_restaurants = (day_restaurants.get("lunch", [])[:2] +
                                                       day_restaurants.get("dinner", [])[:2])
                                trip_map_html = _build_trip_map_html(
                                    selected_spots=ordered_spots_for_map,
                                    route_polyline=best_route.get("ordered_polyline", ""),
                                    hotels=map_hotels if map_hotels else None,
                                    restaurants=map_restaurants if map_restaurants else None,
                                    height="450px",
                                )
                                trip_map_url = _save_map_html(trip_map_html)
                                st.components.v1.iframe(trip_map_url, height=460, width=None)

                                st.caption(f"路线: {best_route.get('name', '')}")
                                st.caption(f"总距离: {best_route.get('total_distance_km', 0):.1f}km · 驾驶: {best_route.get('total_duration_min', 0)}min")
                    except Exception:
                        # Fallback: show without route
                        trip_map_html = _build_trip_map_html(
                            selected_spots=valid_day_spots,
                            route_polyline="",
                            height="450px",
                        )
                        trip_map_url = _save_map_html(trip_map_html)
                        st.components.v1.iframe(trip_map_url, height=460, width=None)
                elif valid_day_spots:
                    trip_map_html = _build_trip_map_html(
                        selected_spots=valid_day_spots,
                        route_polyline="",
                        height="450px",
                    )
                    trip_map_url = _save_map_html(trip_map_html)
                    st.components.v1.iframe(trip_map_url, height=460, width=None)

                st.divider()

                # Spot details
                for i, spot in enumerate(day_spots_list, 1):
                    with st.container(border=True):
                        c_name, c_info, c_price = st.columns([4, 2, 1])
                        level = spot.get("level", "")
                        c_name.markdown(f"**{i}. {spot['name']}**{' `[5A]`' if level == 'A5' else '`[4A]`' if level == 'A4' else ''}")
                        c_info.caption(f"{spot['city']} · {spot['category']}")
                        c_info.caption(f"📌 {spot.get('_reason', '')}")
                        c_price.metric("", f"¥{spot['price']}")

        # Highlights
        if plan.get("highlights"):
            st.divider()
            st.subheader("行程亮点")
            hcols = st.columns(min(len(plan["highlights"]), 3))
            for i, h in enumerate(plan["highlights"]):
                with hcols[i % 3]:
                    with st.container(border=True):
                        st.markdown(f"**{h['name']}**")
                        st.caption(f"{h['city']} · {h['category']}")
                        st.caption(f"¥{h['price']} · {h['play_hours']}h")
                        st.caption(f"📌 {h['reason']}")

        # Add to trip button
        st.divider()
        if st.button("➕ 添加到我的行程", type="secondary", use_container_width=True):
            existing = {s["name"] for s in st.session_state.selected_trip_spots}
            added = 0
            for spot in all_plan_spots:
                if spot["name"] not in existing:
                    st.session_state.selected_trip_spots.append({
                        "name": spot["name"],
                        "lng": spot.get("lng"),
                        "lat": spot.get("lat"),
                        "city": spot["city"],
                        "area": "",
                        "category": spot["category"],
                        "price": spot["price"],
                        "level": spot.get("level", ""),
                        "passes": [],
                    })
                    added += 1
            st.toast(f"已添加 {added} 个景点到行程", icon="✅")

        # Save as unified plan (含坐标/预算，可直接在我的行程编辑)
        st.divider()
        wsc1, wsc2 = st.columns([2, 1])
        with wsc1:
            wk_save_name = st.text_input(
                "行程名称",
                value=f"周末出发·{'-'.join(sorted({s['city'] for d in plan['days'] for s in d['spots']}))}",
                key="wk_save_name")
        with wsc2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("💾 保存到我的行程", key="wk_save_btn", type="primary"):
                save_days = []
                for d in plan["days"]:
                    save_days.append({
                        "day_num": d["day_num"],
                        "travel_km": d.get("travel_km", 0),
                        "play_hours": d.get("play_hours", 0),
                        "stops": [{**s, "note": s.get("_reason", "")}
                                  for s in d.get("spots", [])],
                    })
                _wk_coord = st.session_state.get("weekend_home_coord")
                if _wk_coord:
                    _wk_lng, _wk_lat = _wk_coord["lng"], _wk_coord["lat"]
                else:
                    _wk_lng, _wk_lat = CITY_COORDS.get(dep_city, [114.305, 30.593])
                pid = save_days_plan(
                    save_days, wk_save_name, "weekend",
                    origin_city=home_addr or dep_city,
                    origin_lng=_wk_lng, origin_lat=_wk_lat,
                    travel_month=travel_month_w,
                    meta={"budget": plan.get("budget"),
                          "highlights": plan.get("highlights"),
                          "seasonal_tips": plan.get("seasonal_tips"),
                          "style": style, "home_address": home_addr})
                st.success(f"已保存（ID: {pid}）。到「🧳 我的行程」查看/编辑")
