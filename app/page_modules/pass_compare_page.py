# -*- coding: utf-8 -*-
"""🎫 年卡对比（地图模式） — extracted VERBATIM from app/main.py.

render(ctx) injects main.py's namespace via globals().update(ctx). Do NOT
import app.main here (Streamlit re-execution trap).
"""


def render_pass_compare_page(ctx):
    globals().update(ctx)
    st.title("年卡对比（地图模式）")

    passes_list = sorted(set(s["pass_name"] for s in cleaned))
    selected = st.multiselect(
        "选择年卡对比（默认全部，可删减）",
        passes_list,
        default=passes_list,
    )

    if len(selected) >= 2:
        # Build spot sets per pass
        pass_spots = {}
        for p in selected:
            pass_spots[p] = {s["spot_name"] for s in cleaned if s["pass_name"] == p}

        # Overlap matrix
        st.subheader("重叠矩阵")
        matrix_data = []
        for i, p1 in enumerate(selected):
            row = {"年卡": p1.split("_")[0]}
            for j, p2 in enumerate(selected):
                if i == j:
                    row[p2.split("_")[0]] = f"{len(pass_spots[p2])} (总数)"
                else:
                    row[p2.split("_")[0]] = len(pass_spots[p1] & pass_spots[p2])
            matrix_data.append(row)
        st.dataframe(pd.DataFrame(matrix_data), width="stretch", hide_index=True)

        # 3-card Venn breakdown (7 regions)
        if len(selected) == 3:
            p1, p2, p3 = selected
            s1, s2, s3 = pass_spots[p1], pass_spots[p2], pass_spots[p3]
            n1, n2, n3 = (p.split("_")[0] for p in (p1, p2, p3))
            abc = s1 & s2 & s3
            ab = (s1 & s2) - abc
            ac = (s1 & s3) - abc
            bc = (s2 & s3) - abc
            only1 = s1 - s2 - s3
            only2 = s2 - s1 - s3
            only3 = s3 - s1 - s2
            st.subheader("三卡重叠分解")
            venn_df = pd.DataFrame([
                {"区域": f"仅{n1}", "景点数": len(only1)},
                {"区域": f"仅{n2}", "景点数": len(only2)},
                {"区域": f"仅{n3}", "景点数": len(only3)},
                {"区域": f"{n1}∩{n2}", "景点数": len(ab)},
                {"区域": f"{n1}∩{n3}", "景点数": len(ac)},
                {"区域": f"{n2}∩{n3}", "景点数": len(bc)},
                {"区域": "三卡共有", "景点数": len(abc)},
            ])
            fig_venn = px.bar(venn_df, x="区域", y="景点数", text="景点数",
                              color="景点数", color_continuous_scale="Blues")
            fig_venn.update_traces(textposition="outside")
            fig_venn.update_layout(height=350, showlegend=False, coloraxis_showscale=False)
            st.plotly_chart(fig_venn, width="stretch")
            if abc:
                with st.expander(f"三卡共有景点（{len(abc)}个）"):
                    st.write("、".join(sorted(abc)))

        # Stats for first 2
        if len(selected) == 2:
            p1, p2 = selected
            s1, s2 = pass_spots[p1], pass_spots[p2]
            overlap = s1 & s2
            c1, c2, c3 = st.columns(3)
            c1.metric(f"仅 {p1.split('_')[0]}", len(s1 - overlap))
            c2.metric("重叠景点", len(overlap))
            c3.metric(f"仅 {p2.split('_')[0]}", len(s2 - overlap))

            # Build colored markers for 2-card comparison
            comparison_markers = []
            for s in spots_with_coords:
                if not s.get("lng"):
                    continue
                in_1 = s["name"] in s1
                in_2 = s["name"] in s2
                if in_1 and in_2:
                    color = "#9C27B0"
                elif in_1:
                    color = "#2196F3"
                elif in_2:
                    color = "#FF9800"
                else:
                    continue

                comparison_markers.append({
                    "name": s["name"],
                    "lng": s["lng"],
                    "lat": s["lat"],
                    "category": s["category"],
                    "color": color,
                    "price": s["price"],
                    "city": s["city"],
                    "area": s["area"],
                    "level": s["level"],
                    "passes": s["passes"],
                    "usage": s.get("usage_limit", ""),
                    "notes": s.get("notes", ""),
                })

            st.caption(f"🟣 {len(overlap)} 重叠  🔵 {len(s1 - overlap)} 仅 {p1.split('_')[0]}  🟠 {len(s2 - overlap)} 仅 {p2.split('_')[0]}")

            filters = {"passes": [], "cities": [], "categories": []}
            js_key = st.secrets.get("amap_js_key", "") if hasattr(st, "secrets") else ""
            html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body, #container {{ width: 100%; height: 650px; }}
.amap-info-content {{ font-size: 13px; max-width: 300px; padding: 0 !important; }}
.amap-info-content .amap-info-tip {{ display: none; }}
.info-title {{ font-weight: 700; font-size: 16px; margin-bottom: 8px; color: #1a1a1a; line-height: 1.3; }}
.info-row {{ margin: 4px 0; color: #555; font-size: 13px; }}
.info-label {{ color: #888; margin-right: 4px; }}
.info-badge {{
    display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px;
    background: #f0f4ff; color: #4a6cf7; margin-right: 4px; margin-bottom: 3px;
}}
.info-badge.green {{ background: #e8f5e9; color: #2e7d32; }}
.info-badge.orange {{ background: #fff3e0; color: #e65100; }}
.info-badge.purple {{ background: #f3e5f5; color: #7b1fa2; }}
.info-price {{ font-size: 20px; font-weight: 700; color: #e53935; margin: 8px 0; }}
.info-divider {{ border: 0; border-top: 1px solid #f0f0f0; margin: 10px 0; }}
.info-actions {{ display: flex; gap: 8px; margin-top: 10px; }}
.btn-action {{
    flex: 1; border: none; border-radius: 8px; padding: 8px 6px; font-size: 12px;
    font-weight: 600; cursor: pointer; transition: all 0.15s ease;
    display: flex; align-items: center; justify-content: center; gap: 4px;
}}
.btn-action:active {{ transform: scale(0.96); }}
.btn-add {{ background: linear-gradient(135deg, #4caf50, #2e7d32); color: #fff; }}
.btn-review {{ background: linear-gradient(135deg, #1a73e8, #1565c0); color: #fff; }}
.info-pass-tag {{ display: inline-block; background: #fce4ec; color: #c62828; padding: 2px 8px; border-radius: 10px; font-size: 11px; margin: 2px 3px 2px 0; }}
@keyframes toastIn {{ from {{ opacity: 0; transform: translateY(20px); }} to {{ opacity: 1; transform: translateY(0); }} }}
@keyframes toastOut {{ from {{ opacity: 1; transform: translateY(0); }} to {{ opacity: 0; transform: translateY(-20px); }} }}
.legend {{
    position: fixed; bottom: 30px; right: 15px; z-index: 1000;
    background: rgba(255,255,255,0.92); border-radius: 8px; padding: 12px 14px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15); font-size: 12px;
}}
.legend-item {{ display: flex; align-items: center; margin: 3px 0; }}
.legend-dot {{ width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }}
</style>
<script src="https://webapi.amap.com/maps?v=2.0&key={js_key}"></script>
</head>
<body>
<div id="container"></div>
<div class="legend">
<div style="font-weight:bold;margin-bottom:6px;">对比图例</div>
<div class="legend-item"><div class="legend-dot" style="background:#9C27B0"></div>两张年卡都包含</div>
<div class="legend-item"><div class="legend-dot" style="background:#2196F3"></div>仅 {p1.split('_')[0]}</div>
<div class="legend-item"><div class="legend-dot" style="background:#FF9800"></div>仅 {p2.split('_')[0]}</div>
</div>
<script>
const markersData = {json.dumps(comparison_markers, ensure_ascii=True)};
window._amap = new AMap.Map('container', {{zoom: 8, center: [114.305, 30.593]}});
const map = window._amap;
const infoWindow = new AMap.InfoWindow({{offset: new AMap.Pixel(0, -18), autoMove: true}});
const _compP1 = "{p1.split('_')[0]}";
const _compP2 = "{p2.split('_')[0]}";

function makeMarkerContent(color) {{
    return `<div style="width:18px;height:18px;border-radius:50%;background:${{color}};border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,0.35);"></div>`;
}}

const markerList = markersData.map((m, i) => {{
    return new AMap.Marker({{
        position: [m.lng, m.lat],
        content: makeMarkerContent(m.color),
        offset: new AMap.Pixel(-9, -9),
        extData: m,
    }});
}});
markerList.forEach((marker, i) => {{
    marker.on('click', function(e) {{
        const d = e.target.getExtData();
        const inP1 = d.passes.some(p => p.includes(_compP1));
        const inP2 = d.passes.some(p => p.includes(_compP2));
        const compLabel = (inP1 && inP2) ? '<span class="info-badge purple">两张都含</span>'
            : inP1 ? `<span class="info-badge">仅${{_compP1}}</span>`
            : `<span class="info-badge orange">仅${{_compP2}}</span>`;
        const passesHtml = d.passes.length > 0
            ? d.passes.map(p => `<span class="info-pass-tag">${{p}}</span>`).join('')
            : '';
        const content = `
            <div style="padding: 14px 16px;">
                <div class="info-title">${{d.name}}</div>
                <div style="margin-bottom:6px;"><span class="info-badge green">${{d.category}}</span> ${{compLabel}}</div>
                <div class="info-row"><span class="info-label">位置</span>${{d.city}} ${{d.area}}</div>
                <div class="info-price">￥${{d.price}}</div>
                ${{passesHtml ? `
                    <div style="margin-bottom:6px;">
                        <div class="info-row" style="margin-bottom:4px;"><span class="info-label">包含年卡</span></div>
                        <div>${{passesHtml}}</div>
                    </div>
                ` : ''}}
                <hr class="info-divider">
                <div class="info-actions">
                    <button class="btn-action btn-add" onclick="window.addToTrip('{p1.split('_')[0]}','{p2.split('_')[0]}','${{d.name}}',${{i}})">
                        &#10133; 添加到行程
                    </button>
                    <button class="btn-action btn-review" onclick="window.loadReviews('${{d.name}}',${{i}})">
                        &#11088; 查看评价
                    </button>
                </div>
                <div id="reviews_comp_${{i}}" style="display:none;margin-top:10px;max-height:200px;overflow-y:auto;border-top:1px solid #f0f0f0;padding-top:8px;"></div>
            </div>
        `;
        infoWindow.setContent(content);
        infoWindow.open(map, e.target.getPosition());
        window.parent.postMessage({{type: 'marker_click', name: d.name}}, '*');
    }});
    map.add(marker);
}});

window.addToTrip = function(p1n, p2n, name, idx) {{
    const m = markersData.find(x => x.name === name);
    if (!m) return;
    fetch('/api/add_to_trip', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify(m)
    }}).then(r => r.json()).then(resp => {{
        const type = resp.action === 'added' ? 'success' : 'info';
        const icon = type === 'success' ? '&#10003;' : '&#8505;';
        const msg = resp.action === 'added' ? `已添加 ${{name}} 到行程` : `${{name}} 已在行程中`;
        window.showToast(icon + ' ' + msg, type);
    }}).catch(err => {{
        window.showToast('&#10007; 添加失败: ' + err.message, 'error');
    }});
}};

window.loadReviews = function(name, idx) {{
    const reviewsDiv = document.getElementById('reviews_comp_' + idx);
    if (!reviewsDiv) return;
    if (reviewsDiv.style.display === 'block') {{
        reviewsDiv.style.display = 'none';
        return;
    }}
    reviewsDiv.style.display = 'block';
    reviewsDiv.innerHTML = '<div style="color:#999;font-size:12px;padding:8px 0;text-align:center;">加载评价中...</div>';
    const m = markersData.find(x => x.name === name);
    const city = m ? m.city : '';
    fetch('/api/reviews?name=' + encodeURIComponent(name) + '&city=' + encodeURIComponent(city))
        .then(r => r.json())
        .then(data => {{
            if (!data.reviews || data.reviews.length === 0) {{
                reviewsDiv.innerHTML = '<div style="color:#999;font-size:13px;padding:12px 0;text-align:center;">暂无真实评价</div>';
                return;
            }}
            let html = '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">';
            html += `<div style="font-size:28px;font-weight:800;color:#ff9800;">${{data.overall_rating.toFixed(1)}}</div>`;
            html += '<div style="font-size:12px;color:#999;line-height:1.4;">/ 5.0<br>' + data.review_count + '条评价</div>';
            if (data.sources_used) {{
                data.sources_used.forEach(s => {{
                    const label = s === 'mafengwo' ? '马蜂窝' : s === 'amap' ? '高德' : s;
                    html += ` <span style="background:linear-gradient(135deg,#e3f2fd,#bbdefb);color:#1565c0;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600;">${{label}}</span>`;
                }});
            }}
            html += '</div>';
            data.reviews.forEach(r => {{
                const stars = '★'.repeat(Math.round(r.rating)) + '☆'.repeat(5 - Math.round(r.rating));
                html += `<div style="background:#fafafa;border-radius:8px;padding:10px;margin-bottom:8px;font-size:12px;">`;
                html += `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">`;
                html += `<span style="color:#ff9800;font-size:13px;">${{stars}}</span>`;
                html += `<span style="color:#666;font-size:11px;">${{r.author || '匿名'}} · ${{r.date || ''}}</span>`;
                html += `</div>`;
                const text = r.text.length > 120 ? r.text.substring(0, 120) + '...' : r.text;
                html += `<div style="color:#444;line-height:1.6;font-size:12px;">${{text}}</div>`;
                html += `</div>`;
            }});
            reviewsDiv.innerHTML = html;
        }})
        .catch(err => {{
            reviewsDiv.innerHTML = `<div style="color:#f44336;font-size:12px;padding:12px 0;text-align:center;">加载失败: ${{err.message}}</div>`;
        }});
}};

window.showToast = function(message, type) {{
    const existing = document.querySelectorAll('.trip-toast');
    existing.forEach(el => el.remove());
    const colors = {{
        success: {{bg: '#e8f5e9', border: '#4caf50', text: '#2e7d32'}},
        info: {{bg: '#e3f2fd', border: '#2196f3', text: '#1565c0'}},
        error: {{bg: '#ffebee', border: '#f44336', text: '#c62828'}},
    }};
    const c = colors[type] || colors.info;
    const toast = document.createElement('div');
    toast.className = 'trip-toast';
    toast.innerHTML = message;
    toast.style.cssText = `
        position: fixed; bottom: 80px; right: 20px; z-index: 9999;
        background: ${{c.bg}}; border-left: 4px solid ${{c.border}};
        color: ${{c.text}}; padding: 12px 20px; border-radius: 8px;
        font-size: 13px; font-weight: 600; max-width: 320px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.15);
        animation: toastIn 0.3s ease-out forwards;
    `;
    document.body.appendChild(toast);
    setTimeout(() => {{
        toast.style.animation = 'toastOut 0.3s ease-in forwards';
        setTimeout(() => toast.remove(), 300);
    }}, 2500);
}};
</script>
</body>
</html>"""
            comparison_url = _save_map_html(html)
            st.components.v1.iframe(comparison_url, height=660)

            # Overlap spots list
            with st.expander("重叠景点列表"):
                overlap_spots = [s for s in spots_with_coords if s["name"] in overlap]
                if overlap_spots:
                    df = pd.DataFrame([{
                        "景点": s["name"], "城市": s["city"], "票价": s["price"], "类型": s["category"],
                    } for s in overlap_spots])
                    st.dataframe(df, width="stretch", hide_index=True)

        else:
            # 3+ cards: show overview stats, no map
            st.info("地图模式仅支持2张年卡对比。当前选择了 {} 张，已显示重叠矩阵。".format(len(selected)))
            # Show per-pass stats
            st.subheader("各卡概览")
            cols = st.columns(min(len(selected), 5))
            for i, p in enumerate(selected):
                with cols[i % 5]:
                    with st.container(border=True):
                        st.markdown(f"**{p.split('_')[0]}**")
                        st.metric("景点", len(pass_spots[p]))

        # ================================================================
        # Tabbed analysis sections (always shown for 2+ cards)
        # ================================================================

        # Build pass_name -> pass_id mapping
        pass_name_to_id = {}
        for node in graph_data["nodes"]:
            if node.get("type") == "pass":
                pass_name_to_id[node["name"]] = node["id"]

        selected_ids = [pass_name_to_id.get(p) for p in selected if pass_name_to_id.get(p)]
        if not selected_ids:
            st.stop()

        pi_full = build_pass_info(graph_data, cleaned)

        # Precompute all data once
        savings_data = compute_savings(pi_full)
        exclusive_data = compute_exclusive_spots(pi_full, selected_ids)
        usage_limits = compute_usage_limits(pi_full)
        usage_map = {ul["pass_id"]: ul for ul in usage_limits}
        rankings = compute_cost_performance_ranking(pi_full)
        combos = compute_optimal_combinations(pi_full, max_cards=3)
        limit_details = get_limit_detail(pi_full, selected_ids)

        # Main tabs for organization
        main_tabs = st.tabs(["📊 核心对比", "🎯 组合推荐", "📍 场景分析", "📋 限制明细"])

        # ================================================================
        # Tab 1: 核心对比
        # ================================================================
        with main_tabs[0]:
            # Radar chart
            comp_data = []
            for pid in selected_ids:
                pi = pi_full[pid]
                sv = savings_data.get(pid, {})
                ul = usage_map.get(pid, {})
                exc = exclusive_data.get(pid, [])
                comp_data.append({
                    "年卡": pi["display"],
                    "卡价": pi["price"],
                    "景点数": pi["spot_count"],
                    "城市数": pi["city_count"],
                    "总价值": pi["total_price"],
                    "节省": sv.get("savings", 0),
                    "性价比": pi["value_ratio"],
                    "5A": pi["a5_count"],
                    "4A": pi["a4_count"],
                    "独有景点": len(exc),
                    "无限制": ul.get("unlimited", 0),
                })
            df_comp = pd.DataFrame(comp_data)
            st.subheader("参数对比")
            st.dataframe(df_comp, width="stretch", hide_index=True)

            st.subheader("多维对比")
            metrics = ["景点数", "5A", "节省", "性价比", "城市数", "独有景点"]
            radar_rows = []
            for _, row in df_comp.iterrows():
                radar_row = {"年卡": row["年卡"]}
                for m in metrics:
                    mx = df_comp[m].max()
                    mn = df_comp[m].min()
                    radar_row[m] = round((row[m] - mn) / (mx - mn), 2) if mx != mn else 1.0
                radar_rows.append(radar_row)
            df_radar = pd.DataFrame(radar_rows)

            fig = go.Figure()
            colors = px.colors.qualitative.Set1
            for i, row in df_radar.iterrows():
                values = [row[m] for m in metrics]
                values.append(values[0])
                fig.add_trace(go.Scatterpolar(
                    r=values, theta=metrics + [metrics[0]],
                    fill="toself", name=row["年卡"],
                    line_color=colors[i % len(colors)],
                ))
            fig.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
            )
            st.plotly_chart(fig, width="stretch")

            # Overlap analysis
            if len(selected_ids) >= 2:
                st.subheader("景点重叠分析")
                matrix_data = []
                for i, p1 in enumerate(selected_ids):
                    row_d = {"年卡": pi_full[p1]["display"]}
                    for j, p2 in enumerate(selected_ids):
                        s1 = set(pi_full[p1]["spots"])
                        s2 = set(pi_full[p2]["spots"])
                        if i == j:
                            row_d[pi_full[p2]["display"]] = f"{len(s1)} (总数)"
                        else:
                            row_d[pi_full[p2]["display"]] = len(s1 & s2)
                    matrix_data.append(row_d)
                st.dataframe(pd.DataFrame(matrix_data), width="stretch", hide_index=True)

                if len(selected_ids) == 2:
                    p1n, p2n = selected_ids[0], selected_ids[1]
                    s1s, s2s = set(pi_full[p1n]["spots"]), set(pi_full[p2n]["spots"])
                    ov = s1s & s2s
                    o1, o2, o3 = st.columns(3)
                    o1.metric(f"仅 {pi_full[p1n]['display']}", len(s1s - ov))
                    o2.metric("重叠景点", len(ov))
                    o3.metric(f"仅 {pi_full[p2n]['display']}", len(s2s - ov))

            # Usage limits table
            st.subheader("使用限制")
            usage_rows = []
            for pid in selected_ids:
                ul = usage_map.get(pid, {})
                usage_rows.append({
                    "年卡": pi_full[pid]["display"],
                    "总景点": ul.get("total", 0),
                    "无限制": ul.get("unlimited", 0),
                    "季节限制": ul.get("seasonal", 0),
                    "需预约": ul.get("appointment_needed", 0),
                    "不含节假日": ul.get("holiday_excluded", 0),
                })
            st.dataframe(pd.DataFrame(usage_rows), width="stretch", hide_index=True)

        # ================================================================
        # Tab 2: 组合推荐
        # ================================================================
        with main_tabs[1]:
            # Rankings
            st.subheader("🏆 年卡性价比排名")
            c1, c2, c3 = st.columns(3)
            with c1:
                st.caption("**每元景点数** (越多越好)")
                for r in rankings["per_spot_cost"][:5]:
                    st.caption(f"{r['display']}: {r['score']:.1f}")
            with c2:
                st.caption("**5A景点密度** (占比%)")
                for r in rankings["a5_density"][:5]:
                    st.caption(f"{r['display']}: {r['score']:.1f}%")
            with c3:
                st.caption("**城市覆盖度** (占比%)")
                for r in rankings["city_coverage"][:5]:
                    st.caption(f"{r['display']}: {r['score']:.1f}%")

            # Combo recommendations
            st.divider()
            st.subheader("🎯 最优组合推荐")
            st.caption("按「节省金额/总价」效率排序")
            if combos:
                tab2c, tab3c = st.tabs(["2卡组合 Top10", "3卡组合 Top10"])
                with tab2c:
                    for i, c in enumerate([x for x in combos if len(x["pass_ids"]) == 2][:10]):
                        with st.container(border=True):
                            st.markdown(f"**#{i+1}**  {' + '.join(c['passes'])}")
                            cc1, cc2, cc3, cc4 = st.columns(4)
                            cc1.metric("总价", f"¥{c['total_price']}")
                            cc2.metric("去重景点", f"{c['unique_spots']}个")
                            cc3.metric("节省", f"¥{c['savings']:,}")
                            cc4.metric("效率", f"{c['efficiency_score']:.1f}x")
                with tab3c:
                    for i, c in enumerate([x for x in combos if len(x["pass_ids"]) == 3][:10]):
                        with st.container(border=True):
                            st.markdown(f"**#{i+1}**  {' + '.join(c['passes'])}")
                            cc1, cc2, cc3, cc4 = st.columns(4)
                            cc1.metric("总价", f"¥{c['total_price']}")
                            cc2.metric("去重景点", f"{c['unique_spots']}个")
                            cc3.metric("节省", f"¥{c['savings']:,}")
                            cc4.metric("效率", f"{c['efficiency_score']:.1f}x")

            # Complement suggestions
            if len(selected_ids) >= 2:
                st.divider()
                st.subheader("💡 补卡建议")
                comps = compute_complementarity(selected_ids, pi_full)
                if comps:
                    st.caption("已选基础上，补充以下年卡可最大化收益:")
                    for c in comps[:3]:
                        with st.container(border=True):
                            cc1, cc2, cc3, cc4 = st.columns(4)
                            cc1.metric("补卡", c["display"])
                            cc2.metric("新增景点", f"{c['new_spots_count']}个")
                            cc3.metric("新增价值", f"¥{c['new_spots_value']:,}")
                            cc4.metric("互补度", f"{c['complement_score']}分")

        # ================================================================
        # Tab 3: 场景分析
        # ================================================================
        with main_tabs[2]:
            all_scene_cities = sorted(set(s["city"] for s in spots_with_coords if s["city"]))
            all_scene_levels = ["A5", "A4", "未评级"]
            all_scene_cats = sorted(set(s["category"] for s in spots_with_coords if s["category"]))

            sc1, sc2, sc3 = st.columns(3)
            with sc1:
                sel_scene_city = st.selectbox("按城市筛选", ["不限"] + all_scene_cities)
            with sc2:
                sel_scene_level = st.selectbox("按等级筛选", ["不限"] + all_scene_levels)
            with sc3:
                sel_scene_cat = st.selectbox("按类型筛选", ["不限"] + all_scene_cats)

            city_f = None if sel_scene_city == "不限" else sel_scene_city
            level_f = None if sel_scene_level == "不限" else sel_scene_level
            cat_f = None if sel_scene_cat == "不限" else sel_scene_cat

            scene_result = compute_scene_analysis(pi_full, city=city_f, level=level_f, category=cat_f)
            if scene_result:
                df_scene = pd.DataFrame(scene_result)
                df_scene = df_scene.rename(columns={
                    "display": "年卡", "price": "卡价", "spot_count": "景点数",
                    "total_value": "总价值", "savings": "节省",
                    "a5_count": "5A", "a4_count": "4A",
                })
                st.dataframe(df_scene[["年卡", "卡价", "景点数", "总价值", "节省", "5A", "4A"]],
                             width="stretch", hide_index=True)
            else:
                st.caption("当前筛选条件无匹配景点")

            # Route feasibility
            st.divider()
            st.subheader("🚗 路线可行性")
            route_info = compute_route_feasibility(pi_full, selected_ids, spots_with_coords)
            rc1, rc2, rc3, rc4 = st.columns(4)
            rc1.metric("最远距离", f"{route_info['max_distance_km']:.0f} km")
            rc2.metric("平均距离", f"{route_info['avg_distance_km']:.0f} km")
            rc3.metric("覆盖城市", f"{route_info['city_count']} 个")
            rc4.metric("推荐", route_info["recommendation"])
            if route_info["farthest_pair"][0]:
                st.caption(f"最远景点对: {route_info['farthest_pair'][0]} ↔ {route_info['farthest_pair'][1]}")
            if route_info["city_span"]:
                st.caption(f"城市跨度: {' → '.join(route_info['city_span'])}")

            # City heatmap
            st.divider()
            st.subheader("城市 × 年卡热力图")
            df_heat = compute_city_pass_heatmap(pi_full, selected_ids)
            df_heat_rn = df_heat.rename(columns={pid: pi_full[pid]["display"] for pid in df_heat.columns})
            fig_heat = px.imshow(df_heat_rn, labels=dict(x="年卡", y="城市", color="景点数"),
                                  color_continuous_scale="YlOrRd", text_auto=True)
            fig_heat.update_layout(height=max(200, len(df_heat_rn) * 30))
            st.plotly_chart(fig_heat, width="stretch")

        # ================================================================
        # Tab 4: 限制明细
        # ================================================================
        with main_tabs[3]:
            # Limit details
            st.subheader("限制景点明细")
            for ld in limit_details:
                if ld["limits"]:
                    with st.expander(f"{ld['display']} — {len(ld['limits'])} 个限制景点"):
                        for lim in ld["limits"][:20]:
                            types_str = " · ".join(lim["restriction_types"])
                            st.caption(f"- **{lim['spot_name']}**: {types_str}")
                            if lim["detail"]:
                                st.caption(f"  {lim['detail'][:100]}")
                        if len(ld["limits"]) > 20:
                            st.caption(f"... 还有 {len(ld['limits']) - 20} 个")
                else:
                    with st.expander(f"{ld['display']} — 无限制景点"):
                        st.caption("所有景点均无特殊限制")

            # Exclusive spots
            st.subheader("独有景点")
            for pid in selected_ids:
                exc_spots = exclusive_data.get(pid, [])[:10]
                exc_value = sum(s["price"] for s in exclusive_data.get(pid, []))
                label = pi_full[pid]["display"]
                with st.expander(f"{label} — 独有 {len(exclusive_data.get(pid, []))}个 (总价值 ¥{exc_value:,})"):
                    if exc_spots:
                        df_exc = pd.DataFrame([
                            {"景点": s["name"], "城市": s["city"], "等级": s["level"] or "未评级",
                             "票价": s["price"], "分类": s["category"]}
                            for s in exc_spots
                        ])
                        st.dataframe(df_exc, width="stretch", hide_index=True)
                    else:
                        st.caption("暂无独有景点")
