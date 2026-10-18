"""One-time helper: get a Spotify refresh token for the Spotify card Action.

1. Create an app at https://developer.spotify.com/dashboard
   - Redirect URI: http://127.0.0.1:8888/callback
   - API: Web API
2. Run:  python3 .github/scripts/spotify_auth.py
3. Paste the Client ID and Client Secret when asked, approve access in the browser.
4. Save the three printed values as repository secrets:
   SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REFRESH_TOKEN
"""
import base64
import getpass
import http.server
import json
import secrets
import urllib.parse
import urllib.request
import webbrowser

REDIRECT = "http://127.0.0.1:8888/callback"
SCOPES = "user-read-currently-playing user-read-recently-played"


def main():
    cid = input("Client ID: ").strip()
    secret = getpass.getpass("Client Secret (no se muestra): ").strip()
    state = secrets.token_urlsafe(16)
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": cid, "response_type": "code", "redirect_uri": REDIRECT,
        "scope": SCOPES, "state": state,
    })

    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == state and "code" in q:
                result["code"] = q["code"][0]
                msg = "Listo. Ya puedes cerrar esta pestana y volver a la terminal."
            else:
                msg = "Algo fallo: " + q.get("error", ["respuesta inesperada"])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(msg.encode())

        def log_message(self, *args):
            pass

    print("\nAbriendo el navegador para autorizar... si no se abre, entra a:\n" + url + "\n")
    webbrowser.open(url)
    with http.server.HTTPServer(("127.0.0.1", 8888), Handler) as server:
        while "code" not in result:
            server.handle_request()

    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=urllib.parse.urlencode({
            "grant_type": "authorization_code", "code": result["code"], "redirect_uri": REDIRECT,
        }).encode(),
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        token = json.loads(r.read())["refresh_token"]

    print("Guarda estos 3 secretos en GitHub (Settings > Secrets and variables > Actions):\n")
    print("SPOTIFY_CLIENT_ID      =", cid)
    print("SPOTIFY_CLIENT_SECRET  = (el que pegaste)")
    print("SPOTIFY_REFRESH_TOKEN  =", token)


if __name__ == "__main__":
    main()
