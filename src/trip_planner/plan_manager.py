"""Plan CRUD: save, load, list, delete trip plans as JSON files.

All plans converge on the unified schema (plan_schema.PLAN_SCHEMA_VERSION).
load_plan migrates legacy formats in-memory; disk files are only rewritten
when the user saves again.
"""
from __future__ import annotations

import json
import os
import hashlib
from datetime import datetime, timezone

from src.trip_planner.plan_schema import (
    PLAN_SCHEMA_VERSION, migrate_plan, plan_summary,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLAN_DIR = os.path.join(PROJECT_ROOT, "data", "trip_plans")


def _ensure_dir():
    os.makedirs(PLAN_DIR, exist_ok=True)


def generate_plan_id() -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    h = hashlib.md5(ts.encode()).hexdigest()[:8]
    return f"plan_{ts}_{h}"


def save_plan(plan: dict) -> str:
    """Save plan to data/trip_plans/<id>.json. Returns plan ID.

    Plans carrying a unified `source` are stamped with the current
    schema_version; legacy-shaped payloads (still emitted by a few old
    call sites) are persisted as-is and migrated on next load.
    """
    _ensure_dir()
    plan_id = plan.get("id") or generate_plan_id()
    plan["id"] = plan_id
    if plan.get("source") and not plan.get("schema_version"):
        plan["schema_version"] = PLAN_SCHEMA_VERSION
    plan["updated_at"] = datetime.now(timezone.utc).isoformat()
    if "created_at" not in plan:
        plan["created_at"] = plan["updated_at"]

    fpath = os.path.join(PLAN_DIR, f"{plan_id}.json")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    return plan_id


def load_plan(plan_id: str) -> dict | None:
    """Load a plan by ID (legacy formats auto-migrated to unified v2).

    Returns None if not found.
    """
    fpath = os.path.join(PLAN_DIR, f"{plan_id}.json")
    if not os.path.exists(fpath):
        return None
    with open(fpath, "r", encoding="utf-8") as f:
        return migrate_plan(json.load(f))


def list_plans() -> list[dict]:
    """List all saved plans sorted by updated_at descending."""
    _ensure_dir()
    plans = []
    for fname in sorted(os.listdir(PLAN_DIR), reverse=True):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(PLAN_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                p = json.load(f)
            sm = plan_summary(migrate_plan(p))
            sm["id"] = sm["id"] or fname.replace(".json", "")
            plans.append(sm)
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            continue
    return plans


def save_days_plan(days, name, source, origin_city="", coords=None,
                   plan_id=None, meta=None, travel_month=None,
                   origin_lng=None, origin_lat=None) -> str:
    """Build a unified v2 plan from day dicts (+ optional coord map) and save.

    coords: {name: {lng, lat, source}} merged into stops before save so the
    plan re-renders its map with zero API calls. Non-standard day extras
    (hotel/transport/label) are preserved in meta.day_extras.
    """
    import copy
    from src.trip_planner.plan_schema import build_plan
    out_days = copy.deepcopy(days)
    if coords:
        for d in out_days:
            for s in d.get("stops", []):
                c = coords.get(s.get("name", ""))
                if c:
                    s["lng"] = c["lng"]
                    s["lat"] = c["lat"]
                    if c.get("source") and not s.get("coord_source"):
                        s["coord_source"] = c["source"]
    meta = dict(meta or {})
    for d in out_days:
        extras = {k: d[k] for k in ("hotel", "transport", "label") if d.get(k)}
        if extras:
            meta.setdefault("day_extras", {})[str(d.get("day_num"))] = extras
    origin = {"city": origin_city or "", "lng": origin_lng, "lat": origin_lat}
    plan = build_plan(name, out_days, source, origin=origin,
                      travel_month=travel_month, meta=meta, plan_id=plan_id)
    return save_plan(plan)


def delete_plan(plan_id: str) -> bool:
    """Delete a plan file. Returns True if deleted."""
    fpath = os.path.join(PLAN_DIR, f"{plan_id}.json")
    if os.path.exists(fpath):
        os.remove(fpath)
        return True
    return False
