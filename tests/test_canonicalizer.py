# -*- coding: utf-8 -*-
"""Canonicalizer invariants: district/restriction parens merge, location parens stay,
city-prefix merges, coordinates remap to canonical names."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.canonicalizer import canonicalize_spots, split_base, is_qualifier


def _spot(name, city="武汉", area=""):
    return {"spot_name": name, "city": city, "area": area, "pass_name": "P"}


def test_district_paren_merges():
    spots = [_spot("张公山寨"), _spot("张公山寨(青山区)")]
    coords = {"张公山寨": {"lng": 1, "lat": 1}, "张公山寨(青山区)": {"lng": 2, "lat": 2}}
    spots, coords, aliases, rep = canonicalize_spots(spots, coords)
    assert aliases == {"张公山寨(青山区)": "张公山寨"}
    assert all(s["spot_name"] == "张公山寨" for s in spots)
    assert set(coords) == {"张公山寨"}
    # canonical's own coord wins
    assert coords["张公山寨"] == {"lng": 1, "lat": 1}


def test_restriction_paren_merges():
    spots = [_spot("多乐台球"), _spot("多乐台球（限1次）")]
    coords = {"多乐台球": {"lng": 1, "lat": 1}, "多乐台球（限1次）": {"lng": 2, "lat": 2}}
    spots, coords, aliases, _ = canonicalize_spots(spots, coords)
    assert aliases == {"多乐台球（限1次）": "多乐台球"}
    assert set(coords) == {"多乐台球"}


def test_location_paren_kept_separate():
    spots = [_spot("爱蹦蹦床馆(武昌奥山世纪城店)"), _spot("爱蹦蹦床馆(汉口宗关店)")]
    coords = {s["spot_name"]: {"lng": 1, "lat": 1} for s in spots}
    spots, coords, aliases, _ = canonicalize_spots(spots, coords)
    assert aliases == {}
    assert len(coords) == 2


def test_cross_city_never_merges():
    spots = [_spot("观音洞", city="襄阳"), _spot("观音洞(房县)", city="十堰")]
    coords = {s["spot_name"]: {"lng": 1, "lat": 1} for s in spots}
    spots, coords, aliases, _ = canonicalize_spots(spots, coords)
    assert aliases == {}
    assert len(coords) == 2


def test_city_prefix_merges():
    spots = [_spot("花博汇"), _spot("武汉花博汇")]
    coords = {"花博汇": {"lng": 1, "lat": 1}, "武汉花博汇": {"lng": 1, "lat": 1}}
    spots, coords, aliases, _ = canonicalize_spots(spots, coords)
    assert aliases == {"武汉花博汇": "花博汇"}
    assert set(coords) == {"花博汇"}


def test_qualifier_classification():
    assert is_qualifier("青山区") and is_qualifier("夷陵") and is_qualifier("限1次")
    assert is_qualifier("需补50") and is_qualifier("不含夜场")
    assert not is_qualifier("武昌奥山世纪城店") and not is_qualifier("苗家码头")
    assert not is_qualifier("叶坪景区") and not is_qualifier("极客公园")
    assert split_base("X(A)(B)") == ("X", ["A", "B"])
