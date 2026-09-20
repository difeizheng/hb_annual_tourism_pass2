# -*- coding: utf-8 -*-
"""💡 选卡助手 — extracted VERBATIM from app/main.py.

render(ctx) injects main.py's namespace via globals().update(ctx). Do NOT
import app.main here (Streamlit re-execution trap).
"""


import datetime

from src.seasonal_recommender import MONTH_TO_SEASON, calculate_seasonal_score


def render_pass_assistant_page(ctx):
    globals().update(ctx)
    st.title("选卡助手")

    # Build pass info from graph_data
    pass_info = build_pass_info(graph_data, cleaned)

    # Quick comparison cards
    st.subheader("年卡速览")
    passes_sorted = sorted(pass_info.values(), key=lambda x: -x["value_ratio"])
    cols = st.columns(min(5, len(passes_sorted)))
    for i, pi in enumerate(passes_sorted[:5]):
        with cols[i % 5]:
            with st.container(border=True):
                st.markdown(f"**{pi['display']}**")
                st.metric("卡价", f"¥{pi['price']}")
                st.metric("景点", pi["spot_count"])
                st.metric("城市", pi["city_count"])
                st.metric("性价比", f"{pi['value_ratio']}x")

    tabs = st.tabs(["智能推荐向导", "年卡详情", "预算规划"])
    st.caption("💡 多卡参数/雷达对比已并入「🎫 年卡对比」页")

    # ================================================================
    # Tab 1: Smart Wizard
    # ================================================================
    with tabs[0]:
        # Persona selection
        personas = {
            "武汉本地人": {"cities": ["武汉"], "bonus_cats": ["休闲农业", "主题乐园"], "label": "武汉本地人，周末周边游"},
            "湖北全省游": {"min_cities": 8, "bonus_cats": ["自然景观", "人文历史"], "label": "深度探索湖北全省"},
            "跨省游": {"min_cities": 12, "bonus_cats": [], "label": "跨省游玩，覆盖范围广"},
            "家庭亲子": {"bonus_cats": ["主题乐园", "休闲农业", "城市娱乐"], "min_spots": 30, "label": "带小孩，亲子友好"},
            "预算优先": {"sort_by": "value_ratio", "label": "性价比至上"},
            "品质优先": {"bonus_tags": ["5A", "4A"], "min_a5": 1, "label": "5A/4A 高品质景点"},
        }

        st.subheader("Step 1: 你是哪种游客？")
        selected_persona = st.selectbox(
            "选择最符合你的类型",
            list(personas.keys()),
            format_func=lambda x: personas[x]["label"],
            label_visibility="collapsed",
        )

        st.subheader("Step 2: 你在哪些城市游玩？")
        all_cities_card = sorted(set(s["city"] for s in cleaned if s["city"]))
        wiz_cities = st.multiselect(
            "选择游玩城市（不选=不限）",
            all_cities_card,
            default=personas.get(selected_persona, {}).get("cities", []),
            label_visibility="collapsed",
        )

        st.subheader("Step 3: 你喜欢什么类型的景点？")
        all_cats_card = sorted(set(s.get("_classification", {}).get("category", "其他") for s in cleaned))
        wiz_cats = st.multiselect(
            "选择偏好类型（不选=不限）",
            all_cats_card,
            default=personas.get(selected_persona, {}).get("bonus_cats", []),
            label_visibility="collapsed",
        )

        st.subheader("Step 4: 你的预算是多少？")
        max_pass_price = max(pi["price"] for pi in pass_info.values())
        wiz_budget = st.slider("年卡预算", 100, max_pass_price, max_pass_price, step=50)

        st.subheader("Step 5: 计划几月出行？")
        _cur_m = datetime.datetime.now().month
        wiz_month = st.selectbox(
            "出行月份（影响当季景点权重）",
            ["不限"] + [f"{m}月" for m in range(1, 13)],
            index=_cur_m,
            label_visibility="collapsed",
        )

        # Precompute per-spot seasonal scores once (shared across passes)
        _season_key = None
        _spot_season_score = {}
        if wiz_month != "不限":
            _season_key = MONTH_TO_SEASON[int(wiz_month[:-1])]
            for _s in spots_with_coords:
                _spot_season_score[_s["name"]] = calculate_seasonal_score(_s, _season_key)[0]

        # Scoring
        wizard_results = []
        for pn, pi in pass_info.items():
            if pi["price"] > wiz_budget:
                continue
            score = 0
            reasons = []

            persona_cfg = personas.get(selected_persona, {})

            # City match
            if wiz_cities:
                match = sum(1 for c in wiz_cities if c in pi["cities"])
                score += match * 5
                if match > 0:
                    reasons.append(f"{match}个目标城市有景点")
            elif persona_cfg.get("min_cities"):
                if pi["city_count"] >= persona_cfg["min_cities"]:
                    score += 10
                    reasons.append(f"覆盖{pi['city_count']}个城市")

            # Category match
            if wiz_cats:
                match = sum(1 for c in wiz_cats if c in pi["categories"])
                score += match * 4
                if match > 0:
                    reasons.append(f"{match}个偏好类型匹配")

            # Persona-specific bonuses
            if persona_cfg.get("min_spots") and pi["spot_count"] >= persona_cfg["min_spots"]:
                score += 5
                reasons.append(f"{pi['spot_count']}个景点足够多")
            if persona_cfg.get("min_a5") and pi["a5_count"] >= persona_cfg["min_a5"]:
                score += pi["a5_count"] * 2
                reasons.append(f"{pi['a5_count']}个5A景点")

            # Value ratio bonus
            score += pi["value_ratio"] * 2

            # Seasonal bonus: spots of this pass that are must-visit (>=4) in the chosen month
            if _season_key:
                season_hits = sum(
                    1 for _s in spots_with_coords
                    if pi["name_key"] in _s.get("passes", [])
                    and _spot_season_score.get(_s["name"], 0) >= 4
                )
                if season_hits:
                    score += min(season_hits * 1.5, 15)
                    reasons.append(f"{wiz_month}当季必去{season_hits}个")

            if not reasons:
                reasons.append("性价比不错")

            wizard_results.append({
                "年卡": pi["display"],
                "卡价": pi["price"],
                "景点数": pi["spot_count"],
                "城市数": pi["city_count"],
                "匹配度": round(score, 1),
                "性价比": f"{pi['value_ratio']}x",
                "推荐理由": "；".join(reasons[:3]),
            })

        wizard_results.sort(key=lambda x: -x["匹配度"])

        if wizard_results:
            st.divider()
            st.subheader(f"推荐排行 ({len(wizard_results)}张匹配)")
            df_wiz = pd.DataFrame(wizard_results)
            st.dataframe(df_wiz, use_container_width=True, hide_index=True)

            # Top recommendation
            top = wizard_results[0]
            st.success(f"💡 推荐: **{top['年卡']}** (¥{top['卡价']}) — {top['推荐理由']}")

            # Bar chart of match scores
            fig = px.bar(df_wiz.head(10), x="匹配度", y="年卡", orientation="h",
                         color="匹配度", color_continuous_scale="RdYlGn",
                         text="匹配度", hover_data={"卡价": True, "景点数": True, "推荐理由": True})
            fig.update_traces(texttemplate="%{text:.1f}", textposition="outside")
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("当前条件没有匹配的年卡，请放宽预算或减少筛选。")

    # ================================================================
    # Tab 2: Comparison Panel
    # ================================================================
    with tabs[1]:
        all_pass_names = sorted(pass_info.keys(), key=lambda x: -pass_info[x]["value_ratio"])
        detail_pass = st.selectbox(
            "选择一张年卡查看详情",
            all_pass_names,
            format_func=lambda x: f"{pass_info[x]['display']} (¥{pass_info[x]['price']}, {pass_info[x]['spot_count']}景点)",
        )

        pi = pass_info[detail_pass]

        # Basic info
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("卡价", f"¥{pi['price']}")
        c2.metric("景点数", pi["spot_count"])
        c3.metric("城市数", pi["city_count"])
        c4.metric("总价值", f"¥{pi['total_price']:,}")
        c5.metric("性价比", f"{pi['value_ratio']}x")
        c6.metric("5A景点", pi["a5_count"])

        # Category distribution
        st.subheader("分类占比")
        cat_counts = {}
        for s in cleaned:
            if s.get("pass_name") == detail_pass:
                cat = s.get("_classification", {}).get("category", "其他")
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
        if cat_counts:
            df_detail_cat = pd.DataFrame(list(cat_counts.items()), columns=["分类", "数量"])
            fig = px.pie(df_detail_cat, values="数量", names="分类", hole=0.4)
            st.plotly_chart(fig, use_container_width=True)

        # City distribution
        st.subheader("城市分布")
        city_counts = {}
        for s in cleaned:
            if s.get("pass_name") == detail_pass:
                city = s.get("city", "未知")
                city_counts[city] = city_counts.get(city, 0) + 1
        city_counts = dict(sorted(city_counts.items(), key=lambda x: -x[1]))
        if city_counts:
            df_detail_city = pd.DataFrame(list(city_counts.items()), columns=["城市", "景点数"])
            fig = px.bar(df_detail_city, x="城市", y="景点数", color="景点数",
                         color_continuous_scale="Blues", text_auto=True)
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

        # Spot list
        st.subheader("包含景点")
        spot_list = []
        for s in cleaned:
            if s.get("pass_name") == detail_pass:
                spot_list.append({
                    "景点": s["spot_name"],
                    "城市": s.get("city", ""),
                    "分类": s.get("_classification", {}).get("category", ""),
                    "等级": s.get("level") or "未评级",
                    "票价": s.get("price", 0),
                })
        if spot_list:
            df_spots = pd.DataFrame(spot_list).sort_values("票价", ascending=False)
            st.dataframe(df_spots, use_container_width=True, hide_index=True, height=400)

        # Usage limits and notes
        st.subheader("使用说明")
        usage_notes = set()
        spot_notes = set()
        for s in cleaned:
            if s.get("pass_name") == detail_pass:
                if s.get("usage_limit_raw"):
                    usage_notes.add(s["usage_limit_raw"])
                if s.get("notes_raw"):
                    spot_notes.add(s["notes_raw"][:80])
        if usage_notes:
            st.caption("使用次数:")
            for u in sorted(usage_notes):
                st.caption(f"- {u}")
        if spot_notes:
            st.caption("特殊说明:")
            for n in sorted(spot_notes)[:10]:
                st.caption(f"- {n}")
            if len(spot_notes) > 10:
                st.caption(f"... 还有 {len(spot_notes) - 10} 条")

    # ================================================================
    # Tab 4: 预算规划
    # ================================================================
    with tabs[2]:
        st.subheader("预算规划")
        st.caption("输入预算，自动生成最优游玩方案")

        # Controls
        b_ctrl = st.columns(4)
        with b_ctrl[0]:
            budget_val = st.slider("预算总额 (¥)", 200, 10000, 1000, step=100)
        with b_ctrl[1]:
            people_count = st.slider("人数", 1, 5, 1)
        with b_ctrl[2]:
            budget_days = st.select_slider("天数", [1, 2, 3], value=2)
        with b_ctrl[3]:
            budget_month = st.selectbox("月份", list(range(1, 13)), index=0)

        # Departure city
        all_dep_b = sorted(set(s["city"] for s in spots_with_coords if s["city"]))
        dep_idx = 0 if "武汉" not in all_dep_b else all_dep_b.index("武汉")
        budget_dep = st.selectbox("出发城市", all_dep_b, index=dep_idx)

        if st.button("生成方案", type="primary", use_container_width=True):
            dep_coord_b = CITY_COORDS.get(budget_dep, [114.305, 30.593])
            origin_b = {"name": budget_dep, "lng": dep_coord_b[0], "lat": dep_coord_b[1]}
            pi_budget = build_pass_info(graph_data, cleaned)

            with st.spinner("正在规划预算方案..."):
                budget_result = plan_budget(
                    budget=budget_val,
                    spots=spots_with_coords,
                    pass_info=pi_budget,
                    origin=origin_b,
                    num_days=budget_days,
                    people=people_count,
                    travel_month=budget_month,
                )
                st.session_state.budget_result = budget_result
                st.rerun()

        if st.session_state.get("budget_result"):
            br = st.session_state.budget_result

            if br.get("budget_left", 0) > 0:
                st.success(f"预算内找到方案！剩余 ¥{br['budget_left']:,.0f}")
            else:
                st.warning("预算不足，以下为最优推荐方案")

            # Plan cards
            plan_cols = st.columns(min(len(br["plans"]), 3))
            for idx, plan in enumerate(br["plans"]):
                with plan_cols[idx]:
                    with st.container(border=idx == br["best_plan_idx"]):
                        if idx == br["best_plan_idx"]:
                            st.markdown(f"**⭐ 推荐**")
                        st.markdown(f"**{plan['name']}**")
                        st.caption(plan["description"])

                        st.metric("总费用", f"¥{plan['total_cost']:,.0f}")
                        st.metric("人均", f"¥{plan['per_person']:,.0f}")
                        st.caption(f"{plan['spots_count']} 个景点 · {plan['a5_count']}个5A")

                        feasible_icon = "✅ 预算内" if plan["feasible"] else "⚠️ 超预算"
                        st.caption(f"{feasible_icon}")

                        # Breakdown
                        if plan.get("breakdown"):
                            with st.expander("费用明细"):
                                for k, v in plan["breakdown"].items():
                                    st.caption(f"{k}: ¥{v:,.0f}")

                        # Spots list
                        if plan.get("spots"):
                            with st.expander(f"景点列表 ({min(len(plan['spots']), 10)})"):
                                for s in plan["spots"][:10]:
                                    level = s.get("level", "")
                                    badge = " [5A]" if level == "A5" else (" [4A]" if level == "A4" else "")
                                    st.caption(f"- {s['name']}{badge} · {s['city']} · ¥{s.get('price', 0)}")

            # Comparison table
            st.divider()
            st.subheader("方案对比")
            comp_rows = []
            for p in br["plans"]:
                comp_rows.append({
                    "方案": p["name"],
                    "总费用": int(p["total_cost"]),
                    "人均": int(p["per_person"]),
                    "景点数": p["spots_count"],
                    "5A景点": p["a5_count"],
                    "预算内": "✅" if p["feasible"] else "⚠️",
                })
            st.dataframe(pd.DataFrame(comp_rows), use_container_width=True, hide_index=True)
