# -*- coding: utf-8 -*-
"""📈 数据洞察（原「数据总览」页）— extracted VERBATIM from app/main.py,
rendered as a view mode inside 🗺️ 地图探索.
"""


def render_data_overview_page(ctx):
    globals().update(ctx)
    st.subheader("📊 数据总览")

    stats = graph_data.get("stats", {})

    # KPI row
    free_count = sum(1 for s in cleaned if s.get("price", 0) == 0)
    a5_count = sum(1 for n in graph_data["nodes"] if n.get("type") == "spot" and n.get("level") == "A5")
    total_value = sum(s.get("price", 0) for s in cleaned if s.get("price", 0) > 0)
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("景点总数", stats.get("spot_count", 0))
    k2.metric("年卡数量", stats.get("pass_count", 0))
    k3.metric("覆盖城市", stats.get("city_count", 0))
    k4.metric("总价值", f"¥{total_value:,}")
    k5.metric("免费景点", free_count)
    k6.metric("5A景点", a5_count)

    tabs = st.tabs(["年卡价值分析", "城市与分类", "价格与季节", "年卡覆盖矩阵"])

    with tabs[0]:
        # Pass value analysis
        G_dash = build_graph(cleaned, alignment)
        passes = pass_analysis(G_dash)
        if passes:
            st.subheader("年卡性价比排行")
            df_pass = pd.DataFrame([
                {"年卡": p["name"].split("_")[0], "卡价": p["price"], "景点数": p["spot_count"],
                 "总票价": p["total_price"], "性价比": p["value_ratio"]}
                for p in passes
            ])
            fig = px.bar(df_pass, x="性价比", y="年卡", orientation="h",
                         color="性价比", color_continuous_scale="RdYlGn",
                         text="性价比", hover_data={"卡价": True, "景点数": True, "总票价": True})
            fig.update_traces(texttemplate="%{text:.1f}x", textposition="outside")
            fig.update_layout(showlegend=False, xaxis_title="性价比倍数 (总票价/卡价)")
            st.plotly_chart(fig, use_container_width=True)

        # Overlap analysis
        st.subheader("年卡重叠对比")
        pass_names = [p["name"] for p in passes] if passes else []
        if len(pass_names) >= 2:
            sel_p1, sel_p2 = st.selectbox("选择年卡 A", pass_names, index=0), st.selectbox("选择年卡 B", pass_names, index=1 if len(pass_names) > 1 else 0)
            if sel_p1 != sel_p2:
                overlap = pass_overlap(G_dash, sel_p1, sel_p2)
                c1, c2, c3 = st.columns(3)
                c1.metric("重叠景点", overlap["overlap_count"])
                c2.metric(f"仅 {sel_p1.split('_')[0]}", overlap["only_pass1"])
                c3.metric(f"仅 {sel_p2.split('_')[0]}", overlap["only_pass2"])

                # Overlap detail table
                if overlap["overlap_spots"]:
                    overlap_names = [G_dash.nodes[n].get("name", n) for n in overlap["overlap_spots"]]
                    st.caption(f"{len(overlap_names)} 个重叠景点:")
                    st.dataframe(pd.DataFrame(overlap_names, columns=["景点"]), use_container_width=True, hide_index=True)

    with tabs[1]:
        # City distribution
        st.subheader("城市景点分布")
        city_dist = {}
        for n in graph_data["nodes"]:
            if n.get("type") == "spot":
                city = n.get("city", "未知")
                city_dist[city] = city_dist.get(city, 0) + 1
        city_dist = dict(sorted(city_dist.items(), key=lambda x: -x[1]))
        col1, col2 = st.columns(2)
        with col1:
            df_city = pd.DataFrame(list(city_dist.items()), columns=["城市", "景点数"])
            fig = px.bar(df_city, x="城市", y="景点数", color="景点数", color_continuous_scale="Blues", text_auto=True)
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

        # Category distribution
        with col2:
            st.subheader("景点分类占比")
            cat_dist = category_distribution(G_dash)
            df_cat = pd.DataFrame(list(cat_dist.items()), columns=["分类", "数量"])
            fig = px.pie(df_cat, values="数量", names="分类", hole=0.4,
                         color="分类", color_discrete_sequence=px.colors.qualitative.Set3)
            st.plotly_chart(fig, use_container_width=True)

        # Level distribution
        st.subheader("景点等级分布")
        level_dist = {}
        for n in graph_data["nodes"]:
            if n.get("type") == "spot":
                level = n.get("level") or "未评级"
                level_dist[level] = level_dist.get(level, 0) + 1
        df_level = pd.DataFrame(list(level_dist.items()), columns=["等级", "数量"])
        fig = px.pie(df_level, values="数量", names="等级",
                     color="等级", color_discrete_sequence=px.colors.qualitative.Pastel)
        st.plotly_chart(fig, use_container_width=True)

        # Price by category boxplot
        st.subheader("各分类票价分布")
        price_cat = [{"分类": s["category"], "票价": s["price"]} for s in spots_with_coords if s.get("price", 0) > 0]
        if price_cat:
            df_box = pd.DataFrame(price_cat)
            fig = px.box(df_box, x="分类", y="票价", color="分类", points="outliers")
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

        # City × Category heatmap
        st.subheader("城市 × 分类 热力图")
        heatmap_data = []
        for n in graph_data["nodes"]:
            if n.get("type") == "spot":
                heatmap_data.append({"城市": n.get("city", "未知"), "分类": n.get("category", "其他")})
        if heatmap_data:
            df_heat = pd.DataFrame(heatmap_data)
            pivot = pd.crosstab(df_heat["城市"], df_heat["分类"])
            fig = px.imshow(pivot, text_auto=True, color_continuous_scale="YlOrRd",
                            labels={"x": "分类", "y": "城市", "color": "景点数"})
            st.plotly_chart(fig, use_container_width=True)

    with tabs[2]:
        # Price stats
        st.subheader("票价统计")
        pa = price_analysis(cleaned)
        if pa:
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("最低票价", f"¥{pa['min']}")
            c2.metric("最高票价", f"¥{pa['max']}")
            c3.metric("平均票价", f"¥{pa['mean']}")
            c4.metric("中位数", f"¥{pa['median']}")
            c5.metric("总价值", f"¥{pa['total']:,}")
            c6.metric("免费景点", pa.get("free_count", 0))

        # Price range distribution
        st.subheader("票价区间分布")
        price_list = [s["price"] for s in cleaned]
        bins = [0, 50, 100, 200, 500]
        labels = ["¥0-50", "¥51-100", "¥101-200", "¥200+"]
        df_pr = pd.DataFrame(price_list, columns=["票价"])
        df_pr["区间"] = pd.cut(df_pr["票价"], bins=bins, labels=labels, include_lowest=True)
        fig = px.bar(df_pr["区间"].value_counts().reset_index(), x="区间", y="count",
                     color="count", color_continuous_scale="Viridis", text_auto=True)
        fig.update_layout(xaxis_title="票价区间", yaxis_title="景点数", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

        # Top 20 expensive spots
        st.subheader("高价景点 TOP 20")
        top_spots = top_value_spots(G_dash, top_n=20)
        df_top = pd.DataFrame([
            {"景点": s["name"], "城市": s["city"], "分类": s["category"],
             "等级": s.get("level") or "未评级", "票价": s["price"]}
            for s in top_spots
        ])
        st.dataframe(df_top, use_container_width=True, hide_index=True)

        # Seasonal analysis
        st.subheader("季节性景点统计")
        seasonal = seasonal_analysis(cleaned)
        summer_only = sum(1 for s in seasonal["spots"] if "仅夏季" in s.get("notes", ""))
        winter_only = sum(1 for s in seasonal["spots"] if "仅冬季" in s.get("notes", ""))
        s1, s2, s3 = st.columns(3)
        s1.metric("仅夏季", summer_only)
        s2.metric("仅冬季", winter_only)
        s3.metric("季节性总计", seasonal["count"])

        if seasonal["spots"]:
            df_season = pd.DataFrame(seasonal["spots"])
            st.dataframe(df_season, use_container_width=True, hide_index=True)

    with tabs[3]:
        # Pass × City coverage matrix
        st.subheader("年卡 × 城市 覆盖矩阵")
        pass_city_matrix = defaultdict(lambda: defaultdict(int))
        for u, v, _key, _data in G_dash.edges(data=True, keys=True):
            u_attrs = dict(G_dash.nodes[u])
            v_attrs = dict(G_dash.nodes[v])
            if u_attrs.get("type") == "spot" and v_attrs.get("type") == "pass":
                city = u_attrs.get("city", "未知")
                pass_name = v_attrs.get("name", "").split("_")[0]
                pass_city_matrix[pass_name][city] += 1

        all_cities = sorted(set(c for cities in pass_city_matrix.values() for c in cities))
        all_passes = sorted(pass_city_matrix.keys())
        matrix_data = []
        for pn in all_passes:
            row = {"年卡": pn}
            for city in all_cities:
                row[city] = pass_city_matrix[pn].get(city, 0)
            matrix_data.append(row)

        if matrix_data:
            df_matrix = pd.DataFrame(matrix_data)
            df_matrix_indexed = df_matrix.set_index("年卡")
            fig = px.imshow(df_matrix_indexed, text_auto=True, color_continuous_scale="YlOrRd",
                            labels={"x": "城市", "y": "年卡", "color": "景点数"})
            fig.update_layout(xaxis_title="城市", yaxis_title="年卡")
            st.plotly_chart(fig, use_container_width=True)

        # Pass city coverage count
        st.subheader("年卡覆盖城市数排行")
        city_counts = [(pn, len([c for c, v in cities.items() if v > 0]))
                       for pn, cities in pass_city_matrix.items()]
        city_counts.sort(key=lambda x: -x[1])
        df_cc = pd.DataFrame(city_counts, columns=["年卡", "覆盖城市数"])
        fig = px.bar(df_cc, x="覆盖城市数", y="年卡", orientation="h",
                     color="覆盖城市数", color_continuous_scale="Tealgrn", text_auto=True)
        fig.update_traces(texttemplate="%{text}", textposition="outside")
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
