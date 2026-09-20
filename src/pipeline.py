"""Main pipeline: load, clean, align, classify, build graph, save results."""

import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.loader import load_all_passes
from src.cleaner import clean_all_spots, clean_spot_record
from src.parser import parse_spot_rules
from src.classifier import classify_spot
from src.aligner import align_spots
from src.graph_builder import build_graph, save_graph
from src.canonicalizer import canonicalize_spots


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DATA_DIR = os.path.join(PROJECT_ROOT, "raw_data")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")


def run_pipeline(data_dir: str = None, output_dir: str = None):
    """Execute the full data processing pipeline."""
    _data_dir = data_dir or RAW_DATA_DIR
    _output_dir = output_dir or DATA_DIR
    os.makedirs(_output_dir, exist_ok=True)

    # Step 1: Load
    print("Step 1: Loading raw data...")
    raw_records = load_all_passes(_data_dir)
    print(f"  Loaded {len(raw_records)} spot records")

    # Step 2: Clean
    print("Step 2: Cleaning data...")
    cleaned = clean_all_spots(raw_records)
    print(f"  Cleaned {len(cleaned)} records")

    # Step 2.5: Canonicalize near-duplicate names (张公山寨 vs 张公山寨(青山区))
    # and remap spot_coordinates.json to canonical names. Without this, ~85 name
    # variants double-count in every stat and double-render on the map.
    print("Step 2.5: Canonicalizing spot names...")
    coords_path = os.path.join(_output_dir, "spot_coordinates.json")
    coordinates = {}
    if os.path.exists(coords_path):
        with open(coords_path, encoding="utf-8") as f:
            coordinates = json.load(f)
    cleaned, coordinates, name_aliases, canon_report = canonicalize_spots(cleaned, coordinates)
    print(f"  Aliases merged: {len(name_aliases)}, "
          f"unique names {canon_report['stats']['unique_names_before']} -> {canon_report['stats']['unique_names_after']}")
    # Enrich coords with level from cleaned records — spot_coordinates 原本不带
    # level，而页面的 5A 筛选/[5A] 徽章/推荐排序全依赖它（同名取最高等级）
    if coordinates:
        _lv_rank = {"A5": 5, "A4": 4, "A3": 3, "A2": 2, "A1": 1}
        _name_level = {}
        for r in cleaned:
            lv = r.get("level") or ""
            nm = name_aliases.get(r["spot_name"], r["spot_name"])
            if _lv_rank.get(lv, 0) > _lv_rank.get(_name_level.get(nm, ""), 0):
                _name_level[nm] = lv
        lv_filled = 0
        for nm, entry in coordinates.items():
            if not entry.get("level") and _name_level.get(nm):
                entry["level"] = _name_level[nm]
                lv_filled += 1
        print(f"  Backfilled level for {lv_filled} spots (needed by 5A filters/badges)")
        with open(coords_path, "w", encoding="utf-8") as f:
            json.dump(coordinates, f, ensure_ascii=False, indent=2)
    with open(os.path.join(_output_dir, "name_aliases.json"), "w", encoding="utf-8") as f:
        json.dump(name_aliases, f, ensure_ascii=False, indent=2)
    with open(os.path.join(_output_dir, "canonicalize_report.json"), "w", encoding="utf-8") as f:
        json.dump(canon_report, f, ensure_ascii=False, indent=2)

    # Step 3: Classify
    print("Step 3: Classifying spots...")
    for spot in cleaned:
        classification = classify_spot(spot["spot_name"], spot.get("notes_raw", ""))
        spot["_classification"] = classification
    print(f"  Classified {len(cleaned)} spots")

    # Step 4: Save cleaned data
    cleaned_path = os.path.join(_output_dir, "cleaned_spots.json")
    with open(cleaned_path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)
    print(f"  Saved cleaned data to {cleaned_path}")

    # Step 5: Entity alignment
    print("Step 4: Aligning entities...")
    alignment = align_spots(cleaned)
    print(f"  Found {alignment['stats']['unique_spots']} unique spots from {alignment['stats']['total_records']} records")
    print(f"  Created {alignment['stats']['aligned_pairs']} alignment pairs")

    alignment_path = os.path.join(_output_dir, "alignment_report.json")
    with open(alignment_path, "w", encoding="utf-8") as f:
        json.dump(alignment, f, ensure_ascii=False, indent=2)
    print(f"  Saved alignment to {alignment_path}")

    # Step 6: Build graph
    print("Step 5: Building knowledge graph...")
    G = build_graph(cleaned, alignment)
    print(f"  Nodes: {G.number_of_nodes()}, Edges: {G.number_of_edges()}")

    graph_path = os.path.join(_output_dir, "knowledge_graph.json")
    save_graph(G, graph_path)
    print(f"  Saved graph to {graph_path}")

    # Summary
    print("\n=== Pipeline Summary ===")
    print(f"Total records: {len(cleaned)}")
    print(f"Unique spots: {alignment['stats']['unique_spots']}")
    print(f"Aligned pairs: {alignment['stats']['aligned_pairs']}")
    print(f"Graph nodes: {G.number_of_nodes()}")
    print(f"Graph edges: {G.number_of_edges()}")
    print(f"Output dir: {_output_dir}")

    return {
        "record_count": len(cleaned),
        "unique_spots": alignment["stats"]["unique_spots"],
        "aligned_pairs": alignment["stats"]["aligned_pairs"],
        "graph_nodes": G.number_of_nodes(),
        "graph_edges": G.number_of_edges(),
        "cleaned": cleaned,
        "alignment": alignment,
        "graph": G,
    }


if __name__ == "__main__":
    run_pipeline()
