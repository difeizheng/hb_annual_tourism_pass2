"""Plan CRUD: save, load, list, delete trip plans as JSON files."""
from __future__ import annotations

import json
import os
import hashlib
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLAN_DIR = os.path.join(PROJECT_ROOT, "data", "trip_plans")


def _ensure_dir():
    os.makedirs(PLAN_DIR, exist_ok=True)


def generate_plan_id() -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    h = hashlib.md5(ts.encode()).hexdigest()[:8]
    return f"plan_{ts}_{h}"


def save_plan(plan: dict) -> str:
    """Save plan to data/trip_plans/<id>.json. Returns plan ID."""
    _ensure_dir()
    plan_id = plan.get("id") or generate_plan_id()
    plan["id"] = plan_id
    plan["updated_at"] = datetime.now(timezone.utc).isoformat()
    if "created_at" not in plan:
        plan["created_at"] = plan["updated_at"]

    fpath = os.path.join(PLAN_DIR, f"{plan_id}.json")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    return plan_id


def load_plan(plan_id: str) -> dict | None:
    """Load a plan by ID. Returns None if not found."""
    fpath = os.path.join(PLAN_DIR, f"{plan_id}.json")
    if not os.path.exists(fpath):
        return None
    with open(fpath, "r", encoding="utf-8") as f:
        return json.load(f)


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
            num_spots = p.get("num_spots")
            if num_spots is not None:
                total_spots = num_spots
            else:
                total_spots = sum(len(d.get("spots", [])) for d in p.get("days", []))
            plans.append({
                "id": p.get("id", fname.replace(".json", "")),
                "name": p.get("name", "未命名"),
                "created_at": p.get("created_at", ""),
                "updated_at": p.get("updated_at", ""),
                "num_days": p.get("num_days", 0),
                "departure_date": p.get("departure_date", ""),
                "total_spots": total_spots,
                "trip_type": p.get("trip_type", ""),
            })
        except (json.JSONDecodeError, OSError, KeyError):
            continue
    return plans


def delete_plan(plan_id: str) -> bool:
    """Delete a plan file. Returns True if deleted."""
    fpath = os.path.join(PLAN_DIR, f"{plan_id}.json")
    if os.path.exists(fpath):
        os.remove(fpath)
        return True
    return False
