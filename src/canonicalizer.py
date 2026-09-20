# -*- coding: utf-8 -*-
"""Spot-name canonicalizer: merge near-duplicate name variants into one canonical name.

Background: raw pass data names the same physical spot with variants like
"张公山寨" / "张公山寨(青山区)" / "多乐台球（限1次）" / "武汉多乐台球".
These escape the aligner (city|area grouping) and inflate every count
(897 unique names, ~85 of them variants of another name), double map markers,
and double-count seasonal/pass statistics.

Merge rules (conservative):
1. Paren-variant groups: same city + same paren-stripped base, where EVERY
   parenthesized fragment is a *qualifier* — a district/county name (short,
   or ending 区/县/市/州) or a restriction/price note (限/次/补/预约/夜场/采摘…).
   Fragments that look like a *location identity* (店/码头/景区/公园/中心/馆/营地…)
   keep the name separate: 爱蹦蹦床馆(汉口宗关店) ≠ 爱蹦蹦床馆(武昌奥山世纪城店).
2. City-prefix variants: "武汉花博汇" merges into "花博汇" when the remainder
   (or its canonical) exists in the same city.

Coordinates are remapped to canonical names (prefer the canonical name's own
geocode; fall back to any variant's). An alias map {variant: canonical} is
saved for downstream lookups (reviews, old plans).
"""

import json
import os
import re
from collections import defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

RESTRICT_PAT = re.compile(r"(限|次|补|预约|夜场|采摘|活动|截止|赠|免费|优惠|半价|折)")
LOCATION_PAT = re.compile(r"(店|码头|景区|公园|中心|馆|校区|基地|营地|站|港|广场|大厦|超市|影院|乐园|小镇|古城|山庄|度假村)")
DISTRICT_SUFFIX = ("区", "县", "市", "州")

PAREN_RE = re.compile(r"[（(](.*?)[）)]")


def split_base(name: str) -> tuple[str, list[str]]:
    """Split 'X(A)(B)' -> ('X', ['A', 'B'])."""
    contents = PAREN_RE.findall(name)
    base = PAREN_RE.sub("", name).strip()
    return base, contents


def is_qualifier(content: str) -> bool:
    """A paren fragment that qualifies the SAME spot (district or restriction),
    not one that identifies a DIFFERENT location (store/pier/sub-scenic)."""
    content = content.strip()
    if not content:
        return True
    if RESTRICT_PAT.search(content):
        return True
    if LOCATION_PAT.search(content):
        return False
    if len(content) <= 4 or content.endswith(DISTRICT_SUFFIX):
        return True
    return False


def _paren_canonical(names: list[str]) -> str | None:
    """Given all distinct names in a (city, base) group, return the canonical
    base name if every paren fragment across the group is a qualifier."""
    bases = set()
    for n in names:
        base, contents = split_base(n)
        bases.add(base)
        if any(not is_qualifier(c) for c in contents):
            return None
    # all names share the same base by construction of the group
    return bases.pop()


def canonicalize_spots(spots: list[dict], coordinates: dict) -> tuple[list[dict], dict, dict, dict]:
    """Rewrite spot_name to canonical form; remap coordinates.

    Returns (spots, coordinates, aliases, report).
    aliases: {variant_name: canonical_name}
    report: summary stats + per-group decisions for auditing.
    """
    aliases: dict[str, str] = {}
    groups_log = []

    # ---- Pass 1: paren-variant groups within same city ----
    by_city_base: dict[tuple[str, str], set[str]] = defaultdict(set)
    for s in spots:
        base, _ = split_base(s["spot_name"])
        by_city_base[(s["city"], base)].add(s["spot_name"])

    for (city, base), names in sorted(by_city_base.items()):
        if len(names) < 2:
            continue
        canonical = _paren_canonical(sorted(names))
        if canonical is None:
            groups_log.append({"city": city, "base": base, "names": sorted(names), "decision": "keep_separate"})
            continue
        for n in names:
            if n != canonical:
                aliases[n] = canonical
        groups_log.append({"city": city, "base": base, "names": sorted(names), "decision": "merge", "canonical": canonical})

    # ---- Pass 2: city-prefix variants ("武汉花博汇" -> "花博汇") ----
    # canonical name set after pass 1: map every current name to its canonical
    def canon(n: str) -> str:
        seen = set()
        while n in aliases and n not in seen:
            seen.add(n)
            n = aliases[n]
        return n

    by_city_names: dict[str, set[str]] = defaultdict(set)
    for s in spots:
        by_city_names[s["city"]].add(s["spot_name"])

    for city, names in sorted(by_city_names.items()):
        canonical_set = {canon(n) for n in names}
        for n in sorted(names):
            if not n.startswith(city) or len(n) <= len(city):
                continue
            rest = n[len(city):].strip()
            if not rest:
                continue
            rest_base, rest_contents = split_base(rest)
            if any(not is_qualifier(c) for c in rest_contents):
                continue
            if rest in canonical_set or rest_base in canonical_set:
                target = canon(rest if rest in canonical_set else rest_base)
                if target != canon(n):
                    aliases[n] = target
                    groups_log.append({"city": city, "base": rest, "names": [n, target], "decision": "merge_prefix", "canonical": target})

    # ---- Apply renames ----
    renamed = 0
    for s in spots:
        c = canon(s["spot_name"])
        if c != s["spot_name"]:
            s["spot_name"] = c
            renamed += 1

    # ---- Remap coordinates ----
    new_coords: dict[str, dict] = {}
    coord_log = []
    # group old keys by canonical
    by_canon: dict[str, list[str]] = defaultdict(list)
    for old_key in coordinates:
        by_canon[canon(old_key)].append(old_key)
    for c, keys in by_canon.items():
        # prefer the key that equals the canonical name; else first
        pick = c if c in keys else sorted(keys)[0]
        new_coords[c] = coordinates[pick]
        if len(keys) > 1:
            coord_log.append({"canonical": c, "keys": sorted(keys), "picked": pick})

    report = {
        "stats": {
            "aliases": len(aliases),
            "records_renamed": renamed,
            "unique_names_before": len({k for k in coordinates} | {canon(s['spot_name']) for s in spots}),
            "unique_names_after": len(set(new_coords) | {s["spot_name"] for s in spots}),
            "coords_keys_before": len(coordinates),
            "coords_keys_after": len(new_coords),
        },
        "groups": groups_log,
        "coord_picks": coord_log,
    }
    return spots, new_coords, aliases, report


def run(data_dir: str = None) -> dict:
    """CLI entry: canonicalize cleaned_spots.json + spot_coordinates.json in place."""
    d = data_dir or DATA_DIR
    cleaned_path = os.path.join(d, "cleaned_spots.json")
    coords_path = os.path.join(d, "spot_coordinates.json")
    with open(cleaned_path, encoding="utf-8") as f:
        spots = json.load(f)
    with open(coords_path, encoding="utf-8") as f:
        coords = json.load(f)

    spots, coords, aliases, report = canonicalize_spots(spots, coords)

    with open(cleaned_path, "w", encoding="utf-8") as f:
        json.dump(spots, f, ensure_ascii=False, indent=2)
    with open(coords_path, "w", encoding="utf-8") as f:
        json.dump(coords, f, ensure_ascii=False, indent=2)
    with open(os.path.join(d, "name_aliases.json"), "w", encoding="utf-8") as f:
        json.dump(aliases, f, ensure_ascii=False, indent=2)
    with open(os.path.join(d, "canonicalize_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"aliases: {len(aliases)}, records renamed: {report['stats']['records_renamed']}")
    print(f"unique names: {report['stats']['unique_names_before']} -> {report['stats']['unique_names_after']}")
    print(f"coord keys: {report['stats']['coords_keys_before']} -> {report['stats']['coords_keys_after']}")
    return report


if __name__ == "__main__":
    run()
