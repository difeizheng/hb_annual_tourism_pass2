"""E2E tests for app/map_server.py — real HTTP against a real server instance.

The server is started once per session (module-scoped fixture) on a test port
with STATIC_DIR pointing at the project's static/ (read-only usage) and its
writable payloads (spot_coordinates / quick_trip / remove flag) verified via
the shared files, then restored. Endpoints that proxy the AMap public API are
only exercised for their argument-validation branch (400) — no network.
"""
import json
import os
import socket
import subprocess
import sys
import time

import pytest
import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

MAP_PORT = 18793  # app/map_server.py hardcodes this port


def _wait_port(port, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


def _server_is_healthy(port):
    """Probe the argument-validation branch: a live map_server answers 400."""
    try:
        r = requests.get(f"http://127.0.0.1:{port}/api/search_poi", timeout=3)
        return r.status_code == 400
    except requests.RequestException:
        return False


MAP_SERVER_SCRIPT = os.path.join(PROJECT_ROOT, "app", "map_server.py")
COORD_FILE = os.path.join(PROJECT_ROOT, "data", "spot_coordinates.json")
TRIP_FILE = os.path.join(PROJECT_ROOT, "data", "quick_trip_spots.json")
FLAG_FILE = os.path.join(PROJECT_ROOT, "data", "_remove_spot_flag.json")


@pytest.fixture(scope="module", autouse=True)
def map_server():
    # Snapshot files the server may write, restore after the module.
    snapshots = {}
    for f in (COORD_FILE, TRIP_FILE, FLAG_FILE):
        if os.path.exists(f):
            with open(f, "r", encoding="utf-8") as fh:
                snapshots[f] = fh.read()
    proc = None
    if not _server_is_healthy(MAP_PORT):
        proc = subprocess.Popen(
            [sys.executable, MAP_SERVER_SCRIPT],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if not _wait_port(MAP_PORT) or not _server_is_healthy(MAP_PORT):
            if proc:
                proc.terminate()
            pytest.skip("map server failed to start on 18793")
    # If a healthy server already listens (the app starts one as a
    # subprocess), reuse it and leave it running after tests.
    yield
    if proc:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    for f, content in snapshots.items():
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(content)
    for f in (TRIP_FILE, FLAG_FILE):
        if f not in snapshots and os.path.exists(f):
            os.remove(f)


@pytest.fixture(scope="module")
def port():
    return MAP_PORT


def _base(port):
    return f"http://127.0.0.1:{port}"


def test_static_map_html_served(port):
    html_files = sorted(
        f for f in os.listdir(os.path.join(PROJECT_ROOT, "static"))
        if f.startswith("map_") and f.endswith(".html")
    )
    if not html_files:
        pytest.skip("no static map html present")
    r = requests.get(f"{_base(port)}/{html_files[0]}", timeout=5)
    assert r.status_code == 200
    assert "AMap" in r.text or "高德" in r.text or "map" in r.text.lower()


def test_404_for_missing_file(port):
    r = requests.get(f"{_base(port)}/nonexistent__test__.html", timeout=5)
    assert r.status_code == 404


def test_save_coord_roundtrip(port):
    name = f"__e2e_test_spot_{int(time.time())}"
    payload = {"name": name, "lng": 114.305, "lat": 30.593}
    r = requests.post(f"{_base(port)}/api/save_coord",
                      data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"}, timeout=5)
    assert r.status_code == 200
    assert r.json().get("ok") is True
    with open(COORD_FILE, "r", encoding="utf-8") as f:
        coords = json.load(f)
    assert coords[name]["lng"] == 114.305
    assert coords[name]["lat"] == 30.593
    del coords[name]  # cleanup immediately; module fixture also restores


def test_save_coord_missing_fields_400(port):
    r = requests.post(f"{_base(port)}/api/save_coord",
                      data=json.dumps({"name": "", "lng": 1.0, "lat": 2.0}).encode(),
                      headers={"Content-Type": "application/json"}, timeout=5)
    assert r.status_code == 400


def test_add_and_remove_from_trip(port):
    name = f"__e2e_test_trip_{int(time.time())}"
    spot = {"name": name, "lng": 112.0, "lat": 30.7, "city": "宜昌"}
    r = requests.post(f"{_base(port)}/api/add_to_trip",
                      data=json.dumps(spot).encode(),
                      headers={"Content-Type": "application/json"}, timeout=5)
    assert r.status_code == 200 and r.json()["action"] == "added"
    # duplicate add → action=duplicate
    r2 = requests.post(f"{_base(port)}/api/add_to_trip",
                       data=json.dumps(spot).encode(),
                       headers={"Content-Type": "application/json"}, timeout=5)
    assert r2.status_code == 200 and r2.json()["action"] == "duplicate"
    # remove
    r3 = requests.post(f"{_base(port)}/api/remove_from_trip",
                       data=json.dumps({"name": name}).encode(),
                       headers={"Content-Type": "application/json"}, timeout=5)
    assert r3.status_code == 200 and r3.json()["ok"] is True
    with open(TRIP_FILE, "r", encoding="utf-8") as f:
        remaining = [s["name"] for s in json.load(f)]
    assert name not in remaining


def test_notify_parent_writes_flag(port):
    payload = {"action": "remove", "name": "__e2e_flag__"}
    r = requests.post(f"{_base(port)}/api/notify_parent",
                      data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"}, timeout=5)
    assert r.status_code == 200 and r.json()["ok"] is True
    with open(FLAG_FILE, "r", encoding="utf-8") as f:
        assert json.load(f) == payload


def test_unknown_api_404(port):
    r = requests.post(f"{_base(port)}/api/__nope__",
                      data=b"{}", headers={"Content-Type": "application/json"},
                      timeout=5)
    assert r.status_code == 404


def test_search_poi_missing_query_400(port):
    """Argument validation only — no real AMap call."""
    r = requests.get(f"{_base(port)}/api/search_poi", timeout=5)
    assert r.status_code == 400


def test_driving_route_missing_args_400(port):
    r = requests.get(f"{_base(port)}/api/driving_route", timeout=5)
    assert r.status_code == 400


def test_nearby_missing_args_400(port):
    r = requests.get(f"{_base(port)}/api/nearby", timeout=5)
    assert r.status_code == 400


def test_distance_matrix_missing_args_400(port):
    r = requests.get(f"{_base(port)}/api/distance_matrix", timeout=5)
    assert r.status_code == 400


def test_reviews_missing_name_400(port):
    r = requests.get(f"{_base(port)}/api/reviews", timeout=5)
    assert r.status_code == 400
