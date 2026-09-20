# -*- coding: utf-8 -*-
"""🌿 季节游玩指南 — extracted VERBATIM from app/main.py.

render(ctx) injects main.py's namespace via globals().update(ctx). Do NOT
import app.main here (Streamlit re-execution trap).
"""


def render_season_guide_page(ctx):
    globals().update(ctx)
    st.title("季节游玩指南")

    # City filter in sidebar (month moved to chips below)
    with st.sidebar:
        all_cities_season = sorted(set(s["city"] for s in spots_with_coords if s["city"]))
        sel_cities = st.multiselect("城市筛选", all_cities_season, default=[])
        clear_btn = st.button("清除筛选", type="secondary", use_container_width=True)
        if clear_btn and sel_cities:
            st.rerun()

    # Month chips
    if "selected_month" not in st.session_state:
        st.session_state.selected_month = 1

    st.markdown("#### 选择月份")
    month_cols = st.columns(12)
    for i, col in enumerate(month_cols):
        m = i + 1
        sk = MONTH_TO_SEASON[m]
        em = SEASON_EMOJI[sk]
        is_sel = st.session_state.selected_month == m
        if col.button(f"{em}{m}月", key=f"mc_{m}", type="primary" if is_sel else "secondary", use_container_width=True):
            st.session_state.selected_month = m
            st.rerun()

    month = st.session_state.selected_month

    # Precompute analytics data once
    pi_seasonal = build_pass_info(graph_data, cleaned)
    df_monthly = compute_12_month_overview(spots_with_coords, sel_cities if sel_cities else None)
    pass_ranking = compute_seasonal_pass_ranking(pi_seasonal, spots_with_coords, month, sel_cities if sel_cities else None)
    # Owned pass filter for seasonal data
    _seasonal_spots = spots_with_coords
    if _owned_pass_spots is not None:
        _seasonal_spots = [s for s in spots_with_coords if s["name"] in _owned_pass_spots]

    recs = get_seasonal_recommendations(_seasonal_spots, month, sel_cities if sel_cities else None)
    cat_dist = compute_category_distribution(recs)
    exclusive_spots = find_seasonal_exclusive_spots(_seasonal_spots, month, pi_seasonal)
    df_calendar = compute_seasonal_calendar(_seasonal_spots, pi_seasonal)

    # Tabs
    season_tabs = st.tabs(["📅 月度总览", "🎯 当季推荐", "❄️ 季节专属"])

    # ================================================================
    # Tab 1: 月度总览
    # ================================================================
    with season_tabs[0]:
        # 12-month bar + line chart
        st.subheader("12个月推荐概览")

        fig_monthly = go.Figure()
        season_colors = {"spring": "#4CAF50", "summer": "#FF9800", "autumn": "#8BC34A", "winter": "#2196F3"}
        colors = [season_colors[s] for s in df_monthly["season"]]

        fig_monthly.add_trace(go.Bar(
            x=df_monthly["month"], y=df_monthly["recommended"],
            marker_color=colors, name="推荐景点数",
        ))
        fig_monthly.add_trace(go.Scatter(
            x=df_monthly["month"], y=df_monthly["avg_price"],
            name="平均票价(¥)", mode="lines+markers",
            line=dict(color="#E91E63", width=2),
            yaxis="y2",
        ))
        fig_monthly.update_layout(
            xaxis=dict(title="月份", tickmode="linear", dtick=1),
            yaxis=dict(title="推荐景点数"),
            yaxis2=dict(title="平均票价(¥)", overlaying="y", side="right"),
            height=380, hovermode="x unified", showlegend=True,
        )
        st.plotly_chart(fig_monthly, use_container_width=True)

        # Current month highlight
        cur = df_monthly[df_monthly["month"] == month].iloc[0]
        st.info(
            f"📌 **当前 {month}月** — {SEASON_NAMES[cur['season']]} "
            f"推荐 {cur['recommended']} 个景点，平均票价 ¥{cur['avg_price']:.0f}"
        )

        # Seasonal pass ranking
        st.subheader(f"{SEASON_NAMES[MONTH_TO_SEASON[month]]}年卡性价比排行")
        if pass_ranking:
            df_rank = pd.DataFrame(pass_ranking)
            df_rank["性价比"] = (df_rank["seasonal_savings"] / df_rank["card_price"]).round(2)
            df_rank = df_rank[df_rank["seasonal_value"] > 0].sort_values("seasonal_savings", ascending=False)

            if not df_rank.empty:
                fig_rank = px.bar(
                    df_rank, x="seasonal_value", y="display", orientation="h",
                    color="性价比", color_continuous_scale="RdYlGn",
                    hover_data={"card_price": True, "seasonal_spots": True, "seasonal_savings": True},
                )
                fig_rank.update_layout(
                    yaxis=dict(autorange="reversed"),
                    xaxis_title=f"{SEASON_NAMES[MONTH_TO_SEASON[month]]}可玩景点总价值(¥)",
                    height=max(300, len(df_rank) * 35),
                )
                st.plotly_chart(fig_rank, use_container_width=True)

                # Top 3 metrics
                top3 = df_rank.head(3)
                tcols = st.columns(3)
                for idx, (_, row) in enumerate(top3.iterrows()):
                    with tcols[idx]:
                        st.markdown(f"**{row['display']}**")
                        st.metric("当季节省", f"¥{row['seasonal_savings']:,}")
                        st.caption(f"{row['seasonal_spots']} 个景点 · 性价比 {row['性价比']:.1f}x")
            else:
                st.info("当前季节暂无高价值推荐年卡")
        else:
            st.info("当季暂无推荐景点")

    # ================================================================
    # Tab 2: 当季推荐
    # ================================================================
    with season_tabs[1]:
        # Season card
        emoji = recs["emoji"]
        season_name = recs["season"]
        climate = recs["climate"]
        st.markdown(f"### {emoji} {season_name}（{recs['month']}月） · {climate['temp_range']}")
        st.caption(climate["desc"])
        st.caption(f"💡 {climate['tips']}")

        # Category pie chart
        if cat_dist:
            fig_pie = px.pie(
                values=list(cat_dist.values()), names=list(cat_dist.keys()),
                title="推荐景点类型分布（必去+推荐）", hole=0.4,
            )
            fig_pie.update_traces(textposition="inside", textinfo="percent+label")
            fig_pie.update_layout(height=350)
            st.plotly_chart(fig_pie, use_container_width=True)

        total = recs["total_count"]
        if total == 0:
            st.info("当前筛选条件下暂无推荐景点")
            st.stop()

        st.caption(f"共 {total} 个推荐景点")
        st.divider()

        # Helper: render a spot card
        def _spot_card(spot: dict, reason: str, score: int, key: str):
            with st.container(border=True):
                level_badge = ""
                if spot.get("level") == "A5":
                    level_badge = " `[5A]`"
                elif spot.get("level") == "A4":
                    level_badge = " `[4A]`"
                st.markdown(f"**{spot['name']}**{level_badge}")
                st.caption(f"{spot['city']} {spot.get('area', '')} · {spot['category']}")
                st.caption(f"¥{spot['price']}")
                st.caption(f"📌 {reason}")
                passes = spot.get("passes", [])
                if passes:
                    pass_text = " · ".join(p.split("_")[0] for p in passes[:2])
                    st.caption(f"🎫 {pass_text}")
                if st.button("➕ 添加行程", key=f"season_add_{key}_{spot['name']}", type="secondary", use_container_width=True):
                    existing = {s["name"] for s in st.session_state.selected_trip_spots}
                    if spot["name"] not in existing:
                        st.session_state.selected_trip_spots.append({
                            "name": spot["name"], "lng": spot.get("lng"),
                            "lat": spot.get("lat"), "city": spot["city"],
                            "area": spot.get("area", ""), "category": spot["category"],
                            "price": spot["price"], "level": spot.get("level", ""),
                            "passes": passes,
                        })
                        st.toast(f"已添加 {spot['name']} 到行程", icon="✅")
                    else:
                        st.toast(f"{spot['name']} 已在行程中", icon="ℹ️")

        def _render_tier(title, items, key_prefix, initial=15):
            """Render up to `initial` cards; the rest only enter the DOM on demand
            (st.expander children are rendered server-side anyway, which made this
            page create 860+ widgets per rerun)."""
            if not items:
                return
            st.subheader(f"{title} ({len(items)}个)")
            show_key = f"season_showall_{key_prefix}_{month}"
            show_all = st.session_state.get(show_key, False)
            display = items if show_all else items[:initial]
            cols = st.columns(3)
            for i, (spot, reason, score) in enumerate(display):
                with cols[i % 3]:
                    _spot_card(spot, reason, score, f"{key_prefix}_{i}")
            if len(items) > initial and not show_all:
                if st.button(f"⬇️ 展开剩余 {len(items) - initial} 个",
                             key=f"season_more_{key_prefix}_{month}"):
                    st.session_state[show_key] = True
                    st.rerun()

        # Tier 1
        mv = recs["must_visit"]
        if mv:
            st.subheader(f"⭐ 必去推荐 ({len(mv)}个)")
            cols = st.columns(3)
            for i, (spot, reason, score) in enumerate(mv):
                with cols[i % 3]:
                    _spot_card(spot, reason, score, f"mv_{i}")

        # Tier 2 / Tier 3: lazy
        _render_tier("👍 值得一去", recs["recommended"], "rec")
        _render_tier("📍 也不错", recs["optional"], "opt")

    # ================================================================
    # Tab 3: 季节专属
    # ================================================================
    with season_tabs[2]:
        st.subheader(f"{SEASON_NAMES[MONTH_TO_SEASON[month]]}专属景点")
        st.caption(f"仅在{SEASON_NAMES[MONTH_TO_SEASON[month]]}开放或最佳的景点")

        if exclusive_spots:
            # Stats
            excl_by_type: dict[str, int] = defaultdict(int)
            excl_by_sub: dict[str, int] = defaultdict(int)
            excl_no_cover = 0
            excl_total_value = 0
            for e in exclusive_spots:
                excl_by_type[e["detection_type"]] += 1
                if e["sub_category"]:
                    excl_by_sub[e["sub_category"]] += 1
                elif e["category"]:
                    excl_by_sub[e["category"]] += 1
                if not e["passes_covering"]:
                    excl_no_cover += 1
                excl_total_value += e["price"]

            n1, n2, n3, n4, n5 = st.columns(5)
            n1.metric("专属景点", len(exclusive_spots))
            n2.metric("总票价", f"¥{excl_total_value:,}")
            n3.metric("年卡盲区", excl_no_cover, delta=None)
            n4.metric("检测方式", f"{len(excl_by_type)}种")
            n5.metric("子分类", f"{len(excl_by_sub)}类")

            st.divider()

            # Sub-category stats
            st.subheader("子分类统计")
            sub_cols = st.columns(min(len(excl_by_sub), 5))
            for idx, (sub, cnt) in enumerate(sorted(excl_by_sub.items(), key=lambda x: -x[1])):
                with sub_cols[idx % len(sub_cols)]:
                    with st.container(border=True):
                        st.markdown(f"**{sub}**")
                        st.metric("景点数", cnt)
                        sub_value = sum(e["price"] for e in exclusive_spots if (e["sub_category"] or e["category"]) == sub)
                        st.caption(f"总票价 ¥{sub_value:,}")

            st.divider()

            # 12-month calendar heatmap
            st.subheader("全年季节分布")
            if not df_calendar.empty:
                fig_cal = go.Figure(data=go.Heatmap(
                    z=df_calendar.values,
                    x=[f"{m}月" for m in df_calendar.columns],
                    y=df_calendar.index,
                    text=df_calendar.values,
                    texttemplate="%{text}",
                    textfont={"size": 12},
                    colorscale="YlOrRd",
                    colorbar=dict(title="景点数"),
                ))
                fig_cal.update_layout(
                    height=max(250, len(df_calendar) * 35),
                    xaxis=dict(title="月份"),
                    yaxis=dict(title="分类"),
                )
                st.plotly_chart(fig_cal, use_container_width=True)

            st.divider()

            # Detection type breakdown
            st.subheader("检测方式分布")
            det_cols = st.columns(len(excl_by_type))
            for idx, (det_type, cnt) in enumerate(sorted(excl_by_type.items(), key=lambda x: -x[1])):
                with det_cols[idx]:
                    with st.container(border=True):
                        st.markdown(f"**{det_type}**")
                        st.metric("景点数", cnt)
                        det_value = sum(e["price"] for e in exclusive_spots if e["detection_type"] == det_type)
                        st.caption(f"总票价 ¥{det_value:,}")

            st.divider()

            # Enhanced table with coverage status
            st.subheader("景点明细")
            df_excl = pd.DataFrame(exclusive_spots)
            df_excl["年卡覆盖数"] = df_excl["passes_covering"].apply(len)

            # Coverage status color
            def _cover_icon(status: str) -> str:
                if status == "无覆盖":
                    return "❌ 无覆盖"
                elif status == "部分覆盖":
                    return "⚠️ 部分覆盖"
                return "✅ 全卡覆盖"

            st.dataframe(
                df_excl[["name", "city", "category", "sub_category", "price", "exclusive_type", "detection_type", "年卡覆盖数", "coverage_status"]],
                use_container_width=True, hide_index=True,
                column_config={
                    "price": st.column_config.NumberColumn("票价", format="¥%d"),
                    "coverage_status": st.column_config.TextColumn("覆盖状态"),
                },
            )

            # Pass coverage gap analysis
            st.divider()
            st.subheader("年卡覆盖分析")
            pass_cov: dict[str, int] = defaultdict(int)
            for e in exclusive_spots:
                for pid in e["passes_covering"]:
                    pass_cov[pid] += 1

            if pass_cov:
                df_cov = pd.DataFrame([
                    {"年卡": pi_seasonal[pid]["display"], "覆盖专属景点": cnt}
                    for pid, cnt in sorted(pass_cov.items(), key=lambda x: -x[1])
                ])
                fig_cov = px.bar(df_cov, x="年卡", y="覆盖专属景点", color="覆盖专属景点", color_continuous_scale="Blues")
                st.plotly_chart(fig_cov, use_container_width=True)

                # Coverage gap: spots no pass covers
                if excl_no_cover > 0:
                    st.divider()
                    st.warning(f"⚠️ **{excl_no_cover} 个景点无任何年卡覆盖**（必须自费）")
                    no_cov_spots = [e for e in exclusive_spots if not e["passes_covering"]]
                    for e in no_cov_spots[:10]:
                        st.caption(f"❌ {e['name']} — {e['city']} · {e['category']} · ¥{e['price']}")
                    if len(no_cov_spots) > 10:
                        st.caption(f"... 还有 {len(no_cov_spots) - 10} 个")
            else:
                st.warning(f"⚠️ **所有 {len(exclusive_spots)} 个景点均无年卡覆盖**，需自费")
        else:
            st.info("当前季节无专属景点限制")


# ============================================================
# Page 5: Dashboard (simplified)
# ============================================================
# Planning hub (规划中心): all trip-creation modes, one entry
