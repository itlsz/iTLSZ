"""Vercel function: live Spotify card.

GET /api/spotify?theme=dark|light   (demo=1 renders sample data without calling Spotify)
Needs SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET and SPOTIFY_REFRESH_TOKEN as Vercel env vars.
"""
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spotify.card import THEMES, card, render  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        theme = query.get("theme", ["dark"])[0]
        if theme not in THEMES:
            theme = "dark"
        try:
            svg = card(theme, demo=query.get("demo", ["0"])[0] == "1")
        except Exception:
            # A broken image on the profile looks worse than the offline card.
            traceback.print_exc()
            svg = render(None, THEMES[theme])

        body = svg.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        # GitHub's image proxy honours this, so each profile view asks for a fresh card.
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
