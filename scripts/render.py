"""Render assets/profile.svg and README.md from live GitHub data.

The "about" rows (role, lang, stack, ...) live in PROFILE below. Name, location,
social links, projects and all numbers come from the API on every run.

Stdlib only, so it runs as-is in GitHub Actions.
Needs GITHUB_TOKEN in the environment (any token that can read public data).

    GITHUB_TOKEN=$(gh auth token) python3 scripts/render.py
"""
import base64
import json
import os
import re
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

LOGIN = "adsqwui"
SKIP_REPOS = {f"{LOGIN}/{LOGIN}", f"{LOGIN}/achievements-sandbox"}
MAX_PROJECTS = 4
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
    "server": "", "code": "", "tools": "", "org": "",
    "robot": "\U000f06a9", "dot": "", "repo": "", "pin": "",
}

def _dotted(*items):
    out = []
    for i, x in enumerate(items):
        if i:
            out.append((" · ", DIM))
        out.append((x, WHITE))
    return out


# the "about" rows are written by hand on purpose; everything else is live
PROFILE = [
    (I["server"], "role", [("Backend developer", WHITE)]),
    (I["code"], "lang", _dotted("Go", "TypeScript", "Python")),
    (I["tools"], "stack", _dotted("PostgreSQL", "Docker", "Linux")),
    (I["org"], "company", [("Ion Workshop", WHITE)]),
    (I["robot"], "ai", _dotted("Claude API", "MCP servers")),
    (I["dot"], "status", [("open to collaboration", GREEN)]),
]

# markup/styles are not what people mean by "languages"
NOT_LANGS = {"CSS", "SCSS", "Sass", "Less", "HTML", "MDX", "Markdown", "Dockerfile",
             "PLpgSQL", "PLSQL", "TSQL", "Shell", "Makefile", "HCL", "Nix", "Jupyter Notebook",
             "Procfile", "Batchfile", "PowerShell", "Smarty", "Jinja", "Handlebars", "Vue", "Svelte"}


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


REPO_FIELDS = """nameWithOwner url description pushedAt isFork
  owner{login}
  languages(first:10, orderBy:{field:SIZE, direction:DESC}){edges{size node{name}}}"""


def fetch():
    user = gql(f"""query($login:String!){{user(login:$login){{
        login name bio company location createdAt
        status{{message}}
        socialAccounts(first:10){{nodes{{provider displayName url}}}}
        merged: pullRequests(states:MERGED){{totalCount}}
        contributionsCollection{{
          totalCommitContributions
          contributionCalendar{{totalContributions
            weeks{{contributionDays{{date contributionCount weekday}}}}}}}}
        pinnedItems(first:6, types:REPOSITORY){{nodes{{... on Repository{{ {REPO_FIELDS} }}}}}}
        repositories(first:50, ownerAffiliations:OWNER, privacy:PUBLIC, isFork:false,
                     orderBy:{{field:PUSHED_AT, direction:DESC}}){{nodes{{ {REPO_FIELDS} }}}}
        repositoriesContributedTo(first:50, privacy:PUBLIC, includeUserRepositories:false,
                     contributionTypes:[COMMIT, PULL_REQUEST, REPOSITORY]){{nodes{{ {REPO_FIELDS} }}}}
    }}}}""", login=LOGIN)

    # whole history for streaks, one year per request (API limit)
    created = datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))
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
    return user, days


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


def all_repos(user):
    seen, out = set(), []
    for r in user["repositories"]["nodes"] + user["repositoriesContributedTo"]["nodes"]:
        if r["nameWithOwner"] in seen or r["nameWithOwner"] in SKIP_REPOS or r["isFork"]:
            continue
        seen.add(r["nameWithOwner"])
        out.append(r)
    return out


def projects(user):
    pinned = [r for r in user["pinnedItems"]["nodes"] if r]
    if pinned:
        return pinned[:MAX_PROJECTS]
    repos = sorted(all_repos(user), key=lambda r: r["pushedAt"], reverse=True)
    return repos[:MAX_PROJECTS]


def ago(iso):
    days = (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).days
    if days == 0:
        return "today"
    if days < 31:
        return f"{days}d ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


def first_sentence(text):
    if not text:
        return ""
    return re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0].rstrip(".")


def short_name(repo):
    """case-14-ai-presentation-designer-team-41 -> case-14"""
    name = repo["nameWithOwner"].split("/")[1]
    return name if len(name) <= 14 else "-".join(name.split("-")[:2])[:14]


def clip(text, n):
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def link_label(acc):
    if acc["provider"] != "GENERIC":
        return acc["provider"].lower()
    host = urlparse(acc["url"]).netloc.removeprefix("www.")
    return {"t.me": "telegram", "telegram.me": "telegram"}.get(host, host)


def short_url(url):
    u = urlparse(url)
    return (u.netloc.removeprefix("www.") + u.path).rstrip("/")


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

def render(user, days, projs):
    cc = user["contributionsCollection"]
    cal = cc["contributionCalendar"]
    cur, best = streaks(days)
    msk = datetime.now(ZoneInfo("Europe/Moscow"))
    body = []

    # --- header: Saturn + who
    logo = (ASSETS / "logo.txt").read_text().rstrip("\n").split("\n")
    logo_lh = 16.5
    logo_cols = max(len(l) for l in logo)
    rx = PAD + logo_cols * ADV + 36
    right_cols = int((W - PAD - rx) / ADV)
    top = PAD + 6
    for i, line in enumerate(logo):
        body.append(t(PAD, top + 8 + i * logo_lh, [(line, CYAN, True)], 0.1 + i * 0.04))

    name = user["name"] or user["login"]
    name_y = top + 26
    body.append(t(rx, name_y, [(name, WHITE, True)], 0.3, size=30))
    body.append(f'<rect class="cur" x="{rx + len(name) * 18 + 6:.1f}" y="{name_y - 24:.1f}" width="14" height="28" fill="{CYAN}"/>')
    sub = [("@" + user["login"], CYAN)]
    if user["location"]:
        sub += [("  ", DIM), (I["pin"] + " " + user["location"], DIM)]
    body.append(t(rx, name_y + 24, sub, 0.4))
    body.append(t(rx, name_y + 46, [("─" * right_cols, FAINT)], 0.45))
    for i, (icon, key, value) in enumerate(PROFILE):
        room = right_cols - 12
        if len(value) == 1:
            value = [(clip(value[0][0], room), value[0][1])]
        while len(value) > 1 and sum(len(p[0]) for p in value) > room:
            value = value[:-2]  # drop the last " · item"
        body.append(t(rx, name_y + 74 + i * 23, [(icon + "  ", CYAN), (f"{key:<9}", CYAN)] + value, 0.5 + i * 0.06))

    # --- numbers
    y = top + max(len(logo) * logo_lh, 74 + len(PROFILE) * 23 + 4) + 34
    body.append(heading(y, "github", f"since {datetime.fromisoformat(user['createdAt'][:10]):%b %Y}".lower(), 0.9))
    stats = [
        (f"{cc['totalCommitContributions']}", "commits / year"),
        (f"{cal['totalContributions']}", "contributions"),
        (f"{user['merged']['totalCount']}", "PRs merged"),
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
    gx = PAD + 4 * ADV + 4
    gy = y + 38
    last = None
    for wi, w in enumerate(weeks):
        m = date.fromisoformat(w["contributionDays"][0]["date"]).strftime("%b").lower()
        if m != last and wi < len(weeks) - 2:
            body.append(t(gx + wi * cell_w, gy - 4, [(m, DIM)], 1.35))
            last = m
    for r, day in ((1, "mon"), (3, "wed"), (5, "fri")):
        body.append(t(PAD, gy + (r + 1) * cell_h, [(day, DIM)], 1.35))
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
    body.append(heading(y, "projects", "pinned" if user["pinnedItems"]["nodes"] else "recent", 2.2))
    y += 34
    total_cols = int((W - 2 * PAD) / ADV)
    for i, r in enumerate(projs):
        d = 2.3 + i * 0.08
        owner = r["owner"]["login"]
        stack = " · ".join(e["node"]["name"] for e in r["languages"]["edges"]
                           if e["node"]["name"] not in NOT_LANGS)
        stack = " · ".join(stack.split(" · ")[:2])
        what = clip(first_sentence(r["description"]) or "—", total_cols - 17 - len(stack) - 3)
        where = ("own" if owner == user["login"] else f"contributor · {owner}") + f" · pushed {ago(r['pushedAt'])}"
        body.append(t(PAD, y, [(I["repo"] + "  ", CYAN), (f"{short_name(r):<14}", CYAN, True), (what, WHITE)], d))
        if stack:
            body.append(t(W - PAD, y, [(stack, YELLOW)], d, anchor="end"))
        body.append(t(PAD + 17 * ADV, y + 19, [(where, DIM)], d))
        y += 48

    # --- footer
    y += 4
    body.append(t(PAD, y, [("─" * total_cols, FAINT)], 2.7))
    socials = user["socialAccounts"]["nodes"]
    if socials:
        body.append(t(PAD, y + 24, [(short_url(socials[0]["url"]), DIM)], 2.75))
    body.append(t(W - PAD, y + 24, [(f"updated {msk:%Y-%m-%d %H:%M} msk", DIM)], 2.75, anchor="end"))
    height = round(y + 24 + PAD)

    title = escape(f"{name}: {user['bio'] or ''}".strip(": "))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" viewBox="0 0 {W} {height}">
<title>{title}</title>
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


def readme(user, projs):
    def a(url, label):
        return f'<a href="{escape(url)}"><code>{escape(label)}</code></a>'
    socials = "&nbsp;\n  ".join(a(s["url"], link_label(s)) for s in user["socialAccounts"]["nodes"])
    repos = "&nbsp;\n  ".join(a(r["url"], short_name(r)) for r in projs)
    sep = "\n  &nbsp;·&nbsp;\n  " if socials and repos else ""
    # new URL on every run, so GitHub's image cache never serves an old panel
    version = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    alt = escape(f"{user['name'] or user['login']}: {user['bio'] or ''}. "
                 "Live GitHub stats, contribution heatmap and projects.", {'"': "&quot;"})
    return f"""<!-- generated by scripts/render.py, edits here get overwritten -->
<p align="center">
  <img src="assets/profile.svg?v={version}" width="100%" alt="{alt}">
</p>

<p align="center">
  {socials}{sep}{repos}
</p>
"""


def main():
    user, days = fetch()
    projs = projects(user)
    (ASSETS / "profile.svg").write_text(render(user, days, projs))
    (ROOT / "README.md").write_text(readme(user, projs))
    print("ok", [r["nameWithOwner"] for r in projs])


if __name__ == "__main__":
    main()
