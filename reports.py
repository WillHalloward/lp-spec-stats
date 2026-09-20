"""One-off stat reports.

A report is a self-contained HTML page in ``reports/``; ``reports/index.json``
lists them, newest first. Nothing is generated at request time — adding a report
is: drop the file in, add a row to the index, commit. That keeps a report frozen
as it was written, which is the point of a one-off.

Index entry shape:
    {"slug": "...", "title": "...", "date": "2026-09-10", "kind": "prog night",
     "summary": "one line", "source": "optional link back to the log"}
"""

from __future__ import annotations

import json
import os
from html import escape
from pathlib import Path

REPORTS_DIR = Path(__file__).parent / "reports"
INDEX_FILE = REPORTS_DIR / "index.json"


def load_index() -> list[dict]:
    """Reports that have both an index row and a file on disk."""
    if not INDEX_FILE.exists():
        return []
    try:
        rows = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"reports/index.json is not valid JSON: {exc}", flush=True)
        return []
    return [r for r in rows if report_file(r.get("slug", "")) is not None]


def report_file(slug: str) -> Path | None:
    """Path to a report's HTML, or None. Rejects anything that isn't a plain slug
    so a request can never walk out of the reports directory."""
    if not slug or not all(c.isalnum() or c in "-_" for c in slug):
        return None
    path = REPORTS_DIR / f"{slug}.html"
    return path if path.is_file() else None


def _card(r: dict) -> str:
    slug = escape(str(r.get("slug", "")))
    title = escape(str(r.get("title", slug)))
    date = escape(str(r.get("date", "")))
    kind = escape(str(r.get("kind", "")))
    summary = escape(str(r.get("summary", "")))
    return f"""
    <a class="report" href="/reports/{slug}">
      <div class="meta"><span class="kind">{kind}</span><span class="date">{date}</span></div>
      <h2>{title}</h2>
      <p>{summary}</p>
    </a>"""


# Absolute URL the pages are served from, for link previews.
SITE = os.environ.get("REPORT_SITE_URL", "https://low-pressure-stats.halloward.com").rstrip("/")
_INDEX_BLURB = "Prog-night reports for the Low Pressure raid teams: what the numbers say about each night."


def index_page() -> str:
    rows = load_index()
    cards = "".join(_card(r) for r in rows) or (
        '<p class="empty">No reports yet. Drop an HTML file in <code>reports/</code> '
        "and add a row to <code>reports/index.json</code>.</p>"
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reports &mdash; Low Pressure</title>
<meta name="description" content="{_INDEX_BLURB}">
<meta name="theme-color" content="#e0a526">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Low Pressure">
<meta property="og:title" content="Reports &mdash; Low Pressure">
<meta property="og:description" content="{_INDEX_BLURB}">
<meta property="og:url" content="{SITE}/reports">
<meta name="twitter:card" content="summary">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cinzel:wght@500;600&family=Inter:wght@400;500;600&display=swap">
<style>
:root{{--bg:#070912;--surface:#0f1424;--surface-2:#181f33;--border:#262e44;--border-soft:#1c2438;
  --text:#e6ebf5;--text-muted:#8b95ad;--gold:#e0a526;color-scheme:dark}}
*{{box-sizing:border-box}}
body{{margin:0;background:radial-gradient(ellipse 90% 50% at 50% -10%,rgba(224,165,38,.06),transparent 60%),var(--bg);
  background-attachment:fixed;color:var(--text);font-family:"Inter",system-ui,sans-serif;min-height:100vh}}
.wrap{{max-width:920px;margin:0 auto;padding:56px 24px 80px}}
header{{text-align:center;margin-bottom:40px}}
header h1{{font-family:"Cinzel","Inter",serif;font-weight:600;font-size:38px;letter-spacing:.04em;margin:0 0 16px}}
header .underline{{display:block;width:80px;height:2px;margin:0 auto 20px;
  background:linear-gradient(90deg,transparent,var(--gold),transparent)}}
header .sub{{color:var(--text-muted);font-size:14px;letter-spacing:.04em}}
.topnav{{display:flex;gap:4px;justify-content:center;padding:14px 24px 0;font-size:13px}}
.topnav a{{color:var(--text-muted);text-decoration:none;padding:6px 14px;border-radius:999px;
  letter-spacing:.04em;transition:color .15s ease,background .15s ease}}
.topnav a:hover{{color:var(--text);background:var(--surface-2)}}
.topnav a.active{{color:var(--gold)}}
.topnav a:focus-visible{{outline:2px solid var(--gold);outline-offset:2px}}
.list{{display:flex;flex-direction:column;gap:14px}}
a.report{{display:block;text-decoration:none;color:inherit;background:var(--surface);
  border:1px solid var(--border-soft);border-radius:14px;padding:22px 24px;transition:border-color .2s,transform .2s}}
a.report:hover{{border-color:var(--gold);transform:translateY(-2px)}}
a.report .meta{{display:flex;gap:14px;align-items:center;color:var(--text-muted);font-size:12px;
  letter-spacing:.08em;text-transform:uppercase}}
a.report .kind{{color:var(--gold)}}
a.report h2{{font-size:20px;margin:8px 0 6px;font-weight:600}}
a.report p{{margin:0;color:var(--text-muted);font-size:14px;line-height:1.55}}
.empty{{color:var(--text-muted);text-align:center}}
footer{{margin-top:48px;text-align:center;color:var(--text-muted);font-size:12px}}
</style>
</head>
<body>
<nav class="topnav">
  <a href="/">Dashboard</a>
  <a class="active" href="/reports" aria-current="page">Reports</a>
</nav>
<div class="wrap">
  <header>
    <h1>Reports</h1>
    <span class="underline"></span>
    <div class="sub">One-off digs through the logs &mdash; prog nights, mechanics, whatever was worth counting</div>
  </header>
  <div class="list">{cards}</div>
  <footer>Low Pressure</footer>
</div>
</body>
</html>"""
