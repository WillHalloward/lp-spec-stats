"""Analyze cached raid-helper events and produce an infographic HTML page.

Reads cache/events/*.json, normalizes each event (category, difficulty,
series key), flattens signups, then renders a single self-contained HTML
file (infographic.html) with Plotly charts.
"""

import glob
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

CACHE_DIR = Path("cache/events")
OUTPUT = Path("infographic.html")

# Only count events from ISO week 12 of 2026 onwards (Mon 2026-03-16).
# Season started earlier; pre-week-12 was normal/heroic ramp-up that skews stats.
START_TS = int(datetime(2026, 3, 16, tzinfo=timezone.utc).timestamp())

ABSENCE_ROLES = {"Absence", "Tentative", "Bench", "Late"}
GENERIC_CLASSES = {"Dps", "Tanks", "Healer", "Tank", "Melee", "Ranged"}

CLASS_COLORS = {
    "DK": "#C41E3A", "DH": "#A330C9", "Druid": "#FF7C0A", "Evoker": "#33937F",
    "Hunter": "#AAD372", "Mage": "#3FC7EB", "Monk": "#00FF98", "Paladin": "#F48CBA",
    "Priest": "#FFFFFF", "Rogue": "#FFF468", "Shaman": "#0070DD", "Warlock": "#8788EE",
    "Warrior": "#C69B6D",
}

# Design tokens — kept in sync with the CSS :root in render_html_string.
THEME = {
    "bg": "#070912",
    "surface": "#0f1424",
    "surface_2": "#181f33",
    "border": "#262e44",
    "border_soft": "#1c2438",
    "text": "#e6ebf5",
    "text_muted": "#8b95ad",
    "gold": "#e0a526",
    "gold_soft": "#c08c1c",
    "blue": "#3b82f6",
    "blue_soft": "#2f6acc",
}

# Difficulty progression palette: steel-blue → arcane purple → gold.
DIFFICULTY_COLORS = {
    "Normal": "#4a6fa5",
    "Heroic": "#9b6dd6",
    "Mythic": THEME["gold"],
    "LFR": "#5b6478",
    "Other": "#737d95",
    "M+": "#10b981",
    "Achievement": "#f0d068",
    "Mount": "#ec4899",
}

RAID_KEYWORDS = [
    "Voidspire", "Dreamrift", "Crown of the Cosmos", "MoQD",
    "MFO", "Ansurek", "Gallywix",
    "Sargeras", "Hellfire", "Legion", "Draenor", "Orgrimmar", "Midnight", "ToV", "EN",
]


@dataclass
class Event:
    raid_id: str
    title: str
    unixtime: int
    leader_id: str
    leader_name: str
    category: str        # Raid | M+ | Achievement | Mount
    difficulty: str      # Mythic | Heroic | Normal | LFR | Other
    raid_name: str       # extracted raid keyword or ""
    series_key: str      # leader_id + category/raid_name/difficulty bucket
    series_label: str    # human-readable
    signups: list


# ---- normalization ----

def detect_category(title: str) -> str:
    t = title.lower()
    if "m+" in t or "mythic+" in t or "mythic plus" in t or "m+ mania" in t:
        return "M+"
    if "glory" in t or "achievement" in t or "achiev" in t:
        return "Achievement"
    if "mount run" in t or "mount raid" in t:
        return "Mount"
    return "Raid"


def detect_difficulty(title: str) -> str:
    t = title.lower()
    # Order matters: check Mythic before Heroic (mythic raids can mention heroic prog)
    if re.search(r"\bmythic\b", t):
        return "Mythic"
    if re.search(r"\bheroic\b", t) or re.search(r"\bhc\b", t):
        return "Heroic"
    if re.search(r"\bnormal\b", t):
        return "Normal"
    if re.search(r"\blfr\b", t):
        return "LFR"
    return "Other"


def detect_raid_name(title: str) -> str:
    for kw in RAID_KEYWORDS:
        if kw.lower() in title.lower():
            return kw
    return ""


def normalize_leader_name(name: str) -> str:
    """Strip realm suffix and special chars so 'Mêlôdý - Frostwolf' and 'Melody' collide."""
    if not name:
        return ""
    base = name.split(" - ")[0].split("-")[0].strip()
    return base


# Canonical leader name per leader_id (uses most common variant)
def build_leader_name_map(events: list[dict]) -> dict[str, str]:
    counter: dict[str, Counter] = defaultdict(Counter)
    for e in events:
        counter[e["leaderid"]][e.get("leadername", "")] += 1
    out = {}
    for lid, c in counter.items():
        best = c.most_common(1)[0][0]
        out[lid] = normalize_leader_name(best) or best or lid
    return out


def _load_raw_events() -> list[dict]:
    """Return all event payloads, preferring Postgres if DATABASE_URL is set."""
    if os.environ.get("DATABASE_URL"):
        import db
        with db.connect() as conn:
            return db.load_all_events(conn)
    return [json.load(open(f)) for f in sorted(glob.glob(str(CACHE_DIR / "*.json")))]


def load_events() -> list[Event]:
    now_ts = int(datetime.now(timezone.utc).timestamp())
    raw = []
    for d in _load_raw_events():
        ts = int(d.get("unixtime", 0))
        if ts < START_TS or ts > now_ts:
            continue
        raw.append(d)

    leader_names = build_leader_name_map(raw)

    events: list[Event] = []
    for d in raw:
        title = d.get("displayTitle") or d.get("title") or ""
        category = detect_category(title)
        difficulty = detect_difficulty(title) if category == "Raid" else "—"
        raid_name = detect_raid_name(title) if category == "Raid" else ""
        leader_id = d.get("leaderid", "")
        leader = leader_names.get(leader_id, "?")

        # Series = leader + category. All of a leader's raids (across Voidspire/Dreamrift/...) collapse to one bucket.
        series_key = f"{leader_id}::{category}"
        series_label = f"{leader} — {category}"

        events.append(Event(
            raid_id=str(d["raidid"]),
            title=title,
            unixtime=int(d["unixtime"]),
            leader_id=leader_id,
            leader_name=leader,
            category=category,
            difficulty=difficulty,
            raid_name=raid_name,
            series_key=series_key,
            series_label=series_label,
            signups=d.get("signups", []),
        ))
    events.sort(key=lambda e: e.unixtime)
    return events


# ---- stats ----

def classify_signup(s: dict) -> str:
    """Return 'attending', 'absence', or 'generic'."""
    role = s.get("role", "")
    cls = s.get("class", "")
    if role in ABSENCE_ROLES or cls in ABSENCE_ROLES:
        return "absence"
    if cls in GENERIC_CLASSES:
        return "generic"
    return "attending"


def attending_signups(events: list[Event]):
    for e in events:
        for s in e.signups:
            if classify_signup(s) == "attending":
                yield e, s


# ---- charts ----

def _apply_theme(fig: go.Figure) -> go.Figure:
    """Apply shared theme defaults: fonts, paper bg, gridlines, tooltips."""
    fig.update_layout(
        paper_bgcolor=THEME["surface"],
        plot_bgcolor=THEME["surface"],
        font=dict(family="Inter, system-ui, sans-serif", color=THEME["text"], size=13),
        title=dict(font=dict(family="Inter, system-ui, sans-serif", size=15,
                              color=THEME["text"]), x=0.02, y=0.97, xanchor="left"),
        margin=dict(t=60, b=50, l=70, r=40),
        hoverlabel=dict(
            bgcolor=THEME["surface_2"],
            bordercolor=THEME["gold"],
            font=dict(family="JetBrains Mono, monospace", color=THEME["text"], size=12),
        ),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=THEME["border_soft"],
                    borderwidth=0, font=dict(size=12)),
    )
    fig.update_xaxes(gridcolor=THEME["border_soft"], zerolinecolor=THEME["border_soft"],
                      linecolor=THEME["border"], tickfont=dict(size=11, color=THEME["text_muted"]))
    fig.update_yaxes(gridcolor=THEME["border_soft"], zerolinecolor=THEME["border_soft"],
                      linecolor=THEME["border"], tickfont=dict(size=11, color=THEME["text_muted"]))
    return fig


def chart_class_distribution(events):
    counts = Counter()
    for _, s in attending_signups(events):
        counts[s.get("class", "?")] += 1
    classes = [c for c, _ in counts.most_common()]
    values = [counts[c] for c in classes]
    colors = [CLASS_COLORS.get(c, "#888") for c in classes]
    fig = go.Figure(go.Bar(x=classes, y=values, marker_color=colors, text=values,
                            textposition="outside",
                            textfont=dict(family="JetBrains Mono, monospace", color=THEME["text"])))
    fig.update_layout(title="Signups by class", xaxis_title=None, yaxis_title="Signups")
    return _apply_theme(fig)


def _strip_realm(name: str) -> str:
    # Signup names are formatted "CharacterName-RealmName" (or sometimes just "CharacterName").
    return name.split("-", 1)[0].strip() if name else name


def _clean_spec(spec: str) -> str:
    # raid-helper appends '1' to disambiguate specs sharing a name across classes
    # (e.g. Paladin Protection1, Shaman Restoration1). Strip for display.
    return re.sub(r"\d+$", "", spec) if spec else spec


ROLE_NORMALIZE = {"Tanks": "Tank", "Healers": "Healer", "Melee": "Melee DPS", "Ranged": "Ranged DPS"}
ROLE_ORDER = ["Tank", "Healer", "Melee DPS", "Ranged DPS"]


def chart_spec_distribution(events):
    """Sorted horizontal bar of all specs, colored by class. Custom filter UI on top
    with class chips and role chips: hover to preview-highlight, click to toggle into
    a persistent filter set (additive, multi-select).
    """
    counts = Counter()
    spec_role_counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for _, s in attending_signups(events):
        cls = s.get("class", "?")
        spec = _clean_spec(s.get("spec", "?"))
        counts[(cls, spec)] += 1
        role = ROLE_NORMALIZE.get(s.get("role", ""), "Other")
        spec_role_counts[(cls, spec)][role] += 1

    # Majority role per (class, spec)
    spec_role = {k: rc.most_common(1)[0][0] for k, rc in spec_role_counts.items()}

    sorted_items = counts.most_common()

    def label(cls: str, spec: str) -> str:
        return f"{spec}  ·  {cls}"

    y_order = [label(cls, spec) for (cls, spec), _ in sorted_items][::-1]

    by_class: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    class_first_seen: list[str] = []
    for (cls, spec), n in sorted_items:
        by_class[cls].append((label(cls, spec), n, spec_role[(cls, spec)]))
        if cls not in class_first_seen:
            class_first_seen.append(cls)

    fig = go.Figure()
    trace_meta = []
    for cls in class_first_seen:
        rows = by_class[cls]
        ys = [l for l, _, _ in rows]
        xs = [n for _, n, _ in rows]
        roles = [r for _, _, r in rows]
        fig.add_trace(go.Bar(
            name=cls, y=ys, x=xs, orientation="h",
            marker=dict(color=CLASS_COLORS.get(cls, "#888"), opacity=[1] * len(xs)),
            text=xs, textposition="outside",
            textfont=dict(family="JetBrains Mono, monospace", color=THEME["text"]),
            hovertemplate=f"<b>{cls}</b> · %{{y}}<br>%{{x}} signups<extra></extra>",
        ))
        trace_meta.append({"cls": cls, "roles": roles})

    fig.update_layout(
        height=max(500, 24 * len(y_order)),
        xaxis_title="Signups",
        yaxis=dict(
            categoryorder="array", categoryarray=y_order,
            automargin=True, ticksuffix="   ",
            tickfont=dict(size=12, color=THEME["text"]),
        ),
        margin=dict(t=20, b=50, l=220, r=80),
        showlegend=False,
    )
    _apply_theme(fig)

    chart_id = "spec-chart"
    inner = fig.to_html(include_plotlyjs=False, full_html=False, div_id=chart_id)

    role_chips = "".join(
        f'<button class="cf-chip role-chip" data-role="{r}">{r}</button>'
        for r in ROLE_ORDER
    )
    class_chips = "".join(
        f'<button class="cf-chip class-chip" data-class="{cls}" '
        f'style="--chip-color:{CLASS_COLORS.get(cls, "#888")}">'
        f'<span class="cf-swatch"></span>{cls}</button>'
        for cls in class_first_seen
    )

    trace_meta_json = json.dumps(trace_meta)
    js = (
        "(function(){"
        f"const traceMeta = {trace_meta_json};"
        f'const chartId = "{chart_id}";'
        "const state = {classes: new Set(), roles: new Set()};"
        "function compute(pCls, pRole){"
        "  const useC = pCls ? new Set([pCls]) : state.classes;"
        "  const useR = pRole ? new Set([pRole]) : state.roles;"
        "  return traceMeta.map(t => t.roles.map(r => "
        "    ((useC.size===0 || useC.has(t.cls)) && (useR.size===0 || useR.has(r))) ? 1 : 0.12"
        "  ));"
        "}"
        "function apply(pCls, pRole){"
        "  if(window.Plotly) Plotly.restyle(chartId, {'marker.opacity': compute(pCls, pRole)});"
        "}"
        "function sync(){"
        "  document.querySelectorAll('.class-chip').forEach(c =>"
        "    c.classList.toggle('active', state.classes.has(c.dataset.class)));"
        "  document.querySelectorAll('.role-chip').forEach(c =>"
        "    c.classList.toggle('active', state.roles.has(c.dataset.role)));"
        "}"
        "document.querySelectorAll('.class-chip').forEach(chip => {"
        "  chip.addEventListener('click', () => {"
        "    const c = chip.dataset.class;"
        "    if (state.classes.has(c)) state.classes.delete(c); else state.classes.add(c);"
        "    sync(); apply();"
        "  });"
        "  chip.addEventListener('mouseenter', () => apply(chip.dataset.class, null));"
        "  chip.addEventListener('mouseleave', () => apply());"
        "});"
        "document.querySelectorAll('.role-chip').forEach(chip => {"
        "  chip.addEventListener('click', () => {"
        "    const r = chip.dataset.role;"
        "    if (state.roles.has(r)) state.roles.delete(r); else state.roles.add(r);"
        "    sync(); apply();"
        "  });"
        "  chip.addEventListener('mouseenter', () => apply(null, chip.dataset.role));"
        "  chip.addEventListener('mouseleave', () => apply());"
        "});"
        "document.querySelectorAll('.cf-reset').forEach(btn => {"
        "  btn.addEventListener('click', () => {"
        "    if (btn.dataset.reset === 'class') state.classes.clear();"
        "    else if (btn.dataset.reset === 'role') state.roles.clear();"
        "    else { state.classes.clear(); state.roles.clear(); }"
        "    sync(); apply();"
        "  });"
        "});"
        "})();"
    )

    return (
        f'<div class="custom-chart">'
        f'<div class="custom-chart-head">'
        f'<div class="custom-chart-title">Signups by class + spec</div>'
        f'<div class="custom-chart-sub">Hover a chip to preview · click to add/remove from filter (multi-select).</div>'
        f'</div>'
        f'<div class="cf-filters">'
        f'<div class="cf-group"><div class="cf-label">Role</div>'
        f'<div class="cf-row">{role_chips}'
        f'<button class="cf-chip cf-reset" data-reset="role">Reset</button></div></div>'
        f'<div class="cf-group"><div class="cf-label">Class</div>'
        f'<div class="cf-row">{class_chips}'
        f'<button class="cf-chip cf-reset" data-reset="class">Reset</button></div></div>'
        f'</div>'
        f'{inner}'
        f'<script>{js}</script>'
        f'</div>'
    )


def chart_class_consistency(events):
    """Per-class player commitment: avg events attended per unique character of that class.
    High = the class's players are dedicated raiders; low = lots of one-off signups.
    """
    per_char: dict[str, Counter] = defaultdict(Counter)  # class -> Counter[char_name]
    for e in events:
        for s in e.signups:
            if classify_signup(s) != "attending":
                continue
            cls = s.get("class", "?")
            name = s.get("name", "?")
            per_char[cls][name] += 1

    rows = []
    for cls, chars in per_char.items():
        counts = list(chars.values())
        if not counts:
            continue
        mean = sum(counts) / len(counts)
        median = sorted(counts)[len(counts) // 2]
        rows.append((cls, mean, median, len(counts), sum(counts), max(counts)))

    rows.sort(key=lambda r: -r[1])
    classes = [r[0] for r in rows]
    means = [r[1] for r in rows]
    colors = [CLASS_COLORS.get(c, "#888") for c in classes]
    hover = [
        f"{cls}<br>Avg events per character: {mean:.1f}<br>Median: {median}<br>"
        f"Unique characters: {n_chars}<br>Total signups: {total}<br>Top character: {top} events"
        for cls, mean, median, n_chars, total, top in rows
    ]
    fig = go.Figure(go.Bar(
        y=classes[::-1], x=means[::-1], orientation="h",
        marker_color=colors[::-1],
        text=[f"{m:.1f}" for m in means[::-1]], textposition="outside",
        textfont=dict(family="JetBrains Mono, monospace", color=THEME["text"]),
        hovertext=hover[::-1], hoverinfo="text",
    ))
    fig.update_layout(
        title=f"Player commitment by class — avg events per unique character",
        xaxis_title="Average events attended per unique character",
        height=max(400, 28 * len(classes)),
        margin=dict(t=60, b=50, l=120, r=80),
        yaxis=dict(automargin=True, ticksuffix="   ", tickfont=dict(color=THEME["text"])),
    )
    return _apply_theme(fig)


def chart_role_balance(events):
    """Horizontal stacked bar: actual role split with ideal-mythic markers.
    Ideal for 20-player mythic: 2 tanks (10%), 4.5 healers (22.5%), 13.5 DPS (67.5%).
    """
    role_map = {"Tanks": "Tank", "Healers": "Healer", "Melee": "Melee DPS", "Ranged": "Ranged DPS"}
    role_colors = {"Tank": "#3b82f6", "Healer": "#10b981",
                    "Melee DPS": "#ef4444", "Ranged DPS": "#a855f7"}
    counts = Counter()
    for _, s in attending_signups(events):
        role = role_map.get(s.get("role", ""))
        if role:
            counts[role] += 1
    total = sum(counts.values()) or 1
    order = ["Tank", "Healer", "Melee DPS", "Ranged DPS"]

    fig = go.Figure()
    for role in order:
        pct = 100 * counts.get(role, 0) / total
        fig.add_trace(go.Bar(
            name=role, x=[pct], y=["Actual"], orientation="h",
            marker_color=role_colors[role],
            text=[f"{role}<br>{pct:.1f}% ({counts.get(role, 0)})"],
            textposition="inside",
            textfont=dict(family="Inter, sans-serif", color="white", size=12),
            insidetextanchor="middle",
            hovertemplate=f"{role}: %{{x:.1f}}% (%{{customdata}})<extra></extra>",
            customdata=[counts.get(role, 0)],
        ))

    # Ideal mythic comp: 2 / 4.5 / 13.5 over 20 → 10% / 22.5% / 67.5% (DPS split 50/50 melee/ranged for the bar)
    ideal = {"Tank": 10.0, "Healer": 22.5, "Melee DPS": 33.75, "Ranged DPS": 33.75}
    for role in order:
        fig.add_trace(go.Bar(
            name=f"{role} (ideal)", x=[ideal[role]], y=["Ideal mythic"], orientation="h",
            marker=dict(color=role_colors[role], pattern=dict(shape="/", fgcolor=THEME["surface"],
                                                                 fgopacity=0.35, size=4)),
            text=[f"{ideal[role]:.1f}%"], textposition="inside",
            textfont=dict(family="Inter, sans-serif", color="white", size=11),
            insidetextanchor="middle",
            hovertemplate=f"{role} ideal: %{{x:.1f}}%<extra></extra>",
            showlegend=False,
        ))

    fig.update_layout(
        title="Role composition · actual vs ideal mythic",
        barmode="stack",
        height=260,
        xaxis=dict(range=[0, 100], ticksuffix="%", showgrid=False),
        yaxis=dict(autorange="reversed"),
        bargap=0.35,
        margin=dict(t=60, b=40, l=110, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=-0.35, xanchor="center", x=0.5),
    )
    return _apply_theme(fig)


def chart_top_characters(events, top_n=30):
    counts = Counter()
    last_seen = {}
    for e, s in attending_signups(events):
        name = _strip_realm(s.get("name", "?"))
        counts[name] += 1
        last_seen[name] = max(last_seen.get(name, 0), e.unixtime)
    top = counts.most_common(top_n)
    names = [n for n, _ in top][::-1]
    values = [c for _, c in top][::-1]
    fig = go.Figure(go.Bar(y=names, x=values, orientation="h", text=values, textposition="outside",
                            textfont=dict(family="JetBrains Mono, monospace", color=THEME["text"]),
                            marker_color=THEME["gold"]))
    fig.update_layout(title=f"Top {top_n} most consistent characters", height=max(400, 20 * top_n),
                      xaxis_title="Events signed up to",
                      margin=dict(t=60, b=50, l=200, r=80),
                      yaxis=dict(automargin=True, ticksuffix="   ", tickfont=dict(color=THEME["text"])))
    return _apply_theme(fig)


def chart_top_players(events, top_n=30):
    counts = Counter()
    pretty = {}
    for _, s in attending_signups(events):
        uid = s.get("userid", "?")
        counts[uid] += 1
        # Track names this user used
        pretty.setdefault(uid, Counter())[_strip_realm(s.get("name", "?"))] += 1
    top = counts.most_common(top_n)
    labels = []
    values = []
    for uid, c in top:
        most_used = pretty[uid].most_common(1)[0][0]
        alt = len(pretty[uid])
        label = most_used if alt == 1 else f"{most_used} (+{alt-1} alts)"
        labels.append(label)
        values.append(c)
    fig = go.Figure(go.Bar(y=labels[::-1], x=values[::-1], orientation="h", text=values[::-1],
                            textposition="outside",
                            textfont=dict(family="JetBrains Mono, monospace", color=THEME["text"]),
                            marker_color=THEME["blue"]))
    fig.update_layout(title=f"Top {top_n} most consistent players (unique Discord IDs)",
                      height=max(400, 20 * top_n),
                      xaxis_title="Events signed up to",
                      margin=dict(t=60, b=50, l=200, r=80),
                      yaxis=dict(automargin=True, ticksuffix="   ", tickfont=dict(color=THEME["text"])))
    return _apply_theme(fig)


def chart_signups_over_time(events):
    """Weekly attending signups, stacked by difficulty."""
    by_week: dict[str, Counter] = defaultdict(Counter)
    for e in events:
        dt = datetime.fromtimestamp(e.unixtime, timezone.utc)
        # ISO week start (Monday)
        year, week, _ = dt.isocalendar()
        wk = f"{year}-W{week:02d}"
        attending = sum(1 for s in e.signups if classify_signup(s) == "attending")
        diff = e.difficulty if e.category == "Raid" else e.category
        by_week[wk][diff] += attending

    weeks = sorted(by_week.keys())
    diffs = ["Mythic", "Heroic", "Normal", "LFR", "Other", "M+", "Achievement", "Mount"]
    fig = go.Figure()
    for d in diffs:
        ys = [by_week[w].get(d, 0) for w in weeks]
        if sum(ys) == 0:
            continue
        fig.add_trace(go.Bar(name=d, x=weeks, y=ys, marker_color=DIFFICULTY_COLORS.get(d, "#888")))
    fig.update_layout(barmode="stack", title="Weekly attending signups, by difficulty",
                      xaxis_title=None, yaxis_title="Signups",
                      bargap=0.25)
    return _apply_theme(fig)


def chart_difficulty_progression(events):
    """Events per week by raid difficulty — Normal → Heroic → Mythic progression."""
    by_week: dict[str, Counter] = defaultdict(Counter)
    for e in events:
        if e.category != "Raid":
            continue
        dt = datetime.fromtimestamp(e.unixtime, timezone.utc)
        year, week, _ = dt.isocalendar()
        wk = f"{year}-W{week:02d}"
        by_week[wk][e.difficulty] += 1
    weeks = sorted(by_week.keys())
    diffs = ["Mythic", "Heroic", "Normal", "LFR", "Other"]
    fig = go.Figure()
    for d in diffs:
        ys = [by_week[w].get(d, 0) for w in weeks]
        if sum(ys) == 0:
            continue
        fig.add_trace(go.Bar(name=d, x=weeks, y=ys, marker_color=DIFFICULTY_COLORS[d]))
    fig.update_layout(barmode="stack", title="Raid count per week by difficulty",
                      xaxis_title=None, yaxis_title="Raids", bargap=0.25)
    return _apply_theme(fig)


def _sparkline_svg(values: list[int], width: int = 140, height: int = 28,
                    color: str = "#e0a526") -> str:
    if not values:
        return ""
    n = len(values)
    mx = max(values) or 1
    pad = 3
    if n == 1:
        y = pad + (height - 2 * pad) * (1 - values[0] / mx)
        return (f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
                f'<circle cx="{width//2}" cy="{y:.1f}" r="2" fill="{color}"/></svg>')
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad
    pts = []
    for i, v in enumerate(values):
        x = pad + (i / (n - 1)) * inner_w
        y = pad + inner_h * (1 - v / mx)
        pts.append(f"{x:.1f},{y:.1f}")
    poly = " ".join(pts)
    last_x = pad + inner_w
    area = (f"M {pts[0]} L " + " L ".join(pts[1:])
            + f" L {last_x:.1f},{height - pad:.1f} L {pad},{height - pad:.1f} Z")
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" aria-hidden="true">'
        f'<path d="{area}" fill="{color}" fill-opacity="0.18"/>'
        f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )


def chart_series_breakdown(events):
    """Series breakdown rendered as a real table with a weekly trend sparkline per row."""
    # Aggregate per series
    by_series: dict[str, dict] = {}
    series_weeks: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    all_weeks_set: set[str] = set()
    for e in events:
        attending = sum(1 for s in e.signups if classify_signup(s) == "attending")
        bucket = by_series.setdefault(e.series_label, {"events": 0, "signups": 0, "category": e.category})
        bucket["events"] += 1
        bucket["signups"] += attending
        dt = datetime.fromtimestamp(e.unixtime, timezone.utc)
        y, w, _ = dt.isocalendar()
        wk = f"{y}-W{w:02d}"
        series_weeks[e.series_label][wk] += attending
        all_weeks_set.add(wk)

    all_weeks = sorted(all_weeks_set)
    items = sorted(by_series.items(), key=lambda kv: -kv[1]["events"])

    category_color = {
        "Raid": THEME["gold"], "Achievement": "#f0d068", "M+": "#10b981",
        "Mount": "#ec4899", "Other": "#737d95",
    }

    rows = []
    for label, v in items:
        n_events = v["events"]
        n_signups = v["signups"]
        avg = n_signups / n_events
        category = v["category"]
        weekly = [series_weeks[label].get(w, 0) for w in all_weeks]
        spark = _sparkline_svg(weekly, color=category_color.get(category, THEME["gold"]))
        # Split "Leader — Category" label for nicer rendering
        if " — " in label:
            leader, _cat = label.split(" — ", 1)
        else:
            leader = label
        rows.append(
            f'<tr>'
            f'<td><div class="leader-cell">'
            f'<span class="leader-dot" style="background:{category_color.get(category, THEME["gold"])}"></span>'
            f'<span class="leader-name">{leader}</span>'
            f'</div></td>'
            f'<td><span class="chip">{category}</span></td>'
            f'<td class="num">{n_events}</td>'
            f'<td class="num">{n_signups}</td>'
            f'<td class="num strong">{avg:.1f}</td>'
            f'<td class="spark-cell">{spark}</td>'
            f'</tr>'
        )

    return (
        f'<div class="custom-chart">'
        f'<div class="custom-chart-head">'
        f'<div class="custom-chart-title">Raid series breakdown</div>'
        f'<div class="custom-chart-sub">Sorted by events held. Sparkline = weekly attending signups across the season.</div>'
        f'</div>'
        f'<table class="series-table">'
        f'<thead><tr>'
        f'<th>Leader</th><th>Type</th><th class="num">Events</th>'
        f'<th class="num">Signups</th><th class="num">Avg / event</th>'
        f'<th class="spark-cell">Weekly trend</th>'
        f'</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        f'</table>'
        f'</div>'
    )


# ---- render ----

SECTIONS = [
    ("trends", "Trends", "Signups and raids over time.",
        [chart_signups_over_time, chart_difficulty_progression]),
    ("composition", "Composition", "Who shows up, in what role, with what spec.",
        [chart_class_distribution, chart_class_consistency, chart_role_balance, chart_spec_distribution]),
    ("roster", "Roster & series", "Recurring leaders, characters, and players.",
        [chart_series_breakdown, chart_top_characters, chart_top_players]),
]


ICON_SWORDS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="14.5 17.5 3 6 3 3 6 3 17.5 14.5"/><line x1="13" y1="19" x2="19" y2="13"/><line x1="16" y1="16" x2="20" y2="20"/><line x1="19" y1="21" x2="21" y2="19"/><polyline points="14.5 6.5 18 3 21 3 21 6 17.5 9.5"/><line x1="5" y1="14" x2="9" y2="18"/><line x1="7" y1="17" x2="4" y2="20"/><line x1="3" y1="19" x2="5" y2="21"/></svg>'
ICON_USERS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>'
ICON_USER_CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><polyline points="17 11 19 13 23 9"/></svg>'
ICON_AWARD = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="6"/><polyline points="15.477 12.89 17 22 12 19 7 22 8.523 12.89"/></svg>'


def render_html_string(events: list[Event]) -> str:
    first_event = datetime.fromtimestamp(events[0].unixtime, timezone.utc).strftime("%b %d, %Y")
    last_event = datetime.fromtimestamp(events[-1].unixtime, timezone.utc).strftime("%b %d, %Y")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_signups = sum(1 for _ in attending_signups(events))
    unique_players = len({s.get("userid") for e in events for s in e.signups
                           if classify_signup(s) == "attending"})
    unique_chars = len({s.get("name") for e in events for s in e.signups
                         if classify_signup(s) == "attending"})

    css = (
        ":root {"
        f" --bg: {THEME['bg']};"
        f" --surface: {THEME['surface']};"
        f" --surface-2: {THEME['surface_2']};"
        f" --border: {THEME['border']};"
        f" --border-soft: {THEME['border_soft']};"
        f" --text: {THEME['text']};"
        f" --text-muted: {THEME['text_muted']};"
        f" --gold: {THEME['gold']};"
        f" --gold-soft: {THEME['gold_soft']};"
        f" --blue: {THEME['blue']};"
        "}"
        "* { box-sizing: border-box; }"
        "html, body { background: var(--bg); }"
        "body {"
        " margin: 0; padding: 0;"
        " font-family: 'Inter', -apple-system, system-ui, sans-serif;"
        " color: var(--text);"
        " background:"
        "   radial-gradient(ellipse 90% 50% at 50% -10%, rgba(224,165,38,0.06), transparent 60%),"
        "   radial-gradient(ellipse 80% 50% at 50% 5%, rgba(59,130,246,0.05), transparent 60%),"
        "   var(--bg);"
        " background-attachment: fixed;"
        " min-height: 100vh;"
        "}"
        ".wrap { max-width: 1180px; margin: 0 auto; padding: 56px 24px 80px; }"
        "header { text-align: center; margin-bottom: 56px; }"
        "header h1 {"
        " font-family: 'Cinzel', 'Inter', serif;"
        " font-weight: 600; font-size: 42px; letter-spacing: 0.04em;"
        " margin: 0 0 16px;"
        " color: var(--text);"
        "}"
        "header .underline {"
        " display: block; width: 80px; height: 2px; margin: 0 auto 20px;"
        " background: linear-gradient(90deg, transparent, var(--gold), transparent);"
        "}"
        "header .sub {"
        " color: var(--text-muted); font-size: 14px; letter-spacing: 0.04em;"
        "}"
        "header .sub b { color: var(--text); font-weight: 600; }"
        ".summary {"
        " display: grid;"
        " grid-template-columns: repeat(4, 1fr);"
        " gap: 16px;"
        " margin-bottom: 64px;"
        "}"
        "@media (max-width: 900px) { .summary { grid-template-columns: repeat(2, 1fr); } }"
        ".stat {"
        " position: relative;"
        " background: var(--surface);"
        " border: 1px solid var(--border-soft);"
        " border-radius: 14px;"
        " padding: 24px;"
        " overflow: hidden;"
        " transition: border-color 200ms ease, transform 200ms ease;"
        "}"
        ".stat::before {"
        " content: ''; position: absolute; top: 0; left: 16px; right: 16px; height: 1px;"
        " background: linear-gradient(90deg, transparent, var(--gold), transparent);"
        " opacity: 0.5; transition: opacity 200ms ease, height 200ms ease;"
        "}"
        ".stat:hover { border-color: var(--border); transform: translateY(-2px); }"
        ".stat:hover::before { opacity: 1; height: 2px; }"
        ".stat .row { display: flex; align-items: center; gap: 14px; }"
        ".stat .icon {"
        " width: 36px; height: 36px; flex-shrink: 0;"
        " color: var(--gold); opacity: 0.85;"
        " display: flex; align-items: center; justify-content: center;"
        "}"
        ".stat .icon svg { width: 24px; height: 24px; }"
        ".stat .label {"
        " font-size: 11px; text-transform: uppercase; letter-spacing: 0.12em;"
        " color: var(--text-muted); font-weight: 500;"
        "}"
        ".stat .value {"
        " font-family: 'JetBrains Mono', 'Fira Code', monospace;"
        " font-variant-numeric: tabular-nums;"
        " font-size: 40px; font-weight: 600; line-height: 1.1;"
        " color: var(--text); margin-top: 4px;"
        "}"
        ".stat.primary .value { color: var(--gold); }"
        "section { margin-bottom: 48px; }"
        "section .section-head { margin-bottom: 20px; }"
        "section h2 {"
        " font-family: 'Cinzel', serif; font-weight: 500;"
        " font-size: 22px; letter-spacing: 0.04em;"
        " margin: 0 0 4px;"
        "}"
        "section .section-sub { color: var(--text-muted); font-size: 13px; }"
        ".chart {"
        " background: var(--surface);"
        " border: 1px solid var(--border-soft);"
        " border-radius: 14px;"
        " padding: 8px 4px 4px;"
        " margin-bottom: 20px;"
        " overflow: hidden;"
        " transition: border-color 200ms ease;"
        "}"
        ".chart:hover { border-color: var(--border); }"
        "footer {"
        " margin-top: 80px; padding-top: 24px;"
        " border-top: 1px solid var(--border-soft);"
        " text-align: center; color: var(--text-muted); font-size: 12px;"
        "}"
        "footer a { color: var(--text-muted); text-decoration: underline; text-decoration-color: var(--border); }"
        "footer a:hover { color: var(--text); }"
        # Custom HTML charts (spec grid, series table)
        ".custom-chart { padding: 24px; }"
        ".custom-chart-head { margin-bottom: 20px; }"
        ".custom-chart-title {"
        " font-family: 'Inter', sans-serif; font-weight: 600; font-size: 15px;"
        " color: var(--text); margin-bottom: 4px;"
        "}"
        ".custom-chart-sub { color: var(--text-muted); font-size: 12px; }"
        # Spec grid
        ".spec-grid {"
        " display: grid; grid-template-columns: 1fr 1fr; gap: 16px;"
        "}"
        "@media (max-width: 760px) { .spec-grid { grid-template-columns: 1fr; } }"
        ".spec-card {"
        " background: var(--surface-2); border: 1px solid var(--border-soft);"
        " border-radius: 10px; padding: 16px 18px;"
        "}"
        ".spec-head {"
        " display: flex; align-items: center; gap: 10px; margin-bottom: 12px;"
        "}"
        ".spec-swatch { width: 8px; height: 22px; border-radius: 2px; }"
        ".spec-class {"
        " font-weight: 600; font-size: 14px; color: var(--text); flex: 1;"
        "}"
        ".spec-total {"
        " font-family: 'JetBrains Mono', monospace; font-variant-numeric: tabular-nums;"
        " font-size: 13px; color: var(--text-muted);"
        "}"
        ".spec-rows { display: flex; flex-direction: column; gap: 8px; }"
        ".spec-row {"
        " display: grid; grid-template-columns: 110px 1fr 36px;"
        " align-items: center; gap: 10px; font-size: 12.5px;"
        "}"
        ".spec-name { color: var(--text); }"
        ".spec-bar {"
        " height: 6px; background: rgba(255,255,255,0.04);"
        " border-radius: 3px; overflow: hidden;"
        "}"
        ".spec-fill { height: 100%; border-radius: 3px; opacity: 0.85; }"
        ".spec-count {"
        " font-family: 'JetBrains Mono', monospace; font-variant-numeric: tabular-nums;"
        " text-align: right; color: var(--text-muted); font-size: 12px;"
        "}"
        # Series table
        ".series-table { width: 100%; border-collapse: separate; border-spacing: 0; }"
        ".series-table th {"
        " text-align: left; padding: 10px 14px; font-size: 11px;"
        " text-transform: uppercase; letter-spacing: 0.12em; font-weight: 500;"
        " color: var(--text-muted); border-bottom: 1px solid var(--border-soft);"
        "}"
        ".series-table th.num { text-align: right; }"
        ".series-table td {"
        " padding: 12px 14px; border-bottom: 1px solid var(--border-soft);"
        " font-size: 13px; color: var(--text);"
        "}"
        ".series-table tr:last-child td { border-bottom: none; }"
        ".series-table tr:hover td { background: rgba(255,255,255,0.02); }"
        ".series-table .num {"
        " font-family: 'JetBrains Mono', monospace; font-variant-numeric: tabular-nums;"
        " text-align: right;"
        "}"
        ".series-table .num.strong { color: var(--gold); font-weight: 500; }"
        ".series-table .leader-cell { display: flex; align-items: center; gap: 10px; }"
        ".series-table .leader-dot {"
        " width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;"
        "}"
        ".series-table .leader-name { font-weight: 500; }"
        ".series-table .chip {"
        " display: inline-block; padding: 3px 9px; border-radius: 4px;"
        " background: rgba(255,255,255,0.05); color: var(--text-muted);"
        " font-size: 11px; letter-spacing: 0.04em;"
        "}"
        ".series-table .spark-cell { width: 1px; white-space: nowrap; }"
        ".series-table th.spark-cell, .series-table td.spark-cell { padding-right: 18px; }"
        # Class/role filter chips (spec distribution)
        ".cf-filters {"
        " display: flex; flex-direction: column; gap: 12px;"
        " margin-bottom: 20px; padding: 0 4px;"
        "}"
        ".cf-group { display: flex; align-items: flex-start; gap: 16px; }"
        ".cf-label {"
        " flex-shrink: 0; width: 50px; padding-top: 7px;"
        " font-size: 10px; text-transform: uppercase; letter-spacing: 0.14em;"
        " color: var(--text-muted); font-weight: 500;"
        "}"
        ".cf-row { display: flex; flex-wrap: wrap; gap: 6px; flex: 1; }"
        ".cf-chip {"
        " background: var(--surface-2); border: 1px solid var(--border-soft);"
        " border-radius: 999px; padding: 5px 12px;"
        " font-family: inherit; font-size: 12px; color: var(--text);"
        " cursor: pointer; transition: all 150ms ease;"
        " display: inline-flex; align-items: center; gap: 6px;"
        " line-height: 1.4;"
        "}"
        ".cf-chip:hover { border-color: var(--border); background: var(--surface); }"
        ".cf-chip.active {"
        " border-color: var(--gold);"
        " background: rgba(224, 165, 38, 0.12);"
        " color: var(--gold);"
        "}"
        ".cf-swatch {"
        " width: 8px; height: 8px; border-radius: 50%;"
        " background: var(--chip-color, var(--text-muted));"
        "}"
        ".cf-chip.active .cf-swatch {"
        " box-shadow: 0 0 0 2px rgba(224, 165, 38, 0.25);"
        "}"
        ".cf-reset {"
        " color: var(--text-muted); font-size: 11px;"
        " margin-left: 4px; padding: 5px 10px;"
        "}"
        ".cf-reset:hover { color: var(--text); }"
        "@media (prefers-reduced-motion: reduce) {"
        " *, *::before, *::after { transition: none !important; animation: none !important; }"
        "}"
    )

    head = (
        f"<!doctype html>"
        f"<html lang=\"en\"><head>"
        f"<meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>Low Pressure — Raid stats</title>"
        f"<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">"
        f"<link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>"
        f"<link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css2?"
        f"family=Cinzel:wght@500;600&"
        f"family=Inter:wght@400;500;600&"
        f"family=JetBrains+Mono:wght@500;600&display=swap\">"
        f"<style>{css}</style>"
        f"</head><body>"
        f"<div class=\"wrap\">"
        f"<header>"
        f"<h1>Low Pressure</h1>"
        f"<span class=\"underline\"></span>"
        f"<div class=\"sub\"><b>{len(events)}</b> raids · <b>{first_event}</b> to <b>{last_event}</b></div>"
        f"</header>"
        f"<div class=\"summary\">"
        f"<div class=\"stat primary\"><div class=\"row\"><div class=\"icon\">{ICON_SWORDS}</div>"
        f"<div><div class=\"label\">Events</div><div class=\"value\">{len(events)}</div></div></div></div>"
        f"<div class=\"stat\"><div class=\"row\"><div class=\"icon\">{ICON_USERS}</div>"
        f"<div><div class=\"label\">Attending signups</div><div class=\"value\">{total_signups}</div></div></div></div>"
        f"<div class=\"stat\"><div class=\"row\"><div class=\"icon\">{ICON_USER_CHECK}</div>"
        f"<div><div class=\"label\">Unique characters</div><div class=\"value\">{unique_chars}</div></div></div></div>"
        f"<div class=\"stat\"><div class=\"row\"><div class=\"icon\">{ICON_AWARD}</div>"
        f"<div><div class=\"label\">Unique players</div><div class=\"value\">{unique_players}</div></div></div></div>"
        f"</div>"
    )

    body_parts = []
    first_chart = True
    for section_id, title, subtitle, chart_fns in SECTIONS:
        body_parts.append(
            f"<section id=\"{section_id}\">"
            f"<div class=\"section-head\"><h2>{title}</h2><div class=\"section-sub\">{subtitle}</div></div>"
        )
        for fn in chart_fns:
            result = fn(events)
            if isinstance(result, str):
                # Custom HTML chart (spec grid, series table)
                body_parts.append(f"<div class=\"chart\">{result}</div>")
            else:
                include_js = "cdn" if first_chart else False
                first_chart = False
                body_parts.append(
                    f"<div class=\"chart\">{result.to_html(include_plotlyjs=include_js, full_html=False)}</div>"
                )
        body_parts.append("</section>")

    footer = (
        f"<footer>"
        f"Archived every 15 minutes from raid-helper.xyz · "
        f"Page generated {generated} · "
        f"<a href=\"/health\">status</a>"
        f"</footer>"
        f"</div></body></html>"
    )

    return head + "\n".join(body_parts) + footer


def render_html(events: list[Event]) -> None:
    OUTPUT.write_text(render_html_string(events))
    print(f"Wrote {OUTPUT}")


def main() -> None:
    events = load_events()
    print(f"Loaded {len(events)} events")
    render_html(events)


if __name__ == "__main__":
    main()
