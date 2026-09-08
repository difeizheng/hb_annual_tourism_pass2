"""Self-contained trip-map HTML builder (no Streamlit page code).

Extracted from app/main.py so that chat_planner (or any other module) can
import it WITHOUT re-executing main.py — importing app.main from a page
runs the whole page script a second time and crashes Streamlit with
StreamlitDuplicateElementId (sidebar radio registered twice).
"""
import hashlib
import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

# 与 app/main.py 顶部协商逻辑一致：map_server 绑定失败会自动换端口并把
# 实际端口写入 data/map_server.port；读不到文件时退回首选端口。
DEFAULT_MAP_PORT = 18793


def _resolve_map_port() -> int:
    port_file = os.path.join(DATA_DIR, "map_server.port")
    try:
        with open(port_file, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return DEFAULT_MAP_PORT


def _get_js_key() -> str:
    """amap_js_key: prefer st.secrets (runtime), fall back to reading the
    secrets file directly so this module works outside a Streamlit script."""
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            return st.secrets.get("amap_js_key", "")
    except Exception:
        pass
    try:
        import tomllib
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               ".streamlit", "secrets.toml"), "rb") as f:
            return tomllib.load(f).get("amap_js_key", "")
    except Exception:
        return ""


def _save_map_html(html: str) -> str:
    """Write HTML to static folder and return HTTP URL."""
    h = hashlib.md5(html.encode()).hexdigest()[:8]
    fname = f"map_{h}.html"
    fpath = os.path.join(STATIC_DIR, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(html)
    return f"http://127.0.0.1:{_resolve_map_port()}/{fname}"


# City center coordinates for fallback (地图 cityCoords 常量)
CITY_COORDS = {'武汉': [114.305, 30.593], '黄冈': [114.873, 30.447], '鄂州': [114.894, 30.388], '孝感': [113.917, 30.926], '咸宁': [114.302, 29.841], '黄石': [115.038, 30.22], '十堰': [110.797, 32.629], '宜昌': [111.286, 30.692], '襄阳': [112.122, 32.009], '荆门': [112.204, 31.035], '荆州': [112.241, 30.332], '恩施': [109.488, 30.272], '随州': [113.383, 31.691], '仙桃': [113.454, 30.365], '潜江': [112.897, 30.402], '天门': [113.166, 30.665], '神农架': [110.676, 31.744]}

def _save_map_html(html: str) -> str:
    """Write HTML to static folder and return HTTP URL."""
    h = hashlib.md5(html.encode()).hexdigest()[:8]
    fname = f"map_{h}.html"
    fpath = os.path.join(STATIC_DIR, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(html)
    return f"http://127.0.0.1:{_resolve_map_port()}/{fname}"


def _build_trip_map_html(
    selected_spots: list[dict],
    route_polyline: str = "",
    hotels: list[dict] | None = None,
    restaurants: list[dict] | None = None,
    height: str = "600px",
    day_plan: dict | None = None,
    parkings: list[dict] | None = None,
    day_routes: dict | None = None,
) -> str:
    """Generate AMap HTML for the trip page with numbered spots, route line, and amenities.

    day_plan: optional multi_city_planner result. When present, enables the
    day-toggle UI: spots/hotels/restaurants/parkings are grouped per day and
    shown/hidden via top buttons. Default view = all days (hotels only extras).
    """
    js_key = _get_js_key()

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
    day_routes_json = json.dumps(day_routes or {}, ensure_ascii=True)

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
        // Per-day route polylines follow the day toggle
        Object.keys(dayPolylines).forEach(dn => {{
            const on = (parseInt(dn, 10) === dayNum);
            dayPolylines[dn].forEach(pl => on ? pl.show() : pl.hide());
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

    // Per-day route polylines (toggled with day buttons)
    const dayRoutes = {day_routes_json};
    const dayPolylines = {{}};
    Object.keys(dayRoutes).forEach(dn => {{
        const raw = dayRoutes[dn] || '';
        if (!raw) return;
        const segs = raw.split(';').map(seg => seg.split(',').map(pt => {{
            const xy = pt.split(',');
            return [parseFloat(xy[0]), parseFloat(xy[1])];
        }}).filter(p => !isNaN(p[0]) && !isNaN(p[1])));
        const pls = [];
        segs.forEach(path => {{
            if (path.length > 1) {{
                const pl = new AMap.Polyline({{
                    path: path, strokeColor: '#e53935', strokeWeight: 4,
                    strokeOpacity: 0.75, lineJoin: 'round', lineCap: 'round',
                }});
                map.add(pl);
                pls.push(pl);
            }}
        }});
        dayPolylines[dn] = pls;
    }});

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

def build_trip_map_html(*args, **kwargs):
    """Public alias — 后续新代码用这个名；保留 _ 前缀别名兼容旧调用。"""
    return _build_trip_map_html(*args, **kwargs)
