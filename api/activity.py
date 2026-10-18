"""Vercel function: live GitHub activity card.

GET /api/activity?theme=dark|light   (demo=1 renders sample data without calling GitHub)
Needs GH_STATS_TOKEN (read-only GitHub token) as a Vercel env var.
"""
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from activity.card import THEMES, card, render  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        theme = query.get("theme", ["dark"])[0]
        if theme not in THEMES:
            theme = "dark"
        try:
            svg = card(theme, demo=query.get("demo", ["0"])[0] == "1")
        except Exception:
            traceback.print_exc()
            svg = render(None, THEMES[theme])

        body = svg.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        # Short edge cache: refresh every 5 minutes and never serve a stale copy for long.
        self.send_header("Cache-Control", "public, max-age=0, s-maxage=300, stale-while-revalidate=60")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
