"""Streamlit app: knowledge graph with AMap visualization."""

import json
import os
import sys
import time
from collections import defaultdict
import re
import hashlib
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.loader import load_all_passes
from src.cleaner import clean_all_spots
from src.classifier import classify_spot
from src.aligner import align_spots
from src.graph_builder import build_graph, graph_to_json
from src.geocoder import load_coordinates, save_coordinates, batch_geocode
from src.analyzer import price_analysis, category_distribution, pass_analysis, pass_overlap, seasonal_analysis, top_value_spots
from src.pass_comparator import (
    build_pass_info,
    compute_savings,
    compute_exclusive_spots,
    compute_complementarity,
    compute_city_pass_heatmap,
    compute_usage_limits,
    compute_optimal_combinations,
    compute_scene_analysis,
    compute_route_feasibility,
    compute_cost_performance_ranking,
    get_limit_detail,
)
from src.recommender import recommend_by_season
from src.seasonal_recommender import (
    get_seasonal_recommendations,
    MONTH_TO_SEASON,
    SEASON_NAMES,
    SEASON_EMOJI,
)
from src.seasonal_analytics import (
    compute_12_month_overview,
    compute_seasonal_pass_ranking,
    compute_category_distribution,
    find_seasonal_exclusive_spots,
    compute_seasonal_calendar,
)
from src.trip_planner.llm_client import generate_spot_recommendation
from src.trip_planner.route_optimizer import nearest_neighbor_optimize, compute_route, haversine_distance, generate_route_options
from src.trip_planner.auto_assigner import assign_spots_to_days
from src.trip_planner.nearby_search import search_nearby_hotels, search_nearby_restaurants, geocode_address
from src.trip_planner.plan_manager import save_plan, load_plan, list_plans, delete_plan, save_days_plan
from src.trip_planner.play_duration import estimate_play_duration, get_opening_hours
from src.trip_planner.review_aggregator import aggregate_spot_reviews
from src.trip_planner.pass_coverage import compute_pass_coverage
from src.trip_planner.time_aware_assigner import assign_spots_with_duration
from src.trip_planner.cost_estimator import estimate_trip_cost
from src.weekend_planner import plan_weekend
from src.budget_planner import plan_budget
from src.trip_planner.seasonal_checker import check_seasonal_availability
from src.trip_planner.smart_selector import import_pass_spots, get_all_passes_info, get_persona_recommendations, PERSONA_PROFILES
from src.trip_planner.timeline_builder import build_day_timeline

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DATA_DIR = os.path.join(PROJECT_ROOT, "raw_data")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
DEFAULT_MAP_PORT = 18793


def _resolve_map_port() -> int:
    """map_server 绑定失败会自动向后换端口，并把实际端口写进
    data/map_server.port；这里优先读文件，退回默认值。
    """
    port_file = os.path.join(DATA_DIR, "map_server.port")
    try:
        with open(port_file, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return DEFAULT_MAP_PORT
os.makedirs(STATIC_DIR, exist_ok=True)

# Start a local HTTP server for map HTML files (once per process)
# Launch map_server.py as a separate subprocess to avoid Streamlit thread issues
def _start_map_server():
    """Launch the standalone map server as a subprocess."""
    import subprocess, logging
    log_path = os.path.join(PROJECT_ROOT, 'data', 'map_server.log')
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    # Check if already running: probe both the resolved port and the default,
    # since a previously-negotiated server may sit on a non-default port.
    import socket

    def _listening(port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            return sock.connect_ex(('127.0.0.1', port)) == 0
        finally:
            sock.close()

    resolved = _resolve_map_port()
    if _listening(resolved) or _listening(DEFAULT_MAP_PORT):
        return

    map_server_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'map_server.py')
    log_file = open(log_path, 'a')
    subprocess.Popen(
        [sys.executable, map_server_path],
        stdout=log_file,
        stderr=log_file,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    )
    with open(log_path, 'a') as f:
        f.write(f"[{pd.Timestamp.now()}] launched map_server subprocess\n")
    # map_server picks its port after binding; wait for the port file so the
    # first iframe URL points at the right port.
    for _ in range(50):
        if _resolve_map_port() != resolved or _listening(_resolve_map_port()):
            break
        time.sleep(0.2)


_start_map_server()

# ============================================================
# Category colors for map markers
# ============================================================
CATEGORY_COLORS = {
    "自然景观": "#4CAF50",
    "人文历史": "#FF9800",
    "主题乐园": "#E91E63",
    "温泉康养": "#2196F3",
    "户外运动": "#9C27B0",
    "演艺演出": "#F44336",
    "休闲农业": "#8BC34A",
    "城市娱乐": "#00BCD4",
    "其他": "#9E9E9E",
}

# City center coordinates for fallback
CITY_COORDS = {
    "武汉": [114.305, 30.593],
    "黄冈": [114.873, 30.447],
    "鄂州": [114.894, 30.388],
    "孝感": [113.917, 30.926],
    "咸宁": [114.302, 29.841],
    "黄石": [115.038, 30.220],
    "襄阳": [112.122, 32.042],
    "宜昌": [111.286, 30.700],
    "荆州": [112.183, 30.335],
    "荆门": [112.199, 31.035],
    "随州": [113.373, 31.690],
    "十堰": [110.779, 32.645],
    "恩施": [109.487, 30.283],
    "仙桃": [113.444, 30.365],
    "天门": [113.166, 30.653],
    "潜江": [112.897, 30.414],
    "神农架": [110.671, 31.744],
    "长沙": [112.983, 28.193],
    "南昌": [115.858, 28.683],
    "合肥": [117.227, 31.821],
    "岳阳": [113.128, 29.357],
    "九江": [115.980, 29.712],
    "安庆": [117.053, 30.531],
    "黄山": [118.337, 29.711],
    "株洲": [113.134, 27.827],
    "湘潭": [112.944, 27.829],
    "抚州": [116.358, 27.947],
    "宜春": [114.417, 27.801],
    "鹰潭": [117.033, 28.238],
}

# ============================================================
# Data loading
# ============================================================

@st.cache_data(ttl=3600)
def load_data():
    """Load and process all data."""
    raw_records = load_all_passes(RAW_DATA_DIR)
    cleaned = clean_all_spots(raw_records)
    for spot in cleaned:
        spot["_classification"] = classify_spot(spot["spot_name"], spot.get("notes_raw", ""))
    alignment = align_spots(cleaned)
    G = build_graph(cleaned, alignment)
    graph_data = graph_to_json(G)
    return raw_records, cleaned, alignment, graph_data


def get_or_create_data():
    """Load from cache if exists, otherwise run pipeline."""
    graph_path = os.path.join(DATA_DIR, "knowledge_graph.json")
    cleaned_path = os.path.join(DATA_DIR, "cleaned_spots.json")
    alignment_path = os.path.join(DATA_DIR, "alignment_report.json")

    if os.path.exists(graph_path) and os.path.exists(cleaned_path) and os.path.exists(alignment_path):
        with open(cleaned_path, "r", encoding="utf-8") as f:
            cleaned = json.load(f)
        with open(alignment_path, "r", encoding="utf-8") as f:
            alignment = json.load(f)
        with open(graph_path, "r", encoding="utf-8") as f:
            graph_data = json.load(f)
        raw_records = load_all_passes(RAW_DATA_DIR)
        return raw_records, cleaned, alignment, graph_data
    else:
        return load_data()


def get_unique_spots_with_coords(cleaned, coordinates):
    """Build unique spot list with coordinates, one record per spot."""
    seen = {}
    for s in cleaned:
        name = s["spot_name"]
        if name not in seen or s["price"] > seen[name].get("price", 0):
            seen[name] = s

    spots = []
    for name, s in seen.items():
        coord = coordinates.get(name, {})
        city_coord = CITY_COORDS.get(s.get("city", ""), None)
        spot = {
            "name": name,
            "city": s.get("city", ""),
            "area": s.get("area", ""),
            "level": s.get("level") or "",
            "price": s.get("price", 0),
            "category": s.get("_classification", {}).get("category", "其他"),
            "sub_category": s.get("_classification", {}).get("sub_category", ""),
            "tags": s.get("_classification", {}).get("tags", []),
            "lng": coord.get("lng", None),
            "lat": coord.get("lat", None),
            "city_lng": city_coord[0] if city_coord else None,
            "city_lat": city_coord[1] if city_coord else None,
            "passes": [],
            "usage_limit": s.get("usage_limit_raw", ""),
            "notes": s.get("notes_raw", ""),
        }
        spots.append(spot)

    # Collect passes per spot
    pass_map = {}
    for s in cleaned:
        name = s["spot_name"]
        pn = s.get("pass_name", "")
        if name not in pass_map:
            pass_map[name] = []
        if pn and pn not in pass_map[name]:
            pass_map[name].append(pn)

    for spot in spots:
        spot["passes"] = pass_map.get(spot["name"], [])

    return spots


# ============================================================
# Map HTML generation
# ============================================================

def _build_map_html(spots_with_coords, filters=None, height="700px", clear_filters=False):
    """Generate AMap HTML with markers."""
    js_key = st.secrets.get("amap_js_key", "") if hasattr(st, "secrets") else ""

    # When clear_filters=True, don't apply JS-side filtering (Python already filtered)
    skip_js_filter = clear_filters

    # Sanitize helper: strip control chars, garbled bytes, and HTML-breaking sequences
    def _clean(s):
        if not s:
            return ""
        cleaned = "".join(c for c in s if c.isprintable() or c in "\n\r\t")
        # Prevent breaking </script> tag in HTML template
        return cleaned.replace("</script>", "<\\/script>")

    # Prepare marker data (only spots with coordinates)
    markers = []
    for s in spots_with_coords:
        if s.get("lng") and s.get("lat"):
            markers.append({
                "name": s["name"],
                "lng": s["lng"],
                "lat": s["lat"],
                "category": s["category"],
                "color": CATEGORY_COLORS.get(s["category"], "#9E9E9E"),
                "price": s["price"],
                "city": s["city"],
                "area": s["area"],
                "level": s["level"],
                "passes": s["passes"],
                "usage": _clean(s.get("usage_limit", "")),
                "notes": _clean(s.get("notes", "")),
            })

    # When Python already filtered, pass empty arrays to JS to avoid double-filtering bugs
    # But always pass selected cities for auto-center
    if skip_js_filter:
        filter_passes = "[]"
        filter_cities = "[]"
        filter_cats = "[]"
        selected_city_center = json.dumps(filters.get("cities", []), ensure_ascii=True) if filters else "[]"
    else:
        filter_passes = json.dumps(filters.get("passes", []), ensure_ascii=False) if filters else "[]"
        filter_cities = json.dumps(filters.get("cities", []), ensure_ascii=False) if filters else "[]"
        filter_cats = json.dumps(filters.get("categories", []), ensure_ascii=False) if filters else "[]"
        selected_city_center = filter_cities

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body, #container {{ width: 100%; height: {height}; }}
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
.btn-add:hover {{ background: linear-gradient(135deg, #43a047, #1b5e20); }}
.btn-review {{ background: linear-gradient(135deg, #1a73e8, #1565c0); color: #fff; }}
.btn-review:hover {{ background: linear-gradient(135deg, #1976d2, #0d47a1); }}
.btn-fix {{ background: #f5f5f5; color: #666; flex: 0 0 auto; padding: 8px 10px; }}
.btn-fix:hover {{ background: #eee; }}
.info-pass-tag {{ display: inline-block; background: #fce4ec; color: #c62828; padding: 2px 8px; border-radius: 10px; font-size: 11px; margin: 2px 3px 2px 0; }}
.legend {{
    position: fixed; bottom: 30px; right: 15px; z-index: 1000;
    background: rgba(255,255,255,0.92); border-radius: 8px; padding: 12px 14px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15); font-size: 12px;
}}
.legend-item {{ display: flex; align-items: center; margin: 3px 0; }}
.legend-dot {{ width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; flex-shrink: 0; }}
.stats-bar {{
    position: fixed; top: 10px; left: 50%; transform: translateX(-50%); z-index: 1000;
    background: rgba(255,255,255,0.95); border-radius: 8px; padding: 8px 16px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.12); font-size: 13px; display: flex; gap: 16px;
}}
.stats-bar span {{ color: #333; }}
.stats-bar b {{ color: #1a73e8; }}
@keyframes toastIn {{ from {{ opacity: 0; transform: translateY(20px); }} to {{ opacity: 1; transform: translateY(0); }} }}
@keyframes toastOut {{ from {{ opacity: 1; transform: translateY(0); }} to {{ opacity: 0; transform: translateY(20px); }} }}
</style>
<script src="https://webapi.amap.com/maps?v=2.0&key={js_key}&plugin=AMap.MarkerCluster"></script>
</head>
<body>
<div id="container"></div>
<div class="stats-bar" id="statsBar">加载中...</div>
<div class="legend" id="legend"></div>
<script>
const markersData = {json.dumps(markers, ensure_ascii=True)};
const cityCoords = {json.dumps(CITY_COORDS)};
const selectedCityCenter = {selected_city_center};
const filterPasses = {filter_passes};
const filterCities = {filter_cities};
const filterCats = {filter_cats};

function initMap() {{
    window._amap = new AMap.Map('container', {{
        zoom: 10,
        center: [114.305, 30.593],
    }});
    // Alias for convenience
    const map = window._amap;

    // Single reusable InfoWindow
    const infoWindow = new AMap.InfoWindow({{offset: new AMap.Pixel(0, -18), autoMove: true}});

    // Build legend
    const legendEl = document.getElementById('legend');
    const categories = [...new Set(markersData.map(m => m.category))];
    legendEl.innerHTML = '<div style="font-weight:bold;margin-bottom:6px;">景点类型</div>' +
        categories.map(cat => {{
            const color = markersData.find(m => m.category === cat)?.color || '#999';
            return `<div class="legend-item"><div class="legend-dot" style="background:${{color}}"></div>${{cat}}</div>`;
        }}).join('');

    // Filter markers
    function filteredMarkers() {{
        return markersData.filter(m => {{
            if (filterPasses.length > 0 && !m.passes.some(p => filterPasses.some(fp => p.includes(fp)))) return false;
            if (filterCities.length > 0 && !filterCities.includes(m.city)) return false;
            if (filterCats.length > 0 && !filterCats.includes(m.category)) return false;
            return true;
        }});
    }}

    // Dimmed marker content: small gray dot
    const dimmedContent = '<div style="width:8px;height:8px;border-radius:50%;background:#bbb;opacity:0.4;border:1px solid #999;"></div>';


    // Shared spot-click handler factory (direct markers + cluster散点共用)
    function attachSpotClick(marker, idx) {{
            // Compute index for coord correction UI (use original index in markersData)
            marker.on('click', function(e) {{
                const d = e.target.getExtData();
                const levelBadge = d.level
                    ? `<span class="info-badge orange">${{d.level}}</span>`
                    : '<span class="info-badge">未评级</span>';
                const catBadge = `<span class="info-badge green">${{d.category}}</span>`;
                const passesHtml = d.passes.length > 0
                    ? d.passes.map(p => `<span class="info-pass-tag">${{p}}</span>`).join('')
                    : '';
                const content = `
                    <div style="padding: 14px 16px;">
                        <div class="info-title">${{d.name}}</div>
                        <div style="margin-bottom:6px;">${{catBadge}} ${{levelBadge}}</div>
                        <div class="info-row"><span class="info-label">位置</span>${{d.city}} ${{d.area}}</div>
                        ${{d.usage ? `<div class="info-row"><span class="info-label">使用</span>${{d.usage}}</div>` : ''}}
                        <div class="info-price">￥${{d.price}}</div>
                        ${{passesHtml ? `
                            <div style="margin-bottom:6px;">
                                <div class="info-row" style="margin-bottom:4px;"><span class="info-label">包含年卡</span></div>
                                <div>${{passesHtml}}</div>
                            </div>
                        ` : ''}}
                        <hr class="info-divider">
                        <div class="info-actions">
                            <button class="btn-action btn-add" onclick="window.addToTrip('${{d.name}}',${{idx}})">
                                &#10133; 添加到行程
                            </button>
                            <button class="btn-action btn-review" onclick="window.loadReviews('${{d.name}}',${{idx}})">
                                &#11088; 查看评价
                            </button>
                            <button class="btn-action btn-fix" onclick="document.getElementById('coordSearch_${{idx}}').style.display='block';this.closest('.info-actions').style.display='none';">
                                &#128205;
                            </button>
                        </div>
                        <div id="reviews_${{idx}}" style="display:none;margin-top:10px;max-height:200px;overflow-y:auto;border-top:1px solid #f0f0f0;padding-top:8px;"></div>
                        <div id="coordSearch_${{idx}}" style="display:none;margin-top:10px;">
                            <div style="display:flex;gap:6px;margin-bottom:6px;">
                                <input type="text" id="coordInput_${{idx}}" placeholder="输入景点名称搜索..." value="${{d.name}}"
                                    style="flex:1;font-size:12px;padding:6px 10px;border:1px solid #e0e0e0;border-radius:6px;outline:none;"
                                    onkeydown="if(event.key==='Enter')window.correctCoord('${{d.name}}',${{idx}})">
                                <button onclick="window.correctCoord('${{d.name}}',${{idx}})"
                                    style="background:#1a73e8;color:#fff;border:none;border-radius:6px;padding:6px 14px;font-size:12px;cursor:pointer;font-weight:600;">
                                    搜索
                                </button>
                            </div>
                            <div id="coordResults_${{idx}}"></div>
                        </div>
                    </div>
                `;
                infoWindow.setContent(content);
                infoWindow.open(map, e.target.getPosition());
                window.parent.postMessage({{type: 'marker_click', name: d.name}}, '*');
            }});
    }}

    // Create markers directly on map; cluster when unfiltered & dense
    let currentMarkers = [];
    let cluster = null;
    function renderMarkers() {{
        // Remove old markers / cluster
        map.remove(currentMarkers);
        if (cluster) {{ cluster.setMap(null); cluster = null; }}
        currentMarkers = [];

        const filtered = filteredMarkers();
        const hasFilter = filterPasses.length > 0 || filterCities.length > 0 || filterCats.length > 0;
        const filteredNames = new Set(filtered.map(m => m.name));

        for (let i = 0; i < markersData.length; i++) {{
            const m = markersData[i];
            const isMatch = !hasFilter || filteredNames.has(m.name);

            const markerOpts = {{
                position: [m.lng, m.lat],
                extData: m,
            }};
            if (!isMatch) {{
                markerOpts.content = dimmedContent;
                markerOpts.offset = new AMap.Pixel(-4, -4);
            }}

            const marker = new AMap.Marker(markerOpts);

            // Add name label above matching markers when filters are active
            if (isMatch && hasFilter) {{
                marker.setLabel({{
                    content: `<div style="background:#fff;padding:1px 5px;border-radius:3px;font-size:11px;white-space:nowrap;border:1px solid #ddd;box-shadow:0 1px 3px rgba(0,0,0,0.15)">${{m.name}}</div>`,
                    direction: 'top',
                }});
            }}

            attachSpotClick(marker, i);
            currentMarkers.push(marker);
        }}

        // 聚合：无筛选且点位密集时用 MarkerCluster，筛选态保持直绘
        // （筛选结果少且需要名称标签，聚合反而藏信息）
        // 注意：AMap 2.0 MarkerCluster 构造只吃纯数据 [{{lnglat, weight,...}}]，
        // 传 Marker 实例会静默空渲染（getUserDataLen()=0）——本机 playwright 实测
        if (!hasFilter && currentMarkers.length > 120 && typeof AMap.MarkerCluster === 'function') {{
            const clusterData = currentMarkers.map((mk, i2) => ({{
                lnglat: [mk.getExtData().lng, mk.getExtData().lat],
                weight: 1,
                _d: mk.getExtData(),
                _idx: i2,  // currentMarkers 顺序 == markersData 顺序
            }}));
            try {{
                cluster = new AMap.MarkerCluster(map, clusterData, {{
                    gridSize: 60,
                    maxZoom: 13,
                    renderClusterMarker: function(context) {{
                        const n = context.count;
                        const bg = n > 100 ? '#e0393e' : n > 30 ? '#f39c12' : '#1a73e8';
                        const size = n > 100 ? 44 : n > 30 ? 40 : 34;
                        const div = document.createElement('div');
                        div.style.cssText = `background:${{bg}};color:#fff;border-radius:50%;width:${{size}}px;height:${{size}}px;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:600;box-shadow:0 2px 6px rgba(0,0,0,0.3);cursor:pointer;`;
                        div.innerText = n;
                        context.marker.setContent(div);
                        context.marker.setOffset(new AMap.Pixel(-size/2, -size/2));
                    }},
                    renderMarker: function(context) {{
                        const pt = context.data[0];
                        context.marker.setExtData(pt._d);
                        attachSpotClick(context.marker, pt._idx);
                    }},
                }});
                if (!cluster || cluster.getUserDataLen() === 0) throw new Error('cluster empty');
                // 聚合点击默认不放大（2.0 需自接）：点气泡 → 放大两级居中
                cluster.on('click', function(e) {{
                    if (e.clusterData && e.clusterData.length > 1) {{
                        map.setZoomAndCenter(Math.min(map.getZoom() + 2, 15), e.lnglat);
                    }}
                }});
            }} catch (e) {{
                console.warn('cluster failed, fallback to direct markers', e);
                if (cluster) {{ try {{ cluster.setMap(null); }} catch(_) {{}} cluster = null; }}
                map.add(currentMarkers);
            }}
        }} else {{
            map.add(currentMarkers);
        }}

        const citySet = new Set(filtered.map(m => m.city));
        const filterLabel = hasFilter ? `筛选结果 ` : '';
        document.getElementById('statsBar').innerHTML =
            `${{filterLabel}}<b>${{filtered.length}}</b> / ${{markersData.length}} 个景点 · <b>${{citySet.size}}</b> 个城市`;
        console.log('rendered', filtered.length, 'markers');

        // Auto-center: single city selected → zoom to that city
        if (filtered.length === 0) {{
            // no matches, show all
            if (currentMarkers.length > 0) map.setFitView(currentMarkers);
            return;
        }}
        if (hasFilter && currentMarkers.length > 0) {{
            // zoom to fit matching markers
            map.setFitView(currentMarkers.filter(mk => {{
                const d = mk.getExtData();
                return filteredNames.has(d.name);
            }}));
        }}
        if (selectedCityCenter.length === 1) {{
            const city = selectedCityCenter[0];
            if (cityCoords[city]) {{
                map.setCenter(cityCoords[city]);
                map.setZoom(11);
            }} else if (currentMarkers.length > 0) {{
                map.setFitView(currentMarkers);
            }}
        }}
    }}

    renderMarkers();

    // Listen for filter updates from parent
    window.addEventListener('message', function(e) {{
        if (e.data.type === 'update_filters') {{
            filterPasses.length = 0;
            filterCities.length = 0;
            filterCats.length = 0;
            (e.data.passes || []).forEach(p => filterPasses.push(p));
            (e.data.cities || []).forEach(c => filterCities.push(c));
            (e.data.categories || []).forEach(c => filterCats.push(c));
            renderMarkers();
        }}
        // Receive coordinate correction results from Streamlit
        if (e.data.type === 'coord_updated') {{
            const name = e.data.name;
            const newLng = e.data.lng;
            const newLat = e.data.lat;
            // Update markersData in place
            for (let i = 0; i < markersData.length; i++) {{
                if (markersData[i].name === name) {{
                    markersData[i].lng = newLng;
                    markersData[i].lat = newLat;
                    break;
                }}
            }}
            renderMarkers();
            infoWindow.close();
        }}
    }});

    // Coordinate correction: search and update
    // Uses backend API (no PlaceSearch plugin needed)
    window.correctCoord = function(name, idx) {{
        const input = document.getElementById('coordInput_' + idx);
        const resultsDiv = document.getElementById('coordResults_' + idx);
        if (!input || !resultsDiv) return;

        const query = input.value.trim();
        if (!query) return;

        resultsDiv.innerHTML = '<div style="color:#999;font-size:12px;">搜索中...</div>';

        fetch('/api/search_poi?query=' + encodeURIComponent(query))
            .then(r => r.json())
            .then(data => {{
                if (!data.pois || data.pois.length === 0) {{
                    resultsDiv.innerHTML = '<div style="color:#999;font-size:12px;">未找到结果</div>';
                    return;
                }}
                let html = '';
                for (const p of data.pois) {{
                    const addr = p.address || '';
                    const city = p.city ? `<span style="background:#f0f4ff;color:#4a6cf7;padding:1px 6px;border-radius:8px;font-size:10px;font-weight:600;margin-right:6px;">${{p.city}}</span>` : '';
                    html += `<div class="coord-result" data-lng="${{p.lng}}" data-lat="${{p.lat}}" data-name="${{p.name}}"
                        style="padding:10px 12px;margin:6px 0;background:#fafbfc;border-radius:8px;cursor:pointer;font-size:12px;border:1px solid #e8e8e8;transition:all 0.15s;"
                        onmouseover="this.style.background='#e3f2fd';this.style.borderColor='#1a73e8'" onmouseout="this.style.background='#fafbfc';this.style.borderColor='#e8e8e8'">
                        <div style="font-weight:600;color:#333;margin-bottom:3px;">${{p.name}}</div>
                        <div style="display:flex;align-items:center;">
                            ${{city}}
                            <span style="color:#888;font-size:11px;">${{addr}}</span>
                        </div>
                        <div style="color:#bbb;font-size:10px;margin-top:3px;">(${{p.lng.toFixed(4)}}, ${{p.lat.toFixed(4)}})</div>
                    </div>`;
                }}
                resultsDiv.innerHTML = html;

                // Click to select
                resultsDiv.querySelectorAll('.coord-result').forEach(el => {{
                    el.onclick = function() {{
                        const newLng = parseFloat(this.dataset.lng);
                        const newLat = parseFloat(this.dataset.lat);
                        const spotName = this.dataset.name;
                        // Update marker on map
                        for (let i = 0; i < currentMarkers.length; i++) {{
                            const data = currentMarkers[i].getExtData();
                            if (data.name === name) {{
                                currentMarkers[i].setPosition([newLng, newLat]);
                                break;
                            }}
                        }}
                        // Save via API
                        fetch('/api/save_coord', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/json'}},
                            body: JSON.stringify({{name: name, lng: newLng, lat: newLat}})
                        }}).then(r => r.json()).then(resp => {{
                            if (resp.ok) {{
                                resultsDiv.innerHTML = `<div style="color:#4caf50;font-size:12px;">✓ 已更新: ${{spotName}} (${{newLng.toFixed(4)}}, ${{newLat.toFixed(4)}})</div>`;
                            }} else {{
                                resultsDiv.innerHTML = `<div style="color:#f44336;font-size:12px;">保存失败: ${{resp.error}}</div>`;
                            }}
                        }}).catch(err => {{
                            resultsDiv.innerHTML = `<div style="color:#f44336;font-size:12px;">保存失败: ${{err.message}}</div>`;
                        }});
                    }};
                }});
            }})
            .catch(err => {{
                resultsDiv.innerHTML = `<div style="color:#f44336;font-size:12px;">搜索失败: ${{err.message}}</div>`;
            }});
    }};

    // Load and display reviews
    window.loadReviews = function(name, idx) {{
        const reviewsDiv = document.getElementById('reviews_' + idx);
        if (!reviewsDiv) return;
        if (reviewsDiv.style.display === 'block') {{
            reviewsDiv.style.display = 'none';
            return;
        }}
        reviewsDiv.style.display = 'block';
        reviewsDiv.innerHTML = '<div style="color:#999;font-size:12px;">加载评价中...</div>';

        // Find city from markersData
        const m = markersData.find(x => x.name === name);
        const city = m ? m.city : '';
        fetch('/api/reviews?name=' + encodeURIComponent(name) + '&city=' + encodeURIComponent(city))
            .then(r => r.json())
            .then(data => {{
                if (!data.reviews || data.reviews.length === 0) {{
                    reviewsDiv.innerHTML = '<div style="color:#999;font-size:13px;padding:12px 0;text-align:center;">暂无真实评价</div>';
                    return;
                }}
                // Overall rating
                let html = '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">';
                html += `<div style="font-size:28px;font-weight:800;color:#ff9800;">${{data.overall_rating.toFixed(1)}}</div>`;
                html += '<div style="font-size:12px;color:#999;line-height:1.4;">/ 5.0<br>' + data.review_count + '条评价</div>';
                // Source tags
                if (data.sources_used) {{
                    data.sources_used.forEach(s => {{
                        const label = s === 'mafengwo' ? '马蜂窝' : s === 'amap' ? '高德' : s;
                        html += ` <span style="background:linear-gradient(135deg,#e3f2fd,#bbdefb);color:#1565c0;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600;">${{label}}</span>`;
                    }});
                }}
                html += '</div>';

                // Individual reviews
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

    // Add spot to trip via map server API
    window.addToTrip = function(name, idx) {{
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

    // Toast notification
    window.showToast = function(message, type) {{
        // Remove existing toasts
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
}}

if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', initMap);
}} else {{
    initMap();
}}
</script>
</body>
</html>"""
    return html


def _save_map_html(html: str) -> str:
    """Backward-compat wrapper — real impl in app/map_html.py."""
    from app.map_html import _save_map_html as _impl
    return _impl(html)


def _build_trip_map_html(*args, **kwargs) -> str:
    """Backward-compat wrapper — real impl in app/map_html.py."""
    from app.map_html import _build_trip_map_html as _impl
    return _impl(*args, **kwargs)



# ============================================================
# Page config
# ============================================================
# Ensure map server is running (must be called after Streamlit init)

st.set_page_config(page_title="湖北旅游年卡知识图谱", page_icon="🗺️", layout="wide")

PAGE_TITLES = {
    "🗺️ 地图探索": "地图探索",
    "🎫 年卡对比": "年卡对比",
    "💡 选卡助手": "选卡助手",
    "🌿 季节指南": "季节指南",
    "📊 数据总览": "数据总览",
    "📝 行程规划": "行程规划",
    "🧳 我的行程": "我的行程",
}

with st.spinner("加载中..."):
    raw_records, cleaned, alignment, graph_data = get_or_create_data()

# Load coordinates
coordinates = load_coordinates()

# Build unique spots with coords
spots_with_coords = get_unique_spots_with_coords(cleaned, coordinates)

# Check geocoding status
spots_with_geo = [s for s in spots_with_coords if s.get("lng")]
spots_without_geo = [s for s in spots_with_coords if not s.get("lng")]

# ============================================================
# Trip quick-pick session state
# ============================================================
if "selected_trip_spots" not in st.session_state:
    st.session_state.selected_trip_spots = []
if "route_options" not in st.session_state:
    st.session_state.route_options = []
if "selected_route_idx" not in st.session_state:
    st.session_state.selected_route_idx = 0
if "trip_origin" not in st.session_state:
    st.session_state.trip_origin = "武汉"
if "trip_nearby" not in st.session_state:
    st.session_state.trip_nearby = {"hotels": [], "restaurants": []}

# Draft persistence: reload from disk when session is fresh (survives browser restart)
_DRAFT_FILE = os.path.join(DATA_DIR, "trip_draft.json")
if not st.session_state.selected_trip_spots and os.path.exists(_DRAFT_FILE):
    try:
        with open(_DRAFT_FILE, "r", encoding="utf-8") as _f:
            _draft = json.load(_f)
        if isinstance(_draft, list):
            # tolerate malformed entries — items must be spot dicts with a name
            st.session_state.selected_trip_spots = [
                s for s in _draft if isinstance(s, dict) and s.get("name")]
    except (json.JSONDecodeError, OSError):
        pass

# Multi-slot drafts: trip_drafts.json holds named slots; selected_trip_spots
# always mirrors the ACTIVE slot so all existing code paths stay unchanged.
_DRAFTS_FILE = os.path.join(DATA_DIR, "trip_drafts.json")
if "draft_slots" not in st.session_state:
    _slots, _active = {}, "默认"
    if os.path.exists(_DRAFTS_FILE):
        try:
            with open(_DRAFTS_FILE, "r", encoding="utf-8") as _f:
                _dd = json.load(_f)
            _slots = {k: [s for s in v if isinstance(s, dict) and s.get("name")]
                      for k, v in _dd.get("slots", {}).items() if isinstance(v, list)}
            _active = _dd.get("active") or "默认"
        except (json.JSONDecodeError, OSError, AttributeError):
            _slots, _active = {}, "默认"
    if not _slots:
        _slots = {"默认": list(st.session_state.selected_trip_spots)}
    if _active not in _slots:
        _active = next(iter(_slots))
    st.session_state.draft_slots = _slots
    st.session_state.active_draft = _active
    st.session_state.selected_trip_spots = list(_slots[_active])

# Sync from map server bridge file
_QUICK_TRIP_FILE = os.path.join(DATA_DIR, "quick_trip_spots.json")
if os.path.exists(_QUICK_TRIP_FILE):
    try:
        with open(_QUICK_TRIP_FILE, "r", encoding="utf-8") as f:
            pending = json.load(f)
        existing_names = {s["name"] for s in st.session_state.selected_trip_spots}
        for spot in pending:
            if spot.get("name") and spot["name"] not in existing_names:
                st.session_state.selected_trip_spots.append(spot)
        os.remove(_QUICK_TRIP_FILE)
    except (json.JSONDecodeError, OSError):
        os.remove(_QUICK_TRIP_FILE)

# ============================================================
# Sidebar
# ============================================================
# Pending nav jump: pages request a nav switch by setting _nav_pending
# (assigning nav_page after the radio is instantiated raises StreamlitAPIException)
if st.session_state.get("_nav_pending"):
    st.session_state.nav_page = st.session_state.pop("_nav_pending")
page = st.sidebar.radio(
    "导航",
    ["🗺️ 地图探索", "🎫 年卡对比", "💡 选卡助手", "🌿 季节指南", "🗓️ 规划中心", "🧳 我的行程"],
    index=0,
    key="nav_page",
)

# ============================================================
# Global: Owned pass selector
# ============================================================
_pass_info_global = build_pass_info(graph_data, cleaned)
st.sidebar.divider()
_all_pass_names = sorted(_pass_info_global.keys(), key=lambda x: -_pass_info_global[x]["value_ratio"])
_owned_pass = st.sidebar.selectbox(
    "我已购买的年卡",
    ["无"] + _all_pass_names,
    format_func=lambda x: x if x == "无" else _pass_info_global[x]["display"],
)
if _owned_pass != "无":
    _owned_pass_spots = {s["name"] for s in _pass_info_global[_owned_pass]["spots_detail"]}
    _owned_pass_price = _pass_info_global[_owned_pass]["price"]
    _owned_pass_display = _pass_info_global[_owned_pass]["display"]
else:
    _owned_pass_spots = None
    _owned_pass_price = None
    _owned_pass_display = None

# ============================================================
# Helpers
# ============================================================

def _build_weekend_timeline(
    day_spots: list[dict],
    start_hour: int = 9,
    start_min: int = 0,
) -> dict:
    """Build timeline with actual driving times between spots."""
    if not day_spots:
        return {"slots": [], "lunch": None, "end_time": "", "warnings": ["无景点"]}

    slots = []
    warnings = []
    current_hour = start_hour
    current_min = start_min
    lunch_inserted = False

    for i, spot in enumerate(day_spots):
        play_hours = spot.get("_play_hours", 2.0)
        drive_min = spot.get("_drive_time_min", 0)

        # Lunch break around 12:00
        if not lunch_inserted and current_hour >= 11 and current_min >= 30:
            current_hour += 1
            lunch_inserted = True

        # Check closing hours
        category = spot.get("category", "")
        open_h, close_h = get_opening_hours(category)
        estimated_end = current_hour + play_hours

        if estimated_end > close_h:
            warnings.append(
                f"{spot.get('name', '')} 可能在 {close_h}:00 关闭，建议调整到上午"
            )

        start_str = f"{current_hour:02d}:{current_min:02d}"
        end_hour = current_hour + int(play_hours)
        end_min = current_min + int((play_hours % 1) * 60)
        if end_min >= 60:
            end_hour += 1
            end_min -= 60
        end_str = f"{end_hour:02d}:{end_min:02d}"

        slots.append({
            "spot_name": spot.get("name", ""),
            "city": spot.get("city", ""),
            "category": category,
            "play_hours": play_hours,
            "drive_min": drive_min,
            "start": start_str,
            "end": end_str,
        })

        # Add drive time to next spot
        current_hour = end_hour
        current_min = end_min + drive_min
        if current_min >= 60:
            current_hour += current_min // 60
            current_min %= 60

    # Insert lunch if never inserted
    if not lunch_inserted and len(slots) >= 2:
        mid = len(slots) // 2
        slots.insert(mid, {
            "spot_name": "午餐",
            "city": "",
            "category": "餐饮",
            "play_hours": 1.0,
            "drive_min": 0,
            "start": "12:00",
            "end": "13:00",
        })

    return {
        "slots": slots,
        "lunch": None,
        "end_time": f"{current_hour:02d}:{current_min:02d}",
        "warnings": warnings,
    }


# ============================================================
# Page dispatch (wrapped so the trip draft is persisted even when a
# page calls st.stop())
# ============================================================
try:
    if page == "🗺️ 地图探索":
        from app.page_modules.map_explore_page import render_map_explore_page
        render_map_explore_page(dict(globals()))

    elif page == "🎫 年卡对比":
        from app.page_modules.pass_compare_page import render_pass_compare_page
        render_pass_compare_page(dict(globals()))

    elif page == "💡 选卡助手":
        from app.page_modules.pass_assistant_page import render_pass_assistant_page
        render_pass_assistant_page(dict(globals()))

    elif page == "🌿 季节指南":
        from app.page_modules.season_guide_page import render_season_guide_page
        render_season_guide_page(dict(globals()))

    elif page == "🗓️ 规划中心":
        from app.planning_hub import render_planning_hub
        render_planning_hub(dict(globals()))

    elif page == "🧳 我的行程":
        from app.page_modules.my_trips_page import render_my_trips_page
        render_my_trips_page(dict(globals()))
finally:
    # Persist trip draft every run (small JSON; survives restarts).
    # trip_drafts.json = 多槽位真源；trip_draft.json = 活跃槽镜像（向后兼容）
    try:
        _slots = st.session_state.get("draft_slots")
        if isinstance(_slots, dict) and _slots:
            _active = st.session_state.get("active_draft", "默认")
            _slots[_active] = st.session_state.get("selected_trip_spots", [])
            with open(_DRAFTS_FILE, "w", encoding="utf-8") as _f:
                json.dump({"active": _active, "slots": _slots}, _f,
                          ensure_ascii=False, indent=1)
        with open(_DRAFT_FILE, "w", encoding="utf-8") as _f:
            json.dump(st.session_state.get("selected_trip_spots", []), _f,
                      ensure_ascii=False, indent=1)
    except OSError:
        pass
