"""Tests for seasonal recommendation engine."""
import pytest
from src.seasonal_recommender import (
    calculate_seasonal_score,
    get_seasonal_recommendations,
    MONTH_TO_SEASON,
    SEASON_NAMES,
)


# --- Test fixtures ---

def _make_spot(name, city="武汉", category="其他", sub_category="", tags=None, level=None, price=50, lng=None, lat=None):
    return {
        "name": name, "city": city, "category": category,
        "sub_category": sub_category, "tags": tags or [],
        "level": level, "price": price, "lng": lng, "lat": lat,
    }


# --- Score calculation tests ---

class TestSubCategoryScoring:
    def test_drifting_summer_max(self):
        spot = _make_spot("九畹溪漂流", sub_category="漂流", category="户外运动")
        assert calculate_seasonal_score(spot, "summer") == (5, pytest.approx(5)) or calculate_seasonal_score(spot, "summer")[0] == 5
        score, _ = calculate_seasonal_score(spot, "summer")
        assert score == 5

    def test_drifting_winter_zero(self):
        spot = _make_spot("九畹溪漂流", sub_category="漂流", category="户外运动")
        score, _ = calculate_seasonal_score(spot, "winter")
        assert score == 0

    def test_hot_spring_winter_max(self):
        spot = _make_spot("三江森林温泉", sub_category="温泉", category="温泉康养")
        score, _ = calculate_seasonal_score(spot, "winter")
        assert score == 5

    def test_hot_spring_spring(self):
        spot = _make_spot("三江森林温泉", sub_category="温泉", category="温泉康养")
        score, _ = calculate_seasonal_score(spot, "spring")
        assert score == 3

    def test_ski_winter_max(self):
        spot = _make_spot("神农架滑雪场", sub_category="滑雪", category="户外运动")
        score, _ = calculate_seasonal_score(spot, "winter")
        assert score == 5

    def test_botanical_garden_spring_max(self):
        spot = _make_spot("武汉植物园", sub_category="植物园", category="自然景观")
        score, _ = calculate_seasonal_score(spot, "spring")
        assert score == 5

    def test_zoo_spring_high(self):
        spot = _make_spot("武汉动物园", sub_category="动物园", category="主题乐园")
        score, _ = calculate_seasonal_score(spot, "spring")
        assert score == 4

    def test_museum_winter_boost(self):
        spot = _make_spot("湖北省博物馆", sub_category="博物馆", category="人文历史")
        score, _ = calculate_seasonal_score(spot, "winter")
        assert score == 4

    def test_ancient_town_spring_autumn(self):
        spot = _make_spot("赤壁古战场", sub_category="古镇", category="人文历史")
        s_score, _ = calculate_seasonal_score(spot, "spring")
        a_score, _ = calculate_seasonal_score(spot, "autumn")
        assert s_score == 4
        assert a_score == 4


class TestNameKeywordScoring:
    def test_cherry_blossom_spring(self):
        spot = _make_spot("东湖樱花园", category="自然景观")
        score, _ = calculate_seasonal_score(spot, "spring")
        assert score == 5

    def test_peony_spring(self):
        spot = _make_spot("洛阳牡丹园", category="自然景观")
        score, _ = calculate_seasonal_score(spot, "spring")
        assert score == 5

    def test_canyon_summer(self):
        spot = _make_spot("恩施大峡谷", category="自然景观")
        score, _ = calculate_seasonal_score(spot, "summer")
        assert score == 5


class TestCategoryScoring:
    def test_nature_autumn_max(self):
        spot = _make_spot("某山", category="自然景观")
        score, _ = calculate_seasonal_score(spot, "autumn")
        assert score == 5

    def test_history_winter(self):
        spot = _make_spot("某古迹", category="人文历史")
        score, _ = calculate_seasonal_score(spot, "winter")
        assert score == 4

    def test_agriculture_spring_max(self):
        spot = _make_spot("某农庄", category="休闲农业")
        score, _ = calculate_seasonal_score(spot, "spring")
        assert score == 5

    def test_outdoor_winter_low(self):
        spot = _make_spot("某运动场", category="户外运动")
        score, _ = calculate_seasonal_score(spot, "winter")
        assert score == 1


class TestRatingBonus:
    def test_5a_nature_autumn(self):
        spot = _make_spot("武当山", category="自然景观", tags=["5A"])
        score, _ = calculate_seasonal_score(spot, "autumn")
        # nature autumn = 5, +1 for 5A → capped at 5
        assert score == 5

    def test_4a_winter_history(self):
        spot = _make_spot("黄鹤楼", category="人文历史", tags=["4A"])
        score, _ = calculate_seasonal_score(spot, "winter")
        # history winter = 4, +1 for 4A → capped at 5
        assert score == 5

    def test_seasonal_tag_bonus(self):
        spot = _make_spot("某景点", category="自然景观", tags=["季节性"])
        score, _ = calculate_seasonal_score(spot, "summer")
        # nature summer = 3, +1 for seasonal → 4
        assert score == 4


# --- Main function tests ---

class TestGetSeasonalRecommendations:
    def test_basic_structure(self):
        spots = [_make_spot("武当山", category="自然景观", tags=["5A"])]
        result = get_seasonal_recommendations(spots, 9)  # autumn
        assert "season" in result
        assert "climate" in result
        assert "must_visit" in result
        assert "recommended" in result
        assert "optional" in result
        assert "total_count" in result
        assert result["season"] == "秋季"

    def test_winter_excludes_drifting(self):
        spots = [
            _make_spot("九畹溪漂流", sub_category="漂流", category="户外运动"),
            _make_spot("武当山", category="自然景观", tags=["5A"]),
        ]
        result = get_seasonal_recommendations(spots, 1)  # January
        all_spots = result["must_visit"] + result["recommended"] + result["optional"]
        names = [s["name"] for s, _, _ in all_spots]
        assert "九畹溪漂流" not in names

    def test_city_filter(self):
        spots = [
            _make_spot("武汉景点", city="武汉", category="自然景观"),
            _make_spot("宜昌景点", city="宜昌", category="自然景观"),
        ]
        result = get_seasonal_recommendations(spots, 9, city_filter=["武汉"])
        all_spots = result["must_visit"] + result["recommended"] + result["optional"]
        cities = [s["city"] for s, _, _ in all_spots]
        assert "宜昌" not in cities
        assert "武汉" in cities

    def test_month_to_season_mapping(self):
        for month, expected_season_key in MONTH_TO_SEASON.items():
            spots = [_make_spot("测试景点", category="自然景观")]
            result = get_seasonal_recommendations(spots, month)
            assert result["season_key"] == expected_season_key
            assert result["season"] == SEASON_NAMES[expected_season_key]

    def test_empty_spots(self):
        result = get_seasonal_recommendations([], 6)
        assert result["total_count"] == 0
        assert result["must_visit"] == []
        assert result["recommended"] == []
        assert result["optional"] == []

    def test_sorting_within_tiers(self):
        spots = [
            _make_spot("高价景点", category="自然景观", price=200),
            _make_spot("低价景点", category="自然景观", price=20),
        ]
        result = get_seasonal_recommendations(spots, 9)  # autumn
        mv = result["must_visit"]
        if len(mv) >= 2:
            assert mv[0][0]["price"] >= mv[1][0]["price"]

    def test_tier_assignment(self):
        spots = [
            _make_spot("漂流景区", sub_category="漂流", category="户外运动"),  # summer=5
            _make_spot("自然山", category="自然景观"),  # autumn=5
            _make_spot("普通景点", category="城市娱乐"),  # any=2
        ]
        result = get_seasonal_recommendations(spots, 6)  # summer
        mv_names = [s["name"] for s, _, _ in result["must_visit"]]
        assert "漂流景区" in mv_names
        opt_names = [s["name"] for s, _, _ in result["optional"]]
        assert "普通景点" in opt_names
