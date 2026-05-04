"""Aggregate real visitor reviews from data/reviews/ directory."""
from __future__ import annotations

import glob
import json
import os
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REVIEWS_DIR = os.path.join(PROJECT_ROOT, "data", "reviews")

# Common positive/negative keywords for pros/cons extraction
POSITIVE_KEYWORDS = [
    "风景优美", "壮观", "值得", "不错", "好看", "好玩", "舒服", "清澈",
    "干净", "服务", "推荐", "喜欢", "体验", "震撼", "独特", "满意",
]
NEGATIVE_KEYWORDS = [
    "一般", "失望", "贵", "排队", "拥挤", "脏", "破旧", "不好",
    "坑", "不值", "累", "远", "偏僻", "停车难", "商业化",
]


def load_all_reviews() -> list[dict]:
    """Load all review JSON files from REVIEWS_DIR."""
    if not os.path.exists(REVIEWS_DIR):
        return []

    reviews = []
    for fpath in glob.glob(os.path.join(REVIEWS_DIR, "*.json")):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                reviews.extend(data)
            elif isinstance(data, dict):
                reviews.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return reviews


def aggregate_spot_reviews(spot_name: str) -> dict:
    """Aggregate reviews for a specific spot.

    Returns:
        {
            "review_count": int,
            "avg_rating": float,
            "reviews": list[str],
            "pros": list[str],
            "cons": list[str],
        }
    """
    all_reviews = load_all_reviews()
    if not all_reviews:
        return _empty_review()

    # Match by spot name (fuzzy: contains check)
    matched = []
    for r in all_reviews:
        r_name = (r.get("spot_name") or r.get("name") or "").strip()
        if spot_name in r_name or r_name in spot_name:
            matched.append(r)

    if not matched:
        return _empty_review()

    # Extract ratings
    ratings = []
    review_texts = []
    for r in matched:
        rating = r.get("rating") or r.get("score")
        if rating:
            ratings.append(float(rating))
        text = r.get("text") or r.get("content") or r.get("review")
        if text:
            review_texts.append(text)

    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else 3.5

    # Extract pros/cons from review texts
    pros, cons = _extract_sentiment(review_texts)

    return {
        "review_count": len(matched),
        "avg_rating": avg_rating,
        "reviews": review_texts[:5],
        "pros": pros[:4],
        "cons": cons[:3],
    }


def _extract_sentiment(texts: list[str]) -> tuple[list[str], list[str]]:
    """Extract pros/cons from review texts using keyword matching."""
    pro_counter: Counter = Counter()
    con_counter: Counter = Counter()

    for text in texts:
        if not text:
            continue
        for kw in POSITIVE_KEYWORDS:
            if kw in text:
                pro_counter[kw] += 1
        for kw in NEGATIVE_KEYWORDS:
            if kw in text:
                con_counter[kw] += 1

    # Return top keywords as pros/cons
    pros = [kw for kw, _ in pro_counter.most_common(4)]
    cons = [kw for kw, _ in con_counter.most_common(3)]
    return pros, cons


def _empty_review() -> dict:
    return {
        "review_count": 0,
        "avg_rating": 3.5,
        "reviews": [],
        "pros": [],
        "cons": [],
    }
