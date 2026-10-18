"""Render the terminal-style Spotify card used in the profile README.

Used live by the Vercel function in api/spotify.py, and from the command line:
  python3 spotify/card.py <out dir>            # needs SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REFRESH_TOKEN
  python3 spotify/card.py <out dir> --record   # write last.json with the track on the player (used by the Action)
  python3 spotify/card.py <out dir> --demo     # sample data, no credentials

Writes spotify-dark.svg and spotify-light.svg. Standard library only.
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

THEMES = {
    "dark": dict(
        window="#0d1117", bar="#161b22", border="#30363d", track="#21262d",
        text="#e6edf3", muted="#8b949e", accent="#7ee787", blue="#79c0ff", scan="#ffffff",
    ),
    "light": dict(
        window="#ffffff", bar="#f6f8fa", border="#d0d7de", track="#eaeef2",
        text="#1f2328", muted="#59636e", accent="#1a7f37", blue="#0969da", scan="#000000",
    ),
}

SPOTIFY = "#1DB954"
FONT = "'JetBrains Mono','SF Mono',SFMono-Regular,Menlo,Consolas,'DejaVu Sans Mono',monospace"
W, H = 850, 236
COVER = 120
TEXT_X = 32 + COVER + 28
BAR_W = W - TEXT_X - 32


def http_json(req):
    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read()
        return r.status, (json.loads(body) if body else None)


_token = {"value": None, "expires": 0.0}


def access_token():
    # Warm serverless instances reuse the token until shortly before it expires.
    if _token["value"] and time.time() < _token["expires"]:
        return _token["value"]
    cid = os.environ["SPOTIFY_CLIENT_ID"]
    secret = os.environ["SPOTIFY_CLIENT_SECRET"]
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": os.environ["SPOTIFY_REFRESH_TOKEN"],
    }).encode()
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token", data=data,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
    )
    body = http_json(req)[1]
    _token.update(value=body["access_token"], expires=time.time() + body.get("expires_in", 3600) - 60)
    return _token["value"]


# Last track seen on the player (even paused), recorded by the spotify-card Action every few minutes.
# Spotify's recently-played list only gets tracks that finished, so a song paused halfway would be lost.
LAST_URL = os.environ.get("SPOTIFY_LAST_URL", "https://raw.githubusercontent.com/itlsz/iTLSZ/spotify-card/last.json")


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def player_state(headers):
    """What the player holds right now (playing or paused), or None."""
    status, now = http_json(urllib.request.Request(
        "https://api.spotify.com/v1/me/player/currently-playing?additional_types=track", headers=headers))
    if status == 200 and now and now.get("item") and now.get("currently_playing_type") == "track":
        return track_state(now["item"], playing=now.get("is_playing", False), progress=now.get("progress_ms") or 0)
    return None


def load_last():
    try:
        with urllib.request.urlopen(f"{LAST_URL}?t={int(time.time())}", timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return None


def fetch_state():
    """Return dict(playing, title, artist, album, cover_url, progress_ms, duration_ms)."""
    headers = {"Authorization": f"Bearer {access_token()}"}
    current = player_state(headers)
    if current:
        return current

    _, recent = http_json(urllib.request.Request(
        "https://api.spotify.com/v1/me/player/recently-played?limit=1", headers=headers))
    items = (recent or {}).get("items") or []
    finished = track_state(items[0]["track"], playing=False, progress=None) if items else None
    if finished:
        finished["at"] = items[0].get("played_at", "")[:19] + "Z"

    # Whichever happened last wins: a finished track, or one we saw on the player before it went idle.
    last = load_last()
    candidates = [c for c in (finished, last) if c]
    if not candidates:
        return None
    best = max(candidates, key=lambda c: c.get("at", ""))
    best.update(playing=False, progress_ms=None)
    return best


def record(out):
    """Action mode: keep last.json pointing at the latest track seen on the player."""
    headers = {"Authorization": f"Bearer {access_token()}"}
    current = player_state(headers)
    if current:
        current["at"] = now_iso()
        data = current
    else:
        data = load_last()
    if data:
        data.pop("cover_uri", None)
        (out / "last.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def track_state(item, playing, progress):
    images = sorted(item["album"].get("images") or [], key=lambda i: i.get("width") or 0)
    cover = next((i["url"] for i in images if (i.get("width") or 0) >= 240), images[-1]["url"] if images else None)
    return dict(
        playing=playing,
        title=item["name"],
        artist=", ".join(a["name"] for a in item["artists"]),
        album=item["album"]["name"],
        year=(item["album"].get("release_date") or "")[:4],
        cover_url=cover,
        progress_ms=progress,
        duration_ms=item["duration_ms"],
    )


def cover_data_uri(url):
    if not url:
        return None
    with urllib.request.urlopen(url, timeout=20) as r:
        ctype = r.headers.get_content_type() or "image/jpeg"
        return f"data:{ctype};base64,{base64.b64encode(r.read()).decode()}"


def demo_state():
    cover = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#1DB954"/><stop offset="1" stop-color="#0d4f8b"/></linearGradient></defs>'
        '<rect width="120" height="120" fill="url(#g)"/>'
        '<circle cx="60" cy="60" r="30" fill="none" stroke="#fff" stroke-opacity=".5" stroke-width="2"/>'
        '<circle cx="60" cy="60" r="6" fill="#fff" fill-opacity=".7"/></svg>'
    )
    return dict(
        playing=True, title="Nombre de la canción", artist="Artista de ejemplo",
        album="Álbum de ejemplo", year="2026",
        cover_uri="data:image/svg+xml;base64," + base64.b64encode(cover.encode()).decode(),
        progress_ms=83_000, duration_ms=214_000,
    )


def clip(text, n):
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def mmss(ms):
    s = int(ms // 1000)
    return f"{s // 60}:{s % 60:02d}"


def equalizer(x, base_y, playing):
    bars = []
    steps = [(6, 18, 10), (14, 6, 20), (10, 22, 8), (18, 8, 14), (8, 16, 6)]
    for i, (a, b, c) in enumerate(steps):
        bx = x + i * 7
        if playing:
            dur = f"{0.9 + i * 0.13:.2f}s"
            hs = ";".join(str(v) for v in (a, b, c, a))
            ys = ";".join(str(base_y - v) for v in (a, b, c, a))
            anim = (f'<animate attributeName="height" values="{hs}" dur="{dur}" repeatCount="indefinite"/>'
                    f'<animate attributeName="y" values="{ys}" dur="{dur}" repeatCount="indefinite"/>')
            bars.append(f'<rect x="{bx}" y="{base_y - a}" width="4" height="{a}" rx="1" fill="{SPOTIFY}">{anim}</rect>')
        else:
            bars.append(f'<rect x="{bx}" y="{base_y - 3}" width="4" height="3" rx="1" fill="{SPOTIFY}" opacity="0.5"/>')
    return "".join(bars)


def render(state, t):
    top = 96
    if state is None:
        c = 32 + COVER / 2
        body = (f'<rect x="32" y="{top}" width="{COVER}" height="{COVER}" rx="10" fill="{t["track"]}"/>'
                f'<circle cx="{c}" cy="{top + COVER / 2}" r="44" fill="none" stroke="{t["muted"]}" stroke-opacity="0.4" stroke-width="2"/>'
                f'<circle cx="{c}" cy="{top + COVER / 2}" r="28" fill="none" stroke="{t["muted"]}" stroke-opacity="0.25"/>'
                f'<circle cx="{c}" cy="{top + COVER / 2}" r="6" fill="{t["muted"]}" fill-opacity="0.6"/>'
                f'<text x="{TEXT_X}" y="{top + 26}" font-size="24" font-weight="700" fill="{t["text"]}">Nada sonando por ahora</text>'
                f'<text x="{TEXT_X}" y="{top + 52}" font-size="15" fill="{t["muted"]}">Spotify en pausa · vuelve en un rato</text>')
        return frame(t, body, status_html(t, False, "offline"))

    playing = state["playing"]
    cover = state.get("cover_uri") or cover_data_uri(state["cover_url"])
    title = escape(clip(state["title"], 34))
    artist = escape(clip(state["artist"], 52))
    album_line = escape(clip(state["album"], 46)) + (f' · {state["year"]}' if state.get("year") else "")

    if state["progress_ms"] is not None:
        frac = max(0.0, min(1.0, state["progress_ms"] / max(1, state["duration_ms"])))
        left, right = mmss(state["progress_ms"]), mmss(state["duration_ms"])
    else:
        frac, left, right = 1.0, "", mmss(state["duration_ms"])

    bar_y = top + COVER - 22
    cover_svg = (
        f'<clipPath id="cover"><rect x="32" y="{top}" width="{COVER}" height="{COVER}" rx="10"/></clipPath>'
        f'<image href="{cover}" x="32" y="{top}" width="{COVER}" height="{COVER}" preserveAspectRatio="xMidYMid slice" clip-path="url(#cover)"/>'
        f'<rect x="32.5" y="{top + 0.5}" width="{COVER - 1}" height="{COVER - 1}" rx="10" fill="none" stroke="{t["border"]}"/>'
        if cover else
        f'<rect x="32" y="{top}" width="{COVER}" height="{COVER}" rx="10" fill="{t["track"]}"/>'
    )
    fill_w = BAR_W * frac
    # While playing, the bar and the elapsed clock keep advancing until the song ends.
    remaining = (state["duration_ms"] - state["progress_ms"]) / 1000 if playing and state["progress_ms"] is not None else 0
    grow = (f'<animate attributeName="width" from="{fill_w:.1f}" to="{BAR_W}" dur="{remaining:.1f}s" fill="freeze"/>'
            if remaining > 0 else "")
    slide = (f'<animate attributeName="cx" from="{TEXT_X + fill_w:.1f}" to="{TEXT_X + BAR_W}" dur="{remaining:.1f}s" fill="freeze"/>'
             if remaining > 0 else "")
    fill = (
        f'<rect x="{TEXT_X}" y="{bar_y}" width="{fill_w:.1f}" height="4" rx="2" fill="{SPOTIFY if playing else t["muted"]}">{grow}</rect>'
        + (f'<circle cx="{TEXT_X + fill_w:.1f}" cy="{bar_y + 2}" r="6" fill="{t["text"]}">{slide}</circle>' if playing else "")
    )
    clock = elapsed_clock(t, bar_y + 24, left, state["progress_ms"], int(remaining))
    body = f'''{cover_svg}
    <text x="{TEXT_X}" y="{top + 26}" font-size="24" font-weight="700" fill="{t['text']}">{title}</text>
    <text x="{TEXT_X}" y="{top + 52}" font-size="15" fill="{t['accent']}">{artist}</text>
    <text x="{TEXT_X}" y="{top + 74}" font-size="13" fill="{t['muted']}">{album_line}</text>
    <rect x="{TEXT_X}" y="{bar_y}" width="{BAR_W}" height="4" rx="2" fill="{t['track']}"/>
    {fill}
    {clock}
    <text x="{TEXT_X + BAR_W}" y="{bar_y + 24}" text-anchor="end" font-size="12" fill="{t['muted']}">{right}</text>
    {equalizer(W - 32 - 33, top + 24, playing)}'''
    return frame(t, body, status_html(t, playing, "live" if playing else "recent"))


def elapsed_clock(t, y, label, progress_ms, seconds):
    """Elapsed time that ticks once per second for `seconds` (capped at 15 min)."""
    attrs = f'x="{TEXT_X}" y="{y}" font-size="12" fill="{t["muted"]}"'
    if seconds <= 0:
        return f'<text {attrs}>{label}</text>'
    seconds = min(seconds, 900)
    ticks = [f'<text {attrs}>{label}<set attributeName="visibility" to="hidden" begin="1s" fill="freeze"/></text>']
    for k in range(1, seconds + 1):
        last = k == seconds
        timing = 'fill="freeze"' if last else 'dur="1s"'
        ticks.append(f'<text {attrs} visibility="hidden">{mmss(progress_ms + k * 1000)}'
                     f'<set attributeName="visibility" to="visible" begin="{k}s" {timing}/></text>')
    return "".join(ticks)


def status_html(t, playing, kind):
    label = {"live": "SONANDO AHORA", "recent": "ÚLTIMA ESCUCHA", "offline": "OFFLINE"}[kind]
    color = SPOTIFY if playing else t["muted"]
    pulse = ('<animate attributeName="opacity" values="1;0.25;1" dur="1.6s" repeatCount="indefinite"/>'
             if playing else "")
    width = len(label) * 7.2 + 34
    x = W - 32 - width
    return (f'<rect x="{x:.1f}" y="52" width="{width:.1f}" height="24" rx="12" fill="none" stroke="{color}" stroke-opacity="0.6"/>'
            f'<circle cx="{x + 14:.1f}" cy="64" r="4" fill="{color}">{pulse}</circle>'
            f'<text x="{x + 25:.1f}" y="68" font-size="12" font-weight="700" fill="{color}">{label}</text>')


def frame(t, body, status):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Spotify — lo que estoy escuchando">
  <title>luis@itlsz: ~/music — spotify --now-playing</title>
  <desc>© 2026 Luis López (todoesluis). Todos los derechos reservados. Diseño y código propios: prohibida su copia o reutilización sin permiso del autor.</desc>
  <defs>
    <pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse">
      <rect width="4" height="1" fill="{t['scan']}" opacity="0.03"/>
    </pattern>
    <clipPath id="win"><rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="12"/></clipPath>
  </defs>
  <g clip-path="url(#win)">
    <rect width="{W}" height="{H}" fill="{t['window']}"/>
    <rect width="{W}" height="36" fill="{t['bar']}"/>
    <rect y="36" width="{W}" height="1" fill="{t['border']}"/>
    <rect width="{W}" height="{H}" fill="url(#scan)"/>
  </g>
  <rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" fill="none" stroke="{t['border']}"/>
  <circle cx="22" cy="18" r="6" fill="#ff5f57"/>
  <circle cx="42" cy="18" r="6" fill="#febc2e"/>
  <circle cx="62" cy="18" r="6" fill="#28c840"/>
  <g font-family="{FONT}">
    <text x="{W / 2}" y="23" text-anchor="middle" font-size="13" fill="{t['muted']}">luis@itlsz: ~/music</text>
    <text x="32" y="70" font-size="15"><tspan fill="{t['accent']}">luis@itlsz</tspan><tspan fill="{t['muted']}">:</tspan><tspan fill="{t['blue']}">~</tspan><tspan fill="{t['muted']}">$</tspan> <tspan fill="{t['text']}">spotify --now-playing</tspan></text>
    {status}
    {body}
  </g>
</svg>
'''


def current_state(demo=False):
    state = demo_state() if demo else fetch_state()
    if state and not state.get("cover_uri"):
        state["cover_uri"] = cover_data_uri(state["cover_url"])
    return state


def card(theme="dark", demo=False):
    """SVG for one theme, built from what is playing right now."""
    return render(current_state(demo), THEMES.get(theme, THEMES["dark"]))


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    if "--record" in sys.argv:
        data = record(out)
        print("recorded:", data["title"] if data else "nothing yet")
        return
    state = current_state("--demo" in sys.argv)
    for name, t in THEMES.items():
        (out / f"spotify-{name}.svg").write_text(render(state, t), encoding="utf-8")
    print("playing" if state and state["playing"] else "recent" if state else "nothing", "->", out)


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        sys.exit(f"Spotify API error {e.code}: {e.read().decode(errors='replace')[:300]}")
