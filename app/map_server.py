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

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path.startswith('/api/search_poi'):
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            query = params.get('query', [''])[0]
            if not query:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'missing query'}).encode('utf-8'))
                return
            # Extract city hint from query (e.g. "武汉 黄鹤楼" -> city="武汉", kw="黄鹤楼")
            parts = query.split(None, 1)
            city = parts[0] if len(parts) > 1 else ''
            keywords = parts[1] if len(parts) > 1 else query
            url = "https://restapi.amap.com/v3/place/text"
            api_params = {
                "key": AMAP_WEB_KEY,
                "keywords": keywords,
                "output": "json",
                "pagesize": 5,
            }
            if city:
                api_params["city"] = city
            resp = requests.get(url, params=api_params, timeout=10)
            data = resp.json()
            if data.get("status") == "1" and data.get("pois"):
                pois = []
                for p in data["pois"][:5]:
                    loc = p.get("location", "0,0").split(",")
                    pois.append({
                        "name": p.get("name", ""),
                        "lng": float(loc[0]),
                        "lat": float(loc[1]),
                        "address": p.get("address", ""),
                    })
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"pois": pois}, ensure_ascii=False).encode('utf-8'))
            else:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"pois": []}, ensure_ascii=False).encode('utf-8'))
        else:
            super().do_GET()

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
