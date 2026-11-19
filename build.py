#!/usr/bin/env python3
"""The Tamala Leika website (https://bersling.github.io/tamala-leika), a static site from the shorts.

Python standard library only, so it runs on the host and in GitHub Actions without installs.

    python3 site/build.py export          # videos/BACKLOG.md + videos/<v>/article.md -> site/content/videos.json
    python3 site/build.py build [--all] [--base ""] [--now ISO]   # -> site/_site/ (links under /tamala-leika)
    python3 site/build.py serve           # export, build --all, serve on http://localhost:8738
    python3 site/build.py deploy          # export, build, push the site to the public repo
    python3 site/build.py poster <id> <s> # poster from out/<id>.mp4 at second <s>

A video gets its page once its YouTube release time has passed (`--all` shows every video,
unreleased ones marked). The public repo rebuilds on a schedule just after the 05:00 and 17:00
slots, so scheduled shorts appear on the site without anyone deploying. README, section Website.
"""
from __future__ import annotations

import html
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SITE = Path(__file__).resolve().parent
# A project site under Daniel's account: bersling/tamala-leika is public and holds only the built site
# (the name tamalaleika is taken by this private repo). B is the path prefix of every internal link.
SITE_URL = "https://bersling.github.io/tamala-leika"
PUBLIC_REPO = "bersling/tamala-leika"
B = "/tamala-leika"
ZURICH = ZoneInfo("Europe/Zurich")
YOUTUBE = "https://www.youtube.com/@tamalaleika"
TIKTOK = "https://www.tiktok.com/@tamalaleika"
GOATCOUNTER = "https://tamalaleika.goatcounter.com/count"
NAME = "Tamala Leika"
TAGLINE = "Money, markets and their stories."


# ---------------------------------------------------------------- export (main repo only)

def repo_root() -> Path:
    return SITE.parent


def main_checkout() -> Path:
    """The main checkout, also from a worktree (build/ and out/ live there, see README)."""
    common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            cwd=SITE, capture_output=True, text=True, check=True).stdout.strip()
    return Path(common).parent


def front_matter(text: str) -> tuple[dict, str]:
    meta: dict = {}
    if text.startswith("---\n"):
        head, _, body = text[4:].partition("\n---\n")
        for line in head.splitlines():
            if ":" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        return meta, body.strip() + "\n"
    return meta, text


def youtube_yaml(path: Path) -> dict:
    """title and description from youtube.yaml, without a YAML library."""
    out = {"title": "", "description": ""}
    if not path.exists():
        return out
    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.startswith("title:"):
            out["title"] = line[6:].strip().strip('"\'')
        if line.startswith("description:"):
            block = []
            for nxt in lines[i + 1:]:
                if nxt.strip() and not nxt.startswith("  "):
                    break
                block.append(nxt[2:])
            out["description"] = "\n".join(block).strip()
    return out


def parse_backlog(path: Path) -> list[dict]:
    rows = []
    in_made = False
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            in_made = line.strip() == "## Made"
            continue
        if not in_made or not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] == "Video":
            continue
        folder = cells[1].strip("` ")
        status = "|".join(cells[2:])
        yt = re.search(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})", status)
        when = None
        m = re.search(r"public since (\d{4}-\d{2}-\d{2})", status)
        if m:
            when = datetime.fromisoformat(m.group(1)).replace(tzinfo=ZURICH)
        m = re.search(r"scheduled for (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})", status)
        if m:
            when = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}").replace(tzinfo=ZURICH)
        if not yt or not when:
            continue
        rows.append({"id": folder, "backlogTitle": cells[0], "youtube": yt.group(1),
                     "release": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    return rows


def export() -> list[dict]:
    root = repo_root()
    videos = []
    for row in parse_backlog(root / "videos" / "BACKLOG.md"):
        vdir = root / "videos" / row["id"]
        yt = youtube_yaml(vdir / "youtube.yaml")
        article = vdir / "article.md"
        meta, body = front_matter(article.read_text()) if article.exists() else ({}, "")
        if not body:
            # No article yet: the YouTube description, without its hashtag line, stands in.
            body = "\n".join(l for l in yt["description"].splitlines() if not l.startswith("#")).strip() + "\n"
        videos.append({
            "id": row["id"],
            "slug": meta.get("slug") or row["id"],
            "title": meta.get("title") or row["backlogTitle"],
            "kind": meta.get("kind", "knowledge"),
            "level": meta.get("level", ""),
            "summary": meta.get("summary") or yt["description"].split("\n\n")[0].replace("\n", " "),
            "youtubeTitle": yt["title"],
            "youtube": row["youtube"],
            "release": row["release"],
            "hasArticle": article.exists(),
            "poster": (SITE / "static" / "posters" / f"{row['id']}.jpg").exists(),
            "body": body,
        })
    videos.sort(key=lambda v: v["release"])
    slugs = [v["slug"] for v in videos]
    dupes = {s for s in slugs if slugs.count(s) > 1}
    if dupes:
        sys.exit(f"duplicate slugs: {', '.join(sorted(dupes))}")
    (SITE / "content").mkdir(exist_ok=True)
    (SITE / "content" / "videos.json").write_text(json.dumps(videos, indent=1, ensure_ascii=False) + "\n")
    missing = [v["id"] for v in videos if not v["hasArticle"]]
    print(f"exported {len(videos)} videos to site/content/videos.json"
          + (f"; no article yet: {', '.join(missing)}" if missing else ""))
    return videos


# ---------------------------------------------------------------- markdown (the subset articles use)

def inline(text: str) -> str:
    t = html.escape(text, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", t)

    def link(m):
        href = m.group(2).replace('"', "%22")
        ext = href.startswith("http")
        return (f'<a href="{href}"' + (' rel="noopener"' if ext else "") + f">{m.group(1)}</a>")
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, t)


def markdown(src: str) -> str:
    out, para, items, kind, quote = [], [], [], None, []

    def flush():
        nonlocal para, items, kind, quote
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
        if items:
            tag = "ol" if kind == "ol" else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(i)}</li>" for i in items) + f"</{tag}>")
        if quote:
            out.append(f"<blockquote>{markdown(chr(10).join(quote))}</blockquote>")
        para, items, kind, quote = [], [], None, []

    for raw in src.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        if line.startswith(">"):
            if not quote:
                flush()
            quote.append(line[1:].lstrip())
            continue
        h = re.match(r"(#{2,4}) (.+)", line)
        if h:
            flush()
            level = len(h.group(1))
            text = h.group(2).strip()
            anchor = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
            out.append(f'<h{level} id="{anchor}">{inline(text)}</h{level}>')
            continue
        li = re.match(r"\s*(?:[-*]|(\d+)\.) (.+)", line)
        if li:
            k = "ol" if li.group(1) else "ul"
            if para or quote or (items and kind != k):
                flush()
            kind = k
            items.append(li.group(2))
            continue
        if items and raw.startswith("  "):
            items[-1] += " " + line.strip()
            continue
        if items or quote:
            flush()
        para.append(line.strip())
    flush()
    return "\n".join(out)


# ---------------------------------------------------------------- hand-drawn SVG

def wobble(points, seed: int, amp: float = 1.6, step: float = 10.0) -> str:
    """A polyline through `points`, drawn as if by hand: exact, with a slight wobble."""
    rnd = random.Random(seed)
    phases = [rnd.uniform(0, 6.283) for _ in range(3)]
    freqs = [0.031, 0.067, 0.143]
    pts, dist = [], 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        n = max(1, int(seg / step))
        nx, ny = (-(y1 - y0) / seg, (x1 - x0) / seg) if seg else (0, 0)
        for i in range(n):
            f = i / n
            d = dist + seg * f
            off = amp * sum(math.sin(d * fr + ph) / (k + 1) for k, (fr, ph) in enumerate(zip(freqs, phases)))
            pts.append((x0 + (x1 - x0) * f + nx * off, y0 + (y1 - y0) * f + ny * off))
        dist += seg
    pts.append(points[-1])
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts)


def rule(seed: int = 1, cls: str = "rule") -> str:
    """The dashed divider from the shorts' caption panel."""
    d = wobble([(4, 7), (996, 7)], seed, amp=1.3, step=14)
    return (f'<svg class="{cls}" viewBox="0 0 1000 14" preserveAspectRatio="none" aria-hidden="true">'
            f'<path d="{d}"/></svg>')


def frame(seed: int) -> str:
    """An inked frame drawn by hand: four strokes that overshoot their corners a little."""
    rnd = random.Random(seed)
    j = lambda: rnd.uniform(-2.5, 2.5)
    sides = [[(-2 + j(), 2 + j()), (302 + j(), 2 + j())], [(298 + j(), -2 + j()), (298 + j(), 402 + j())],
             [(302 + j(), 398 + j()), (-2 + j(), 398 + j())], [(2 + j(), 402 + j()), (2 + j(), -2 + j())]]
    d = " ".join(wobble(s, seed * 7 + i, amp=1.1, step=12) for i, s in enumerate(sides))
    return f'<svg class="frame" viewBox="0 0 300 400" preserveAspectRatio="none" aria-hidden="true"><path d="{d}"/></svg>'


def avatar_svg(seed: int = 17) -> str:
    """The channel face drawn as an inline wobbly SVG badge with a hatched doodle shadow."""
    # Outer badge ring (centred at 102, 98, radius ~80)
    cx, cy, rx, ry = 102, 98, 80, 78
    ring_pts = [(cx + rx * math.cos(a / 32 * 6.32 - 0.5), cy + ry * math.sin(a / 32 * 6.32 - 0.5)) for a in range(33)]
    ring2_pts = [(cx + (rx + 1.5) * math.cos(a / 26 * 6.28 + 0.8), cy + (ry + 1.5) * math.sin(a / 26 * 6.28 + 0.8)) for a in range(27)]
    # Offset shadow rim on bottom-left (shifted by -9, +9) with diagonal hatch lines matching Rubik Doodle Shadow
    sx, sy = cx - 9, cy + 9
    shadow_pts = [(sx + rx * math.cos(a / 32 * 6.28), sy + ry * math.sin(a / 32 * 6.28)) for a in range(33)]
    hatches = []
    for k in range(-12, 13):
        # Diagonal lines x + y = const clipped to the shadow circle
        c = sx + sy + k * 11
        # Intersect x + y = c with (x - sx)^2 + (y - sy)^2 <= r^2
        # Midpoint is ((c + sx - sy)/2, (c - sx + sy)/2), distance from center is |k*11| / sqrt(2)
        d_center = abs(k * 11) / 1.4142
        r_avg = 79.0
        if d_center < r_avg - 3:
            half_chord = math.sqrt(r_avg * r_avg - d_center * d_center) / 1.4142
            mx = (c + sx - sy) / 2
            my = (c - sx + sy) / 2
            hatches.append(wobble([(mx - half_chord, my + half_chord), (mx + half_chord, my - half_chord)], seed + 30 + k, amp=0.5, step=8))
    hatch_svg = "".join(f'<path class="badge-hatch" d="{h}"/>' for h in hatches)
    # Character face (positioned inside the circle so the bun has generous orange room above it)
    head_pts = [(100 + 56 * math.cos(a / 28 * 6.38 - 0.2), 112 + 60 * math.sin(a / 28 * 6.38 - 0.2)) for a in range(29)]
    bun_pts = [(100 + 24 * math.cos(a / 18 * 6.38), 46 + 20 * math.sin(a / 18 * 6.38)) for a in range(19)]
    hair_top = wobble([(45, 105), (50, 82), (66, 62), (84, 53), (100, 51), (116, 53), (134, 62), (150, 82), (155, 105)], seed + 6, amp=0.8, step=6)
    hair_bot = wobble([(155, 105), (138, 90), (118, 80), (100, 83), (82, 80), (62, 90), (45, 105)], seed + 7, amp=0.8, step=6)
    hair_d = hair_top + " L" + hair_bot[1:] + " Z"
    smile = wobble([(77, 134), (89, 145), (100, 148), (111, 145), (123, 134)], seed + 4, amp=0.8, step=5)
    eye_l = wobble([(80 + 6.5 * math.cos(a / 10 * 6.3), 113 + 6.8 * math.sin(a / 10 * 6.3)) for a in range(11)], seed + 8, amp=0.4, step=3)
    eye_r = wobble([(120 + 6.5 * math.cos(a / 10 * 6.3), 113 + 6.8 * math.sin(a / 10 * 6.3)) for a in range(11)], seed + 9, amp=0.4, step=3)
    return (
        '<svg class="logo-badge" viewBox="0 0 204 204" aria-hidden="true">'
        f'<path class="badge-shadow-bg" d="{wobble(shadow_pts, seed + 1, amp=1.2, step=10)} Z"/>'
        f'{hatch_svg}'
        f'<path class="badge-shadow-ring" d="{wobble(shadow_pts, seed + 1, amp=1.2, step=10)}"/>'
        f'<path class="badge-bg" d="{wobble(ring_pts, seed, amp=1.3, step=10)} Z"/>'
        '<g transform="translate(102 110) scale(0.90) translate(-100 -106)">'
        f'<path class="face-bun" d="{wobble(bun_pts, seed + 2, amp=0.8, step=6)} Z"/>'
        f'<path class="face-skin" d="{wobble(head_pts, seed + 3, amp=1.1, step=8)} Z"/>'
        f'<path class="face-hair" d="{hair_d}"/>'
        f'<path class="face-line" d="{wobble(head_pts, seed + 3, amp=1.1, step=8)}"/>'
        f'<path class="face-eye" d="{eye_l} Z"/>'
        f'<path class="face-eye" d="{eye_r} Z"/>'
        f'<path class="face-smile" d="{smile}"/>'
        '</g>'
        f'<path class="badge-ring" d="{wobble(ring_pts, seed, amp=1.3, step=10)}"/>'
        f'<path class="badge-ring-2" d="{wobble(ring2_pts, seed + 5, amp=1.5, step=14)}"/>'
        '</svg>'
    )


def hero_svg() -> str:
    """The home page drawing: a bubble, its crash and the question the channel answers."""
    ax = wobble([(70, 40), (70, 400), (640, 400)], 3, amp=1.2)
    ticks = "".join(f'<path class="ink thin" d="{wobble([(x, 400), (x, 412)], 10 + i, amp=0.4, step=4)}"/>'
                    for i, x in enumerate(range(150, 640, 90)))
    ticks += "".join(f'<path class="ink thin" d="{wobble([(58, y), (70, y)], 20 + i, amp=0.4, step=4)}"/>'
                     for i, y in enumerate(range(100, 400, 75)))
    random.seed(7)
    wild, y = [], 330.0
    shape = [(i, 330 - 230 * math.exp(-((i - 330) / 120) ** 2) - 40 * i / 600) for i in range(80, 420, 12)]
    for x, base in shape:
        wild.append((x, base + random.uniform(-9, 9)))
    for x in range(420, 630, 12):
        y = 330 - 60 * math.exp(-((x - 330) / 120) ** 2) + 40 - 30 * (x - 420) / 210 + random.uniform(-6, 6)
        wild.append((x, y))
    calm = [(x, 300 - 0.22 * (x - 80) + 5 * math.sin(x / 37)) for x in range(80, 631, 30)]
    peak = min(wild, key=lambda p: p[1])
    ell_c = (peak[0] + 4, peak[1] + 6)
    ell = wobble([(ell_c[0] + 62 * math.cos(a / 20 * 6.4 - 0.3), ell_c[1] + 34 * math.sin(a / 20 * 6.4 - 0.3))
                  for a in range(21)], 5, amp=2.0, step=8)
    arrow = wobble([(470, 120), (430, 102), (ell_c[0] + 66, ell_c[1] - 10)], 6, amp=1.4)
    head_x, head_y = ell_c[0] + 66, ell_c[1] - 10
    head = wobble([(head_x + 14, head_y - 8), (head_x, head_y), (head_x + 15, head_y + 7)], 8, amp=0.6, step=4)
    return f'''<svg class="hero-chart" viewBox="0 0 680 470" role="img" aria-label="Chart of a price shooting up and crashing, with the peak circled and the question: wait, why did it crash?">
  <path class="ink axis" pathLength="1" d="{ax}"/>
  {ticks}
  <text class="hand axis-label" x="16" y="60">price</text>
  <text class="hand axis-label" x="590" y="446">time</text>
  <path class="data blue dashed" d="{wobble(calm, 11, amp=1.0)}"/>
  <path class="data orange" pathLength="1" d="{wobble(wild, 12, amp=1.2, step=6)}"/>
  <path class="mark circle" pathLength="1" d="{ell}"/>
  <path class="mark arrow" pathLength="1" d="{arrow}"/>
  <path class="mark arrow head" pathLength="1" d="{head}"/>
  <text class="hand note" x="472" y="112">wait, why did</text>
  <text class="hand note" x="472" y="142">it crash?</text>
  <text class="hand note small blue-text" x="520" y="232">what it's worth</text>
</svg>'''


# ---------------------------------------------------------------- page parts

CSS_VERSION = "3"


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def fmt_date(iso: str, with_time: bool = False) -> str:
    dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(ZURICH)
    if with_time:
        return f"{dt.strftime('%a')} {dt.day} {dt.strftime('%b')}, {dt.strftime('%H:%M')}"
    return f"{dt.day} {dt.strftime('%b %Y')}"


def tag(v: dict) -> str:
    if v["kind"] == "story":
        return '<span class="tag story">story</span>'
    level = {"basic": "the basics", "advanced": "advanced", "pro": "pro"}.get(v["level"], "concept")
    return f'<span class="tag concept">{level}</span>'


def poster(v: dict) -> str:
    return f"/static/posters/{v['id']}.jpg" if v.get("poster") else "/static/poster-blank.svg"


def card(v: dict, coming: bool = False) -> str:
    inner = (f'<div class="card-img"><img src="{B}{poster(v)}" alt="" loading="lazy" width="720" height="960">{frame(len(v["id"]) * 13 + ord(v["id"][0]))}</div>'
             f'<div class="card-text">{tag(v)}<h3>{esc(v["title"])}</h3><p>{esc(v["summary"])}</p>'
             + (f'<p class="when">coming {fmt_date(v["release"], True)}</p>' if coming else "")
             + "</div>")
    if coming:
        return f'<div class="card coming">{inner}</div>'
    return f'<a class="card" href="{B}/{v["slug"]}/">{inner}</a>'


def grid(videos: list[dict], now: datetime, show_all: bool) -> str:
    return '<div class="grid">' + "".join(card(v, coming=show_all and not released(v, now)) for v in videos) + "</div>"


def header(path: str) -> str:
    def nav(href, label):
        cur = ' aria-current="page"' if path == href else ""
        return f'<a href="{B}{href}"{cur}>{label}</a>'
    return f'''<header class="site-header">
  <div class="wrap header-row">
    <a class="logo" href="{B}/">{avatar_svg(17)}<span>{NAME}</span></a>
    <nav>{nav("/videos/", "All videos")}{nav("/about/", "About")}<a class="ext" href="{YOUTUBE}" rel="noopener">YouTube</a></nav>
  </div>
  {rule(2, "rule header-rule")}
</header>'''


def footer() -> str:
    return f'''<footer class="site-footer panel">
  {rule(9, "rule panel-rule")}
  <div class="wrap footer-row">
    <div>
      <p class="logo small">{avatar_svg(29)}<span>{NAME}</span></p>
      <p class="fine">Short finance explainers, made with AI and curated by a human. Not financial advice.</p>
    </div>
    <nav class="footer-nav">
      <a href="{B}/videos/">All videos</a><a href="{B}/about/">About</a>
      <a href="{YOUTUBE}" rel="noopener">YouTube</a><a href="{TIKTOK}" rel="noopener">TikTok</a><a href="{B}/feed.xml">Feed</a>
    </nav>
  </div>
</footer>'''


def layout(*, title: str, description: str, path: str, body: str, image: str = "/static/og.png",
           page_class: str = "", og_type: str = "website", head: str = "") -> str:
    full_title = title if title == NAME else f"{title} · {NAME}"
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(full_title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{SITE_URL}{path}">
<meta property="og:site_name" content="{NAME}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:type" content="{og_type}">
<meta property="og:url" content="{SITE_URL}{path}">
<meta property="og:image" content="{SITE_URL}{image}">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#ffffff">
<link rel="icon" href="{B}/static/favicon.png" type="image/png">
<link rel="apple-touch-icon" href="{B}/static/apple-touch-icon.png">
<link rel="alternate" type="application/atom+xml" title="{NAME}" href="{B}/feed.xml">
<link rel="preload" href="{B}/static/fonts/rubik-doodle-shadow.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="{B}/static/fonts/literata.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{B}/static/style.css?v={CSS_VERSION}">
{head}<script data-goatcounter="{GOATCOUNTER}" async src="//gc.zgo.at/count.js"></script>
</head>
<body class="{page_class}">
<a class="skip" href="#main">Skip to content</a>
{header(path)}
<main id="main">
{body}
</main>
{footer()}
<script src="{B}/static/site.js?v={CSS_VERSION}" defer></script>
</body>
</html>
'''


# ---------------------------------------------------------------- pages

def released(v: dict, now: datetime) -> bool:
    return datetime.strptime(v["release"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) <= now


def home(videos, now, show_all) -> str:
    out = [v for v in videos if released(v, now)]
    latest = list(reversed(out))[:6]
    first = latest[0] if latest else None
    cta = (f'<a class="btn primary" href="{B}/{first["slug"]}/">Watch the latest</a>' if first else "")
    body = f'''<section class="hero wrap">
  <div class="hero-text">
    <p class="kicker hand">short finance explainers</p>
    <h1 class="display">{NAME}</h1>
    <p class="hero-sub">{TAGLINE}</p>
    <p class="hero-lead">Short videos on how financial markets work — from basic concepts like options, bonds and leverage to the stories behind big crashes, bubbles and bets. Every video comes with a written version right below it if you'd rather read than watch.</p>
    <div class="actions">{cta}<a class="btn" href="{B}/videos/">All videos</a></div>
  </div>
  <div class="hero-art">{hero_svg()}</div>
</section>
<section class="wrap section">
  <div class="section-head"><h2 class="sketch">Latest</h2><a class="more hand" href="{B}/videos/">see all &rarr;</a></div>
  {grid(latest, now, False)}
</section>
<section class="wrap section about-strip">
  <div class="about-box">
    <h2 class="sketch">Who makes this?</h2>
    <p>I'm not a finance guy — these are just the things I learned along the way, turned into short videos with the help of AI. The machine writes, speaks and draws them, and I spar with it and edit the drafts until they clear my bar.</p>
    <a class="btn" href="{B}/about/">About the channel</a>
  </div>
</section>'''
    return layout(title=NAME, description=f"{TAGLINE} Short videos and articles on options, markets, crashes and bubbles.",
                  path="/", body=body, page_class="home")


def video_page(v, videos, now) -> str:
    out = [o for o in videos if released(o, now) and o["id"] != v["id"]]
    same = [o for o in reversed(out) if o["kind"] == v["kind"]]
    other = [o for o in reversed(out) if o["kind"] != v["kind"]]
    more = (same + other)[:3]
    yt_url = f"https://www.youtube.com/shorts/{v['youtube']}"
    body = f'''<article class="video-page wrap">
  <p class="crumbs hand"><a href="{B}/videos/">&larr; all videos</a></p>
  <header class="video-head">
    {tag(v)}
    <h1 class="display page-title">{esc(v["title"])}</h1>
    <p class="lede">{esc(v["summary"])}</p>
  </header>
  <div class="video-layout">
    <aside class="video-col">
      <div class="short" data-yt="{v["youtube"]}" data-title="{esc(v["youtubeTitle"] or v["title"])}">
        {frame(99)}
        <button class="short-play" type="button" aria-label="Play the short: {esc(v["title"])}">
          <img src="{B}{poster(v)}" alt="" width="720" height="960">
          <span class="play" aria-hidden="true"><svg viewBox="0 0 100 100"><path d="{wobble([(50 + 40 * math.cos(a / 24 * 6.5), 50 + 40 * math.sin(a / 24 * 6.5)) for a in range(25)], 31, amp=1.2, step=6)}"/><path class="tri" d="{wobble([(40, 32), (70, 50), (40, 68), (40, 32)], 32, amp=0.8, step=5)}"/></svg></span>
          <span class="short-caption">{esc(v["title"])}</span>
        </button>
      </div>
      <p class="video-links hand"><a href="{yt_url}" rel="noopener">watch on YouTube &nearr;</a> <a href="{TIKTOK}" rel="noopener">TikTok &nearr;</a></p>
      <p class="fine center">The video loads from YouTube when you press play.</p>
    </aside>
    <div class="prose">
{markdown(v["body"])}
    </div>
  </div>
</article>'''
    if more:
        body += f'''
<section class="panel section">
  {rule(v["id"].__len__() + 40, "rule panel-rule")}
  <div class="wrap">
    <div class="section-head"><h2 class="sketch">Keep watching</h2><a class="more hand" href="{B}/videos/">all videos &rarr;</a></div>
    {grid(more, now, False)}
  </div>
</section>'''
    ld = {"@context": "https://schema.org", "@type": "VideoObject", "name": v["title"],
          "description": v["summary"], "thumbnailUrl": f"{SITE_URL}{poster(v)}",
          "uploadDate": v["release"], "embedUrl": f"https://www.youtube-nocookie.com/embed/{v['youtube']}",
          "contentUrl": yt_url}
    head = f'<script type="application/ld+json">{json.dumps(ld)}</script>\n'
    return layout(title=v["title"], description=v["summary"], path=f"/{v['slug']}/", body=body,
                  image=poster(v), page_class="video", og_type="article", head=head)


def index_page(videos, now, show_all) -> str:
    vis = [v for v in videos if show_all or released(v, now)]
    groups = [
        ("Concepts: the basics", "The building blocks, explained from scratch.",
         [v for v in vis if v["kind"] != "story" and v["level"] in ("basic", "")]),
        ("Concepts: one step further", "Going a bit deeper once the basics are clear.",
         [v for v in vis if v["kind"] != "story" and v["level"] in ("advanced", "pro")]),
        ("Stories", "Big bets, bubbles, frauds and collapses.",
         [v for v in vis if v["kind"] == "story"]),
    ]
    sections = ""
    for i, (h, sub, vs) in enumerate(groups):
        if not vs:
            continue
        sections += f'''<section class="section">
  <div class="section-head"><h2 class="sketch">{h}</h2><p class="hand note-inline">{sub}</p></div>
  {grid(list(reversed(vs)), now, show_all)}
</section>'''
    n = len([v for v in videos if released(v, now)])
    body = f'''<div class="wrap">
  <header class="page-head">
    <h1 class="display page-title">All videos</h1>
    <p class="lede">{n} short{"s" if n != 1 else ""} so far, each with a written version to read.</p>
  </header>
  {sections}
</div>'''
    return layout(title="All videos", description="Every Tamala Leika short with its written article: options, short selling, leverage, crashes, bubbles and the people behind them.",
                  path="/videos/", body=body, page_class="index")


def text_page(src: Path, path: str) -> str:
    meta, body = front_matter(src.read_text())
    content = f'''<article class="wrap text-page">
  <header class="page-head"><h1 class="display page-title">{esc(meta.get("title", ""))}</h1></header>
  <div class="prose solo">
{markdown(body)}
  </div>
</article>'''
    return layout(title=meta.get("title", NAME), description=meta.get("summary", TAGLINE), path=path,
                  body=content, page_class="text")


def not_found() -> str:
    line = wobble([(20, 40), (90, 30), (150, 50), (210, 20), (240, 150), (300, 160)], 41, amp=1.5, step=6)
    body = f'''<div class="wrap text-page center">
  <svg class="lost" viewBox="0 0 320 180" aria-hidden="true"><path class="data orange" d="{line}"/></svg>
  <h1 class="display page-title">Page not found</h1>
  <p class="lede">There's nothing at this address, but all the videos are still there.</p>
  <p><a class="btn primary" href="{B}/videos/">All videos</a></p>
</div>'''
    return layout(title="Page not found", description="This page does not exist.", path="/404.html", body=body, page_class="text")


def feed(videos, now) -> str:
    out = list(reversed([v for v in videos if released(v, now)]))[:30]
    updated = out[0]["release"] if out else now.strftime("%Y-%m-%dT%H:%M:%SZ")
    entries = "".join(f'''<entry><title>{esc(v["title"])}</title><link href="{SITE_URL}/{v["slug"]}/"/>
<id>{SITE_URL}/{v["slug"]}/</id><updated>{v["release"]}</updated><summary>{esc(v["summary"])}</summary></entry>
''' for v in out)
    return f'''<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>{NAME}</title><subtitle>{esc(TAGLINE)}</subtitle>
<link href="{SITE_URL}/"/><link rel="self" href="{SITE_URL}/feed.xml"/><id>{SITE_URL}/</id>
<updated>{updated}</updated><author><name>{NAME}</name></author>
{entries}</feed>
'''


def build(out: Path, show_all: bool = False, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    videos = json.loads((SITE / "content" / "videos.json").read_text())
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copytree(SITE / "static", out / "static")

    def write(rel: str, text: str):
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    write("index.html", home(videos, now, show_all))
    write("videos/index.html", index_page(videos, now, show_all))
    pages = []
    for v in videos:
        if show_all or released(v, now):
            write(f"{v['slug']}/index.html", video_page(v, videos, now))
            pages.append((f"/{v['slug']}/", v["release"][:10]))
    for src in sorted((SITE / "pages").glob("*.md")):
        write(f"{src.stem}/index.html", text_page(src, f"/{src.stem}/"))
        pages.append((f"/{src.stem}/", None))
    write("404.html", not_found())
    write("feed.xml", feed(videos, now))
    urls = [("/", None), ("/videos/", None)] + pages
    write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "".join(f"<url><loc>{SITE_URL}{u}</loc>" + (f"<lastmod>{d}</lastmod>" if d else "") + "</url>\n" for u, d in urls)
          + "</urlset>\n")
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n")
    (out / ".nojekyll").write_text("")
    shown = sum(1 for v in videos if show_all or released(v, now))
    print(f"built {out} ({shown} of {len(videos)} videos{' (--all)' if show_all else ''})")


# ---------------------------------------------------------------- serve / deploy

def git(*args, cwd: Path, check=True):
    return subprocess.run(["git", *args], cwd=cwd, check=check, text=True, capture_output=True)


def deploy(force: bool = False) -> None:
    top = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=SITE, capture_output=True,
                              text=True, check=True).stdout.strip())
    if top != main_checkout() and not force:
        # A worktree's BACKLOG.md lacks the rows other sessions added on main since it branched.
        sys.exit("deploy from the main checkout (after merging), not from a worktree; --force overrides")
    export()
    build(SITE / "_site")
    repo = main_checkout() / "build" / "site-repo"
    if not (repo / ".git").exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        # SSH, not the gh token: pushing .github/workflows/ over HTTPS needs the `workflow` scope.
        git("clone", f"git@github.com:{PUBLIC_REPO}.git", str(repo), cwd=repo.parent)
    git("pull", "--ff-only", cwd=repo, check=False)
    for item in repo.iterdir():
        if item.name != ".git":
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    for name in ["build.py", "static", "pages", "content"]:
        src = SITE / name
        (shutil.copytree if src.is_dir() else shutil.copy2)(src, repo / name)
    (repo / ".github" / "workflows").mkdir(parents=True)
    shutil.copy2(SITE / "pages.yml", repo / ".github" / "workflows" / "pages.yml")
    shutil.copy2(SITE / "PUBLIC_README.md", repo / "README.md")
    (repo / ".gitignore").write_text("_site/\n__pycache__/\n")
    git("add", "-A", cwd=repo)
    if not git("status", "--porcelain", cwd=repo).stdout.strip():
        print("site repo already up to date")
        return
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=SITE, capture_output=True, text=True).stdout.strip()
    git("commit", "-m", f"Update site (tamalaleika {sha})", cwd=repo)
    r = git("push", "origin", "HEAD:main", cwd=repo, check=False)
    if r.returncode:
        sys.exit(r.stderr)
    print(f"pushed to {PUBLIC_REPO}; GitHub Actions deploys it to {SITE_URL} in a minute or two")


def make_poster(vid: str, seconds: float) -> None:
    """site/static/posters/<id>.jpg: the drawing (top 1440 px) of the render at `seconds`."""
    src = main_checkout() / "out" / f"{vid}.mp4"
    dst = SITE / "static" / "posters" / f"{vid}.jpg"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(seconds), "-i", str(src), "-frames:v", "1",
                    "-vf", "crop=1080:1440:0:0,scale=720:960", "-q:v", "3", str(dst)], check=True)
    print(f"wrote {dst.relative_to(SITE.parent)} ({dst.stat().st_size // 1024} KB)")


def serve(port: int = 8738, show_all: bool = False) -> None:
    import functools
    import http.server
    export()
    global B
    B = ""
    out = SITE / "_site"
    build(out, show_all=show_all)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
    print(f"http://localhost:{port}/")
    http.server.ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "build"
    if cmd == "export":
        export()
    elif cmd == "build":
        out = Path(args[args.index("--out") + 1]) if "--out" in args else SITE / "_site"
        now = None
        if "--now" in args:
            now = datetime.fromisoformat(args[args.index("--now") + 1]).astimezone(timezone.utc)
        if "--base" in args:
            B = args[args.index("--base") + 1]
        build(out, show_all="--all" in args, now=now)
    elif cmd == "serve":
        serve(show_all="--all" in args)
    elif cmd == "poster":
        make_poster(args[1], float(args[2]))
    elif cmd == "deploy":
        deploy(force="--force" in args)
    else:
        sys.exit(__doc__)
