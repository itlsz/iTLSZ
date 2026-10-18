"""Live GitHub activity card: contribution heatmap, streak and the languages of the week.

Used by the Vercel function in api/activity.py. Needs GH_STATS_TOKEN, a read-only fine-grained token
of the profile owner (Metadata + Contents read on all repositories). It first asks GitHub for the
contribution calendar; when the profile is private that comes back empty, so it counts the owner's
commits repo by repo instead. Private work is counted without naming any repo: only totals and
language names are rendered. Standard library only.
"""
import datetime as dt
import json
import os
import random
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape

THEMES = {
    "dark": dict(
        window="#0d1117", bar="#161b22", border="#30363d", tile="#161b22", track="#21262d",
        text="#e6edf3", muted="#8b949e", accent="#7ee787", blue="#79c0ff", scan="#ffffff",
        levels=["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"],
    ),
    "light": dict(
        window="#ffffff", bar="#f6f8fa", border="#d0d7de", tile="#f6f8fa", track="#eaeef2",
        text="#1f2328", muted="#59636e", accent="#1a7f37", blue="#0969da", scan="#000000",
        levels=["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
    ),
}
LEVEL = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}

FONT = "'JetBrains Mono','SF Mono',SFMono-Regular,Menlo,Consolas,'DejaVu Sans Mono',monospace"
SANS = "Inter,'Segoe UI','Helvetica Neue',Helvetica,Arial,sans-serif"
COPY = ("<desc>© 2026 Luis López (todoesluis). Todos los derechos reservados. "
        "Diseño y código propios: prohibida su copia o reutilización sin permiso del autor.</desc>")
W, H = 850, 432
X0 = 32
WEEKS = 26
CELL, STEP = 11, 14

QUERY = """
query($from: DateTime!, $to: DateTime!) {
  viewer {
    calendar: contributionsCollection {
      contributionCalendar { totalContributions weeks { contributionDays { date contributionCount contributionLevel } } }
    }
    recent: contributionsCollection(from: $from, to: $to) {
      commitContributionsByRepository(maxRepositories: 100) {
        repository { primaryLanguage { name color } }
        contributions { totalCount }
      }
    }
  }
}
"""


def graphql(variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": variables}).encode(),
        headers={"Authorization": f"Bearer {os.environ['GH_STATS_TOKEN']}", "Content-Type": "application/json",
                 "User-Agent": "itlsz-profile-card"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.loads(r.read())
    if body.get("errors"):
        raise RuntimeError(body["errors"][0].get("message", "GraphQL error"))
    return body["data"]["viewer"]


def languages(by_repo):
    totals, colors = {}, {}
    for item in by_repo:
        lang = item["repository"].get("primaryLanguage")
        if not lang:
            continue
        totals[lang["name"]] = totals.get(lang["name"], 0) + item["contributions"]["totalCount"]
        colors[lang["name"]] = lang.get("color") or "#8b949e"
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    return [(name, count, colors[name]) for name, count in ranked]


LOGIN = os.environ.get("GH_STATS_LOGIN", "itlsz")
TZ = dt.timezone(dt.timedelta(hours=-5))          # Colombia, no daylight saving
LANG_COLORS = {
    "Python": "#3572A5", "TypeScript": "#3178c6", "JavaScript": "#f1e05a", "Dart": "#00B4AB",
    "HTML": "#e34c26", "CSS": "#563d7c", "SCSS": "#c6538c", "Shell": "#89e051", "PHP": "#4F5D95",
    "Kotlin": "#A97BFF", "Swift": "#F05138", "Go": "#00ADD8", "Java": "#b07219", "C#": "#178600",
    "C++": "#f34b7d", "Rust": "#dea584", "Ruby": "#701516", "Dockerfile": "#384d54", "SQL": "#e38c00",
    "PLpgSQL": "#336790", "Vue": "#41b883", "Svelte": "#ff3e00", "Astro": "#ff5a03",
    "Jupyter Notebook": "#DA5B0B", "PowerShell": "#012456", "Docker": "#2496ED", "YAML": "#cb171e",
    "Prisma": "#5a67d8", "GraphQL": "#e10098", "Terraform": "#7B42BC", "C": "#555555", "R": "#198CE7",
    "Makefile": "#427819", "Nginx": "#009639",
}


EXT_LANG = {
    ".py": "Python", ".ipynb": "Jupyter Notebook", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".dart": "Dart",
    ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "SCSS", ".sass": "SCSS", ".sql": "SQL",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".php": "PHP", ".kt": "Kotlin", ".kts": "Kotlin",
    ".swift": "Swift", ".java": "Java", ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".cs": "C#", ".cpp": "C++",
    ".c": "C", ".vue": "Vue", ".svelte": "Svelte", ".astro": "Astro", ".prisma": "Prisma", ".graphql": "GraphQL",
    ".gql": "GraphQL", ".tf": "Terraform", ".ps1": "PowerShell", ".yml": "YAML", ".yaml": "YAML", ".r": "R",
}
NAME_LANG = {"docker-compose.yml": "Docker", "docker-compose.yaml": "Docker", "compose.yml": "Docker",
             "compose.yaml": "Docker", "makefile": "Makefile", "nginx.conf": "Nginx"}
SKIP_DIRS = ("node_modules/", "dist/", "build/", ".next/", "vendor/", "__pycache__/", ".venv/", "venv/",
             "coverage/", "Pods/", ".dart_tool/", "migrations/")
SKIP_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock",
              "pubspec.lock", "composer.lock", "Podfile.lock"}
MAX_LINES_PER_FILE = 500          # so one generated file cannot swallow the chart


def file_lang(path):
    name = path.rsplit("/", 1)[-1]
    if name in SKIP_FILES or any(d in path for d in SKIP_DIRS):
        return None
    low = name.lower()
    if low in NAME_LANG:
        return NAME_LANG[low]
    if low.startswith("dockerfile"):
        return "Docker"
    return EXT_LANG.get(os.path.splitext(low)[1])


def rest(path):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={"Authorization": f"Bearer {os.environ['GH_STATS_TOKEN']}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "itlsz-profile-card"},
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())


def paged(path, max_pages):
    items = []
    for page in range(1, max_pages + 1):
        sep = "&" if "?" in path else "?"
        batch = rest(f"{path}{sep}per_page=100&page={page}")
        items += batch
        if len(batch) < 100:
            break
    return items


def level_of(count, cuts):
    if not count:
        return "NONE"
    return ["FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"][sum(count > c for c in cuts)]


def recent_commits(now, days):
    """(repo, sha) for the owner's commits in the window, newest first, across every readable repo."""
    stamp = (now - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    repos = [r for r in paged("/user/repos?affiliation=owner,collaborator,organization_member&sort=pushed", 3)
             if not r.get("fork") and (r.get("pushed_at") or "") >= stamp]

    def commits(repo):
        try:
            return [(repo["full_name"], c["sha"], c["commit"]["author"]["date"])
                    for c in paged(f"/repos/{repo['full_name']}/commits?author={LOGIN}&since={stamp}", 3)]
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=8) as pool:
        found = [c for batch in pool.map(commits, repos) for c in batch]
    return sorted(found, key=lambda c: c[2], reverse=True)


def file_languages(now, days, limit=80):
    """Languages weighted by lines changed per file. None when commit contents can't be read."""
    items = recent_commits(now, days)

    def detail(item):
        try:
            return rest(f"/repos/{item[0]}/commits/{item[1]}").get("files") or []
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=10) as pool:
        details = list(pool.map(detail, items[:limit]))
    readable = [d for d in details if d is not None]
    if items and not readable:
        return None
    weights = Counter()
    for files in readable:
        for f in files:
            lang = file_lang(f.get("filename", ""))
            if lang:
                weights[lang] += max(1, min(MAX_LINES_PER_FILE, f.get("additions", 0) + f.get("deletions", 0)))
    langs = [(name, w, LANG_COLORS.get(name, "#8b949e")) for name, w in weights.most_common()]
    return dict(langs=langs, commits=len(items))


def languages_for(now, fallback):
    """Prefer per-file languages for the week; widen to 30 days when the week shows fewer than two."""
    try:
        week = file_languages(now, 7)
        if week is None:
            return fallback
        if len(week["langs"]) >= 2:
            return dict(week, span="esta semana")
        month = file_languages(now, 30)
        if month and len(month["langs"]) > len(week["langs"]):
            return dict(month, span="este mes")
        if week["langs"]:
            return dict(week, span="esta semana")
        return fallback
    except Exception:
        return fallback


def repo_languages():
    """Languages across every non-fork repo the token can see, weighted by bytes of code."""
    repos = [r for r in paged("/user/repos?affiliation=owner,collaborator,organization_member", 3) if not r.get("fork")]

    def langs(repo):
        try:
            return rest(f"/repos/{repo['full_name']}/languages")
        except Exception:
            return {}

    with ThreadPoolExecutor(max_workers=10) as pool:
        per_repo = list(pool.map(langs, repos))
    total = Counter()
    for item in per_repo:
        total.update({k: v for k, v in item.items() if v})
    ranked = [(name, n, LANG_COLORS.get(name, "#8b949e")) for name, n in total.most_common()]
    return dict(all_langs=ranked, repos=sum(1 for item in per_repo if item))


def with_portfolio(state):
    try:
        state.update(repo_languages())
    except Exception:
        pass
    return state


def commit_state(now):
    """Build the calendar and the languages from the owner's commits in every repo the token can read."""
    since = now - dt.timedelta(days=365)
    stamp = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    repos = [r for r in paged("/user/repos?affiliation=owner,collaborator,organization_member&sort=pushed", 3)
             if not r.get("fork") and (r.get("pushed_at") or "") >= stamp]

    def commits(repo):
        try:
            return repo, paged(f"/repos/{repo['full_name']}/commits?author={LOGIN}&since={stamp}", 5)
        except Exception:                    # empty repo or no Contents permission: skip it
            return repo, []

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(commits, repos))

    per_day, week, month = Counter(), Counter(), Counter()
    for repo, items in results:
        lang = repo.get("language")
        for c in items:
            when = dt.datetime.fromisoformat(c["commit"]["author"]["date"].replace("Z", "+00:00"))
            per_day[when.astimezone(TZ).date()] += 1
            if lang and when >= now - dt.timedelta(days=30):
                month[lang] += 1
                if when >= now - dt.timedelta(days=7):
                    week[lang] += 1
    if not per_day:
        return None

    nonzero = sorted(v for v in per_day.values() if v)
    cuts = [nonzero[int(len(nonzero) * q)] for q in (0.25, 0.5, 0.75)]
    today = now.astimezone(TZ).date()
    days = []
    for i in range(7 * 53):
        d = today - dt.timedelta(days=7 * 53 - 1 - i)
        n = per_day.get(d, 0)
        days.append(dict(date=d.isoformat(), contributionCount=n, contributionLevel=level_of(n, cuts)))
    counts, span = (week, "esta semana") if week else (month, "este mes")
    repo_langs = [(name, n, LANG_COLORS.get(name, "#8b949e")) for name, n in counts.most_common()]
    picked = languages_for(now, dict(langs=repo_langs, commits=sum(counts.values()), span=span))
    return with_portfolio(dict(days=days, total=sum(per_day.values()), **picked))


def fetch_state(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    week = graphql({"from": (now - dt.timedelta(days=7)).isoformat(), "to": now.isoformat()})
    langs, span = languages(week["recent"]["commitContributionsByRepository"]), "esta semana"
    if not langs:
        month = graphql({"from": (now - dt.timedelta(days=30)).isoformat(), "to": now.isoformat()})
        langs, span = languages(month["recent"]["commitContributionsByRepository"]), "este mes"
    cal = week["calendar"]["contributionCalendar"]
    days = [d for w in cal["weeks"] for d in w["contributionDays"]]
    if not cal["totalContributions"] and not langs:
        # private profile: GitHub hides the calendar even from the owner's token, so count commits directly;
        # None (nothing readable) shows the private placeholder, never zeros
        return commit_state(now)
    by_repo = (week if span == "esta semana" else month)["recent"]["commitContributionsByRepository"]
    fallback = dict(langs=langs, commits=sum(i["contributions"]["totalCount"] for i in by_repo), span=span)
    picked = languages_for(now, fallback)
    if picked["span"] == span:
        picked["commits"] = fallback["commits"]   # GitHub's own count, even for rewritten or unreadable history
    return with_portfolio(dict(days=days, total=cal["totalContributions"], **picked))


def demo_state():
    rnd = random.Random(7)
    today = dt.date(2026, 10, 17)
    days = []
    for i in range(7 * 53):
        d = today - dt.timedelta(days=7 * 53 - 1 - i)
        n = 0 if rnd.random() < 0.18 else rnd.choice([1, 2, 3, 4, 6, 8, 11, 14])
        lvl = "NONE" if n == 0 else ["FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"][min(3, n // 4)]
        days.append(dict(date=d.isoformat(), contributionCount=n, contributionLevel=lvl))
    langs = [("TypeScript", 21, "#3178c6"), ("Python", 14, "#3572A5"), ("Dart", 7, "#00B4AB"),
             ("Shell", 5, "#89e051"), ("Dockerfile", 3, "#384d54"), ("SQL", 2, "#e38c00")]
    all_langs = [("TypeScript", 420, "#3178c6"), ("Python", 310, "#3572A5"), ("JavaScript", 160, "#f1e05a"),
                 ("Dart", 120, "#00B4AB"), ("HTML", 80, "#e34c26"), ("CSS", 60, "#563d7c"), ("PHP", 40, "#4F5D95"),
                 ("Shell", 20, "#89e051"), ("Docker", 10, "#2496ED")]
    return dict(days=days, total=sum(d["contributionCount"] for d in days), langs=langs, span="esta semana",
                all_langs=all_langs, repos=18)


def streak(days):
    counts = [d["contributionCount"] for d in days]
    if counts and counts[-1] == 0:          # today may simply not have started yet
        counts = counts[:-1]
    n = 0
    for c in reversed(counts):
        if c == 0:
            break
        n += 1
    return n


def fade(begin, dur=0.3):
    end = begin + dur
    return f'<animate attributeName="opacity" values="0;0;1" keyTimes="0;{begin / end:.3f};1" dur="{end:.2f}s" fill="freeze"/>'


def render(state, t):
    parts = []
    days = state["days"][-WEEKS * 7:] if state else [{"contributionLevel": "NONE"}] * (WEEKS * 7)
    # heatmap: columns are weeks, rows are weekdays
    hx, hy = X0, 104
    for i, d in enumerate(days):
        col, row = divmod(i, 7)
        color = t["levels"][LEVEL.get(d["contributionLevel"], 0)]
        parts.append(f'<rect x="{hx + col * STEP}" y="{hy + row * STEP}" width="{CELL}" height="{CELL}" rx="2.5" fill="{color}">{fade(0.2 + col * 0.03, 0.2)}</rect>')
    legend_y = hy + 7 * STEP + 14
    parts.append(f'<text x="{hx}" y="{legend_y + 9}" font-family="{FONT}" font-size="10" fill="{t["muted"]}">últimos 6 meses · incluye repos privados</text>')
    for k, color in enumerate(t["levels"]):
        parts.append(f'<rect x="{hx + WEEKS * STEP - 5 * 14 + k * 14 - 3}" y="{legend_y}" width="{CELL}" height="{CELL}" rx="2.5" fill="{color}"/>')

    # stats: one full-width row of four boxes under the heatmap and the languages
    week_commits = state.get("commits", sum(c for _, c, _ in state["langs"])) if state else 0
    span_word = "semana" if not state or state["span"] == "esta semana" else "mes"
    days_streak = streak(state["days"]) if state else 0
    stats = [
        (f'{state["total"]:,}'.replace(",", ".") if state else "—", "contribuciones", "año", t["accent"]),
        (f'{days_streak} {"día" if days_streak == 1 else "días"}' if state else "—", "racha", "seguida", t["blue"]),
        (str(week_commits) if state else "—", "commits", span_word, "#d29922"),
        (str(len((state.get("all_langs") or state["langs"]))) if state else "—", "lenguajes",
         "en total" if state and state.get("all_langs") else span_word, "#bc8cff"),
    ]
    sy = legend_y + 36 + (38 if state and state.get("all_langs") else 0)
    gap = 14
    sw = (W - 2 * X0 - gap * (len(stats) - 1)) / len(stats)
    for i, (value, label, hint, color) in enumerate(stats):
        x = hx + i * (sw + gap)
        parts.append(f'''<g>{fade(0.9 + i * 0.12)}
    <rect x="{x:.1f}" y="{sy}" width="{sw:.1f}" height="66" rx="12" fill="{t['tile']}" stroke="{t['border']}"/>
    <rect x="{x + 16:.1f}" y="{sy}" width="{sw - 32:.1f}" height="2.5" rx="1.25" fill="{color}"/>
    <text x="{x + 18:.1f}" y="{sy + 33}" font-family="{SANS}" font-size="22" font-weight="800" fill="{t['text']}">{escape(value)}</text>
    <text x="{x + 18:.1f}" y="{sy + 52}" font-family="{FONT}" font-size="11" fill="{t['muted']}"><tspan fill="{color}">{escape(label)}</tspan> · {escape(hint)}</text>
  </g>''')
    rule_y = sy + 66 + 22
    parts.append(f'<rect x="{X0}" y="{rule_y}" width="{W - 2 * X0}" height="1" fill="{t["border"]}"/>')

    # right column: every project (portfolio) on top, this week below
    lx = hx + WEEKS * STEP + 34
    lw = W - X0 - lx
    all_langs = (state or {}).get("all_langs") or []
    wy = hy + 8
    if all_langs:
        repos = state.get("repos", 0)
        parts.append(f'<text x="{lx}" y="{hy + 8}" font-family="{FONT}" font-size="13" font-weight="700" fill="{t["text"]}">'
                     f'<tspan fill="{t["accent"]}">▸</tspan> en todos mis proyectos '
                     f'<tspan font-size="10" font-weight="400" fill="{t["muted"]}">· {repos} repos · por código</tspan></text>')
        grand_all = sum(n for _, n, _ in all_langs) or 1
        top8 = [l for l in all_langs[:8] if l[1] / grand_all >= 0.01]     # under 1% goes to "otros"
        rest_n = grand_all - sum(n for _, n, _ in top8)
        segs = top8 + ([("otros", rest_n, t["muted"])] if rest_n else [])
        grand = sum(n for _, n, _ in segs) or 1
        bx, by = lx, hy + 20
        parts.append(f'<clipPath id="pbar"><rect x="{bx}" y="{by}" width="{lw}" height="12" rx="6"/></clipPath>')
        seg_svg, cx = [], bx
        for i, (name, n, color) in enumerate(segs):
            w = lw * n / grand
            seg_svg.append(f'<rect x="{cx:.1f}" y="{by}" width="{w + 0.5:.1f}" height="12" fill="{color}"/>')
            cx += w
        parts.append(f'<g clip-path="url(#pbar)">{fade(0.5, 0.6)}<rect x="{bx}" y="{by}" width="{lw}" height="12" fill="{t["track"]}"/>{"".join(seg_svg)}</g>')
        # legend, flowing over up to two lines
        lgx, lgy = lx, by + 32
        for i, (name, n, color) in enumerate(segs):
            label = f"{name} {n / grand * 100:.0f}%"
            w = 16 + len(label) * 6.6 + 12
            if lgx + w > W - X0:
                lgx, lgy = lx, lgy + 18
                if lgy > by + 32 + 18:
                    break
            parts.append(f'<g>{fade(0.8 + i * 0.05)}<circle cx="{lgx + 4:.1f}" cy="{lgy - 4}" r="4" fill="{color}"/>'
                         f'<text x="{lgx + 13:.1f}" y="{lgy}" font-family="{FONT}" font-size="11" fill="{t["text"]}">{escape(label)}</text></g>')
            lgx += w
        wy = hy + 98

    span = state["span"] if state else "esta semana"
    parts.append(f'<text x="{lx}" y="{wy}" font-family="{FONT}" font-size="13" font-weight="700" fill="{t["text"]}">'
                 f'<tspan fill="{t["accent"]}">▸</tspan> {escape(span)} estuve con: '
                 f'<tspan font-size="10" font-weight="400" fill="{t["muted"]}">· por líneas de código</tspan></text>')
    langs = (state["langs"] if state else [])[:3 if all_langs else 6]
    total = sum(c for _, c, _ in langs) or 1
    bar_x, bar_w = lx + 104, lw - 104 - 44
    for i, (name, count, color) in enumerate(langs):
        y = wy + 22 + i * 21
        pct = count / total
        w = max(4, bar_w * pct)
        parts.append(f'''<g>{fade(0.5 + i * 0.1)}
    <circle cx="{lx + 5}" cy="{y - 4}" r="4.5" fill="{color}"/>
    <text x="{lx + 16}" y="{y}" font-family="{FONT}" font-size="12" fill="{t['text']}">{escape(name[:11])}</text>
    <rect x="{bar_x}" y="{y - 9}" width="{bar_w}" height="8" rx="4" fill="{t['track']}"/>
    <rect x="{bar_x}" y="{y - 9}" width="{w:.1f}" height="8" rx="4" fill="{color}">
      <animate attributeName="width" values="0;0;{w:.1f}" keyTimes="0;{(0.6 + i * 0.1) / (1.4 + i * 0.1):.3f};1" dur="{1.4 + i * 0.1:.2f}s" fill="freeze"/>
    </rect>
    <text x="{W - X0}" y="{y}" text-anchor="end" font-family="{FONT}" font-size="11" fill="{t['muted']}">{pct * 100:.0f}%</text>
  </g>''')
    if not langs:
        parts.append(f'<text x="{lx}" y="{wy + 30}" font-family="{FONT}" font-size="12" fill="{t["muted"]}">'
                     f'{"actividad privada · trabajando en repos privados" if not state else "sin commits recientes… preparando lo siguiente"}</text>')

    # rotating "learning" line through the week's languages
    ry = H - 22
    names = [n for n, _, _ in langs] or ["de todo un poco"]
    slot = 2.4
    cycle = slot * len(names)
    parts.append(f'<text x="{X0}" y="{ry}" font-family="{FONT}" font-size="13"><tspan fill="{t["accent"]}">$</tspan> '
                 f'<tspan fill="{t["text"]}">learning --now</tspan> <tspan fill="{t["muted"]}">→ aprendiendo de todo un poco · hoy toca:</tspan></text>')
    rx = X0 + 59 * 7.8
    for i, name in enumerate(names):
        a, b = i * slot / cycle, (i + 1) * slot / cycle
        if len(names) == 1:
            anim = ""
            vis = ""
        else:
            vis = ' opacity="0"'
            anim = (f'<animate attributeName="opacity" values="0;0;1;1;0;0" '
                    f'keyTimes="0;{a:.3f};{a + 0.02:.3f};{b - 0.02:.3f};{b:.3f};1" dur="{cycle:.1f}s" repeatCount="indefinite"/>')
        color = langs[i][2] if langs else t["blue"]
        parts.append(f'<text x="{rx:.1f}" y="{ry}" font-family="{FONT}" font-size="13" font-weight="700" fill="{color}"{vis}>{anim}{escape(name)}</text>')
    parts.append(f'<rect x="{W - X0 - 8}" y="{ry - 12}" width="8" height="15" fill="{t["accent"]}">'
                 f'<animate attributeName="opacity" values="1;1;0;0" keyTimes="0;0.5;0.5;1" dur="1s" repeatCount="indefinite"/></rect>')

    body = "\n  ".join(parts)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Actividad en GitHub: contribuciones de los últimos 6 meses, racha y lenguajes de la semana">
  <title>luis@itlsz: ~/activity — git activity --live</title>
  {COPY}
  <defs>
    <pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="1" fill="{t['scan']}" opacity="0.03"/></pattern>
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
    <text x="{W / 2}" y="23" text-anchor="middle" font-size="13" fill="{t['muted']}">luis@itlsz: ~/activity</text>
    <text x="{X0}" y="70" font-size="15"><tspan fill="{t['accent']}">luis@itlsz</tspan><tspan fill="{t['muted']}">:</tspan><tspan fill="{t['blue']}">~</tspan><tspan fill="{t['muted']}">$</tspan> <tspan fill="{t['text']}">git activity --live</tspan></text>
    <circle cx="{W - X0 - 19 * 7.2 - 12:.1f}" cy="66" r="4" fill="{t['accent']}"><animate attributeName="opacity" values="1;0.25;1" dur="1.6s" repeatCount="indefinite"/></circle>
    <text x="{W - X0}" y="70" text-anchor="end" font-size="12" fill="{t['muted']}">actualizado en vivo</text>
  </g>
  {body}
</svg>
'''


def card(theme="dark", demo=False):
    return render(demo_state() if demo else fetch_state(), THEMES.get(theme, THEMES["dark"]))

