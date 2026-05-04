"""Streamlit app: knowledge graph with AMap visualization."""

import json
import os
import sys
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
from src.analyzer import price_analysis
from src.recommender import recommend_by_season

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

def recommend_by_season_from_graph(graph_data: dict, month: int) -> dict:
    """Recommend spots by season from graph data."""
    kw = {
        1: "冬季", 2: "冬季", 3: "春季", 4: "春季", 5: "春季",
        6: "夏季", 7: "夏季", 8: "夏季", 9: "秋季",
        10: "秋季", 11: "秋季", 12: "冬季",
    }
    words = {
        "冬季": ["滑雪", "温泉"],
        "春季": ["樱花", "桃花", "梅园", "牡丹", "郁金香"],
        "夏季": ["漂流", "水上", "水世界"],
        "秋季": ["红叶", "赏秋", "登山"],
    }
    season = kw.get(month, "")
    results = []
    for n in graph_data["nodes"]:
        if n.get("type") != "spot":
            continue
        name = n.get("name", "")
        for w in words.get(season, []):
            if w in name:
                results.append({
                    "name": name, "city": n.get("city", ""),
                    "price": n.get("price", 0), "category": n.get("category", ""),
                    "reason": w,
                })
                break
    return {"season": season, "spots": results}


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
.amap-info-content {{ font-size: 13px; max-width: 260px; }}
.info-title {{ font-weight: bold; font-size: 15px; margin-bottom: 6px; color: #333; }}
.info-row {{ margin: 3px 0; color: #666; }}
.info-label {{ color: #999; }}
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
    const infoWindow = new AMap.InfoWindow({{offset: new AMap.Pixel(0, -10)}});

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
                const passesHtml = d.passes.length > 0
                    ? '<div class="info-row"><span class="info-label">包含年卡:</span> ' + d.passes.join('、') + '</div>'
                    : '';
                const content = `
                    <div class="info-title">${{d.name}}</div>
                    <div class="info-row"><span class="info-label">城市:</span> ${{d.city}} ${{d.area}}</div>
                    <div class="info-row"><span class="info-label">类型:</span> ${{d.category}}</div>
                    <div class="info-row"><span class="info-label">票价:</span> ￥${{d.price}}</div>
                    <div class="info-row"><span class="info-label">等级:</span> ${{d.level || '未评级'}}</div>
                    ${{d.usage ? `<div class="info-row"><span class="info-label">使用:</span> ${{d.usage}}</div>` : ''}}
                    ${{passesHtml}}
                    <div style="margin-top:8px;border-top:1px solid #eee;padding-top:6px;">
                        <button onclick="document.getElementById('coordSearch_${{idx}}').style.display='block';this.style.display='none';"
                            style="background:none;border:1px solid #ddd;border-radius:4px;padding:3px 8px;font-size:11px;cursor:pointer;color:#666;">
                            &#128205; 坐标有误？纠正
                        </button>
                        <div id="coordSearch_${{idx}}" style="display:none;">
                            <div style="display:flex;gap:4px;margin-bottom:4px;">
                                <input type="text" id="coordInput_${{idx}}" placeholder="搜索地点..." value="${{d.name}} ${{d.city}}"
                                    style="flex:1;font-size:12px;padding:4px 6px;border:1px solid #ddd;border-radius:4px;"
                                    onkeydown="if(event.key==='Enter')window.correctCoord('${{d.name}}',${{idx}})">
                                <button onclick="window.correctCoord('${{d.name}}',${{idx}})"
                                    style="background:#1a73e8;color:#fff;border:none;border-radius:4px;padding:4px 10px;font-size:12px;cursor:pointer;">
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
                    const addr = p.address || p.name;
                    html += `<div class="coord-result" data-lng="${{p.lng}}" data-lat="${{p.lat}}" data-name="${{p.name}}"
                        style="padding:8px;margin:4px 0;background:#f5f5f5;border-radius:4px;cursor:pointer;font-size:12px;border:1px solid #ddd;"
                        onmouseover="this.style.background='#e3f2fd'" onmouseout="this.style.background='#f5f5f5'">
                        <div style="font-weight:bold;">${{p.name}}</div>
                        <div style="color:#666;font-size:11px;">${{addr}}</div>
                        <div style="color:#999;font-size:11px;">(${{p.lng.toFixed(4)}}, ${{p.lat.toFixed(4)}})</div>
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


# ============================================================
# Page config
# ============================================================
# Ensure map server is running (must be called after Streamlit init)

st.set_page_config(page_title="湖北旅游年卡知识图谱", page_icon="🗺️", layout="wide")
st.title("湖北/武汉旅游年卡景点知识图谱系统")

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
# Sidebar
# ============================================================
page = st.sidebar.radio(
    "导航",
    ["🗺️ 地图探索", "🎫 年卡对比", "💡 选卡助手", "🌿 季节指南", "📊 数据总览"],
    index=0,
)

# ============================================================
# Page 1: Map Exploration (default)
# ============================================================
if page == "🗺️ 地图探索":
    st.header("地图探索")

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
        search = st.text_input("搜索景点", placeholder="输入名称...")
        if search:
            matched = [s for s in filtered if search in s["name"]]
            if matched:
                cols = st.columns(min(3, len(matched)))
                for i, s in enumerate(matched[:3]):
                    with cols[i]:
                        st.markdown(f"**{s['name']}**")
                        st.caption(f"{s['city']} {s['area']}")
                        st.write(f"票价: ¥{s['price']}")
                        st.write(f"类型: {s['category']}")
                        st.write(f"等级: {s['level'] or '未评级'}")
                        st.write(f"包含年卡: {', '.join(s['passes'])}")


# ============================================================
# Page 2: Pass Comparison (map-based)
# ============================================================
elif page == "🎫 年卡对比":
    st.header("年卡对比（地图模式）")

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
.amap-info-content {{ font-size: 13px; max-width: 260px; }}
.info-title {{ font-weight: bold; font-size: 15px; margin-bottom: 6px; color: #333; }}
.info-row {{ margin: 3px 0; color: #666; }}
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
const infoWindow = new AMap.InfoWindow({{offset: new AMap.Pixel(0, -10)}});

// Create colored marker content
function makeMarkerContent(color) {{
    return `<div style="width:18px;height:18px;border-radius:50%;background:${{color}};border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,0.35);"></div>`;
}}

const markerList = markersData.map(m => {{
    return new AMap.Marker({{
        position: [m.lng, m.lat],
        content: makeMarkerContent(m.color),
        offset: new AMap.Pixel(-9, -9),
        extData: m,
    }});
}});
markerList.forEach(marker => {{
    marker.on('click', function(e) {{
        const d = e.target.getExtData();
        const content = `<div class="info-title">${{d.name}}</div>
                <div class="info-row">票价: ￥${{d.price}}</div>
                <div class="info-row">类型: ${{d.category}}</div>`;
        infoWindow.setContent(content);
        infoWindow.open(map, e.target.getPosition());
        window.parent.postMessage({{type: 'marker_click', name: d.name}}, '*');
    }});
    map.add(marker);
}});
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
    st.header("选卡助手")

    st.write("回答 3 个问题，帮你找到最合适的年卡。")

    # Question 1
    all_cities = sorted(set(s["city"] for s in cleaned))
    cities = st.multiselect("1. 你主要在哪些城市游玩？", all_cities)

    # Question 2
    all_cats = sorted(set(s.get("_classification", {}).get("category", "其他") for s in cleaned))
    cats = st.multiselect("2. 你喜欢什么类型的景点？", all_cats)

    # Question 3
    budget = st.slider("3. 你的年卡预算是多少？", 50, 400, 200)

    if cities or cats:
        # Score each pass
        scored = []
        for pn in set(s["pass_name"] for s in cleaned):
            spots = [s for s in cleaned if s["pass_name"] == pn]
            m = re.search(r"(\d+)元", pn)
            price = int(m.group(1)) if m else 0

            if price > budget:
                continue

            score = 0
            if cities:
                city_matches = sum(1 for s in spots if s["city"] in cities)
                score += city_matches * 3
            if cats:
                cat_matches = sum(1 for s in spots if s.get("_classification", {}).get("category") in cats)
                score += cat_matches * 2

            total_value = sum(s["price"] for s in spots)
            ratio = total_value / price if price else 0
            score += ratio

            scored.append({
                "年卡": pn.split("_")[0],
                "卡价": price,
                "景点数": len(spots),
                "总票价": total_value,
                "匹配度": round(score, 1),
                "性价比": round(ratio, 1),
            })

        scored.sort(key=lambda x: -x["匹配度"])

        if scored:
            st.subheader("推荐排行")
            df = pd.DataFrame(scored[:5])
            st.dataframe(df, use_container_width=True, hide_index=True)

            # Top recommendation detail
            top = scored[0]
            st.success(f"推荐: **{top['年卡']}** (¥{top['卡价']}) — 包含 {top['景点数']} 个景点，总票价 ¥{top['总票价']}")
        else:
            st.info("当前筛选条件下没有匹配的年卡，请放宽条件。")


# ============================================================
# Page 4: Seasonal Guide
# ============================================================
elif page == "🌿 季节指南":
    st.header("季节游玩指南")

    month = st.selectbox("选择月份", list(range(1, 13)), index=0)
    season_data = recommend_by_season_from_graph(graph_data, month)

    season_emoji = {"winter": "❄️ 冬季", "spring": "🌸 春季", "summer": "☀️ 夏季", "autumn": "🍂 秋季"}
    st.subheader(f"{season_emoji.get(season_data.get('season', ''), '')} — {len(season_data.get('spots', []))} 个推荐景点")

    if season_data.get("spots"):
        df = pd.DataFrame([{
            "景点": s["name"], "城市": s.get("city", ""),
            "票价": s.get("price", 0), "类型": s.get("category", ""),
            "推荐理由": s.get("reason", ""),
        } for s in season_data["spots"]])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("该季节暂无特别推荐的季节性景点")


# ============================================================
# Page 5: Dashboard (simplified)
# ============================================================
elif page == "📊 数据总览":
    st.header("数据总览")

    stats = graph_data.get("stats", {})
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("景点总数", stats.get("spot_count", 0))
    col2.metric("年卡数量", stats.get("pass_count", 0))
    col3.metric("覆盖城市", stats.get("city_count", 0))
    col4.metric("关联关系", stats.get("edge_count", 0))

    tab1, tab2 = st.tabs(["覆盖分析", "价格分析"])

    with tab1:
        # City distribution
        city_dist = {}
        for n in graph_data["nodes"]:
            if n.get("type") == "spot":
                city = n.get("city", "未知")
                city_dist[city] = city_dist.get(city, 0) + 1
        city_dist = dict(sorted(city_dist.items(), key=lambda x: -x[1]))

        col1, col2 = st.columns(2)
        with col1:
            df = pd.DataFrame(list(city_dist.items()), columns=["城市", "景点数"])
            fig = px.bar(df, x="城市", y="景点数", color="景点数", color_continuous_scale="Blues", text_auto=True)
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            level_dist = {}
            for n in graph_data["nodes"]:
                if n.get("type") == "spot":
                    level = n.get("level") or "未评级"
                    level_dist[level] = level_dist.get(level, 0) + 1
            df = pd.DataFrame(list(level_dist.items()), columns=["等级", "数量"])
            fig = px.pie(df, values="数量", names="等级")
            st.plotly_chart(fig, use_container_width=True)

    with tab2:
        pa = price_analysis(cleaned)
        if pa:
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("最低票价", f"¥{pa['min']}")
            col2.metric("最高票价", f"¥{pa['max']}")
            col3.metric("平均票价", f"¥{pa['mean']}")
            col4.metric("中位数", f"¥{pa['median']}")
            col5.metric("总价值", f"¥{pa['total']}")
