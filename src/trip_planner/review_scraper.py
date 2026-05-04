"""Scrape real tourist attraction reviews from Chinese travel platforms.

Fallback chain: AMap biz_ext.rating (real) → cached data → LLM analysis (labeled AI-generated).
"""
from __future__ import annotations

import json
import hashlib
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

try:
    import httpx
    from bs4 import BeautifulSoup
except ImportError:
    httpx = None
    BeautifulSoup = None

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REVIEW_CACHE_DIR = os.path.join(PROJECT_ROOT, "data", "reviews")
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days

# AMap Web Service key — loaded lazily from secrets or env
_AMAP_WEB_KEY: str = ""


def set_amap_key(key: str):
    global _AMAP_WEB_KEY
    _AMAP_WEB_KEY = key


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]


@dataclass
class Review:
    source: str  # "amap" | "mafengwo" | "llm"
    rating: float
    text: str
    author: str
    date: str
    upvotes: int = 0


@dataclass
class SpotReviews:
    spot_name: str
    overall_rating: float
    review_count: int
    reviews: list[Review] = field(default_factory=list)
    cached_at: str = ""
    sources_used: list[str] = field(default_factory=list)


def _ensure_cache_dir():
    os.makedirs(REVIEW_CACHE_DIR, exist_ok=True)


def _cache_path(spot_name: str) -> str:
    h = hashlib.md5(spot_name.encode("utf-8")).hexdigest()
    return os.path.join(REVIEW_CACHE_DIR, f"{h}.json")


def _load_cache(spot_name: str) -> SpotReviews | None:
    path = _cache_path(spot_name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        cached_at = raw.get("cached_at", "")
        if cached_at:
            dt = datetime.fromisoformat(cached_at)
            age = (datetime.now(timezone.utc) - dt).total_seconds()
            if age > CACHE_TTL_SECONDS:
                os.remove(path)
                return None
        reviews = [
            Review(
                source=r["source"], rating=r["rating"], text=r["text"],
                author=r["author"], date=r["date"], upvotes=r.get("upvotes", 0),
            )
            for r in raw.get("reviews", [])
        ]
        return SpotReviews(
            spot_name=raw["spot_name"],
            overall_rating=raw.get("overall_rating", 0),
            review_count=raw.get("review_count", 0),
            reviews=reviews,
            cached_at=cached_at,
            sources_used=raw.get("sources_used", []),
        )
    except (json.JSONDecodeError, OSError, KeyError):
        return None


def _save_cache(sr: SpotReviews):
    _ensure_cache_dir()
    path = _cache_path(sr.spot_name)
    raw = {
        "spot_name": sr.spot_name,
        "overall_rating": sr.overall_rating,
        "review_count": sr.review_count,
        "reviews": [
            {"source": r.source, "rating": r.rating, "text": r.text,
             "author": r.author, "date": r.date, "upvotes": r.upvotes}
            for r in sr.reviews
        ],
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "sources_used": sr.sources_used,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)


def _random_ua() -> str:
    return random.choice(USER_AGENTS)


def _http_headers() -> dict:
    return {
        "User-Agent": _random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def _delay():
    time.sleep(random.uniform(1.0, 3.0))


def fetch_amap_rating(spot_name: str, city: str = "") -> float | None:
    """Get rating from AMap place search biz_ext.rating. Returns None if unavailable."""
    if not _AMAP_WEB_KEY or httpx is None:
        return None
    try:
        keywords = f"{city} {spot_name}" if city else spot_name
        resp = httpx.get(
            "https://restapi.amap.com/v3/place/text",
            params={"key": _AMAP_WEB_KEY, "keywords": keywords, "output": "json", "pagesize": 1},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("status") == "1" and data.get("pois"):
            biz_ext = data["pois"][0].get("biz_ext", {})
            rating_str = biz_ext.get("rating", "")
            if rating_str:
                return float(rating_str)
    except Exception:
        pass
    return None


def scrape_mafengwo(spot_name: str) -> list[Review]:
    """Try to scrape reviews from mafengwo.cn. Returns empty list on failure (anti-bot is strong)."""
    if httpx is None or BeautifulSoup is None:
        return []

    # Search for the attraction
    search_url = "https://travel.mafengwo.cn/mafengwo/search/searchJson"
    try:
        resp = httpx.post(
            search_url,
            data={"keyword": spot_name},
            headers={**_http_headers(), "Referer": "https://www.mafengwo.cn/",
                     "X-Requested-With": "XMLHttpRequest"},
            timeout=10,
            follow_redirects=True,
        )
        # 202 = challenge page (anti-bot)
        if resp.status_code not in (200,) or len(resp.text) < 200:
            return []
        _delay()
    except Exception:
        return []

    # Parse search results for POI ID
    poi_id = None
    try:
        data = resp.json()
        items = data.get("data", {}).get("list", data.get("list", []))
        if isinstance(items, list):
            for item in items[:5]:
                pid = item.get("poi_id") or item.get("id")
                if pid:
                    poi_id = str(pid)
                    break
    except Exception:
        pass

    if not poi_id:
        return []

    # Fetch detail page
    detail_url = f"https://travel.mafengwo.cn/poi/{poi_id}.html"
    try:
        resp = httpx.get(detail_url, headers=_http_headers(), timeout=15)
        if resp.status_code != 200:
            return []
        _delay()
    except Exception:
        return []

    # Parse reviews
    reviews = []
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        comment_items = soup.select("div.comment-list li, ul.comment-list li, .review-item")
        for item in comment_items[:8]:
            author_el = item.select_one(".user-name, .author, .user-info a")
            rating_el = item.select_one(".star, .score, .rate")
            text_el = item.select_one(".content, .review-text, .comment-text")
            date_el = item.select_one(".time, .date")

            author = author_el.get_text(strip=True) if author_el else ""
            text = text_el.get_text(strip=True) if text_el else ""
            date = date_el.get_text(strip=True) if date_el else ""

            rating = 5.0
            if rating_el:
                score_text = rating_el.get_text(strip=True)
                m = re.search(r"([\d.]+)", score_text)
                if m:
                    rating = float(m.group(1))

            if text and len(text) > 10:
                reviews.append(Review(
                    source="mafengwo", rating=rating, text=text[:500],
                    author=author, date=date,
                ))
    except Exception:
        pass

    return reviews[:5]


def scrape_reviews(spot_name: str, city: str = "") -> SpotReviews:
    """Main entry: try all sources in order, merge results, cache, return SpotReviews.

    Priority: AMap rating (real) → Mafengwo reviews (real, if not blocked) → empty.
    LLM analysis is handled separately by the caller (llm_client.py).
    """
    cached = _load_cache(spot_name)
    if cached:
        return cached

    all_reviews: list[Review] = []
    sources: list[str] = []

    # 1. AMap rating (reliable, real data)
    amap_rating = fetch_amap_rating(spot_name, city)
    if amap_rating:
        all_reviews.append(Review(
            source="amap", rating=amap_rating,
            text=f"高德地图综合评分：{amap_rating}/5.0",
            author="高德地图", date="",
        ))
        sources.append("amap")

    # 2. Mafengwo reviews (attempt, may fail due to anti-bot)
    mf_reviews = scrape_mafengwo(spot_name)
    if mf_reviews:
        all_reviews.extend(mf_reviews)
        sources.append("mafengwo")

    if not all_reviews:
        return SpotReviews(
            spot_name=spot_name, overall_rating=0, review_count=0,
            reviews=[], sources_used=sources,
            cached_at=datetime.now(timezone.utc).isoformat(),
        )

    overall = sum(r.rating for r in all_reviews) / len(all_reviews)
    result = SpotReviews(
        spot_name=spot_name,
        overall_rating=round(overall, 1),
        review_count=len(all_reviews),
        reviews=all_reviews[:8],
        sources_used=sources,
        cached_at=datetime.now(timezone.utc).isoformat(),
    )
    _save_cache(result)
    return result
