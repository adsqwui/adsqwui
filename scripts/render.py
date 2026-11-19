"""Render assets/profile.svg: one terminal-style panel with live GitHub numbers.

Stdlib only, so it runs as-is in GitHub Actions.
Needs GITHUB_TOKEN in the environment (any token that can read public data).

    GITHUB_TOKEN=$(gh auth token) python3 scripts/render.py
"""
import base64
import json
import os
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

LOGIN = "adsqwui"
ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

BG = "#16171b"
BORDER = "#2b2d33"
CYAN = "#2bd2e3"
WHITE = "#e6e6e6"
DIM = "#8b8f98"
FAINT = "#3a3d44"
GREEN = "#7fd88f"
YELLOW = "#e5c07b"

W = 930
PAD = 30
FS = 13
ADV = FS * 0.6  # JetBrains Mono advance

I = {  # Nerd Font icons
    "server": "", "go": "", "db": "", "robot": "\U000f06a9",
    "org": "", "dot": "", "repo": "", "pin": "",
}

PROFILE = [
    (I["server"], "role", [("Backend developer", WHITE)]),
    (I["go"], "lang", [("Go", WHITE), (" · ", DIM), ("TypeScript", WHITE), (" · ", DIM), ("Python", WHITE)]),
    (I["db"], "stack", [("PostgreSQL", WHITE), (" · ", DIM), ("Docker", WHITE), (" · ", DIM), ("Linux", WHITE)]),
    (I["robot"], "ai", [("Claude API", WHITE), (" · ", DIM), ("MCP servers", WHITE)]),
    (I["org"], "company", [("Ion Workshop", WHITE)]),
    (I["dot"], "status", [("open to collaboration", GREEN)]),
]

PROJECTS = [
    ("reshis-avia", "Airline ticket sales forecasting service", "«Reshis» tournament, dev track", "TypeScript"),
    ("case-14", "AI presentation designer", "LCT 2026 hackathon, VK Tech case", "TypeScript · Python"),
    ("hilari", "Autonomous production task system", "contributor", "TypeScript · PostgreSQL"),
    ("clawdy", "Personal AI assistant built on Claude", "pet project", "Claude API"),
]


# ---------------------------------------------------------------- data

def gql(query, **variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {os.environ['GITHUB_TOKEN']}",
                 "User-Agent": "profile-readme-render"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    if "errors" in body:
        raise SystemExit(body["errors"])
    return body["data"]["user"]


def fetch():
    base = gql("""query($login:String!){user(login:$login){
        createdAt
        merged: pullRequests(states:MERGED){totalCount}
        contributionsCollection{
          totalCommitContributions
          contributionCalendar{totalContributions
            weeks{contributionDays{date contributionCount weekday}}}}
    }}""", login=LOGIN)

    # whole history for streaks, one year per request (API limit)
    created = datetime.fromisoformat(base["createdAt"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    days = {}
    start = created
    while start < now:
        end = min(start + timedelta(days=365), now)
        cc = gql("""query($login:String!,$from:DateTime!,$to:DateTime!){user(login:$login){
            contributionsCollection(from:$from, to:$to){
              contributionCalendar{weeks{contributionDays{date contributionCount}}}}}}""",
                 login=LOGIN, **{"from": start.isoformat(), "to": end.isoformat()})
        for w in cc["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for d in w["contributionDays"]:
                days[d["date"]] = d["contributionCount"]
        start = end
    return base, days


def streaks(days):
    today = date.today()
    active = {date.fromisoformat(d) for d, c in days.items() if c > 0}
    best = run = 0
    prev = None
    for d in sorted(active):
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d
    cur = 0
    d = today if today in active else today - timedelta(days=1)
    while d in active:
        cur += 1
        d -= timedelta(days=1)
    return cur, best


# ---------------------------------------------------------------- svg bits

def font_face():
    out = []
    for weight, name in ((400, "regular"), (700, "bold")):
        b64 = base64.b64encode((ASSETS / f"fonts/jbm-{name}.woff2").read_bytes()).decode()
        out.append(f"@font-face{{font-family:'JBM';font-weight:{weight};"
                   f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}")
    return "".join(out)


def t(x, y, parts, delay, size=None, anchor=None):
    """One line of text. parts = [(text, color[, bold]), ...]"""
    bold = ' font-weight="700"'
    spans = "".join(
        f'<tspan fill="{p[1]}"{bold if len(p) > 2 and p[2] else ""}>{escape(p[0])}</tspan>'
        for p in parts)
    style = f"animation-delay:{delay:.2f}s" + (f";font-size:{size}px" if size else "")
    a = f' text-anchor="{anchor}"' if anchor else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" class="ln"{a} style="{style}">{spans}</text>'


def heading(y, label, note, delay):
    """`label ───────────── note` across the panel."""
    left = len(label) + 1
    right = len(note) + 1 if note else 0
    fill = int((W - 2 * PAD) / ADV) - left - right
    parts = [(label, CYAN, True), (" " + "─" * fill, FAINT)]
    if note:
        parts.append((" " + note, DIM))
    return t(PAD, y, parts, delay)


# ---------------------------------------------------------------- panel

def render(base, days):
    cc = base["contributionsCollection"]
    cal = cc["contributionCalendar"]
    cur, best = streaks(days)
    msk = datetime.now(ZoneInfo("Europe/Moscow"))
    body = []

    # --- header: Saturn + who
    logo = (ASSETS / "logo.txt").read_text().rstrip("\n").split("\n")
    logo_lh = 16.5
    logo_cols = max(len(l) for l in logo)
    rx = PAD + logo_cols * ADV + 36
    top = PAD + 6
    for i, line in enumerate(logo):
        body.append(t(PAD, top + 8 + i * logo_lh, [(line, CYAN, True)], 0.1 + i * 0.04))

    name_y = top + 26
    body.append(t(rx, name_y, [("whyme", WHITE, True)], 0.3, size=30))
    body.append(f'<rect class="cur" x="{rx + 5 * 18 + 6:.1f}" y="{name_y - 24:.1f}" width="14" height="28" fill="{CYAN}"/>')
    body.append(t(rx, name_y + 24, [("@adsqwui", CYAN), ("  ", DIM), (I["pin"] + " Moscow", DIM)], 0.4))
    rule_cols = int((W - PAD - rx) / ADV)
    body.append(t(rx, name_y + 46, [("─" * rule_cols, FAINT)], 0.45))
    for i, (icon, key, value) in enumerate(PROFILE):
        body.append(t(rx, name_y + 74 + i * 23, [(icon + "  ", CYAN), (f"{key:<9}", CYAN)] + value, 0.5 + i * 0.06))

    # --- numbers
    y = top + max(len(logo) * logo_lh, 74 + len(PROFILE) * 23 + 4) + 34
    body.append(heading(y, "github", f"since {datetime.fromisoformat(base['createdAt'][:10]):%b %Y}".lower(), 0.9))
    stats = [
        (f"{cc['totalCommitContributions']}", "commits / year"),
        (f"{cal['totalContributions']}", "contributions"),
        (f"{base['merged']['totalCount']}", "PRs merged"),
        (f"{cur}d", f"streak · best {best}d"),
    ]
    col = (W - 2 * PAD) / len(stats)
    for i, (num, label) in enumerate(stats):
        x = PAD + i * col
        body.append(t(x, y + 42, [(num, WHITE, True)], 1.0 + i * 0.06, size=26))
        body.append(t(x, y + 62, [(label, DIM)], 1.05 + i * 0.06))
        if i:
            body.append(f'<line x1="{x - 16:.1f}" x2="{x - 16:.1f}" y1="{y + 22:.1f}" y2="{y + 66:.1f}" stroke="{FAINT}"/>')

    # --- heatmap
    y += 108
    body.append(heading(y, "activity", "last 12 months", 1.3))
    weeks = cal["weeks"]
    nonzero = sorted(d["contributionCount"] for w in weeks for d in w["contributionDays"] if d["contributionCount"])
    quart = [nonzero[int(len(nonzero) * f)] for f in (0.25, 0.5, 0.75)] if nonzero else []

    def level(c):
        return 0 if c == 0 else 1 + sum(c > q for q in quart)

    ramp = ["·", "░", "▒", "▓", "█"]
    cell_w, cell_h, cell_fs = 14.5, 15.5, 10
    label_w = 4 * ADV
    gx = PAD + label_w + 4
    gy = y + 38
    last = None
    for wi, w in enumerate(weeks):
        m = date.fromisoformat(w["contributionDays"][0]["date"]).strftime("%b").lower()
        if m != last and wi < len(weeks) - 2:
            body.append(t(gx + wi * cell_w, gy - 4, [(m, DIM)], 1.35))
            last = m
    for r, name in ((1, "mon"), (3, "wed"), (5, "fri")):
        body.append(t(PAD, gy + (r + 1) * cell_h, [(name, DIM)], 1.35))
    for wi, w in enumerate(weeks):
        delay = 1.4 + wi * 0.012
        for d in w["contributionDays"]:
            lv = level(d["contributionCount"])
            glyph = " ·" if lv == 0 else ramp[lv] * 2
            color, op = (DIM, 0.5) if lv == 0 else (CYAN, [0, .55, .75, .9, 1][lv])
            body.append(f'<text x="{gx + wi * cell_w:.1f}" y="{gy + (d["weekday"] + 1) * cell_h:.1f}" class="ln" '
                        f'fill="{color}" fill-opacity="{op}" style="font-size:{cell_fs}px;animation-delay:{delay:.2f}s">'
                        f'{glyph}</text>')
    ly = gy + 7 * cell_h + 26
    legend = [("less ", DIM), ("·", DIM)] + [(" " + ch, CYAN) for ch in ramp[1:]] + [(" more", DIM)]
    body.append(t(W - PAD, ly, legend, 2.1, anchor="end"))

    # --- projects
    y = ly + 40
    body.append(heading(y, "projects", "selected", 2.2))
    y += 34
    for i, (name, what, where, stack) in enumerate(PROJECTS):
        d = 2.3 + i * 0.08
        body.append(t(PAD, y, [(I["repo"] + "  ", CYAN), (f"{name:<14}", CYAN, True), (what, WHITE)], d))
        body.append(t(W - PAD, y, [(stack, YELLOW)], d, anchor="end"))
        body.append(t(PAD + 17 * ADV, y + 19, [(where, DIM)], d))
        y += 48

    # --- footer
    y += 4
    body.append(t(PAD, y, [("─" * int((W - 2 * PAD) / ADV), FAINT)], 2.7))
    body.append(t(PAD, y + 24, [("t.me/HeartedWhyMe", DIM)], 2.75))
    body.append(t(W - PAD, y + 24, [(f"updated {msk:%Y-%m-%d %H:%M} msk", DIM)], 2.75, anchor="end"))
    height = round(y + 24 + PAD)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" viewBox="0 0 {W} {height}">
<title>whyme: backend developer (Go), Moscow</title>
<style>{font_face()}
text{{font-family:'JBM',ui-monospace,Menlo,Consolas,monospace;font-size:{FS}px;white-space:pre}}
.ln{{opacity:0;animation:in .35s ease-out forwards}}
@keyframes in{{from{{opacity:0;transform:translateY(3px)}}to{{opacity:1;transform:none}}}}
.cur{{animation:blink 1.1s steps(1) infinite}}
@keyframes blink{{50%{{opacity:0}}}}
@media (prefers-reduced-motion:reduce){{.ln{{animation:none;opacity:1}}.cur{{animation:none}}}}
</style>
<rect x=".5" y=".5" width="{W - 1}" height="{height - 1}" rx="12" fill="{BG}" stroke="{BORDER}"/>
{chr(10).join(body)}
</svg>
"""


def main():
    base, days = fetch()
    (ASSETS / "profile.svg").write_text(render(base, days))
    print("ok")


if __name__ == "__main__":
    main()
