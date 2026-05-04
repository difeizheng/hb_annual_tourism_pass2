"""End-to-end test for map server and coordinate correction flow."""
import json
import os
import socket
import subprocess
import sys
import time

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_PORT = 18793
MAP_SERVER_SCRIPT = os.path.join(PROJECT_ROOT, 'app', 'map_server.py')
COORD_FILE = os.path.join(PROJECT_ROOT, 'data', 'spot_coordinates.json')


def is_port_open(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    return result == 0


def start_map_server():
    if is_port_open(MAP_PORT):
        print("Map server already running")
        return None
    log_path = os.path.join(PROJECT_ROOT, 'data', 'test_map_server.log')
    with open(log_path, 'w') as log:
        proc = subprocess.Popen(
            [sys.executable, MAP_SERVER_SCRIPT],
            stdout=log,
            stderr=log,
        )
    time.sleep(2)
    if not is_port_open(MAP_PORT):
        print("ERROR: Map server failed to start")
        with open(log_path) as f:
            print(f.read())
        return None
    print(f"Map server started on port {MAP_PORT}")
    return proc


def test_static_file_serving():
    """Test that map HTML files are served correctly."""
    html_files = [f for f in os.listdir(os.path.join(PROJECT_ROOT, 'static'))
                  if f.startswith('map_') and f.endswith('.html')]
    if not html_files:
        print("SKIP: No map HTML files found")
        return True
    fname = html_files[0]
    r = requests.get(f'http://127.0.0.1:{MAP_PORT}/{fname}', timeout=5)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    assert 'AMap' in r.text or '高德' in r.text, "Map HTML should contain AMap content"
    print(f"PASS: Static file serving ({fname}, {len(r.text)} bytes)")
    return True


def test_404_for_missing():
    """Test that missing files return 404."""
    r = requests.get(f'http://127.0.0.1:{MAP_PORT}/nonexistent.html', timeout=5)
    assert r.status_code == 404, f"Expected 404, got {r.status_code}"
    print("PASS: 404 for missing files")
    return True


def test_search_poi_endpoint():
    """Test POI search endpoint exists and returns valid JSON."""
    r = requests.get(f'http://127.0.0.1:{MAP_PORT}/api/search_poi?query=test', timeout=5)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert 'pois' in data, "Response should have 'pois' field"
    print(f"PASS: POI search endpoint returns valid JSON (results: {len(data['pois'])})")
    if data['pois']:
        poi = data['pois'][0]
        assert 'name' in poi, "POI should have 'name'"
        assert 'lng' in poi, "POI should have 'lng'"
        assert 'lat' in poi, "POI should have 'lat'"
    return True


def test_save_coord_endpoint():
    """Test coordinate saving."""
    test_name = f"__test_spot_{time.time()}"
    payload = json.dumps({'name': test_name, 'lng': 114.305, 'lat': 30.593})
    r = requests.post(f'http://127.0.0.1:{MAP_PORT}/api/save_coord',
                      data=payload.encode(),
                      headers={'Content-Type': 'application/json'},
                      timeout=5)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert data.get('ok') is True, "Response should have ok=true"

    # Verify saved in file
    assert os.path.exists(COORD_FILE), "Coordinate file should exist"
    with open(COORD_FILE, 'r', encoding='utf-8') as f:
        coords = json.load(f)
    assert test_name in coords, f"Test spot should be in coordinates"
    assert coords[test_name]['lng'] == 114.305
    assert coords[test_name]['lat'] == 30.593

    # Clean up
    del coords[test_name]
    with open(COORD_FILE, 'w', encoding='utf-8') as f:
        json.dump(coords, f, ensure_ascii=False, indent=2)

    print("PASS: Save coordinate endpoint works")
    return True


def test_map_html_content():
    """Test that map HTML contains coordinate correction UI."""
    html_files = [f for f in os.listdir(os.path.join(PROJECT_ROOT, 'static'))
                  if f.startswith('map_') and f.endswith('.html')]
    if not html_files:
        print("SKIP: No map HTML files to check for correction UI")
        return True
    fname = html_files[0]
    with open(os.path.join(PROJECT_ROOT, 'static', fname), 'r', encoding='utf-8') as f:
        html = f.read()
    has_correction_ui = '坐标有误' in html or 'correctCoord' in html
    assert has_correction_ui, "Map HTML should contain coordinate correction UI"
    print("PASS: Coordinate correction UI present in map HTML")
    return True


def main():
    print("=" * 50)
    print("Map Server E2E Tests")
    print("=" * 50)

    proc = start_map_server()
    if not is_port_open(MAP_PORT):
        print("FAIL: Map server not available. Aborting tests.")
        sys.exit(1)

    tests = [
        test_static_file_serving,
        test_404_for_missing,
        test_search_poi_endpoint,
        test_save_coord_endpoint,
        test_map_html_content,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"FAIL: {test.__name__}: {e}")
            failed += 1

    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 50)

    if proc:
        proc.terminate()

    sys.exit(1 if failed > 0 else 0)


if __name__ == '__main__':
    main()
