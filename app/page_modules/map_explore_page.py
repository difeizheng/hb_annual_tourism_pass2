# -*- coding: utf-8 -*-
"""🗺️ 地图探索 — extracted VERBATIM from app/main.py.

render(ctx) injects main.py's namespace via globals().update(ctx). Do NOT
import app.main here (Streamlit re-execution trap).
"""

_LV_DISP = {"A5": "5A", "A4": "4A", "A3": "3A"}


def render_map_explore_page(ctx):
    globals().update(ctx)
    st.title("地图探索")

    # Owned pass info badge
    if _owned_pass_spots is not None:
        st.info(
            f"🎫 **{_owned_pass_display}** — 覆盖 {_owned_pass_price} 元年卡，"
            f"{len(_owned_pass_spots)} 个景点，总票价 ¥{sum(s.get('price', 0) for s in spots_with_coords if s['name'] in _owned_pass_spots):,}"
        )

    # API Key setup
    web_key = st.secrets.get("amap_web_key", "")
    if not spots_with_geo:
        if not web_key:
            st.warning("⚠️ 请在 `.streamlit/secrets.toml` 中配置高德 Web 服务 API Key")
            st.info("申请地址: https://console.amap.com/dev/key/app → 选择 Web 服务")
        elif st.button("🚀 开始坐标转换"):
            with st.spinner(f"正在转换 {len(spots_without_geo)} 个景点坐标..."):
                result, ok, fail = batch_geocode(spots_without_geo, web_key, coordinates)
                save_coordinates(result)
                st.success(f"完成！成功 {ok}，失败 {fail}")
                st.rerun()
        else:
            st.info("已检测到高德 API Key，点击按钮开始坐标转换。")
    else:
        # Filters in sidebar
        st.sidebar.subheader("筛选条件")

        all_cities = sorted(set(s["city"] for s in spots_with_coords if s["city"]))
        all_cats = sorted(set(s["category"] for s in spots_with_coords if s["category"]))
        all_passes = sorted(set(p for s in spots_with_coords for p in s["passes"]))

        # 预设/清除在下一帧 widget 实例化前应用（widget key 不能同帧改）
        _pp = st.session_state.pop("_map_preset_pending", None)
        if _pp:
            if _pp.get("city") is not None:
                st.session_state["mx_city"] = list(_pp["city"])
            if _pp.get("category") is not None:
                st.session_state["mx_cat"] = list(_pp["category"])
        if st.session_state.pop("_map_clear_pending", False):
            st.session_state["mx_city"] = []
            st.session_state["mx_cat"] = []
            st.session_state["mx_pass"] = []

        sel_city = st.sidebar.multiselect("城市", all_cities, default=[], key="mx_city")
        sel_cat = st.sidebar.multiselect("类型", all_cats, default=[], key="mx_cat")
        sel_pass = st.sidebar.multiselect("年卡", all_passes, default=[], key="mx_pass",
                                           format_func=_pass_display_name)
        name_q = st.sidebar.text_input("🔍 搜索景点名", placeholder="输入名称关键字")

        has_active = bool(
            sel_city or sel_cat or sel_pass
            or st.session_state.get("_map_level")
            or st.session_state.get("_map_free_only")
            or st.session_state.get("_map_high_value")
        )
        if has_active and st.sidebar.button("清除筛选", type="secondary", width="stretch"):
            st.session_state["_map_clear_pending"] = True
            st.session_state["_map_level"] = None
            st.session_state["_map_free_only"] = False
            st.session_state["_map_high_value"] = False
            st.rerun()

        # --- 6. Quick filter presets ---
        st.sidebar.divider()
        st.sidebar.subheader("快捷筛选")
        presets = {
            "武汉5A": {"city": ["武汉"], "level": "A5"},
            "武汉周边": {"city": ["武汉", "鄂州", "黄石", "咸宁", "孝感"]},
            "自然景点": {"category": ["自然景观"]},
            "人文历史": {"category": ["人文历史"]},
            "免费景点": {"free_only": True},
            "高性价比": {"high_value": True},
            "5A全景": {"level": "A5"},
            "主题乐园": {"category": ["主题乐园"]},
        }
        preset_clicked = False
        for preset_name in presets:
            if st.sidebar.button(preset_name, width="stretch", key=f"preset_{preset_name}"):
                preset = presets[preset_name]
                st.session_state["_map_preset_pending"] = preset
                preset_clicked = True
                st.session_state["_map_level"] = preset.get("level")
                st.session_state["_map_free_only"] = preset.get("free_only", False)
                st.session_state["_map_high_value"] = preset.get("high_value", False)
                st.rerun()

        preset_level = st.session_state.get("_map_level")
        preset_free = st.session_state.get("_map_free_only", False)
        preset_hv = st.session_state.get("_map_high_value", False)

        # Apply filters
        filtered = spots_with_coords
        if sel_city:
            filtered = [s for s in filtered if s["city"] in sel_city]
        if sel_cat:
            filtered = [s for s in filtered if s["category"] in sel_cat]
        if sel_pass:
            filtered = [s for s in filtered if any(sel in p for p in s["passes"] for sel in sel_pass)]
        if name_q:
            filtered = [s for s in filtered if name_q in s.get("name", "")]
        if preset_level:
            filtered = [s for s in filtered if s.get("level") == preset_level]
        if preset_free:
            filtered = [s for s in filtered if s.get("price", 0) == 0]
        if preset_hv:
            filtered = [s for s in filtered if s.get("price", 0) > 0 and s.get("price", 0) <= 50]

        # Owned pass filter
        if _owned_pass_spots is not None:
            filtered = [s for s in filtered if s["name"] in _owned_pass_spots]

        filters = {
            "cities": sel_city,
            "categories": sel_cat,
            "passes": sel_pass,
        }

        # Stats row
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("显示景点", len(filtered))
        c2.metric("有坐标", len([s for s in filtered if s.get("lng")]))
        c3.metric("覆盖城市", len(set(s["city"] for s in filtered if s["city"])))
        c4.metric("总票价", f"¥{sum(s.get('price', 0) for s in filtered):,}")

        # --- View toggle ---
        view_mode = st.radio("视图模式", ["🗺️ 地图", "📋 列表", "📊 图表", "📈 数据洞察"], horizontal=True, label_visibility="collapsed")

        if view_mode == "🗺️ 地图":
            # Map — save to file and serve via local HTTP server
            html = _build_map_html(filtered, filters, height="650px", clear_filters=True)
            map_url = _save_map_html(html)
            st.components.v1.iframe(map_url, height=660)

            # --- 2. Stats charts below map ---
            st.divider()
            st.subheader("当前筛选统计")
            fc1, fc2 = st.columns(2)
            with fc1:
                # City distribution
                city_counts = {}
                for s in filtered:
                    c = s.get("city", "未知")
                    if c:
                        city_counts[c] = city_counts.get(c, 0) + 1
                if city_counts:
                    df_city = pd.DataFrame(list(city_counts.items()), columns=["城市", "景点数"])
                    df_city = df_city.sort_values("景点数", ascending=False)
                    fig_city = px.bar(df_city, x="城市", y="景点数", color="景点数",
                                      color_continuous_scale="Blues", text_auto=True)
                    fig_city.update_layout(showlegend=False, title="城市分布")
                    st.plotly_chart(fig_city, width="stretch")
            with fc2:
                # Category pie
                cat_counts = {}
                for s in filtered:
                    cat = s.get("category", "其他")
                    if cat:
                        cat_counts[cat] = cat_counts.get(cat, 0) + 1
                if cat_counts:
                    df_cat = pd.DataFrame(list(cat_counts.items()), columns=["分类", "数量"])
                    fig_cat = px.pie(df_cat, values="数量", names="分类", title="分类占比", hole=0.4)
                    st.plotly_chart(fig_cat, width="stretch")

            fp1, fp2 = st.columns(2)
            with fp1:
                # Price distribution
                prices = [s.get("price", 0) for s in filtered if s.get("price", 0) > 0]
                if prices:
                    df_price = pd.DataFrame(prices, columns=["票价"])
                    fig_price = px.histogram(df_price, x="票价", nbins=20,
                                             color_discrete_sequence=["#1a73e8"])
                    fig_price.update_layout(showlegend=False, title="票价分布")
                    st.plotly_chart(fig_price, width="stretch")
            with fp2:
                # Level distribution
                level_counts = {}
                for s in filtered:
                    lv = _LV_DISP.get(s.get("level"), s.get("level") or "未评级")
                    level_counts[lv] = level_counts.get(lv, 0) + 1
                if level_counts:
                    df_level = pd.DataFrame(list(level_counts.items()), columns=["等级", "数量"])
                    fig_level = px.bar(df_level, x="等级", y="数量", color="数量",
                                       color_continuous_scale="RdYlGn", text_auto=True)
                    fig_level.update_layout(showlegend=False, title="等级分布")
                    st.plotly_chart(fig_level, width="stretch")

        elif view_mode == "📋 列表":
            # Enhanced list view
            st.subheader(f"景点列表 ({len(filtered)}个)")
            # Sort controls
            sc1, sc2, sc3 = st.columns(3)
            with sc1:
                sort_by = st.selectbox("排序方式", ["票价降序", "票价升序", "等级优先", "名称"])
            with sc2:
                level_filter = st.selectbox("等级筛选", ["全部", "A5", "A4", "未评级"],
                                            format_func=lambda v: _LV_DISP.get(v, v))
            with sc3:
                if st.button("应用筛选", type="primary", width="stretch"):
                    pass  # rerun handled by selectbox change

            if level_filter != "全部":
                filtered = [s for s in filtered if s.get("level") == level_filter]

            sort_map = {"票价降序": ("price", True), "票价升序": ("price", False),
                        "等级优先": ("level", True), "名称": ("name", False)}
            skey, srev = sort_map.get(sort_by, ("price", True))
            level_order = {"A5": 3, "A4": 2, "A3": 1}
            if skey == "level":
                filtered.sort(key=lambda x: level_order.get(x.get("level", ""), 0), reverse=srev)
            else:
                filtered.sort(key=lambda x: x.get(skey, ""), reverse=srev)

            # Results table
            df_list = pd.DataFrame([{
                "景点": s["name"], "城市": s.get("city", ""), "分类": s.get("category", ""),
                "等级": _LV_DISP.get(s.get("level"), s.get("level") or "未评级"), "票价": s.get("price", 0),
                "包含年卡": len(s.get("passes", [])),
            } for s in filtered])
            st.dataframe(df_list, width="stretch", hide_index=True, height=500)

            # Card view
            cols = st.columns(3)
            for i, s in enumerate(filtered[:18]):
                with cols[i % 3]:
                    with st.container(border=True):
                        lv_badge = ""
                        if s.get("level") == "A5":
                            lv_badge = " `[5A]`"
                        elif s.get("level") == "A4":
                            lv_badge = " `[4A]`"
                        st.markdown(f"**{s['name']}**{lv_badge}")
                        st.caption(f"{s.get('city', '')} · {s.get('category', '')}")
                        st.caption(f"¥{s.get('price', 0)}")
                        if s.get("passes"):
                            st.caption(f"🎫 {', '.join(p.split('_')[0] for p in s['passes'][:2])}")
                        trip_names = {t["name"] for t in st.session_state.selected_trip_spots}
                        if s["name"] in trip_names:
                            st.caption("✅ 已在行程中")
                        else:
                            if st.button("➕ 加入行程", key=f"map_add_{s['name']}",
                                         type="secondary", width="stretch"):
                                st.session_state.selected_trip_spots.append({
                                    "name": s["name"], "lng": s.get("lng"),
                                    "lat": s.get("lat"), "city": s.get("city", ""),
                                    "area": s.get("area", ""), "category": s.get("category", ""),
                                    "price": s.get("price", 0), "level": s.get("level", ""),
                                    "passes": s.get("passes", []),
                                })
                                st.toast(f"已添加 {s['name']}", icon="✅")

        elif view_mode == "📊 图表":
            # --- 5. Data visualization mode ---
            st.subheader("数据可视化")

            # City heatmap: city × category
            city_cat_matrix = {}
            for s in filtered:
                c = s.get("city", "未知")
                cat = s.get("category", "其他")
                if c not in city_cat_matrix:
                    city_cat_matrix[c] = {}
                city_cat_matrix[c][cat] = city_cat_matrix[c].get(cat, 0) + 1

            df_heat = pd.DataFrame(city_cat_matrix).T.fillna(0).astype(int)
            if df_heat.shape[0] > 0 and df_heat.shape[1] > 0:
                fig_heat = px.imshow(df_heat.values, labels=dict(x="分类", y="城市", color="景点数"),
                                     x=df_heat.columns, y=df_heat.index,
                                     aspect="auto",
                                     color_continuous_scale="YlOrRd", text_auto=True)
                st.plotly_chart(fig_heat, width="stretch")

            # Price vs category scatter (jittered)
            st.divider()
            st.subheader("票价 × 等级散点图")
            scatter_data = []
            for s in filtered:
                lv = s.get("level") or "未评级"
                lv_num = {"A5": 5, "A4": 4, "A3": 3}.get(lv, 1)
                scatter_data.append({"景点": s["name"], "票价": s.get("price", 0),
                                     "等级分": lv_num, "城市": s.get("city", "")})
            if scatter_data:
                df_scatter = pd.DataFrame(scatter_data)
                fig_scatter = px.scatter(df_scatter, x="票价", y="等级分", color="城市",
                                         hover_data=["景点"], title="票价 vs 等级（颜色=城市）",
                                         size="票价", size_max=15)
                fig_scatter.update_layout(yaxis=dict(tickvals=[1, 3, 4, 5],
                                                     ticktext=["未评级", "3A", "4A", "5A"]))
                st.plotly_chart(fig_scatter, width="stretch")

        # Spot details (shows when marker clicked / search)
        st.divider()
        st.subheader("景点详情")
        c_search, c_btn = st.columns([3, 1])
        with c_search:
            search = st.text_input("搜索景点", placeholder="输入名称...")
        if search:
            matched = [s for s in filtered if search in s["name"]]
            if matched:
                st.caption(f"找到 {len(matched)} 个结果")
                for s in matched[:6]:
                    with st.container(border=True):
                        cc1, cc2 = st.columns([3, 2])
                        with cc1:
                            st.markdown(f"**{s['name']}**")
                            st.caption(f"{s['city']} {s['area']} · {s['category']} · {s['level'] or '未评级'}")
                        with cc2:
                            st.metric("票价", f"¥{s['price']}")
                        if s["passes"]:
                            st.caption(f"包含年卡: {', '.join(s['passes'])}")
                        # Trip link
                        trip_names = {t["name"] for t in st.session_state.selected_trip_spots}
                        if s["name"] in trip_names:
                            st.caption("✅ 已在行程中")
                        else:
                            if st.button("➕ 加入行程", key=f"search_add_{s['name']}",
                                         type="secondary", width="stretch"):
                                st.session_state.selected_trip_spots.append({
                                    "name": s["name"], "lng": s.get("lng"),
                                    "lat": s.get("lat"), "city": s.get("city", ""),
                                    "area": s.get("area", ""), "category": s.get("category", ""),
                                    "price": s.get("price", 0), "level": s.get("level", ""),
                                    "passes": s.get("passes", []),
                                })
                                st.toast(f"已添加 {s['name']}", icon="✅")


# ============================================================
# Page 2: Pass Comparison (map-based)
# ============================================================
        elif view_mode == "📈 数据洞察":
            from app.page_modules.data_overview_page import render_data_overview_page
            render_data_overview_page(dict(globals()))
