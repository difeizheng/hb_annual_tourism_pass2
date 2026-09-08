# -*- coding: utf-8 -*-
'''Itinerary text importer: parse pasted multi-day text into structured
days, geocode stop names, attach per-day driving routes.

LLM only structures the text (never reorders or invents); geocoding and
routing are deterministic. Unresolved stops are flagged, not dropped.
'''

from __future__ import annotations

import json
import os
import re

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
CUSTOM_STOPS_FILE = os.path.join(DATA_DIR, 'custom_stops.json')


def _extract_json_array(text):
    start = text.find(chr(91))
    end = text.rfind(chr(93))
    if start < 0 or end <= start:
        raise ValueError("no JSON array in LLM output")
    return json.loads(text[start:end+1])


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


def _poi_search(name, web_key):
    import requests
    try:
        resp = requests.get(
            "https://restapi.amap.com/v3/place/text",
            params={"key": web_key, "keywords": name,
                    "output": "json", "pagesize": 1},
            timeout=10)
        data = resp.json()
        if data.get("status") == "1" and data.get("pois"):
            p = data["pois"][0]
            loc = p.get("location", "0,0").split(",")
            return {"lng": float(loc[0]), "lat": float(loc[1]),
                    "source": "poi"}
    except Exception:
        pass
    return None


def resolve_stop_coords(days, pass_pool, web_key):
    """Geocode stop names: pass pool -> custom stops -> AMap POI.

    Returns {name: {lng,lat,source}}; unresolved stops get
    stop["_unresolved"]=True (flagged in place, never dropped).
    """
    coords = {}
    pool_by_name = {s["name"]: s for s in pass_pool}
    custom = _load_custom_stops()
    for day in days:
        for s in day["stops"]:
            name = s["name"]
            if name in coords:
                continue
            hit = pool_by_name.get(name)
            if hit and hit.get("lng") and hit.get("lat"):
                coords[name] = {"lng": float(hit["lng"]),
                                "lat": float(hit["lat"]),
                                "source": "pass"}
                continue
            cs = custom.get(name)
            if cs and cs.get("lng") and cs.get("lat"):
                coords[name] = {"lng": float(cs["lng"]),
                                "lat": float(cs["lat"]),
                                "source": "custom"}
                continue
            poi = _poi_search(name, web_key)
            if poi:
                coords[name] = poi
            else:
                s["_unresolved"] = True
    return coords


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


def save_imported_itinerary(days, name, departure_city):
    """Persist to plan_manager with trip_type=imported_itinerary."""
    from src.trip_planner.plan_manager import save_plan
    plan_data = {
        'name': name,
        'trip_type': 'imported_itinerary',
        'days': days,
        'departure_city': departure_city,
        'num_days': len(days),
        'total_spots': sum(len(d['stops']) for d in days),
    }
    return save_plan(plan_data)
