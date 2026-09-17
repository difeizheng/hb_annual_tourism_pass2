"""Unified trip-plan schema (v2) + legacy migrations.

All saved trip plans converge on ONE shape (schema_version=2)::

    {
      "id": str, "schema_version": 2, "name": str,
      "source": "manual|chat|import|day_route|weekend",
      "created_at": iso, "updated_at": iso,
      "origin": {"city": str, "lng": float|None, "lat": float|None, "address": str},
      "travel_month": int|None,
      "num_days": int, "total_spots": int,
      "days": [
        {"day_num": int, "city": str, "date": str, "is_transfer_day": bool,
         "travel_km": float, "play_hours": float,
         "stops": [Stop], "route": {"polyline": str, "km": float, "min": float}}
      ],
      "meta": dict,   # source-specific extras (intent_meta, budget, warnings...)
    }

    Stop = {"name": str, "lng": float|None, "lat": float|None,
            "arrive": str, "hours": float, "note": str,
            "price": float, "category": str, "level": str, "city": str,
            "passes": [str], "coord_source": str}

Legacy formats (migrated in-memory on load; disk file untouched until
the next save):
  - imported_itinerary : days[].stops/route already close to target
  - trip_planner_v2 / chat_planner_v1 : cart + assignment.days[].spots
  - quick_trip : flat selected_trip_spots -> single day
"""
from __future__ import annotations

PLAN_SCHEMA_VERSION = 2

SOURCES = ("manual", "chat", "import", "day_route", "weekend")

# legacy trip_type -> unified source
_LEGACY_SOURCE = {
    "trip_planner_v2": "manual",
    "chat_planner_v1": "chat",
    "imported_itinerary": "import",
    "quick_trip": "manual",  # quick_trip becomes a manual single-day plan
    "day_route_v1": "day_route",
    "weekend_v1": "weekend",
}

_STOP_FIELDS = ("name", "lng", "lat", "arrive", "hours", "note",
                "price", "category", "level", "city", "passes", "coord_source")


# ----------------------------------------------------------------------
# Builders
# ----------------------------------------------------------------------
def normalize_stop(raw: dict) -> dict:
    """Normalize one stop dict to the unified field set (extras dropped)."""
    stop = {
        "name": str(raw.get("name", "")).strip(),
        "lng": raw.get("lng"),
        "lat": raw.get("lat"),
        "arrive": str(raw.get("arrive", "") or ""),
        "hours": float(raw.get("hours") or raw.get("_play_hours") or raw.get("play_hours") or 2.0),
        "note": str(raw.get("note", "") or raw.get("reason", "") or ""),
        "price": float(raw.get("price") or 0),
        "category": str(raw.get("category", "") or ""),
        "level": str(raw.get("level", "") or ""),
        "city": str(raw.get("city", "") or ""),
        "passes": list(raw.get("passes") or []),
        "coord_source": str(raw.get("coord_source") or raw.get("source") or ""),
    }
    return stop


def normalize_day(raw: dict, day_num: int) -> dict:
    """Normalize one day dict."""
    stops = [normalize_stop(s) for s in raw.get("stops") or raw.get("spots") or []]
    route_raw = raw.get("route") or {}
    route = {
        "polyline": str(route_raw.get("polyline", "") or ""),
        "km": float(route_raw.get("km") or 0),
        "min": float(route_raw.get("min") or 0),
    }
    if route_raw.get("from"):
        route["from"] = str(route_raw["from"])
    return {
        "day_num": int(raw.get("day_num") or day_num),
        "city": str(raw.get("city") or raw.get("primary_city") or raw.get("label", "") or ""),
        "date": str(raw.get("date", "") or ""),
        "is_transfer_day": bool(raw.get("is_transfer_day", False)),
        "travel_km": float(raw.get("travel_km") or 0),
        "play_hours": float(raw.get("play_hours") or 0),
        "stops": stops,
        "route": route,
    }


def build_plan(name: str, days: list[dict], source: str,
               origin: dict | None = None, travel_month: int | None = None,
               meta: dict | None = None, plan_id: str | None = None) -> dict:
    """Assemble a unified v2 plan from normalized/raw days."""
    assert source in SOURCES, f"unknown source: {source}"
    norm_days = [normalize_day(d, i + 1) for i, d in enumerate(days)]
    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "name": name,
        "source": source,
        "origin": {
            "city": (origin or {}).get("city", ""),
            "lng": (origin or {}).get("lng"),
            "lat": (origin or {}).get("lat"),
            "address": (origin or {}).get("address", ""),
        },
        "travel_month": travel_month,
        "num_days": len(norm_days),
        "total_spots": sum(len(d["stops"]) for d in norm_days),
        "days": norm_days,
        "meta": meta or {},
    }
    if plan_id:
        plan["id"] = plan_id
    return plan


def validate_plan(plan: dict) -> list[str]:
    """Return a list of human-readable issues (empty = OK)."""
    issues: list[str] = []
    if not plan.get("name"):
        issues.append("缺少 name")
    if plan.get("source") not in SOURCES:
        issues.append(f"未知 source: {plan.get('source')}")
    days = plan.get("days")
    if not isinstance(days, list) or not days:
        issues.append("days 为空")
        return issues
    for d in days:
        if not d.get("stops"):
            issues.append(f"D{d.get('day_num')} 无站点")
        for s in d.get("stops", []):
            if not s.get("name"):
                issues.append(f"D{d.get('day_num')} 存在无名站点")
            if s.get("lng") is None or s.get("lat") is None:
                issues.append(f"站点「{s.get('name')}」无坐标")
    return issues


# ----------------------------------------------------------------------
# Migration
# ----------------------------------------------------------------------
def migrate_plan(raw: dict) -> dict:
    """Migrate any known legacy plan to unified v2 (in-memory).

    Unknown future versions pass through; unknown legacy types get a
    best-effort wrap. Never raises on missing fields.
    """
    if not isinstance(raw, dict):
        raise TypeError("plan must be a dict")
    if raw.get("schema_version") == PLAN_SCHEMA_VERSION:
        return raw

    t = raw.get("trip_type", "")
    if t == "imported_itinerary":
        return _migrate_imported(raw)
    if t in ("trip_planner_v2", "chat_planner_v1"):
        return _migrate_v2(raw)
    if t == "quick_trip":
        return _migrate_quick(raw)
    # best effort: already has days?
    if raw.get("days"):
        return _migrate_imported(raw)
    # last resort: empty single-day plan preserving the name
    plan = build_plan(raw.get("name", "未命名行程"), [], "manual",
                      origin={"city": raw.get("departure_city", "")})
    return _carry_identity(raw, plan)


def _carry_identity(raw: dict, plan: dict) -> dict:
    for k in ("id", "created_at", "updated_at"):
        if raw.get(k):
            plan[k] = raw[k]
    return plan


def _migrate_imported(raw: dict) -> dict:
    days = raw.get("days", [])
    meta = {}
    for d in days:  # keep non-standard day extras (hotel/transport/label) in meta
        extras = {k: d[k] for k in ("hotel", "transport", "label") if d.get(k)}
        if extras:
            meta.setdefault("day_extras", {})[str(d.get("day_num"))] = extras
    plan = build_plan(
        raw.get("name", "导入行程"), days, "import",
        origin={"city": raw.get("departure_city", "")},
        meta=meta,
    )
    return _carry_identity(raw, plan)


def _migrate_v2(raw: dict) -> dict:
    assignment = raw.get("assignment") or {}
    src = _LEGACY_SOURCE[raw.get("trip_type", "trip_planner_v2")]
    meta = {}
    if assignment.get("seasonal_warnings"):
        meta["seasonal_warnings"] = assignment["seasonal_warnings"]
    if raw.get("intent_meta"):
        meta["intent_meta"] = raw["intent_meta"]
    if raw.get("city_order"):
        meta["city_order"] = raw["city_order"]
    plan = build_plan(
        raw.get("name", "行程"), assignment.get("days", []), src,
        origin={"city": raw.get("departure_city", "")},
        travel_month=raw.get("travel_month"),
        meta=meta,
    )
    return _carry_identity(raw, plan)


def _migrate_quick(raw: dict) -> dict:
    spots = raw.get("selected_trip_spots") or []
    origin = raw.get("origin") or {}
    if isinstance(origin, str):
        origin = {"city": origin}
    days = [{
        "day_num": 1, "city": origin.get("city", ""),
        "stops": spots, "route": {},
    }] if spots else []
    plan = build_plan(raw.get("name", "快速行程"), days, "manual", origin=origin)
    # preserve chosen route option if present
    opts = raw.get("route_options") or []
    idx = raw.get("selected_route_idx", 0)
    if days and opts and 0 <= idx < len(opts):
        chosen = opts[idx] or {}
        if chosen.get("polyline"):
            plan["days"][0]["route"] = {
                "polyline": chosen["polyline"],
                "km": float(chosen.get("km") or 0),
                "min": float(chosen.get("min") or 0),
            }
    return _carry_identity(raw, plan)


# ----------------------------------------------------------------------
# View helpers
# ----------------------------------------------------------------------
def plan_to_editor_days(plan):
    """Unified plan -> (editor day dicts, coord map) for app/plan_editor.py.

    Day extras (hotel/transport/label) are restored from meta.day_extras;
    coords are derived from stop lng/lat so the editor can re-render the
    map and re-geocode renamed stops with zero extra state.
    """
    days, coords = [], {}
    extras = (plan.get("meta") or {}).get("day_extras", {})
    for d in plan.get("days", []):
        ed = {"day_num": d.get("day_num"), "city": d.get("city", ""),
              "date": d.get("date", ""),
              "stops": [dict(s) for s in d.get("stops", [])],
              "route": dict(d.get("route") or {})}
        ex = extras.get(str(d.get("day_num"))) or {}
        for k in ("hotel", "transport", "label"):
            if ex.get(k):
                ed[k] = ex[k]
        days.append(ed)
        for s in ed["stops"]:
            if s.get("lng") is not None and s.get("lat") is not None:
                coords[s["name"]] = {"lng": s["lng"], "lat": s["lat"],
                                     "source": s.get("coord_source") or "saved"}
    return days, coords


def plan_summary(plan: dict) -> dict:
    """Compact summary for list rendering."""
    cities = []
    for d in plan.get("days", []):
        c = d.get("city") or (d["stops"][0].get("city") if d.get("stops") else "")
        if c and c not in cities:
            cities.append(c)
    return {
        "id": plan.get("id", ""),
        "name": plan.get("name", "未命名"),
        "source": plan.get("source", "manual"),
        "num_days": plan.get("num_days", len(plan.get("days", []))),
        "total_spots": plan.get("total_spots") or sum(len(d.get("stops", [])) for d in plan.get("days", [])),
        "cities": cities,
        "updated_at": plan.get("updated_at", ""),
        "created_at": plan.get("created_at", ""),
    }


def all_stops(plan: dict) -> list[dict]:
    """Flatten all stops with day_num attached (for map rendering)."""
    out = []
    for d in plan.get("days", []):
        for s in d.get("stops", []):
            if s.get("lng") is not None and s.get("lat") is not None:
                out.append({**s, "day_num": d.get("day_num", 0)})
    return out
