"""Data loader for tourism annual pass JSON and XLSX files."""

import json
import glob
import os
from pathlib import Path

import pandas as pd


def load_json(filepath: str) -> list[dict]:
    """Load a single JSON file and return list of spot records."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def load_xlsx(filepath: str) -> list[dict]:
    """Load a single XLSX file and return list of spot records."""
    df = pd.read_excel(filepath)
    return df.to_dict(orient="records")


def load_all_passes(data_dir: str) -> list[dict]:
    """Load all pass files from data_dir. Returns list of pass records with pass_name metadata."""
    json_files = sorted(glob.glob(os.path.join(data_dir, "*.json")))
    results = []

    for filepath in json_files:
        filename = os.path.basename(filepath)
        # Extract pass name from filename: "大武汉景区旅游年卡_200元.json" -> "大武汉景区旅游年卡_200元"
        pass_name = Path(filename).stem
        records = load_json(filepath)

        for rec in records:
            # Skip summary rows (seq == -1)
            if rec.get("seq") == -1:
                continue
            rec["pass_name"] = pass_name
            results.append(rec)

    return results


def get_pass_names(data_dir: str) -> list[str]:
    """Get list of all pass names from filenames."""
    json_files = sorted(glob.glob(os.path.join(data_dir, "*.json")))
    return [Path(f).stem for f in json_files]
