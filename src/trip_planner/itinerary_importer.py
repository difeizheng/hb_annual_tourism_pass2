# -*- coding: utf-8 -*-
'''Itinerary text importer: parse pasted multi-day text into structured
days, geocode stop names, attach per-day driving routes.

LLM only structures the text (never reorders or invents); geocoding and
routing are deterministic. Unresolved stops are flagged, not dropped.
'''

from __future__ import annotations

import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
CUSTOM_STOPS_FILE = os.path.join(DATA_DIR, 'custom_stops.json')

CITY_COORDS = {
    '武汉': [114.305, 30.593], '黄冈': [114.873, 30.447], '鄂州': [114.894, 30.388],
    '孝感': [113.917, 30.926], '咸宁': [114.302, 29.841], '黄石': [115.038, 30.22],
    '十堰': [110.797, 32.629], '宜昌': [111.286, 30.692], '襄阳': [112.122, 32.009],
    '荆门': [112.204, 31.035], '荆州': [112.241, 30.332], '恩施': [109.488, 30.272],
    '随州': [113.383, 31.691], '仙桃': [113.454, 30.365], '潜江': [112.897, 30.402],
    '天门': [113.166, 30.665], '神农架': [110.676, 31.744],
}

# 常见旅游县级市/县（含在站名里时短路为县城坐标，防全国 POI 乱匹配）
COUNTY_COORDS = {
    '利川': [108.942, 30.291], '宣恩': [109.490, 29.990],
    '建始': [109.722, 30.600], '巴东': [110.340, 31.040],
    '鹤峰': [110.040, 29.890], '来凤': [109.390, 29.490],
    '咸丰': [109.140, 29.860], '长阳': [111.200, 30.470],
    '秭归': [110.984, 30.823],
}


def _extract_json_array(text):
    start = text.find('[')
    end = text.rfind(']')
    if start < 0 or end <= start:
        raise ValueError("no JSON array in LLM output")
    return json.loads(text[start:end + 1])


PARSE_SYSTEM_PROMPT = (
    '    You are an itinerary text parser. Convert the pasted multi-day itinerary text into a JSON array. Each element: {day_num:int, date:str, label:str, transport:str, stops:[{name:str, arrive:str, hours:float, note:str}], hotel:str}. Rules: only structure what the user'
    '    wrote; never add, retime anything. MISSING TIME = empty string; hours default 0; note holds hints such as raincoat or reservation required; hotel location goes into the hotel field; output ONLY the JSON array, no prose.'
)


def _to_hours(v):
    try:
        return float(str(v).strip().rstrip('小时hH'))
    except (TypeError, ValueError):
        return 0.0


def _to_int(v, default):
    try:
        return int(float(str(v)))
    except (TypeError, ValueError):
        return default


def parse_itinerary_text(text, secrets=None):
    """LLM-parse pasted itinerary into structured days (list of dicts)."""
    if secrets is None:
        try:
            import streamlit as st
            secrets = dict(st.secrets)
        except Exception:
            secrets = {}
    from src.trip_planner.llm_client import chat_completion, _get_llm_config
    cfg = _get_llm_config(secrets)
    if not cfg:
        raise ValueError("LLM not configured (secrets llm_api_*)")
    body = {
        'model': cfg.get('model', 'qwen3.5-plus'),
        'messages': [
            {'role': 'system', 'content': PARSE_SYSTEM_PROMPT},
            {'role': 'user', 'content': text},
        ],
    }
    resp = chat_completion(cfg["base"], cfg["key"], body, timeout=120)
    if hasattr(resp, "json"):
        resp = resp.json()
    try:
        content = resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ValueError("LLM bad response shape")
    days = _extract_json_array(content)
    if not isinstance(days, list) or not days:
        raise ValueError("LLM parsed nothing")
    norm = []
    for i, d in enumerate(days, 1):
        if not isinstance(d, dict):
            continue
        stops = []
        for s in d.get("stops") or []:
            if not isinstance(s, dict) or not s.get("name"):
                continue
            stops.append({
                'name': str(s['name']).strip(),
                'arrive': str(s.get('arrive') or '').strip(),
                'hours': _to_hours(s.get('hours')),
                'note': str(s.get('note') or '').strip(),
            })
        if not stops:
            continue
        norm.append({
            'day_num': _to_int(d.get('day_num'), i),
            'date': str(d.get('date') or '').strip(),
            'label': str(d.get('label') or '').strip(),
            'transport': str(d.get('transport') or '').strip(),
            'stops': stops,
            'hotel': str(d.get('hotel') or '').strip(),
        })
    if not norm:
        raise ValueError("LLM parsed no usable days")
    return norm


def _load_custom_stops():
    try:
        with open(CUSTOM_STOPS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


# 中转型站名填充词：去掉城市名后只剩这些 → 当中转点用城市坐标
WAYPOINT_FILLERS = ('出发', '休整', '返程', '返回', '抵达', '住宿', '集合',
                    '县城', '市区')


def _split_city_name(name):
    """(coord, rest) if name mentions a city/county, else (None, name).

    rest = name minus city name minus filler words; empty rest means
    the stop is a waypoint (武汉出发/利川休整) not a searchable POI.
    """
    for table in (CITY_COORDS, COUNTY_COORDS):
        for city, coord in table.items():
            if city in name:
                rest = name.replace(city, '')
                for f in WAYPOINT_FILLERS:
                    rest = rest.replace(f, '')
                return {"lng": coord[0], "lat": coord[1]}, rest.strip()
    return None, name


def _poi_search(name, web_key, anchor=None):
    """AMap text search for one stop name.

    anchor: {lng,lat} nearby-city hint — biases the search by distance and
    radius so generic names (博物馆/滨江公园) don't match another province.
    """
    import requests
    params = {"key": web_key, "keywords": name,
              "output": "json", "pagesize": 1}
    if anchor:
        params["location"] = "%.6f,%.6f" % (anchor["lng"], anchor["lat"])
        params["radius"] = "50000"
        params["sortrule"] = "distance"
    try:
        resp = requests.get(
            "https://restapi.amap.com/v3/place/text",
            params=params, timeout=10)
        data = resp.json()
        if data.get("status") == "1" and data.get("pois"):
            p = data["pois"][0]
            loc = p.get("location", "0,0").split(",")
            return {"lng": float(loc[0]), "lat": float(loc[1]),
                    "source": "poi"}
    except Exception:
        pass
    return None


def resolve_stop_coords(days, pass_pool, web_key, prev_days=None):
    """Geocode stop names: pass pool -> custom stops -> AMap POI.

    Two deterministic guards against wild POI matches:
    1. stop name containing a Hubei city name -> use that city's coord
       (武汉出发 / 恩施 / 利川休整 are waypoints, not searchable POIs);
    2. with anchor (previous day's last resolved stop, or the day's own
       earlier stops), POI search is biased within 50km of the anchor.

    Returns {name: {lng,lat,source}}; unresolved stops get
    stop["_unresolved"]=True (flagged in place, never dropped).
    """
    coords = {}
    pool_by_name = {s["name"]: s for s in pass_pool}
    custom = _load_custom_stops()
    anchor = None
    if prev_days and prev_days[-1].get("stops"):
        ps = prev_days[-1]["stops"][-1]
        if ps.get("lng") and ps.get("lat"):
            anchor = {"lng": ps["lng"], "lat": ps["lat"]}
    for day in days:
        for s in day["stops"]:
            name = s["name"]
            if name in coords:
                anchor = coords[name]
                continue
            hit = pool_by_name.get(name)
            if hit and hit.get("lng") and hit.get("lat"):
                coords[name] = {"lng": float(hit["lng"]),
                                "lat": float(hit["lat"]),
                                "source": "pass"}
                anchor = coords[name]
                continue
            cs = custom.get(name)
            if cs and cs.get("lng") and cs.get("lat"):
                coords[name] = {"lng": float(cs["lng"]),
                                "lat": float(cs["lat"]),
                                "source": "custom"}
                anchor = coords[name]
                continue
            city_coord, rest = _split_city_name(name)
            if city_coord and len(rest) < 2:
                coords[name] = {**city_coord, "source": "city"}
                anchor = coords[name]
                continue
            if city_coord:
                # real POI whose name contains a city — try precise POI
                # first (anchor-biased), city center as fallback
                poi = _poi_search(name, web_key, anchor=anchor)
                if poi:
                    coords[name] = poi
                else:
                    coords[name] = {**city_coord, "source": "city"}
                anchor = coords[name]
                continue
            poi = _poi_search(name, web_key, anchor=anchor)
            if poi:
                coords[name] = poi
                anchor = poi
            else:
                s["_unresolved"] = True
    return coords


def resolve_single_stop(name, pass_pool, web_key, anchor=None):
    """Resolve ONE stop name -> {lng,lat,source} or None.

    Same deterministic chain as resolve_stop_coords (pass pool -> custom
    stops -> city-name guard -> anchor-biased POI), for editor add/rename.
    """
    for s in pass_pool:
        if s.get("name") == name and s.get("lng") and s.get("lat"):
            return {"lng": float(s["lng"]), "lat": float(s["lat"]),
                    "source": "pass"}
    cs = _load_custom_stops().get(name)
    if cs and cs.get("lng") and cs.get("lat"):
        return {"lng": float(cs["lng"]), "lat": float(cs["lat"]),
                "source": "custom"}
    city_coord, rest = _split_city_name(name)
    if city_coord and len(rest) < 2:
        return {**city_coord, "source": "city"}
    if city_coord:
        poi = _poi_search(name, web_key, anchor=anchor)
        return poi if poi else {**city_coord, "source": "city"}
    return _poi_search(name, web_key, anchor=anchor)


def attach_day_routes(days, coords, origin, web_key):
    """Attach day["route"] = {polyline,km,min,from} per day.

    Day 1 starts at origin; later days start at previous day last stop.
    Days with no resolved stops get route=None.
    """
    from src.trip_planner.route_optimizer import compute_route
    prev_end = origin
    for day in days:
        pts = [coords[s["name"]] for s in day["stops"]
               if s["name"] in coords and not s.get("_unresolved")]
        if not pts:
            day["route"] = None
            continue
        route = compute_route(prev_end, pts, web_key)
        day["route"] = {
            'polyline': route.ordered_polyline,
            'km': route.total_distance_km,
            'min': route.total_duration_min,
            'from': prev_end.get('name', ''),
        }
        prev_end = pts[-1]
    return days


def save_imported_itinerary(days, name, departure_city, coords=None,
                            plan_id=None):
    """Persist as a unified v2 plan (source='import').

    Kept for backward compatibility — thin wrapper over
    plan_manager.save_days_plan. coords: {name: {lng,lat,source}} merged
    into stops; plan_id overwrites that plan file.
    """
    from src.trip_planner.plan_manager import save_days_plan
    return save_days_plan(days, name, "import", origin_city=departure_city,
                          coords=coords, plan_id=plan_id)
