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
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.loader import load_all_passes
from src.cleaner import clean_all_spots
from src.classifier import classify_spot
from src.aligner import align_spots
from src.graph_builder import build_graph, graph_to_json
from src.geocoder import load_coordinates, save_coordinates, batch_geocode
from src.analyzer import price_analysis, category_distribution, pass_analysis, pass_overlap, seasonal_analysis, top_value_spots
from src.recommender import recommend_by_season
from src.seasonal_recommender import get_seasonal_recommendations
from src.trip_planner.llm_client import generate_spot_recommendation
from src.trip_planner.route_optimizer import nearest_neighbor_optimize, compute_route, haversine_distance, generate_route_options
from src.trip_planner.auto_assigner import assign_spots_to_days
from src.trip_planner.nearby_search import search_nearby_hotels, search_nearby_restaurants
from src.trip_planner.plan_manager import save_plan, load_plan, list_plans, delete_plan
from src.trip_planner.play_duration import estimate_play_duration, get_opening_hours
from src.trip_planner.review_aggregator import aggregate_spot_reviews
from src.trip_planner.pass_coverage import compute_pass_coverage
from src.trip_planner.time_aware_assigner import assign_spots_with_duration
from src.trip_planner.cost_estimator import estimate_trip_cost
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
) -> str:
    """Generate AMap HTML for the trip page with numbered spots, route line, and amenities."""
    js_key = st.secrets.get("amap_js_key", "") if hasattr(st, "secrets") else ""

    hotels = hotels or []
    restaurants = restaurants or []

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
const cityCoords = {json.dumps(CITY_COORDS)};

function initTripMap() {{
    const map = new AMap.Map('container', {{zoom: 10, center: [114.305, 30.593]}});
    const infoWindow = new AMap.InfoWindow({{offset: new AMap.Pixel(0, -10)}});

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
            infoWindow.setContent(`
                <div style="padding: 14px 16px;">
                    <div class="info-title">${{d.name}}</div>
                    <div style="margin-bottom:6px;">${{catBadge}} ${{levelBadge}}</div>
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
            extData: {{...h, _type: 'hotel'}},
        }});
        marker.on('click', function(e) {{
            const d = e.target.getExtData();
            infoWindow.setContent(`
                <div style="font-weight:bold;">&#127976; ${{d.name}}</div>
                <div style="color:#666;font-size:12px;">${{d.address || ''}}</div>
                <div style="color:#999;font-size:11px;">距离: ${{d.distance}}m</div>
            `);
            infoWindow.open(map, e.target.getPosition());
        }});
        hotelMarkers.push(marker);
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
            extData: {{...r, _type: 'restaurant'}},
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
    }});
    map.add(restMarkers);

    // Auto-fit
    const allMarkers = markers.concat(hotelMarkers, restMarkers);
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
    ["🗺️ 地图探索", "🎫 年卡对比", "💡 选卡助手", "🌿 季节指南", "📊 数据总览", "📝 行程规划", "🧳 我的行程"],
    index=0,
)

# ============================================================
# Page 1: Map Exploration (default)
# ============================================================
if page == "🗺️ 地图探索":
    st.title("地图探索")

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

        # Apply filters
        filtered = spots_with_coords
        if sel_city:
            filtered = [s for s in filtered if s["city"] in sel_city]
        if sel_cat:
            filtered = [s for s in filtered if s["category"] in sel_cat]
        if sel_pass:
            filtered = [s for s in filtered if any(sel in p for p in s["passes"] for sel in sel_pass)]

        filters = {
            "cities": sel_city,
            "categories": sel_cat,
            "passes": sel_pass,
        }

        # Stats row
        c1, c2, c3 = st.columns(3)
        c1.metric("显示景点", len(filtered))
        c2.metric("有坐标", len([s for s in filtered if s.get("lng")]))
        c3.metric("覆盖城市", len(set(s["city"] for s in filtered)))

        # Map — save to file and serve via local HTTP server
        html = _build_map_html(filtered, filters, height="650px", clear_filters=True)
        map_url = _save_map_html(html)
        st.components.v1.iframe(map_url, height=660)

        # Spot details (shows when marker clicked)
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


# ============================================================
# Page 2: Pass Comparison (map-based)
# ============================================================
elif page == "🎫 年卡对比":
    st.title("年卡对比（地图模式）")

    passes_list = sorted(set(s["pass_name"] for s in cleaned))
    selected = st.multiselect("选择 2 张年卡对比", passes_list, default=passes_list[:2] if len(passes_list) >= 2 else passes_list)

    if len(selected) == 2:
        p1, p2 = selected
        spots1 = {s["spot_name"] for s in cleaned if s["pass_name"] == p1}
        spots2 = {s["spot_name"] for s in cleaned if s["pass_name"] == p2}
        overlap = spots1 & spots2

        # Stats
        c1, c2, c3 = st.columns(3)
        c1.metric(f"仅 {p1.split('_')[0]}", len(spots1 - overlap))
        c2.metric("重叠景点", len(overlap))
        c3.metric(f"仅 {p2.split('_')[0]}", len(spots2 - overlap))

        # Build colored markers
        comparison_markers = []
        for s in spots_with_coords:
            if not s.get("lng"):
                continue
            in_1 = s["name"] in spots1
            in_2 = s["name"] in spots2
            if in_1 and in_2:
                color = "#9C27B0"  # purple overlap
                label = "重叠"
            elif in_1:
                color = "#2196F3"  # blue only 1
                label = f"仅 {p1.split('_')[0]}"
            elif in_2:
                color = "#FF9800"  # orange only 2
                label = f"仅 {p2.split('_')[0]}"
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

        # Legend
        st.caption(f"🟣 {len(overlap)} 重叠  🔵 {len(spots1 - overlap)} 仅 {p1.split('_')[0]}  🟠 {len(spots2 - overlap)} 仅 {p2.split('_')[0]}")

        # Render map with comparison markers
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
@keyframes toastOut {{ from {{ opacity: 1; transform: translateY(0); }} to {{ opacity: 0; transform: translateY(20px); }} }}
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

// Create colored marker content
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
                    <button class="btn-action btn-add" onclick="window.addToTrip('${{d.name}}',${{i}})">
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


# ============================================================
# Page 3: Card Selector Assistant
# ============================================================
elif page == "💡 选卡助手":
    st.title("选卡助手")

    # Build pass info from graph_data
    import re
    pass_info = {}
    for node in graph_data["nodes"]:
        if node.get("type") == "pass":
            price_m = re.search(r"(\d+)元", node.get("name", ""))
            pass_info[node["id"]] = {
                "name_key": node["name"],
                "display": node["name"].split("_")[0],
                "price": int(price_m.group(1)) if price_m else 0,
                "spots": [], "cities": set(), "categories": set(),
                "total_price": 0, "levels": [],
            }
    # Assign spots to passes
    for edge in graph_data["edges"]:
        target = edge.get("target", "")
        if target in pass_info:
            source = edge.get("source", "")
            for n in graph_data["nodes"]:
                if n.get("id") == source and n.get("type") == "spot":
                    pi = pass_info[target]
                    pi["spots"].append(n.get("name", ""))
                    pi["cities"].add(n.get("city", ""))
                    pi["categories"].add(n.get("category", ""))
                    pi["total_price"] += n.get("price", 0)
                    pi["levels"].append(n.get("level") or "")

    for pn, pi in pass_info.items():
        pi["city_count"] = len(pi["cities"])
        pi["spot_count"] = len(pi["spots"])
        pi["value_ratio"] = round(pi["total_price"] / pi["price"], 1) if pi["price"] else 0
        pi["a5_count"] = sum(1 for lv in pi["levels"] if lv == "A5")
        pi["a4_count"] = sum(1 for lv in pi["levels"] if lv == "A4")

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

    tabs = st.tabs(["智能推荐向导", "年卡对比面板", "年卡详情"])

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
            "选择2-4张年卡对比",
            all_pass_names,
            default=[all_pass_names[0], all_pass_names[1]] if len(all_pass_names) >= 2 else all_pass_names,
            format_func=lambda x: pass_info[x]["display"],
        )

        if len(comp_selection) >= 2:
            comp_data = []
            for pn in comp_selection:
                pi = pass_info[pn]
                comp_data.append({
                    "年卡": pi["display"],
                    "卡价": pi["price"],
                    "景点数": pi["spot_count"],
                    "城市数": pi["city_count"],
                    "总价值": pi["total_price"],
                    "性价比": pi["value_ratio"],
                    "5A": pi["a5_count"],
                    "4A": pi["a4_count"],
                })
            df_comp = pd.DataFrame(comp_data)

            # Comparison table
            st.subheader("参数对比")
            st.dataframe(df_comp, use_container_width=True, hide_index=True)

            # Bar chart: price vs value
            c1, c2 = st.columns(2)
            with c1:
                fig = px.bar(df_comp, x="年卡", y="卡价", color="卡价",
                             color_continuous_scale="Reds", text_auto=True)
                fig.update_layout(showlegend=False, title="年卡价格")
                st.plotly_chart(fig, use_container_width=True)
            with c2:
                fig = px.bar(df_comp, x="年卡", y="性价比", color="性价比",
                             color_continuous_scale="Greens", text_auto=True)
                fig.update_traces(texttemplate="%{text:.1f}x")
                fig.update_layout(showlegend=False, title="性价比倍数")
                st.plotly_chart(fig, use_container_width=True)

            # Spot count comparison
            c1, c2 = st.columns(2)
            with c1:
                fig = px.bar(df_comp, x="年卡", y="景点数", color="景点数",
                             color_continuous_scale="Blues", text_auto=True)
                fig.update_layout(showlegend=False, title="景点数量")
                st.plotly_chart(fig, use_container_width=True)
            with c2:
                fig = px.bar(df_comp, x="年卡", y="城市数", color="城市数",
                             color_continuous_scale="Oranges", text_auto=True)
                fig.update_layout(showlegend=False, title="覆盖城市")
                st.plotly_chart(fig, use_container_width=True)

            # Overlap analysis (first 2 selected)
            if len(comp_selection) >= 2:
                st.subheader("景点重叠分析")
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

                if overlap:
                    st.caption(f"{len(overlap)} 个重叠景点:")
                    st.dataframe(pd.DataFrame(sorted(overlap), columns=["景点"]),
                                 use_container_width=True, hide_index=True, height=200)
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


# ============================================================
# Page 4: Seasonal Guide
# ============================================================
elif page == "🌿 季节指南":
    st.title("季节游玩指南")

    # Month picker in sidebar
    with st.sidebar:
        month = st.selectbox("选择月份", list(range(1, 13)), index=0)
        all_cities_season = sorted(set(s["city"] for s in spots_with_coords if s["city"]))
        sel_cities = st.multiselect("城市筛选", all_cities_season, default=[])
        clear_btn = st.button("清除筛选", type="secondary", use_container_width=True)
        if clear_btn and sel_cities:
            st.rerun()

    # Get recommendations
    recs = get_seasonal_recommendations(spots_with_coords, month, sel_cities if sel_cities else None)

    # Season overview card
    emoji = recs["emoji"]
    season_name = recs["season"]
    climate = recs["climate"]
    st.markdown(
        f"### {emoji} {season_name}（{recs['month']}月）"
        f" · {climate['temp_range']}"
    )
    st.caption(climate["desc"])
    st.caption(f"💡 {climate['tips']}")
    st.divider()

    total = recs["total_count"]
    if total == 0:
        st.info("当前筛选条件下暂无推荐景点")
        st.stop()

    st.caption(f"共 {total} 个推荐景点")

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
            # Pass badges
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

    # Tier 1: Must visit
    mv = recs["must_visit"]
    if mv:
        st.subheader(f"⭐ 必去推荐 ({len(mv)}个)")
        cols = st.columns(3)
        for i, (spot, reason, score) in enumerate(mv):
            with cols[i % 3]:
                _spot_card(spot, reason, score, f"mv_{i}")

    # Tier 2: Recommended
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

    # Tier 3: Optional
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
