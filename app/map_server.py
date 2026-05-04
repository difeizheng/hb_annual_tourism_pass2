"""Standalone map server for the tourism pass app.

Run this separately from Streamlit:
    python map_server.py

It serves static map HTML files and provides API endpoints for coordinate correction.
"""
import json
import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests

# Add project root to path for trip_planner imports
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, PROJECT_ROOT)

STATIC_DIR = os.path.join(PROJECT_ROOT, 'static')
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
MAP_PORT = 18793

# Try to load API key from Streamlit secrets file
SECRETS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.streamlit', 'secrets.toml')
AMAP_WEB_KEY = ""
if os.path.exists(SECRETS_FILE):
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with open(SECRETS_FILE, 'rb') as f:
        secrets = tomllib.load(f)
        AMAP_WEB_KEY = secrets.get('amap_web_key', '')


class MapHandler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=STATIC_DIR, **k)

    def guess_type(self, path):
        if path.endswith('.html'):
            return 'text/html; charset=utf-8'
        return super().guess_type(path)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def do_POST(self):
        if self.path == '/api/save_coord':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode('utf-8'))
                name = data.get('name', '')
                lng = data.get('lng')
                lat = data.get('lat')
                if name and lng is not None and lat is not None:
                    coord_file = os.path.join(DATA_DIR, 'spot_coordinates.json')
                    coords = {}
                    if os.path.exists(coord_file):
                        with open(coord_file, 'r', encoding='utf-8') as f:
                            coords = json.load(f)
                    coords[name] = {'lng': lng, 'lat': lat}
                    os.makedirs(os.path.dirname(coord_file), exist_ok=True)
                    with open(coord_file, 'w', encoding='utf-8') as f:
                        json.dump(coords, f, ensure_ascii=False, indent=2)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': True}).encode('utf-8'))
                    print(f"[save_coord] {name} -> ({lng}, {lat})")
                else:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'missing fields'}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        elif self.path == '/api/add_to_trip':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode('utf-8'))
                name = data.get('name', '')
                if not name:
                    self._json_response(400, {'error': 'missing spot name'})
                    return
                trip_file = os.path.join(DATA_DIR, 'quick_trip_spots.json')
                trip_spots = []
                if os.path.exists(trip_file):
                    with open(trip_file, 'r', encoding='utf-8') as f:
                        trip_spots = json.load(f)
                existing = {s.get('name') for s in trip_spots}
                action = 'duplicate' if name in existing else 'added'
                if name not in existing:
                    trip_spots.append(data)
                    os.makedirs(os.path.dirname(trip_file), exist_ok=True)
                    with open(trip_file, 'w', encoding='utf-8') as f:
                        json.dump(trip_spots, f, ensure_ascii=False, indent=2)
                self._json_response(200, {'ok': True, 'action': action})
                print(f"[add_to_trip] {name} -> {action}")
            except Exception as e:
                self._json_response(500, {'error': str(e)})
        elif self.path == '/api/remove_from_trip':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode('utf-8'))
                name = data.get('name', '')
                trip_file = os.path.join(DATA_DIR, 'quick_trip_spots.json')
                if os.path.exists(trip_file):
                    with open(trip_file, 'r', encoding='utf-8') as f:
                        trip_spots = json.load(f)
                    trip_spots = [s for s in trip_spots if s.get('name') != name]
                    with open(trip_file, 'w', encoding='utf-8') as f:
                        json.dump(trip_spots, f, ensure_ascii=False, indent=2)
                self._json_response(200, {'ok': True})
                print(f"[remove_from_trip] {name}")
            except Exception as e:
                self._json_response(500, {'error': str(e)})
        elif self.path == '/api/notify_parent':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode('utf-8'))
                flag_file = os.path.join(DATA_DIR, "_remove_spot_flag.json")
                with open(flag_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                self._json_response(200, {'ok': True})
            except Exception as e:
                self._json_response(500, {'error': str(e)})
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == '/api/search_poi':
            self._handle_search_poi(params)
        elif path == '/api/driving_route':
            self._handle_driving_route(params)
        elif path == '/api/nearby':
            self._handle_nearby(params)
        elif path == '/api/distance_matrix':
            self._handle_distance_matrix(params)
        elif path == '/api/reviews':
            self._handle_reviews(params)
        else:
            super().do_GET()

    def _handle_search_poi(self, params):
        query = params.get('query', [''])[0]
        if not query:
            self._json_response(400, {'error': 'missing query'})
            return
        url = "https://restapi.amap.com/v3/place/text"

        # Strategy 1: search by keywords only (no city filter) — highest relevance
        api_params = {"key": AMAP_WEB_KEY, "keywords": query, "output": "json", "pagesize": 8}
        resp = requests.get(url, params=api_params, timeout=10)
        data = resp.json()
        if data.get("status") == "1" and data.get("pois"):
            pois = []
            for p in data["pois"][:8]:
                loc = p.get("location", "0,0").split(",")
                pois.append({
                    "name": p.get("name", ""),
                    "lng": float(loc[0]),
                    "lat": float(loc[1]),
                    "address": p.get("address", ""),
                    "city": p.get("cityname", ""),
                })
            self._json_response(200, {"pois": pois})
            return

        # Strategy 2: split into city + keywords, retry with city filter
        parts = query.split(None, 1)
        if len(parts) == 2:
            city, keywords = parts
            api_params = {
                "key": AMAP_WEB_KEY, "keywords": keywords,
                "city": city, "output": "json", "pagesize": 8,
            }
            resp = requests.get(url, params=api_params, timeout=10)
            data = resp.json()
            if data.get("status") == "1" and data.get("pois"):
                pois = []
                for p in data["pois"][:8]:
                    loc = p.get("location", "0,0").split(",")
                    pois.append({
                        "name": p.get("name", ""),
                        "lng": float(loc[0]),
                        "lat": float(loc[1]),
                        "address": p.get("address", ""),
                        "city": p.get("cityname", ""),
                    })
                self._json_response(200, {"pois": pois})
                return

        self._json_response(200, {"pois": []})

    def _handle_driving_route(self, params):
        origin = params.get('origin', [''])[0]
        destination = params.get('destination', [''])[0]
        if not origin or not destination:
            self._json_response(400, {'error': 'missing origin or destination'})
            return
        waypoints = params.get('waypoints', [''])[0]
        url = "https://restapi.amap.com/v3/direction/driving"
        api_params = {"key": AMAP_WEB_KEY, "origin": origin, "destination": destination, "extensions": "all", "output": "json"}
        if waypoints:
            api_params["waypoints"] = waypoints
        try:
            resp = requests.get(url, params=api_params, timeout=15)
            self._json_response(200, resp.json())
        except Exception as e:
            self._json_response(500, {'error': str(e)})

    def _handle_nearby(self, params):
        location = params.get('location', [''])[0]
        if not location:
            self._json_response(400, {'error': 'missing location'})
            return
        poi_type = params.get('types', params.get('type', ['']))[0]
        radius = params.get('radius', ['2000'])[0]
        url = "https://restapi.amap.com/v3/place/around"
        api_params = {"key": AMAP_WEB_KEY, "location": location, "radius": min(int(radius), 50000), "output": "json"}
        if poi_type:
            api_params["types"] = poi_type
        try:
            resp = requests.get(url, params=api_params, timeout=10)
            self._json_response(200, resp.json())
        except Exception as e:
            self._json_response(500, {'error': str(e)})

    def _handle_distance_matrix(self, params):
        origins = params.get('origins', [''])[0]
        destinations = params.get('destinations', params.get('destination', ['']))[0]
        if not origins or not destinations:
            self._json_response(400, {'error': 'missing origins or destinations'})
            return
        dist_type = params.get('type', ['1'])[0]
        url = "https://restapi.amap.com/v3/distance"
        api_params = {"key": AMAP_WEB_KEY, "origins": origins, "destination": destinations, "type": dist_type, "output": "json"}
        try:
            resp = requests.get(url, params=api_params, timeout=10)
            self._json_response(200, resp.json())
        except Exception as e:
            self._json_response(500, {'error': str(e)})

    def _handle_reviews(self, params):
        name = params.get('name', [''])[0]
        city = params.get('city', [''])[0]
        if not name:
            self._json_response(400, {'error': 'missing spot name'})
            return
        from src.trip_planner.review_scraper import scrape_reviews, set_amap_key
        set_amap_key(AMAP_WEB_KEY)
        try:
            result = scrape_reviews(name, city)
            self._json_response(200, {
                "spot_name": result.spot_name,
                "overall_rating": result.overall_rating,
                "review_count": result.review_count,
                "reviews": [
                    {"source": r.source, "rating": r.rating, "text": r.text,
                     "author": r.author, "date": r.date, "upvotes": r.upvotes}
                    for r in result.reviews
                ],
                "sources_used": result.sources_used,
                "cached_at": result.cached_at,
            })
        except Exception as e:
            self._json_response(500, {'error': str(e)})

    def _json_response(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def log_message(self, fmt, *args):
        pass


def main():
    os.makedirs(STATIC_DIR, exist_ok=True)
    server = HTTPServer(("127.0.0.1", MAP_PORT), MapHandler)
    print(f"Map server started on http://127.0.0.1:{MAP_PORT}")
    print(f"  Static dir: {STATIC_DIR}")
    print(f"  API key loaded: {'yes' if AMAP_WEB_KEY else 'no'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
