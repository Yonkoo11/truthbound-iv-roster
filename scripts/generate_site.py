from __future__ import annotations

"""
generate_site.py — Static site generator for TRUTHBOUND IV Roster.

Reads from SQLite, generates docs/index.html with:
  - Clean light theme, responsive card layout
  - "Next Move" hero highlighting #1 priority
  - Composite priority score (deadline urgency + prize + theme fit)
  - Filter tabs + sort by priority/deadline/prize/fit
  - Only shows verified links
  - Past entries collapsed by default
  - Pipeline status bar

Usage:
    python scripts/generate_site.py           # generate docs/index.html
    python scripts/generate_site.py --dry-run # print HTML to stdout
"""

import html
import json
import sys
from datetime import date, datetime
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_DIR))

import db
from classify import classify, days_until

DOCS_DIR = REPO_DIR / "docs"


# ── Priority scoring ─────────────────────────────────────────────────────────

def priority_score(opp: dict) -> int:
    """Composite priority score (0-100). Higher = act sooner.

    Weights:
      - Deadline urgency:  0-40 pts (closer = higher)
      - Prize value:       0-25 pts (more = higher)
      - Theme fit:         0-25 pts (higher = higher)
      - Category bonus:    0-10 pts (accelerator/hackathon > grant > bounty)
    """
    score = 0

    # Deadline urgency (40 pts max)
    days = days_until(opp.get("deadline"))
    if days <= 0:
        score += 40
    elif days <= 3:
        score += 38
    elif days <= 7:
        score += 32
    elif days <= 14:
        score += 24
    elif days <= 21:
        score += 18
    elif days <= 30:
        score += 12
    elif days <= 60:
        score += 6
    elif days < 9999:
        score += 2
    # Rolling (9999) gets 0 urgency

    # Prize (25 pts max)
    prize = opp.get("prize_usd", 0) or 0
    if prize >= 200_000:
        score += 25
    elif prize >= 100_000:
        score += 22
    elif prize >= 50_000:
        score += 18
    elif prize >= 30_000:
        score += 14
    elif prize >= 10_000:
        score += 10
    elif prize >= 5_000:
        score += 6
    elif prize > 0:
        score += 3

    # Theme fit (25 pts max)
    fit = opp.get("theme_fit", 0) or 0
    score += min(int(fit * 2.5), 25)

    # Category bonus (10 pts max)
    cat = opp.get("category", "")
    cat_bonus = {"accelerator": 10, "hackathon": 8, "grant": 5, "bounty": 3}
    score += cat_bonus.get(cat, 0)

    return min(score, 100)


def _score_label(score: int) -> str:
    if score >= 75:
        return "Critical"
    if score >= 55:
        return "High"
    if score >= 35:
        return "Medium"
    return "Low"


def _score_color(score: int) -> tuple[str, str]:
    """Returns (text_color, bg_color) for a priority score."""
    if score >= 75:
        return "#b91c1c", "#fef2f2"
    if score >= 55:
        return "#92400e", "#fffbeb"
    if score >= 35:
        return "#1e40af", "#eff6ff"
    return "#374151", "#f3f4f6"


# ── Formatting helpers ────────────────────────────────────────────────────────

def _fmt_prize(opp: dict) -> str:
    p = opp.get("prize_usd", 0) or 0
    if p >= 1_000_000:
        return f"${p / 1_000_000:.1f}M"
    if p >= 1_000:
        return f"${p // 1_000}K"
    if p > 0:
        return f"${p}"
    note = opp.get("prize_note", "") or ""
    if note and len(note) <= 30:
        return note
    return ""


def _countdown(opp: dict) -> str:
    dl = opp.get("deadline")
    if not dl:
        return "Rolling"
    days = days_until(dl)
    if days < 0:
        return "Ended"
    if days == 0:
        return "TODAY"
    if days == 1:
        return "1 day left"
    if days <= 7:
        return f"{days}d left"
    try:
        return datetime.strptime(dl, "%Y-%m-%d").strftime("%b %d")
    except ValueError:
        return dl


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def _tier_colors(tier: str) -> tuple[str, str]:
    """Returns (text_color, bg_color) for light theme."""
    return {
        "Must-Do":       ("#b91c1c", "#fef2f2"),
        "Should-Do":     ("#92400e", "#fffbeb"),
        "May-Do":        ("#1e40af", "#eff6ff"),
        "Needs-Review":  ("#6b21a8", "#faf5ff"),
        "Closed":        ("#6b7280", "#f3f4f6"),
    }.get(tier, ("#6b7280", "#f3f4f6"))


def _build_card(opp: dict, tier: str, score: int) -> str:
    name = _esc(opp["name"])
    category = _esc((opp.get("category") or "other").capitalize())
    prize = _esc(_fmt_prize(opp))
    countdown = _esc(_countdown(opp))
    fit = opp.get("theme_fit", 0) or 0
    url = opp.get("url", "")
    sub_url = opp.get("submission_url", "")
    tracks = opp.get("tracks", [])
    if isinstance(tracks, str):
        try:
            tracks = json.loads(tracks)
        except (json.JSONDecodeError, TypeError):
            tracks = []

    tier_fg, tier_bg = _tier_colors(tier)
    score_fg, score_bg = _score_color(score)
    cat_data = _esc(opp.get("category", "all"))

    days = days_until(opp.get("deadline"))
    countdown_class = ""
    if 0 <= days <= 3:
        countdown_class = "urgent"
    elif 4 <= days <= 7:
        countdown_class = "soon"

    lines = []
    lines.append(f'<div class="card" data-category="{cat_data}" data-tier="{_esc(tier)}" '
                 f'data-deadline="{_esc(opp.get("deadline") or "9999-12-31")}" '
                 f'data-prize="{opp.get("prize_usd", 0) or 0}" '
                 f'data-fit="{fit}" data-score="{score}">')

    # Score bar
    lines.append(f'  <div class="score-bar">')
    lines.append(f'    <div class="score-fill" style="width:{score}%;background:{score_fg}"></div>')
    lines.append(f'  </div>')

    lines.append(f'  <div class="card-header">')
    lines.append(f'    <span class="tier-badge" style="color:{tier_fg};background:{tier_bg}">{_esc(tier)}</span>')
    lines.append(f'    <span class="cat-badge">{category}</span>')
    lines.append(f'    <span class="score-badge" style="color:{score_fg};background:{score_bg}">{score}</span>')
    if countdown:
        lines.append(f'    <span class="countdown {countdown_class}">{countdown}</span>')
    lines.append(f'  </div>')

    lines.append(f'  <h3 class="card-title">{name}</h3>')

    lines.append(f'  <div class="card-meta">')
    if prize:
        lines.append(f'    <span class="prize">{prize}</span>')
    if fit:
        lines.append(f'    <span class="fit">fit {fit}/10</span>')
    lines.append(f'  </div>')

    if tracks:
        lines.append(f'  <div class="tracks">')
        for t in tracks[:5]:
            lines.append(f'    <span class="track-tag">{_esc(str(t))}</span>')
        lines.append(f'  </div>')

    lines.append(f'  <div class="card-actions">')
    if url:
        lines.append(f'    <a href="{_esc(url)}" target="_blank" rel="noopener" class="btn btn-details">Details</a>')
    if sub_url:
        lines.append(f'    <a href="{_esc(sub_url)}" target="_blank" rel="noopener" class="btn btn-submit">Submit</a>')
    if not url and not sub_url:
        lines.append(f'    <span class="no-link">No links yet</span>')
    lines.append(f'  </div>')
    lines.append(f'</div>')
    return "\n".join(lines)


def _build_hero(opp: dict, tier: str, score: int) -> str:
    """Build the Next Move hero section."""
    name = _esc(opp["name"])
    prize = _esc(_fmt_prize(opp))
    countdown = _esc(_countdown(opp))
    fit = opp.get("theme_fit", 0) or 0
    url = opp.get("url", "")
    sub_url = opp.get("submission_url", "")
    angle = _esc((opp.get("angle") or "")[:120])

    days = days_until(opp.get("deadline"))
    if days <= 3:
        urgency = "Act now"
        urgency_color = "#dc2626"
    elif days <= 7:
        urgency = "This week"
        urgency_color = "#d97706"
    else:
        urgency = f"{days} days"
        urgency_color = "#2563eb"

    hero = f"""<div class="hero">
  <div class="hero-label">YOUR NEXT MOVE</div>
  <h2 class="hero-title">{name}</h2>
  <div class="hero-stats">
    <span class="hero-urgency" style="color:{urgency_color}">{urgency}</span>"""
    if prize:
        hero += f'\n    <span class="hero-prize">{prize}</span>'
    hero += f"""
    <span class="hero-fit">fit {fit}/10</span>
    <span class="hero-score">priority {score}/100</span>
  </div>"""
    if angle:
        hero += f'\n  <p class="hero-angle">"{angle}"</p>'
    hero += '\n  <div class="hero-actions">'
    if url:
        hero += f'\n    <a href="{_esc(url)}" target="_blank" rel="noopener" class="btn-hero btn-hero-details">View Details</a>'
    if sub_url:
        hero += f'\n    <a href="{_esc(sub_url)}" target="_blank" rel="noopener" class="btn-hero btn-hero-submit">Go to Submission</a>'
    hero += '\n  </div>\n</div>'
    return hero


def generate() -> str:
    """Generate the full HTML page."""
    today = date.today()
    opps = db.get_all()

    # Score and classify
    scored = []
    past_list = []
    for o in opps:
        tier = classify(o)
        score = priority_score(o)
        if tier in ("Closed", "Expired") or o.get("status") in ("closed", "rejected"):
            past_list.append((o, tier, score))
        else:
            scored.append((o, tier, score))

    # Sort by priority score descending
    scored.sort(key=lambda x: -x[2])
    past_list.sort(key=lambda x: x[0].get("deadline") or "0000", reverse=True)

    # Stats
    active_count = sum(1 for o, t, s in scored if o.get("status") == "active")
    submitted_count = sum(1 for o, t, s in scored if o.get("status") == "submitted")
    total_prize = sum((o.get("prize_usd") or 0) for o, t, s in scored if o.get("status") == "active")
    prize_str = f"${total_prize // 1_000}K" if total_prize >= 1_000 else f"${total_prize}"
    won_count = sum(1 for o in opps if o.get("status") == "won")
    review_count = sum(1 for o, t, s in scored if o.get("status") == "needs_review")

    # Next deadline
    next_dl_name = ""
    next_dl_days = 0
    for o, t, s in scored:
        dl = o.get("deadline")
        if dl:
            d = days_until(dl)
            if d >= 0:
                next_dl_name = o["name"]
                next_dl_days = d
                break

    # Hero: top priority active item
    hero_html = ""
    for o, t, s in scored:
        if o.get("status") == "active" and (o.get("url") or o.get("submission_url")):
            hero_html = _build_hero(o, t, s)
            break

    # Build cards
    active_cards = "\n".join(_build_card(o, t, s) for o, t, s in scored)
    past_cards = "\n".join(_build_card(o, t, s) for o, t, s in past_list)

    updated = today.strftime("%b %d, %Y")

    # Automation status
    sources = ["ETHGlobal", "Devpost", "DoraHacks"]
    sources_str = ", ".join(sources)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TRUTHBOUND ROSTER</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:#fafafa;color:#1a1a1a;line-height:1.6;
  min-height:100vh;
}}
a{{color:#2563eb;text-decoration:none}}
a:hover{{text-decoration:underline}}

.container{{max-width:1100px;margin:0 auto;padding:2rem 1.25rem}}

/* Header */
header{{margin-bottom:1.75rem}}
header h1{{
  font-size:1.35rem;font-weight:800;letter-spacing:0.12em;
  color:#111;margin-bottom:0.15rem;
}}
header .updated{{font-size:0.75rem;color:#9ca3af}}

/* Stats strip */
.stats{{
  display:flex;gap:1.5rem;flex-wrap:wrap;
  margin-bottom:1.75rem;font-size:0.8rem;color:#6b7280;
}}
.stats span{{white-space:nowrap}}
.stats .value{{color:#111;font-weight:700}}
.stats .divider{{color:#d1d5db}}

/* Hero: Next Move */
.hero{{
  background:#fff;border:2px solid #e5e7eb;border-radius:12px;
  padding:1.5rem 1.75rem;margin-bottom:2rem;position:relative;
  box-shadow:0 1px 3px rgba(0,0,0,0.04);
}}
.hero-label{{
  font-size:0.65rem;font-weight:700;letter-spacing:0.1em;
  color:#9ca3af;text-transform:uppercase;margin-bottom:0.35rem;
}}
.hero-title{{font-size:1.2rem;font-weight:700;color:#111;margin-bottom:0.5rem}}
.hero-stats{{display:flex;gap:1rem;flex-wrap:wrap;font-size:0.8rem;margin-bottom:0.5rem}}
.hero-urgency{{font-weight:700}}
.hero-prize{{color:#059669;font-weight:600}}
.hero-fit,.hero-score{{color:#6b7280}}
.hero-angle{{
  font-size:0.8rem;color:#6b7280;font-style:italic;
  margin-bottom:0.75rem;line-height:1.5;
}}
.hero-actions{{display:flex;gap:0.5rem;flex-wrap:wrap}}
.btn-hero{{
  padding:0.45rem 1rem;border-radius:7px;font-size:0.8rem;font-weight:600;
  display:inline-block;transition:all 0.15s;
}}
.btn-hero-details{{background:#2563eb;color:#fff}}
.btn-hero-details:hover{{background:#1d4ed8;text-decoration:none}}
.btn-hero-submit{{background:#059669;color:#fff}}
.btn-hero-submit:hover{{background:#047857;text-decoration:none}}

/* Controls */
.controls{{
  display:flex;gap:0.75rem;flex-wrap:wrap;align-items:center;
  justify-content:space-between;margin-bottom:1.25rem;
}}
.filters{{display:flex;gap:0.3rem;flex-wrap:wrap}}
.filter-btn{{
  padding:0.35rem 0.75rem;border-radius:7px;border:1px solid #e5e7eb;
  background:#fff;color:#6b7280;cursor:pointer;font-size:0.78rem;
  transition:all 0.15s;font-weight:500;
}}
.filter-btn:hover{{border-color:#d1d5db;color:#111}}
.filter-btn.active{{background:#2563eb;border-color:#2563eb;color:#fff}}
.sort-select{{
  padding:0.35rem 0.5rem;border-radius:7px;border:1px solid #e5e7eb;
  background:#fff;color:#6b7280;font-size:0.78rem;cursor:pointer;
}}
.sort-select:focus{{outline:2px solid #2563eb;outline-offset:1px}}

/* Grid */
.grid{{
  display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));
  gap:0.85rem;
}}

/* Cards */
.card{{
  background:#fff;border:1px solid #e5e7eb;border-radius:10px;
  padding:1rem 1.15rem;transition:all 0.15s;position:relative;
  display:flex;flex-direction:column;
}}
.card:hover{{border-color:#d1d5db;box-shadow:0 2px 8px rgba(0,0,0,0.04)}}

.score-bar{{
  height:3px;background:#f3f4f6;border-radius:2px;margin-bottom:0.65rem;
  overflow:hidden;
}}
.score-fill{{height:100%;border-radius:2px;transition:width 0.3s}}

.card-header{{display:flex;align-items:center;gap:0.4rem;flex-wrap:wrap;margin-bottom:0.4rem}}
.tier-badge{{
  font-size:0.65rem;font-weight:700;padding:0.12rem 0.45rem;border-radius:4px;
  text-transform:uppercase;letter-spacing:0.04em;
}}
.cat-badge{{
  font-size:0.6rem;color:#9ca3af;border:1px solid #e5e7eb;padding:0.08rem 0.35rem;
  border-radius:3px;text-transform:uppercase;letter-spacing:0.03em;
}}
.score-badge{{
  font-size:0.6rem;font-weight:700;padding:0.08rem 0.35rem;border-radius:3px;
}}
.countdown{{font-size:0.73rem;color:#9ca3af;margin-left:auto;font-weight:500}}
.countdown.urgent{{color:#dc2626;font-weight:700}}
.countdown.soon{{color:#d97706;font-weight:600}}

.card-title{{font-size:0.9rem;font-weight:600;color:#111;margin-bottom:0.35rem}}

.card-meta{{display:flex;gap:0.75rem;font-size:0.78rem;color:#6b7280;margin-bottom:0.4rem}}
.prize{{color:#059669;font-weight:600}}

.tracks{{display:flex;gap:0.25rem;flex-wrap:wrap;margin-bottom:0.5rem}}
.track-tag{{
  font-size:0.6rem;color:#9ca3af;background:#f9fafb;border:1px solid #f3f4f6;
  padding:0.08rem 0.3rem;border-radius:3px;
}}

.card-actions{{display:flex;gap:0.4rem;margin-top:auto;padding-top:0.25rem}}
.btn{{
  padding:0.3rem 0.65rem;border-radius:6px;font-size:0.72rem;font-weight:500;
  transition:all 0.15s;display:inline-block;
}}
.btn-details{{background:#eff6ff;color:#2563eb;border:1px solid #dbeafe}}
.btn-details:hover{{background:#dbeafe;text-decoration:none}}
.btn-submit{{background:#ecfdf5;color:#059669;border:1px solid #d1fae5}}
.btn-submit:hover{{background:#d1fae5;text-decoration:none}}
.no-link{{font-size:0.68rem;color:#d1d5db;font-style:italic}}

/* Past section */
.past-section{{margin-top:2.5rem;border-top:1px solid #f3f4f6;padding-top:1rem}}
.past-toggle{{
  cursor:pointer;color:#9ca3af;font-size:0.8rem;font-weight:500;
  padding:0.5rem 0;display:flex;align-items:center;gap:0.5rem;
  border:none;background:none;
}}
.past-toggle:hover{{color:#6b7280}}
.past-toggle .arrow{{transition:transform 0.2s;display:inline-block;font-size:0.7rem}}
.past-toggle.open .arrow{{transform:rotate(90deg)}}
.past-grid{{display:none}}
.past-grid.show{{
  display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));
  gap:0.85rem;margin-top:0.75rem;
}}
.past-grid .card{{opacity:0.45}}
.past-grid .card:hover{{opacity:0.7}}

/* Pipeline status */
.pipeline{{
  margin-top:2rem;padding:1rem 1.25rem;background:#f9fafb;
  border:1px solid #f3f4f6;border-radius:8px;font-size:0.72rem;color:#9ca3af;
}}
.pipeline strong{{color:#6b7280;font-weight:600}}
.pipeline .sources{{color:#6b7280}}

footer{{text-align:center;margin-top:2rem;padding:1rem 0;font-size:0.68rem;color:#d1d5db}}

@media(max-width:400px){{
  .grid,.past-grid.show{{grid-template-columns:1fr}}
  .stats{{flex-direction:column;gap:0.2rem}}
  .controls{{flex-direction:column}}
  .hero{{padding:1rem 1.15rem}}
}}
</style>
</head>
<body>
<div class="container">

<header>
  <h1>TRUTHBOUND ROSTER</h1>
  <div class="updated">Updated {updated}</div>
</header>

<div class="stats">
  <span><span class="value">{active_count}</span> active</span>
  <span class="divider">|</span>
  <span><span class="value">{prize_str}</span> in scope</span>
  <span class="divider">|</span>
  <span><span class="value">{submitted_count}</span> submitted</span>
  <span class="divider">|</span>
  <span><span class="value">{won_count}</span> won</span>
  {"<span class='divider'>|</span><span><span class='value'>" + str(review_count) + "</span> to review</span>" if review_count else ""}
</div>

{hero_html}

<div class="controls">
  <div class="filters">
    <button class="filter-btn active" data-filter="all">All</button>
    <button class="filter-btn" data-filter="hackathon">Hackathons</button>
    <button class="filter-btn" data-filter="grant">Grants</button>
    <button class="filter-btn" data-filter="accelerator">Accelerators</button>
    <button class="filter-btn" data-filter="bounty">Bounties</button>
  </div>
  <select class="sort-select" id="sort">
    <option value="score">Sort: Priority</option>
    <option value="deadline">Sort: Deadline</option>
    <option value="prize">Sort: Prize</option>
    <option value="fit">Sort: Theme Fit</option>
  </select>
</div>

<div class="grid" id="grid">
{active_cards}
</div>

<div class="past-section">
  <button class="past-toggle" id="pastToggle">
    <span class="arrow">&#9654;</span> Past &amp; Closed ({len(past_list)})
  </button>
  <div class="past-grid" id="pastGrid">
{past_cards}
  </div>
</div>

<div class="pipeline">
  <strong>Auto-scanning:</strong>
  <span class="sources">{sources_str}</span> every Sunday 9AM.
  Expired entries auto-closed. Site regenerated and pushed on each scan.
</div>

<footer>TRUTHBOUND IV</footer>

</div>

<script>
// Filtering
document.querySelectorAll('.filter-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const filter = btn.dataset.filter;
    document.querySelectorAll('#grid .card').forEach(card => {{
      card.style.display = (filter === 'all' || card.dataset.category === filter) ? '' : 'none';
    }});
  }});
}});

// Sorting
document.getElementById('sort').addEventListener('change', (e) => {{
  const grid = document.getElementById('grid');
  const cards = Array.from(grid.querySelectorAll('.card'));
  const key = e.target.value;
  cards.sort((a, b) => {{
    if (key === 'score') return parseInt(b.dataset.score) - parseInt(a.dataset.score);
    if (key === 'deadline') return a.dataset.deadline.localeCompare(b.dataset.deadline);
    if (key === 'prize') return parseInt(b.dataset.prize) - parseInt(a.dataset.prize);
    if (key === 'fit') return parseInt(b.dataset.fit) - parseInt(a.dataset.fit);
    return 0;
  }});
  cards.forEach(c => grid.appendChild(c));
}});

// Past toggle
document.getElementById('pastToggle').addEventListener('click', function() {{
  this.classList.toggle('open');
  document.getElementById('pastGrid').classList.toggle('show');
}});
</script>
</body>
</html>"""


def main() -> None:
    page = generate()
    if "--dry-run" in sys.argv:
        print(page)
        return
    DOCS_DIR.mkdir(exist_ok=True)
    out = DOCS_DIR / "index.html"
    out.write_text(page)
    print(f"Generated {out} ({len(page)} bytes)")


if __name__ == "__main__":
    main()
