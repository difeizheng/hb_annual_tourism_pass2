"""Streamlit app: knowledge graph with AMap visualization."""

import json
import os
import sys
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
from src.trip_planner.plan_manager import save_plan, load_plan, list_plans, delete_plan
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
MAP_PORT = 18793
os.makedirs(STATIC_DIR, exist_ok=True)

# Start a local HTTP server for map HTML files (once per process)
# Launch map_server.py as a separate subprocess to avoid Streamlit thread issues
def _start_map_server():
    """Launch the standalone map server as a subprocess."""
    import subprocess, logging
    log_path = os.path.join(PROJECT_ROOT, 'data', 'map_server.log')
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    # Check if already running
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', MAP_PORT))
    sock.close()
    if result == 0:
        with open(log_path, 'a') as f:
            f.write(f"[{pd.Timestamp.now()}] port already in use\n")
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
<script src="https://webapi.amap.com/maps?v=2.0&key={js_key}"></script>
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

    // Create markers directly on map (no clustering)
    let currentMarkers = [];
    function renderMarkers() {{
        // Remove old markers
        map.remove(currentMarkers);
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

            // Compute index for coord correction UI (use original index in markersData)
            const idx = i;
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
            currentMarkers.push(marker);
        }}
        map.add(currentMarkers);

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
    """Write HTML to static folder and return HTTP URL."""
    h = hashlib.md5(html.encode()).hexdigest()[:8]
    fname = f"map_{h}.html"
    fpath = os.path.join(STATIC_DIR, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(html)
    return f"http://127.0.0.1:{MAP_PORT}/{fname}"


def _build_trip_map_html(
    selected_spots: list[dict],
    route_polyline: str = "",
    hotels: list[dict] | None = None,
    restaurants: list[dict] | None = None,
    height: str = "600px",
    day_plan: dict | None = None,
    parkings: list[dict] | None = None,
) -> str:
    """Generate AMap HTML for the trip page with numbered spots, route line, and amenities.

    day_plan: optional multi_city_planner result. When present, enables the
    day-toggle UI: spots/hotels/restaurants/parkings are grouped per day and
    shown/hidden via top buttons. Default view = all days (hotels only extras).
    """
    js_key = st.secrets.get("amap_js_key", "") if hasattr(st, "secrets") else ""

    hotels = hotels or []
    restaurants = restaurants or []
    parkings = parkings or []

    # --- Day grouping (for day-toggle UI) ---
    day_groups = None
    if day_plan and day_plan.get("days"):
        # name -> day_num for each spot
        spot_day = {}
        for d in day_plan["days"]:
            for s in d.get("spots", []):
                spot_day[s.get("name", "")] = d["day_num"]
        day_groups = spot_day

    # Precompute JS data blobs (avoid brace-escaping issues inside f-string expressions)
    spot_day_json = json.dumps(day_groups if day_groups is not None else {}, ensure_ascii=True)
    if day_plan and day_plan.get("days"):
        day_count = len(day_plan["days"])
        day_meta = {d["day_num"]: {"city": d.get("city", ""), "transfer": bool(d.get("is_transfer_day"))} for d in day_plan["days"]}
    else:
        day_count = 0
        day_meta = {}
    day_meta_json = json.dumps(day_meta, ensure_ascii=True)

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
.btn-remove {{ background: linear-gradient(135deg, #f44336, #c62828); color: #fff; }}
.btn-remove:hover {{ background: linear-gradient(135deg, #e53935, #b71c1c); }}
.info-pass-tag {{ display: inline-block; background: #fce4ec; color: #c62828; padding: 2px 8px; border-radius: 10px; font-size: 11px; margin: 2px 3px 2px 0; }}
.legend {{
    position: fixed; bottom: 30px; right: 15px; z-index: 1000;
    background: rgba(255,255,255,0.92); border-radius: 8px; padding: 12px 14px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15); font-size: 12px;
}}
.legend-item {{ display: flex; align-items: center; margin: 4px 0; }}
.legend-dot {{ width: 12px; height: 12px; border-radius: 50%; margin-right: 6px; flex-shrink: 0; }}
</style>
<script src="https://webapi.amap.com/maps?v=2.0&key={js_key}"></script>
</head>
<body>
<div id="container"></div>
<div class="legend">
<div style="font-weight:bold;margin-bottom:6px;">图例</div>
<div class="legend-item"><div class="legend-dot" style="background:#1a73e8"></div>行程景点（带序号）</div>
<div class="legend-item"><div class="legend-dot" style="background:#FF9800"></div>酒店</div>
<div class="legend-item"><div class="legend-dot" style="background:#4CAF50"></div>餐厅</div>
</div>
<script>
const spotsData = {json.dumps(selected_spots, ensure_ascii=True)};
const routePolyline = {json.dumps(route_polyline)};
const hotelsData = {json.dumps(hotels, ensure_ascii=True)};
const restaurantsData = {json.dumps(restaurants, ensure_ascii=True)};
const parkingsData = {json.dumps(parkings, ensure_ascii=True)};
const cityCoords = {json.dumps(CITY_COORDS)};
const spotDayMap = {spot_day_json};
const dayCount = {day_count};
const dayMeta = {day_meta_json};

// Grouped marker registry for day toggling
let dayMarkers = {{}};  // day_num -> [markers]
let spotMarkerById = {{}};  // name -> marker
let allExtras = [];  // hotel/restaurant/parking markers (with _day attr)

function initTripMap() {{
    const map = new AMap.Map('container', {{zoom: 10, center: [114.305, 30.593]}});
    const infoWindow = new AMap.InfoWindow({{offset: new AMap.Pixel(0, -10)}});

    // Day toggle bar (only when day plan exists)
    if (dayCount > 0) {{
        const bar = document.createElement('div');
        bar.style.cssText = 'position:absolute;top:10px;left:10px;z-index:1000;display:flex;gap:6px;flex-wrap:wrap;background:rgba(255,255,255,0.95);padding:8px 10px;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,0.18);max-width:70%;';
        const allBtn = mkBtn('全部', 0);
        bar.appendChild(allBtn);
        for (let d = 1; d <= dayCount; d++) {{
            const meta = dayMeta[d] || {{}};
            const label = meta.transfer ? `🚗 D${{d}} ${{meta.city}}` : `D${{d}} ${{meta.city}}`;
            bar.appendChild(mkBtn(label, d));
        }}
        document.getElementById('container').appendChild(bar);
    }}

    function mkBtn(label, dayNum) {{
        const b = document.createElement('button');
        b.textContent = label;
        b.style.cssText = 'border:1px solid #ddd;background:#fff;border-radius:6px;padding:4px 10px;font-size:12px;cursor:pointer;font-weight:600;';
        if (dayNum === 0) b.style.cssText += 'background:#1a73e8;color:#fff;border-color:#1a73e8;';
        b.onclick = () => {{
            setActiveDay(dayNum);
            [...bar.children].forEach(c => {{
                c.style.background = '#fff'; c.style.color = '#333'; c.style.borderColor = '#ddd';
            }});
            b.style.background = '#1a73e8'; b.style.color = '#fff'; b.style.borderColor = '#1a73e8';
        }};
        return b;
    }}

    let currentDay = 0;
    function setActiveDay(dayNum) {{
        currentDay = dayNum;
        // dayNum 0 = all days: spots always on; extras per rule
        Object.values(spotMarkerById).forEach(m => m.show());
        allExtras.forEach(m => {{
            const ext = m.getExtData();
            const d = ext._day || 0;
            const isHotel = ext._type === 'hotel';
            if (dayNum === 0) {{
                // default view: hotels only
                isHotel ? m.show() : m.hide();
            }} else {{
                (d === dayNum) ? m.show() : m.hide();
            }}
        }});
        // Fit view to visible markers (filter by rule, not getVisible)
        const visible = Object.values(spotMarkerById).concat(allExtras.filter(m => {{
            const ext = m.getExtData();
            if (dayNum === 0) return ext._type === 'hotel';
            return (ext._day || 0) === dayNum;
        }}));
        if (visible.length > 0) map.setFitView(visible);
    }}

    // Numbered spot markers
    const markers = [];
    spotsData.forEach((s, i) => {{
        const content = `<div style="width:28px;height:28px;border-radius:50%;background:#1a73e8;color:#fff;
            display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:bold;
            border:2px solid #fff;box-shadow:0 2px 4px rgba(0,0,0,0.3);">${{i + 1}}</div>`;
        const marker = new AMap.Marker({{
            position: [s.lng, s.lat],
            content: content,
            offset: new AMap.Pixel(-14, -14),
            extData: s,
        }});
        marker.on('click', function(e) {{
            const d = e.target.getExtData();
            const catBadge = d.category ? `<span class="info-badge">${{d.category}}</span>` : '';
            const levelBadge = d.level ? `<span class="info-badge green">${{d.level}}</span>` : '';
            const passesHtml = (d.passes && d.passes.length > 0) ?
                d.passes.map(p => `<span class="info-pass-tag">${{p}}</span>`).join('') : '';
            const dayInfo = spotDayMap[d.name] ? `<div class="info-row"><span class="info-label">天数</span>第 ${{spotDayMap[d.name]}} 天</div>` : '';
            infoWindow.setContent(`
                <div style="padding: 14px 16px;">
                    <div class="info-title">${{d.name}}</div>
                    <div style="margin-bottom:6px;">${{catBadge}} ${{levelBadge}}</div>
                    <div style="margin-bottom:6px;">${{dayInfo}}</div>
                    <div class="info-row"><span class="info-label">位置</span>${{d.city}} ${{d.area || ''}}</div>
                    <div class="info-price">￥${{d.price}}</div>
                    ${{passesHtml ? `
                        <div style="margin-bottom:6px;">
                            <div class="info-row" style="margin-bottom:4px;"><span class="info-label">包含年卡</span></div>
                            <div>${{passesHtml}}</div>
                        </div>
                    ` : ''}}
                    <hr class="info-divider">
                    <div class="info-actions">
                        <button class="btn-action btn-remove" onclick="window.removeFromTrip('${{d.name}}')">
                            &#10060; 从行程移除
                        </button>
                    </div>
                </div>
            `);
            infoWindow.open(map, e.target.getPosition());
        }});
        markers.push(marker);
        spotMarkerById[s.name] = marker;
    }});
    map.add(markers);

    // Route polyline
    if (routePolyline && routePolyline.length > 0) {{
        const path = routePolyline.split(';').map(p => {{
            const parts = p.split(',');
            return [parseFloat(parts[0]), parseFloat(parts[1])];
        }}).filter(p => !isNaN(p[0]) && !isNaN(p[1]));

        if (path.length > 1) {{
            const polyline = new AMap.Polyline({{
                path: path,
                strokeColor: '#1a73e8',
                strokeWeight: 5,
                strokeOpacity: 0.8,
                lineJoin: 'round',
                lineCap: 'round',
            }});
            map.add(polyline);
        }}
    }} else if (spotsData.length > 1) {{
        // Fallback: draw straight lines between ordered spots
        const path = spotsData.map(s => [s.lng, s.lat]);
        const polyline = new AMap.Polyline({{
            path: path,
            strokeColor: '#1a73e8',
            strokeWeight: 3,
            strokeOpacity: 0.6,
            strokeStyle: 'dashed',
            lineJoin: 'round',
            lineCap: 'round',
        }});
        map.add(polyline);
    }}

    // Hotel markers
    const hotelMarkers = [];
    hotelsData.forEach(h => {{
        const content = '<div style="width:14px;height:14px;border-radius:50%;background:#FF9800;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,0.3);"></div>';
        const marker = new AMap.Marker({{
            position: [h.lng, h.lat],
            content: content,
            offset: new AMap.Pixel(-7, -7),
            extData: {{...h, _type: 'hotel', _day: h.day_num || 0}},
        }});
        marker.on('click', function(e) {{
            const d = e.target.getExtData();
            infoWindow.setContent(`
                <div style="font-weight:bold;">&#127976; ${{d.name}}</div>
                <div style="color:#666;font-size:12px;">${{d.address || ''}}</div>
                <div style="color:#999;font-size:11px;">距离质心: ${{d.distance}}m · 住 ${{d.nights || '?'}} 晚</div>
            `);
            infoWindow.open(map, e.target.getPosition());
        }});
        hotelMarkers.push(marker);
        allExtras.push(marker);
    }});
    map.add(hotelMarkers);

    // Restaurant markers
    const restMarkers = [];
    restaurantsData.forEach(r => {{
        const content = '<div style="width:14px;height:14px;border-radius:50%;background:#4CAF50;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,0.3);"></div>';
        const marker = new AMap.Marker({{
            position: [r.lng, r.lat],
            content: content,
            offset: new AMap.Pixel(-7, -7),
            extData: {{...r, _type: 'restaurant', _day: r.day_num || 0}},
        }});
        marker.on('click', function(e) {{
            const d = e.target.getExtData();
            infoWindow.setContent(`
                <div style="font-weight:bold;">&#127860; ${{d.name}}</div>
                <div style="color:#666;font-size:12px;">${{d.address || ''}}</div>
                <div style="color:#999;font-size:11px;">距离: ${{d.distance}}m</div>
            `);
            infoWindow.open(map, e.target.getPosition());
        }});
        restMarkers.push(marker);
        allExtras.push(marker);
    }});
    map.add(restMarkers);

    // Parking markers
    const parkMarkers = [];
    parkingsData.forEach(p => {{
        const content = '<div style="width:14px;height:14px;border-radius:3px;background:#9C27B0;color:#fff;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:bold;border:1px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,0.3);">P</div>';
        const marker = new AMap.Marker({{
            position: [p.lng, p.lat],
            content: content,
            offset: new AMap.Pixel(-7, -7),
            extData: {{...p, _type: 'parking', _day: p.day_num || 0}},
        }});
        marker.on('click', function(e) {{
            const d = e.target.getExtData();
            infoWindow.setContent(`
                <div style="font-weight:bold;">🅿️ ${{d.name}}</div>
                <div style="color:#666;font-size:12px;">${{d.address || ''}}</div>
                <div style="color:#999;font-size:11px;">距 ${{d.spot_name || ''}}: ${{d.distance}}m</div>
            `);
            infoWindow.open(map, e.target.getPosition());
        }});
        parkMarkers.push(marker);
        allExtras.push(marker);
    }});
    map.add(parkMarkers);

    // Initial visibility: if day plan exists, apply default (hotels only)
    if (dayCount > 0) {{
        setActiveDay(0);
    }}

    // Auto-fit
    const allMarkers = markers.concat(hotelMarkers, restMarkers, parkMarkers);
    if (allMarkers.length > 0) {{
        map.setFitView(allMarkers);
    }}
}}

// Remove from trip
window.removeFromTrip = function(name) {{
    fetch('/api/remove_from_trip', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{name: name}})
    }}).then(() => {{
        // Write removal flag so Streamlit parent can pick it up
        fetch('/api/notify_parent', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{type: 'spot_removed', name: name}})
        }}).catch(() => {{}});
        const toast = document.createElement('div');
        toast.style.cssText = 'position:fixed;bottom:80px;right:20px;z-index:9999;background:#fff3e0;border-left:4px solid #ff9800;color:#e65100;padding:12px 20px;border-radius:8px;font-size:13px;font-weight:600;box-shadow:0 4px 16px rgba(0,0,0,0.15);animation:toastIn 0.3s ease-out forwards;';
        toast.textContent = '✖ 已移除 ' + name;
        document.body.appendChild(toast);
        setTimeout(() => {{ toast.style.animation = 'toastOut 0.3s ease-in forwards'; setTimeout(() => toast.remove(), 300); }}, 2500);
    }});
}};

if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', initTripMap);
}} else {{
    initTripMap();
}}
</script>
</body>
</html>"""
    return html


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
page = st.sidebar.radio(
    "导航",
    ["🗺️ 地图探索", "🎫 年卡对比", "💡 选卡助手", "🌿 季节指南", "📊 数据总览", "📝 行程规划", "💬 对话规划", "🧳 我的行程", "🚗 周末出发"],
    index=0,
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
# Page 1: Map Exploration (default)
# ============================================================
if page == "🗺️ 地图探索":
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

        sel_city = st.sidebar.multiselect("城市", all_cities, default=[])
        sel_cat = st.sidebar.multiselect("类型", all_cats, default=[])
        sel_pass = st.sidebar.multiselect("年卡", all_passes, default=[])

        has_active = sel_city or sel_cat or sel_pass
        if has_active and st.sidebar.button("清除筛选", type="secondary", use_container_width=True):
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
            if st.sidebar.button(preset_name, use_container_width=True, key=f"preset_{preset_name}"):
                preset = presets[preset_name]
                sel_city = preset.get("city", sel_city)
                sel_cat = preset.get("category", sel_cat)
                has_active = True
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
        view_mode = st.radio("视图模式", ["🗺️ 地图", "📋 列表", "📊 图表"], horizontal=True, label_visibility="collapsed")

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
                    st.plotly_chart(fig_city, use_container_width=True)
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
                    st.plotly_chart(fig_cat, use_container_width=True)

            fp1, fp2 = st.columns(2)
            with fp1:
                # Price distribution
                prices = [s.get("price", 0) for s in filtered if s.get("price", 0) > 0]
                if prices:
                    df_price = pd.DataFrame(prices, columns=["票价"])
                    fig_price = px.histogram(df_price, x="票价", nbins=20,
                                             color_discrete_sequence=["#1a73e8"])
                    fig_price.update_layout(showlegend=False, title="票价分布")
                    st.plotly_chart(fig_price, use_container_width=True)
            with fp2:
                # Level distribution
                level_counts = {}
                for s in filtered:
                    lv = s.get("level") or "未评级"
                    level_counts[lv] = level_counts.get(lv, 0) + 1
                if level_counts:
                    df_level = pd.DataFrame(list(level_counts.items()), columns=["等级", "数量"])
                    fig_level = px.bar(df_level, x="等级", y="数量", color="数量",
                                       color_continuous_scale="RdYlGn", text_auto=True)
                    fig_level.update_layout(showlegend=False, title="等级分布")
                    st.plotly_chart(fig_level, use_container_width=True)

        elif view_mode == "📋 列表":
            # Enhanced list view
            st.subheader(f"景点列表 ({len(filtered)}个)")
            # Sort controls
            sc1, sc2, sc3 = st.columns(3)
            with sc1:
                sort_by = st.selectbox("排序方式", ["票价降序", "票价升序", "等级优先", "名称"])
            with sc2:
                level_filter = st.selectbox("等级筛选", ["全部", "A5", "A4", "未评级"])
            with sc3:
                if st.button("应用筛选", type="primary", use_container_width=True):
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
                "等级": s.get("level") or "未评级", "票价": s.get("price", 0),
                "包含年卡": len(s.get("passes", [])),
            } for s in filtered])
            st.dataframe(df_list, use_container_width=True, hide_index=True, height=500)

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
                                         type="secondary", use_container_width=True):
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
                                     color_continuous_scale="YlOrRd", text_auto=True)
                st.plotly_chart(fig_heat, use_container_width=True)

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
                st.plotly_chart(fig_scatter, use_container_width=True)

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
                                         type="secondary", use_container_width=True):
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
elif page == "🎫 年卡对比":
    st.title("年卡对比（地图模式）")

    passes_list = sorted(set(s["pass_name"] for s in cleaned))
    selected = st.multiselect(
        "选择 2-5 张年卡对比",
        passes_list,
        default=passes_list[:2] if len(passes_list) >= 2 else passes_list,
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
        st.dataframe(pd.DataFrame(matrix_data), use_container_width=True, hide_index=True)

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
                    st.dataframe(df, use_container_width=True, hide_index=True)

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
            st.dataframe(df_comp, use_container_width=True, hide_index=True)

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
            st.plotly_chart(fig, use_container_width=True)

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
                st.dataframe(pd.DataFrame(matrix_data), use_container_width=True, hide_index=True)

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
            st.dataframe(pd.DataFrame(usage_rows), use_container_width=True, hide_index=True)

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
                             use_container_width=True, hide_index=True)
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
            st.plotly_chart(fig_heat, use_container_width=True)

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
                        st.dataframe(df_exc, use_container_width=True, hide_index=True)
                    else:
                        st.caption("暂无独有景点")


# ============================================================
# Page 3: Card Selector Assistant
# ============================================================
elif page == "💡 选卡助手":
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

    tabs = st.tabs(["智能推荐向导", "年卡对比面板", "年卡详情", "预算规划"])

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
        comp_selection = st.multiselect(
            "选择2-5张年卡对比",
            all_pass_names,
            default=[all_pass_names[0], all_pass_names[1]] if len(all_pass_names) >= 2 else all_pass_names,
            format_func=lambda x: pass_info[x]["display"],
        )

        if len(comp_selection) >= 2:
            # Compute all analysis data
            savings_data = compute_savings(pass_info)
            exclusive_data = compute_exclusive_spots(pass_info, comp_selection)
            usage_limits = compute_usage_limits(pass_info)
            usage_map = {ul["pass_id"]: ul for ul in usage_limits}

            # --- Enhanced comparison table ---
            comp_data = []
            for pn in comp_selection:
                pi = pass_info[pn]
                sv = savings_data.get(pn, {})
                ul = usage_map.get(pn, {})
                exc = exclusive_data.get(pn, [])
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
            st.dataframe(df_comp, use_container_width=True, hide_index=True)

            # --- Radar chart ---
            st.subheader("多维对比")
            metrics = ["景点数", "5A", "节省", "性价比", "城市数", "独有景点"]
            # Normalize each metric to 0-1
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
                values.append(values[0])  # close the radar
                fig.add_trace(go.Scatterpolar(
                    r=values,
                    theta=metrics + [metrics[0]],
                    fill="toself",
                    name=row["年卡"],
                    line_color=colors[i % len(colors)],
                ))
            fig.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
            )
            st.plotly_chart(fig, use_container_width=True)

            # --- Overlap analysis ---
            st.subheader("景点重叠分析")
            # Overlap matrix
            if len(comp_selection) >= 2:
                matrix_data = []
                for i, p1 in enumerate(comp_selection):
                    row = {"年卡": pass_info[p1]["display"]}
                    for j, p2 in enumerate(comp_selection):
                        s1 = set(pass_info[p1]["spots"])
                        s2 = set(pass_info[p2]["spots"])
                        if i == j:
                            row[pass_info[p2]["display"]] = f"{len(s1)} (总数)"
                        else:
                            row[pass_info[p2]["display"]] = len(s1 & s2)
                    matrix_data.append(row)
                df_matrix = pd.DataFrame(matrix_data)
                st.dataframe(df_matrix, use_container_width=True, hide_index=True)

                # Detailed overlap for first 2
                p1_name, p2_name = comp_selection[0], comp_selection[1]
                s1 = set(pass_info[p1_name]["spots"])
                s2 = set(pass_info[p2_name]["spots"])
                overlap = s1 & s2
                only1 = s1 - s2
                only2 = s2 - s1

                o1, o2, o3 = st.columns(3)
                o1.metric(f"仅 {pass_info[p1_name]['display']}", len(only1))
                o2.metric("重叠景点", len(overlap))
                o3.metric(f"仅 {pass_info[p2_name]['display']}", len(only2))

            # --- Exclusive high-value spots ---
            st.subheader("独有高价值景点")
            for pn in comp_selection:
                exc_spots = exclusive_data.get(pn, [])[:15]
                exc_value = sum(s["price"] for s in exclusive_data.get(pn, []))
                label = pass_info[pn]["display"]
                with st.expander(f"{label} — 独有景点 {len(exclusive_data.get(pn, []))}个 (总价值 ¥{exc_value:,})"):
                    if exc_spots:
                        df_exc = pd.DataFrame([
                            {"景点": s["name"], "城市": s["city"], "等级": s["level"] or "未评级",
                             "票价": s["price"], "分类": s["category"]}
                            for s in exc_spots
                        ])
                        st.dataframe(df_exc, use_container_width=True, hide_index=True, height=300)
                    else:
                        st.caption("暂无独有景点")

            # --- City x Pass heatmap ---
            st.subheader("城市 × 年卡热力图")
            df_heat = compute_city_pass_heatmap(pass_info, comp_selection)
            df_heat_renamed = df_heat.rename(columns={pid: pass_info[pid]["display"] for pid in df_heat.columns})
            fig_heat = px.imshow(
                df_heat_renamed,
                labels=dict(x="年卡", y="城市", color="景点数"),
                color_continuous_scale="YlOrRd",
                text_auto=True,
            )
            fig_heat.update_layout(height=max(200, len(df_heat_renamed) * 30))
            st.plotly_chart(fig_heat, use_container_width=True)

            # --- Complement suggestions ---
            if len(comp_selection) >= 2:
                st.subheader("补卡建议")
                comps = compute_complementarity(comp_selection, pass_info)
                if comps:
                    st.caption("已选年卡基础上，补充以下年卡可最大化收益:")
                    for c in comps[:3]:
                        with st.container(border=True):
                            cc1, cc2, cc3, cc4 = st.columns(4)
                            cc1.metric("补卡", c["display"])
                            cc2.metric("新增景点", f"{c['new_spots_count']}个")
                            cc3.metric("新增价值", f"¥{c['new_spots_value']:,}")
                            cc4.metric("互补度", f"{c['complement_score']}分")

            # --- Usage limits comparison ---
            st.subheader("使用限制对比")
            usage_rows = []
            for pn in comp_selection:
                ul = usage_map.get(pn, {})
                usage_rows.append({
                    "年卡": pass_info[pn]["display"],
                    "总景点": ul.get("total", 0),
                    "无限制": ul.get("unlimited", 0),
                    "季节限制": ul.get("seasonal", 0),
                    "需预约": ul.get("appointment_needed", 0),
                    "不含节假日": ul.get("holiday_excluded", 0),
                })
            df_usage = pd.DataFrame(usage_rows)
            st.dataframe(df_usage, use_container_width=True, hide_index=True)
        else:
            st.info("请选择至少2张年卡进行对比。")

    # ================================================================
    # Tab 3: Pass Detail
    # ================================================================
    with tabs[2]:
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
    with tabs[3]:
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


# ============================================================
# Page 4: Seasonal Guide
# ============================================================
elif page == "🌿 季节指南":
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

        # Tier 1
        mv = recs["must_visit"]
        if mv:
            st.subheader(f"⭐ 必去推荐 ({len(mv)}个)")
            cols = st.columns(3)
            for i, (spot, reason, score) in enumerate(mv):
                with cols[i % 3]:
                    _spot_card(spot, reason, score, f"mv_{i}")

        # Tier 2
        rec = recs["recommended"]
        if rec:
            st.subheader(f"👍 值得一去 ({len(rec)}个)")
            display_rec = rec[:15]
            cols = st.columns(3)
            for i, (spot, reason, score) in enumerate(display_rec):
                with cols[i % 3]:
                    _spot_card(spot, reason, score, f"rec_{i}")
            if len(rec) > 15:
                with st.expander(f"查看更多推荐 ({len(rec) - 15}个)"):
                    cols2 = st.columns(3)
                    for i, (spot, reason, score) in enumerate(rec[15:]):
                        with cols2[i % 3]:
                            _spot_card(spot, reason, score, f"rec2_{i}")

        # Tier 3
        opt = recs["optional"]
        if opt:
            st.subheader(f"📍 也不错 ({len(opt)}个)")
            display_opt = opt[:15]
            cols = st.columns(3)
            for i, (spot, reason, score) in enumerate(display_opt):
                with cols[i % 3]:
                    _spot_card(spot, reason, score, f"opt_{i}")
            if len(opt) > 15:
                with st.expander(f"查看更多 ({len(opt) - 15}个)"):
                    cols2 = st.columns(3)
                    for i, (spot, reason, score) in enumerate(opt[15:]):
                        with cols2[i % 3]:
                            _spot_card(spot, reason, score, f"opt2_{i}")

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
elif page == "📊 数据总览":
    st.title("数据总览")

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


# ============================================================
# Page 6: Trip Planner (行程规划)
# ============================================================
elif page == "📝 行程规划":
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
                )
            with c2:
                pass_data = next((p for p in passes_info if p["name"] == selected_pass_name), None)
                if pass_data:
                    st.metric("景点数", pass_data["spot_count"])
                    st.metric("性价比", pass_data["value_ratio"])
            with c3:
                if st.button("一键导入", type="primary", use_container_width=True):
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
            st.dataframe(cart_df, use_container_width=True, hide_index=True)

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
                num_days = st.number_input("天数", 1, 7, st.session_state.tp_num_days)
            with c4:
                daily_cap = st.slider("每日时长(h)", 6.0, 12.0, 8.0, 0.5)

            if st.button("自动编排行程", type="primary", use_container_width=True):
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
                # Seasonal warnings banner
                if assignment["seasonal_warnings"]:
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
                if st.button("保存行程", type="primary", use_container_width=True):
                    plan_data = {
                        "name": trip_name,
                        "trip_type": "trip_planner_v2",
                        "cart": cart,
                        "assignment": assignment,
                        "departure_city": st.session_state.tp_departure_city,
                        "num_days": st.session_state.tp_num_days,
                        "travel_month": st.session_state.tp_travel_month,
                        "total_spots": len(cart),
                    }
                    plan_id = save_plan(plan_data)
                    st.success(f"已保存！行程ID: {plan_id}")

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

            # Load saved plans
            st.divider()
            st.subheader("历史记录")
            saved = list_plans()
            v2_plans = [p for p in saved if p.get("trip_type") == "trip_planner_v2"]
            if not v2_plans:
                st.caption("暂无保存的行程")
            else:
                for p in v2_plans:
                    date_str = p["updated_at"][:10] if p.get("updated_at") else ""
                    with st.expander(f"**{p['name']}** · {p.get('num_days', 0)}天 · {p.get('total_spots', 0)}个景点 · {date_str}"):
                        if st.button("加载", key=f"tp_load_{p['id']}"):
                            plan = load_plan(p["id"])
                            if plan:
                                st.session_state.tp_cart = plan.get("cart", [])
                                st.session_state.tp_assignment = plan.get("assignment")
                                st.session_state.tp_departure_city = plan.get("departure_city", "武汉")
                                st.session_state.tp_num_days = plan.get("num_days", 3)
                                st.session_state.tp_travel_month = plan.get("travel_month", 6)
                                st.rerun()
                        if st.button("删除", key=f"tp_del_{p['id']}"):
                            delete_plan(p["id"])
                            st.rerun()


# ============================================================
# Page 7: My Trip (我的行程)
# ============================================================
elif page == "🧳 我的行程":
    st.title("我的行程")

    trip_origin = st.session_state.trip_origin
    all_cities_for_dep = sorted(set(s["city"] for s in spots_with_coords if s["city"]))

    # Sidebar controls
    with st.sidebar:
        st.subheader("行程设置")
        trip_origin = st.selectbox(
            "出发城市", all_cities_for_dep,
            index=all_cities_for_dep.index(st.session_state.trip_origin)
                if st.session_state.trip_origin in all_cities_for_dep else 0,
        )
        st.session_state.trip_origin = trip_origin

        # Save current trip
        if st.session_state.selected_trip_spots:
            plan_name = st.text_input("行程名称", value=f"我的行程-{len(st.session_state.selected_trip_spots)}个景点")
            if st.button("保存行程", type="primary", use_container_width=True):
                plan_data = {
                    "name": plan_name,
                    "trip_type": "quick_trip",
                    "origin": st.session_state.trip_origin,
                    "selected_trip_spots": st.session_state.selected_trip_spots,
                    "route_options": st.session_state.route_options,
                    "selected_route_idx": st.session_state.selected_route_idx,
                    "num_spots": len(st.session_state.selected_trip_spots),
                }
                plan_id = save_plan(plan_data)
                st.success(f"已保存！ID: {plan_id}")

        # Load saved trips
        st.divider()
        st.subheader("历史记录")
        saved = list_plans()
        quick_trips = [p for p in saved if p.get("trip_type") == "quick_trip"]
        if not quick_trips:
            st.caption("暂无保存的行程")
        else:
            for p in quick_trips:
                date_str = p["updated_at"][:10] if p.get("updated_at") else ""
                with st.expander(f"**{p['name']}** · {p.get('num_spots', 0)}个景点 · {date_str}"):
                    if st.button("加载", key=f"load_trip_{p['id']}"):
                        full = load_plan(p["id"])
                        if full:
                            st.session_state.trip_origin = full.get("origin", "武汉")
                            st.session_state.selected_trip_spots = full.get("selected_trip_spots", [])
                            st.session_state.route_options = full.get("route_options", [])
                            st.session_state.selected_route_idx = full.get("selected_route_idx", 0)
                            st.session_state.trip_nearby = {"hotels": [], "restaurants": []}
                            st.rerun()
                    if st.button("删除", key=f"del_trip_{p['id']}"):
                        delete_plan(p["id"])
                        st.rerun()

        if st.button("清空行程", type="secondary", use_container_width=True):
            st.session_state.selected_trip_spots = []
            st.session_state.route_options = []
            st.session_state.selected_route_idx = 0
            st.session_state.trip_nearby = {"hotels": [], "restaurants": []}
            st.rerun()

    # Layout: spot list + map
    col_list, col_map = st.columns([1, 2])

    with col_list:
        st.subheader(f"已选景点 ({len(st.session_state.selected_trip_spots)})")

        if not st.session_state.selected_trip_spots:
            st.info("在地图探索页面点击景点弹窗中的「添加到行程」按钮，将景点加入行程。")
        else:
            for i, spot in enumerate(st.session_state.selected_trip_spots):
                with st.container(border=True):
                    st.markdown(f"**{i+1}. {spot['name']}**")
                    st.caption(f"{spot['city']} {spot.get('area', '')} · {spot['category']} · ¥{spot['price']}")
                    if st.button("移除", key=f"remove_spot_{spot['name']}"):
                        st.session_state.selected_trip_spots.pop(i)
                        st.session_state.route_options = []
                        st.session_state.selected_route_idx = 0
                        st.rerun()

            st.divider()

            # Route optimization
            if len(st.session_state.selected_trip_spots) >= 2:
                if st.button("优化路线", type="primary", use_container_width=True):
                    valid_spots = [s for s in st.session_state.selected_trip_spots
                                   if s.get("lng") and s.get("lat")]
                    dep_coord = CITY_COORDS.get(trip_origin, [114.305, 30.593])
                    departure = {"name": trip_origin, "lng": dep_coord[0], "lat": dep_coord[1]}

                    with st.spinner("正在生成多套路线方案..."):
                        web_key = st.secrets.get("amap_web_key", "")
                        options = generate_route_options(departure, valid_spots, web_key)
                        st.session_state.route_options = options
                        st.session_state.selected_route_idx = 0
                    st.rerun()

            # Nearby search
            if st.session_state.selected_trip_spots:
                st.subheader("周边搜索")
                if st.button("搜索附近酒店"):
                    with st.spinner("搜索中..."):
                        hotels = []
                        for spot in st.session_state.selected_trip_spots[:3]:
                            if spot.get("lng") and spot.get("lat"):
                                h = search_nearby_hotels(
                                    spot["lng"], spot["lat"],
                                    st.secrets.get("amap_web_key", ""),
                                    radius=3000, max_results=5,
                                )
                                hotels.extend(h)
                        # Dedup by name
                        seen = set()
                        unique_hotels = []
                        for h in hotels:
                            if h["name"] not in seen:
                                seen.add(h["name"])
                                unique_hotels.append(h)
                        st.session_state.trip_nearby["hotels"] = unique_hotels[:15]
                        st.rerun()

                if st.button("搜索附近餐厅"):
                    with st.spinner("搜索中..."):
                        restaurants = []
                        for spot in st.session_state.selected_trip_spots[:3]:
                            if spot.get("lng") and spot.get("lat"):
                                r = search_nearby_restaurants(
                                    spot["lng"], spot["lat"],
                                    st.secrets.get("amap_web_key", ""),
                                    radius=2000, max_results=5,
                                )
                                restaurants.extend(r)
                        seen = set()
                        unique_rest = []
                        for r in restaurants:
                            if r["name"] not in seen:
                                seen.add(r["name"])
                                unique_rest.append(r)
                        st.session_state.trip_nearby["restaurants"] = unique_rest[:15]
                        st.rerun()

                # Show cached nearby results
                if st.session_state.trip_nearby.get("hotels"):
                    st.write("**附近酒店**")
                    hotel_df = pd.DataFrame([
                        {"酒店": h["name"], "地址": h.get("address", ""), "距离(m)": h.get("distance", 0)}
                        for h in st.session_state.trip_nearby["hotels"][:10]
                    ])
                    st.dataframe(hotel_df, use_container_width=True, hide_index=True)

                if st.session_state.trip_nearby.get("restaurants"):
                    st.write("**附近餐厅**")
                    rest_df = pd.DataFrame([
                        {"餐厅": r["name"], "地址": r.get("address", ""), "距离(m)": r.get("distance", 0)}
                        for r in st.session_state.trip_nearby["restaurants"][:10]
                    ])
                    st.dataframe(rest_df, use_container_width=True, hide_index=True)

            # Route options selector
            if st.session_state.route_options:
                st.divider()
                options = st.session_state.route_options
                idx = st.session_state.selected_route_idx

                # Route selector
                labels = [f"方案{i+1}: {opt['name']}" for i, opt in enumerate(options)]
                safe_idx = min(idx, len(labels) - 1)
                if safe_idx != idx:
                    st.session_state.selected_route_idx = safe_idx
                selected_label = st.radio("选择方案", labels, index=safe_idx, horizontal=True)
                new_idx = labels.index(selected_label)
                if new_idx != idx:
                    st.session_state.selected_route_idx = new_idx
                    st.rerun()

                # Current chosen
                chosen = options[new_idx]
                st.subheader(f"路线概览 — {chosen['name']}")
                c1, c2 = st.columns(2)
                c1.metric("总距离", f"{chosen['total_distance_km']:.1f} km")
                c2.metric("预计驾驶", f"{chosen['total_duration_min']} 分钟")

                # Pros/cons
                col_p, col_c = st.columns(2)
                with col_p:
                    st.markdown("**优点**")
                    for pro in chosen["pros"]:
                        st.markdown(f"- {pro}")
                with col_c:
                    st.markdown("**缺点**")
                    for con in chosen["cons"]:
                        st.markdown(f"- {con}")

                st.write("**推荐游览顺序:**")
                for i, s in enumerate(chosen["ordered_spots"]):
                    st.write(f"{i+1}. {s['name']} ({s['city']})")
                st.write(f"起点: {trip_origin}")

    with col_map:
        if not st.session_state.selected_trip_spots:
            st.info("请先添加景点到行程")
        else:
            hotels = st.session_state.trip_nearby.get("hotels", [])
            restaurants = st.session_state.trip_nearby.get("restaurants", [])
            route_polyline = ""
            map_spots = st.session_state.selected_trip_spots
            if st.session_state.route_options:
                idx = min(st.session_state.selected_route_idx, len(st.session_state.route_options) - 1)
                chosen = st.session_state.route_options[idx]
                route_polyline = chosen.get("ordered_polyline", "")
                map_spots = chosen.get("ordered_spots", map_spots)

            trip_map_html = _build_trip_map_html(
                selected_spots=map_spots,
                route_polyline=route_polyline,
                hotels=hotels,
                restaurants=restaurants,
                height="650px",
            )
            trip_map_url = _save_map_html(trip_map_html)
            st.components.v1.iframe(trip_map_url, height=660)

            # Check for removal flag from map server (triggers on each rerun)
            _REMOVE_FLAG = os.path.join(DATA_DIR, "_remove_spot_flag.json")
            if os.path.exists(_REMOVE_FLAG):
                try:
                    with open(_REMOVE_FLAG, "r", encoding="utf-8") as _f:
                        _flag_data = json.load(_f)
                    _remove_name = _flag_data.get("name")
                    if _remove_name:
                        st.session_state.selected_trip_spots = [
                            s for s in st.session_state.selected_trip_spots
                            if s.get("name") != _remove_name
                        ]
                        st.session_state.route_options = []
                        st.session_state.selected_route_idx = 0
                    os.remove(_REMOVE_FLAG)
                    st.rerun()
                except (json.JSONDecodeError, OSError):
                    try:
                        os.remove(_REMOVE_FLAG)
                    except OSError:
                        pass



# ============================================================
# Page 7.5: Chat Planner (对话规划)
# ============================================================
elif page == "💬 对话规划":
    from app.chat_planner import render_chat_planner_page
    dep_coords = {
        name: {"name": name, "lng": lnglat[0], "lat": lnglat[1]}
        for name, lnglat in CITY_COORDS.items()
    }
    render_chat_planner_page(spots_with_coords, graph_data, cleaned, dep_coords)


# ============================================================
# Page 8: Weekend Getaway (周末出发)
# ============================================================
elif page == "🚗 周末出发":
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
