# -*- coding: utf-8 -*-
"""📝 表单规划（原「行程规划」页） — extracted VERBATIM from app/main.py.

render(ctx) injects main.py's namespace via globals().update(ctx); the
moved block is unchanged to keep behavior identical. Do NOT import
app.main here (Streamlit re-execution trap).
"""


def render_trip_planner_page(ctx):
    globals().update(ctx)
    st.title("行程规划")

    # --- Initialize session state ---
    if "tp_cart" not in st.session_state:
        st.session_state.tp_cart = []
    if "tp_assignment" not in st.session_state:
        st.session_state.tp_assignment = None
    if "tp_route_options" not in st.session_state:
        st.session_state.tp_route_options = []
    if "tp_selected_route" not in st.session_state:
        st.session_state.tp_selected_route = 0
    if "tp_travel_month" not in st.session_state:
        st.session_state.tp_travel_month = 6
    if "tp_departure_city" not in st.session_state:
        st.session_state.tp_departure_city = "武汉"
    if "tp_num_days" not in st.session_state:
        st.session_state.tp_num_days = 3

    # --- Tab navigation ---
    tab1, tab2, tab3, tab4 = st.tabs(["智能选景", "行程编排", "路线优化", "行程总览"])

    st.caption("💾 保存的行程统一在「🧳 我的行程」查看与编辑（✏️ 可进编辑器修改）")
    # ============================================================
    # Tab 1: 智能选景
    # ============================================================
    with tab1:
        st.subheader("快速导入年卡景点")

        passes_info = get_all_passes_info(graph_data)
        if passes_info:
            c1, c2, c3 = st.columns([3, 1, 1])
            with c1:
                selected_pass_name = st.selectbox(
                    "选择年卡",
                    [p["name"] for p in passes_info],
                    label_visibility="collapsed",
                    format_func=_pass_display_name,
                )
            with c2:
                pass_data = next((p for p in passes_info if p["name"] == selected_pass_name), None)
                if pass_data:
                    st.metric("景点数", pass_data["spot_count"])
                    st.metric("性价比", pass_data["value_ratio"])
            with c3:
                if st.button("一键导入", type="primary", width="stretch"):
                    imported = import_pass_spots(selected_pass_name, graph_data, cleaned)
                    if imported:
                        st.session_state.tp_cart = imported
                        st.rerun()

        st.divider()
        st.subheader("季节性推荐")

        month = st.slider("出行月份", 1, 12, st.session_state.tp_travel_month)
        st.session_state.tp_travel_month = month

        persona = st.radio(
            "游玩偏好",
            ["family", "adventure", "culture", "relax"],
            format_func=lambda x: PERSONA_PROFILES[x]["label"],
            horizontal=True,
        )

        persona_recs = get_persona_recommendations(persona, month, spots_with_coords)
        if persona_recs:
            top = persona_recs[:12]
            cols = st.columns(4)
            for idx, (spot, score, reason, _bonus) in enumerate(top):
                with cols[idx % 4]:
                    with st.container(border=True):
                        st.caption(spot.get("name", "")[:12])
                        st.caption(f"{spot.get('city', '')} · ¥{spot.get('price', 0)}")
                        emoji = "✅" if score >= 4 else "⚠️" if score >= 2 else "❌"
                        st.caption(f"{emoji} 季节分 {score}")
                        if st.button("加入行程", key=f"rec_add_{idx}"):
                            entry = {
                                "name": spot.get("name", ""),
                                "city": spot.get("city", ""),
                                "category": spot.get("category", ""),
                                "sub_category": spot.get("_classification", {}).get("sub_category", ""),
                                "level": spot.get("level", ""),
                                "price": spot.get("price", 0),
                                "lng": spot.get("lng"),
                                "lat": spot.get("lat"),
                                "tags": spot.get("tags", []),
                            }
                            names = [s["name"] for s in st.session_state.tp_cart]
                            if entry["name"] not in names:
                                st.session_state.tp_cart.append(entry)
                            st.rerun()

        st.divider()
        st.subheader("手动选择")

        search_text = st.text_input("搜索景点名称或城市", placeholder="输入关键词...")
        filtered_manual = spots_with_coords
        if search_text:
            filtered_manual = [
                s for s in spots_with_coords
                if search_text in s.get("name", "") or search_text in s.get("city", "")
            ]

        if filtered_manual:
            with st.expander(f"点击展开选择（{len(filtered_manual)}个结果）"):
                manual_options = [f"{s['city']} - {s['name']}" for s in filtered_manual]
                manual_map = {f"{s['city']} - {s['name']}": s for s in filtered_manual}
                picked_manual = st.multiselect(
                    "选择景点",
                    manual_options,
                    label_visibility="collapsed",
                )
                if picked_manual and st.button("添加到行程"):
                    for key in picked_manual:
                        s = manual_map[key]
                        entry = {
                            "name": s.get("name", ""),
                            "city": s.get("city", ""),
                            "category": s.get("category", ""),
                            "sub_category": s.get("_classification", {}).get("sub_category", ""),
                            "level": s.get("level", ""),
                            "price": s.get("price", 0),
                            "lng": s.get("lng"),
                            "lat": s.get("lat"),
                            "tags": s.get("tags", []),
                        }
                        names = [s["name"] for s in st.session_state.tp_cart]
                        if entry["name"] not in names:
                            st.session_state.tp_cart.append(entry)
                    st.rerun()

        # --- Cart display ---
        st.divider()
        if st.session_state.tp_cart:
            st.subheader(f"已选景点（{len(st.session_state.tp_cart)}个）")

            # Summary stats
            total_tickets = sum(s.get("price", 0) for s in st.session_state.tp_cart)
            cities = set(s.get("city", "") for s in st.session_state.tp_cart)
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("门票总计", f"¥{total_tickets}")
            sc2.metric("涉及城市", len(cities))
            sc3.metric("年卡对比", f"¥{total_tickets // len(st.session_state.tp_cart)}/人" if st.session_state.tp_cart else "¥0")

            # Cart table
            cart_df = pd.DataFrame([
                {
                    "景点": s["name"],
                    "城市": s.get("city", ""),
                    "类型": s.get("category", ""),
                    "时长(h)": estimate_play_duration(
                        s.get("category", ""), s.get("sub_category", ""),
                        s.get("level", ""), s.get("price", 0),
                    ),
                    "票价": s.get("price", 0),
                }
                for s in st.session_state.tp_cart
            ])
            st.dataframe(cart_df, width="stretch", hide_index=True)

            if st.button("清空行程", type="secondary"):
                st.session_state.tp_cart = []
                st.session_state.tp_assignment = None
                st.rerun()
        else:
            st.info("请从上方导入年卡景点或手动选择")

    # ============================================================
    # Tab 2: 行程编排
    # ============================================================
    with tab2:
        if not st.session_state.tp_cart:
            st.info("请先在「智能选景」Tab添加景点")
        else:
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                all_cities = sorted(set(s["city"] for s in spots_with_coords if s["city"]))
                dep_idx = all_cities.index("武汉") if "武汉" in all_cities else 0
                dep_city = st.selectbox("出发城市", all_cities, index=dep_idx)
            with c2:
                travel_month = st.selectbox("出行月份", range(1, 13), index=month - 1)
            with c3:
                # 上限 30：对话规划可生成 10+ 天长线行程，加载后要能原样显示；
                # 此前写死 7 导致 StreamlitValueAboveMaxError
                num_days = st.number_input("天数", 1, 30, st.session_state.tp_num_days)
            with c4:
                daily_cap = st.slider("每日时长(h)", 6.0, 12.0, 8.0, 0.5)

            if st.button("自动编排行程", type="primary", width="stretch"):
                dep_coord = CITY_COORDS.get(dep_city, [114.305, 30.593])
                departure = {"name": dep_city, "lng": dep_coord[0], "lat": dep_coord[1]}
                valid = [s for s in st.session_state.tp_cart if s.get("lng") and s.get("lat")]

                with st.spinner("正在编排..."):
                    assignment = assign_spots_with_duration(
                        valid, departure, num_days, travel_month, daily_cap,
                    )
                    st.session_state.tp_assignment = assignment
                    st.session_state.tp_departure_city = dep_city
                    st.session_state.tp_num_days = num_days
                    st.session_state.tp_travel_month = travel_month
                st.rerun()

            # Display assignment
            assignment = st.session_state.tp_assignment
            if assignment:
                # 兼容 chat_planner_v1 的 assignment（只有 days 键；
                # tp_v2 的 assign_spots_with_duration 才带 seasonal_warnings）
                if assignment.get("seasonal_warnings"):
                    st.warning("⚠️ 季节性提醒：")
                    for w in assignment["seasonal_warnings"]:
                        st.caption(f"❌ {w['spot_name']} — {w['reason']}")

                # Day cards
                for day_data in assignment["days"]:
                    spots = day_data["spots"]
                    if not spots:
                        st.caption(f"Day {day_data['day_num']}: 无景点")
                        continue

                    with st.expander(
                        f"**Day {day_data['day_num']}** — {len(spots)}个景点 · 游玩{day_data['play_hours']:.1f}h · 驾驶{day_data['travel_km']:.0f}km · {day_data['primary_city']}",
                        expanded=True,
                    ):
                        # Spot list with duration and reviews
                        for spot in spots:
                            name = spot.get("name", "")
                            play_h = spot.get("_play_hours", 2.0)
                            score = spot.get("_seasonal_score", 3)
                            emoji = "✅" if score >= 4 else "⚠️" if score >= 2 else "❌"

                            col_n, col_d, col_s = st.columns([4, 1, 1])
                            col_n.markdown(f"**{name}**")
                            col_n.caption(f"{spot.get('city', '')} · {spot.get('category', '')} · ¥{spot.get('price', 0)}")
                            col_d.metric("游玩时长", f"{play_h}h")
                            col_s.metric("季节分", f"{emoji}{score}")

                            # Review button
                            if col_s.button("评价", key=f"tp_review_{name}"):
                                reviews = aggregate_spot_reviews(name)
                                if reviews["review_count"] > 0:
                                    st.caption(f"真实评价: {reviews['avg_rating']:.1f}/5 ({reviews['review_count']}条)")
                                    if reviews["pros"]:
                                        st.caption("优点: " + ", ".join(reviews["pros"]))
                                    if reviews["cons"]:
                                        st.caption("注意: " + ", ".join(reviews["cons"]))
                                else:
                                    st.caption("暂无真实评价，使用AI评价")
                                    rec = generate_spot_recommendation(spot, st.secrets)
                                    st.caption(f"评分: {rec.rating:.1f}/5")
                                    if rec.pros:
                                        st.caption("优点: " + ", ".join(rec.pros[:2]))

                        # Timeline
                        timeline = build_day_timeline(spots)
                        st.caption(f"时间轴: {timeline['slots'][0]['start'] if timeline['slots'] else ''} → {timeline['end_time']}")
                        if timeline["warnings"]:
                            for w in timeline["warnings"]:
                                st.caption(f"⚠️ {w}")

            # No assignment yet
            if not assignment:
                st.info("点击「自动编排行程」生成每日行程")

    # ============================================================
    # Tab 3: 路线优化
    # ============================================================
    with tab3:
        assignment = st.session_state.tp_assignment
        if not assignment or not assignment.get("days"):
            st.info("请先在「行程编排」Tab生成每日行程")
        else:
            # Pick a day to optimize
            day_nums = [d["day_num"] for d in assignment["days"] if d["spots"]]
            if day_nums:
                selected_day = st.radio("选择要优化的日期", day_nums, horizontal=True)
                day_data = next((d for d in assignment["days"] if d["day_num"] == selected_day), None)

                if day_data and day_data["spots"]:
                    dep_coord = CITY_COORDS.get(
                        st.session_state.tp_departure_city, [114.305, 30.593]
                    )
                    departure = {
                        "name": st.session_state.tp_departure_city,
                        "lng": dep_coord[0], "lat": dep_coord[1],
                    }
                    web_key = st.secrets.get("amap_web_key", "")

                    if st.button("生成路线方案", type="primary"):
                        spots_for_route = [
                            s for s in day_data["spots"] if s.get("lng") and s.get("lat")
                        ]
                        with st.spinner("正在计算路线..."):
                            options = generate_route_options(departure, spots_for_route, web_key)
                            st.session_state.tp_route_options = options
                            st.session_state.tp_selected_route = 0
                        st.rerun()

                    if st.session_state.tp_route_options:
                        options = st.session_state.tp_route_options
                        labels = [f"方案{i+1}: {opt['name']}" for i, opt in enumerate(options)]
                        sel = st.radio("选择方案", labels, index=st.session_state.tp_selected_route, horizontal=True)
                        new_idx = labels.index(sel)
                        if new_idx != st.session_state.tp_selected_route:
                            st.session_state.tp_selected_route = new_idx
                            st.rerun()

                        chosen = options[st.session_state.tp_selected_route]

                        # Route summary
                        c1, c2, c3 = st.columns(3)
                        c1.metric("总距离", f"{chosen['total_distance_km']:.1f}km")
                        c2.metric("预计驾驶", f"{chosen['total_duration_min']}分钟")
                        c3.metric("景点数", len(chosen.get("ordered_spots", [])))

                        # Pros/cons
                        cp, cc = st.columns(2)
                        with cp:
                            st.markdown("**优点**")
                            for pro in chosen.get("pros", []):
                                st.markdown(f"- {pro}")
                        with cc:
                            st.markdown("**缺点**")
                            for con in chosen.get("cons", []):
                                st.markdown(f"- {con}")

                        # Recommended order
                        st.markdown("**推荐游览顺序:**")
                        for i, s in enumerate(chosen.get("ordered_spots", [])):
                            st.markdown(f"{i+1}. {s.get('name', '')} ({s.get('city', '')})")

                        # Cost estimation
                        st.divider()
                        st.subheader("成本估算")
                        total_ticket = sum(s.get("price", 0) for s in day_data["spots"])
                        cost = estimate_trip_cost(
                            total_distance_km=chosen["total_distance_km"],
                            num_days=1,
                            ticket_cost=total_ticket,
                        )
                        cc1, cc2, cc3, cc4 = st.columns(4)
                        cc1.metric("驾驶费用", f"¥{cost['driving']['total']}")
                        cc2.metric("餐饮", f"¥{cost['food']['total']}")
                        cc3.metric("门票", f"¥{cost['tickets']['net']}")
                        cc4.metric("当日总计", f"¥{cost['grand_total']}")

    # ============================================================
    # Tab 4: 行程总览
    # ============================================================
    with tab4:
        assignment = st.session_state.tp_assignment
        cart = st.session_state.tp_cart

        if not cart:
            st.info("请先添加景点")
        else:
            # Trip settings
            st.subheader("行程设置")
            c1, c2, c3 = st.columns(3)
            with c1:
                trip_name = st.text_input("行程名称", value=f"{st.session_state.tp_departure_city}出发-{st.session_state.tp_num_days}日游")
            with c2:
                travel_style = st.selectbox("消费水平", ["economy", "midrange", "luxury"], format_func=lambda x: {"economy": "经济型", "midrange": "舒适型", "luxury": "豪华型"}.get(x, x))
            with c3:
                if st.button("保存行程", type="primary", width="stretch"):
                    plan_id = save_days_plan(
                        assignment["days"], trip_name, "manual",
                        origin_city=st.session_state.tp_departure_city,
                        travel_month=st.session_state.tp_travel_month,
                        meta={"seasonal_warnings": assignment.get("seasonal_warnings", [])})
                    st.success(f"已保存！行程ID: {plan_id}（🧳 我的行程 可查看/编辑）")

            # Seasonal checklist
            st.subheader("季节性检查")
            warnings = check_seasonal_availability(cart, st.session_state.tp_travel_month)
            ok_spots = [w for w in warnings if w["severity"] == "ok"]
            warn_spots = [w for w in warnings if w["severity"] == "warning"]
            danger_spots = [w for w in warnings if w["severity"] == "danger"]

            cc1, cc2, cc3 = st.columns(3)
            cc1.metric("✅ 适宜", len(ok_spots))
            cc2.metric("⚠️ 一般", len(warn_spots))
            cc3.metric("❌ 不适宜", len(danger_spots))

            if danger_spots:
                st.error("以下景点出行季节不适宜：")
                for w in danger_spots:
                    st.caption(f"❌ {w['spot_name']} — {w['seasonal_reason']}")

            # Pass coverage
            st.subheader("年卡覆盖分析")
            coverage = compute_pass_coverage(cart, graph_data)
            if coverage["pass_stats"]:
                for ps in coverage["pass_stats"][:5]:
                    st.caption(f"🎫 {ps['pass_name']}: 覆盖{ps['covered_count']}个景点 · 价值¥{ps['total_value']}")
            else:
                st.caption("当前所选景点暂无年卡覆盖")

            cc1, cc2 = st.columns(2)
            cc1.metric("门票总计", f"¥{coverage['total_ticket_cost']}")
            if coverage["pass_stats"]:
                best_pass = coverage["pass_stats"][0]
                cc2.metric("最佳年卡价值", f"¥{best_pass['total_value']} (覆盖{best_pass['covered_count']}个)")

            # Full itinerary if assigned
            if assignment:
                st.divider()
                st.subheader("完整行程")
                for day_data in assignment["days"]:
                    if not day_data["spots"]:
                        continue
                    with st.expander(
                        f"**Day {day_data['day_num']}** — {len(day_data['spots'])}个景点 · {day_data['primary_city']}",
                        expanded=True,
                    ):
                        for spot in day_data["spots"]:
                            name = spot.get("name", "")
                            play_h = spot.get("_play_hours", 2.0)
                            st.markdown(f"- **{name}** · {play_h}h · ¥{spot.get('price', 0)}")

                        # Timeline for this day
                        timeline = build_day_timeline(day_data["spots"])
                        if timeline["slots"]:
                            times = [f"{s['start']} {s['spot_name']}" for s in timeline["slots"]]
                            st.caption("时间轴: " + " → ".join(times))

            # Total cost summary
            st.divider()
            st.subheader("费用总览")

            total_distance = sum(d.get("travel_km", 0) for d in (assignment["days"] if assignment else []))
            total_tickets = sum(s.get("price", 0) for s in cart)
            pass_savings = coverage["total_pass_value"] if coverage else 0

            cost = estimate_trip_cost(
                total_distance_km=total_distance,
                num_days=st.session_state.tp_num_days,
                ticket_cost=total_tickets,
                pass_savings=pass_savings,
                travel_style=travel_style,
            )

            cost_cols = st.columns(5)
            cost_cols[0].metric("驾驶", f"¥{cost['driving']['total']}")
            cost_cols[1].metric("住宿", f"¥{cost['accommodation']['total']}")
            cost_cols[2].metric("门票", f"¥{cost['tickets']['net']}")
            cost_cols[3].metric("餐饮", f"¥{cost['food']['total']}")
            cost_cols[4].metric("总计", f"¥{cost['grand_total']}")

            if pass_savings > 0:
                st.success(f"使用年卡预计节省 ¥{pass_savings:.0f}")



# ============================================================
# Page 7: My Trip (我的行程)
# ============================================================
