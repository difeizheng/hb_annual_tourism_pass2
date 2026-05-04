"""Re-geocode spots with imprecise coordinates using enhanced addresses and POI search."""

import json
import os
import time

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COORD_FILE = os.path.join(BASE_DIR, "data", "spot_coordinates.json")
CLEANED_FILE = os.path.join(BASE_DIR, "data", "cleaned_spots.json")


def load_coordinates() -> dict:
    if os.path.exists(COORD_FILE):
        with open(COORD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_coordinates(coords: dict):
    os.makedirs(os.path.dirname(COORD_FILE), exist_ok=True)
    with open(COORD_FILE, "w", encoding="utf-8") as f:
        json.dump(coords, f, ensure_ascii=False, indent=2)


def geocode_poi(name: str, city: str, area: str, api_key: str) -> dict | None:
    """Try POI search first, fall back to geo with detailed address."""
    # Strategy 1: POI text search (most precise for named places)
    url = "https://restapi.amap.com/v3/place/text"
    params = {
        "key": api_key,
        "keywords": name,
        "city": city,
        "citylimit": "true",
        "output": "json",
        "pagesize": 1,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("status") == "1" and data.get("pois"):
            poi = data["pois"][0]
            loc = poi["location"]
            lng, lat = loc.split(",")
            return {"lng": float(lng), "lat": float(lat), "source": "poi"}
    except Exception:
        pass

    # Strategy 2: Geo with detailed address (city + area + name)
    address = f"{city}{area}{name}" if area else f"{city}{name}"
    url = "https://restapi.amap.com/v3/geocode/geo"
    params = {"key": api_key, "address": address, "output": "json"}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("status") == "1" and data.get("geocodes"):
            loc = data["geocodes"][0]["location"]
            lng, lat = loc.split(",")
            return {"lng": float(lng), "lat": float(lat), "source": "geo_detailed"}
    except Exception:
        pass

    return None


def find_conflict_spots(cleaned: list, coords: dict, threshold: int = 3) -> list[str]:
    """Find spot names that share coordinates with >= threshold other spots."""
    seen = {}
    for s in cleaned:
        name = s["spot_name"]
        if name not in seen or s["price"] > seen[name].get("price", 0):
            seen[name] = s

    markers = []
    for name, s in seen.items():
        coord = coords.get(name, {})
        if coord.get("lng") and coord.get("lat"):
            markers.append({"name": name, "lng": coord["lng"], "lat": coord["lat"], "city": s.get("city", ""), "area": s.get("area", "")})

    coord_map = {}
    for m in markers:
        key = (round(m["lng"], 3), round(m["lat"], 3))
        coord_map.setdefault(key, []).append(m)

    conflict_names = set()
    for group in coord_map.values():
        if len(group) >= threshold:
            for m in group:
                conflict_names.add(m["name"])

    return sorted(conflict_names)


def main():
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    with open(CLEANED_FILE, "r", encoding="utf-8") as f:
        cleaned = json.load(f)

    coords = load_coordinates()
    api_key = input("高德 Web 服务 API Key: ").strip()
    if not api_key:
        print("需要 API Key 才能继续")
        return

    conflict_names = find_conflict_spots(cleaned, coords, threshold=3)

    # Also add spots with no coordinates
    seen = {}
    for s in cleaned:
        name = s["spot_name"]
        if name not in seen or s["price"] > seen[name].get("price", 0):
            seen[name] = s

    no_coord_names = [n for n in seen if n not in coords or not coords[n].get("lng")]

    to_geocode = sorted(set(conflict_names) | set(no_coord_names))
    print(f"需要重新编码: {len(to_geocode)} 个景点")
    print(f"  - 坐标冲突: {len(conflict_names)}")
    print(f"  - 无坐标: {len(no_coord_names)}")

    # Build spot info lookup
    spot_info = {}
    for s in cleaned:
        name = s["spot_name"]
        if name not in spot_info:
            spot_info[name] = {"city": s.get("city", ""), "area": s.get("area", ""), "category": s.get("_classification", {}).get("category", "")}

    success = 0
    failed = 0
    updated = 0

    for i, name in enumerate(to_geocode):
        info = spot_info.get(name, {"city": "", "area": ""})
        result = geocode_poi(name, info["city"], info["area"], api_key)

        if result:
            old = coords.get(name, {})
            old_coord = (old.get("lng"), old.get("lat"))
            new_coord = (result["lng"], result["lat"])
            changed = old_coord != new_coord

            coords[name] = {"lng": result["lng"], "lat": result["lat"]}
            if changed:
                updated += 1
                print(f"  [{i+1}/{len(to_geocode)}] UPDATED: {name} ({info['city']}{info['area']})")
                print(f"    old: {old_coord} -> new: {new_coord} [{result['source']}]")
            else:
                success += 1
            if not changed:
                print(f"  [{i+1}/{len(to_geocode)}] SAME: {name} -> {new_coord} [{result['source']}]")
        else:
            failed += 1
            print(f"  [{i+1}/{len(to_geocode)}] FAILED: {name} ({info['city']}{info['area']})")

        if i + 1 < len(to_geocode):
            time.sleep(0.2)

    save_coordinates(coords)
    print(f"\n完成! 成功 {success}, 更新 {updated}, 失败 {failed}")
    print(f"坐标文件已保存: {COORD_FILE}")


if __name__ == "__main__":
    main()
