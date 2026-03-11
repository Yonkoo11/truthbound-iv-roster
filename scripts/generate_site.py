from __future__ import annotations

"""
generate_site.py — Static site generator for TRUTHBOUND IV Roster.

Reads from SQLite, generates docs/index.html with:
  - Dark theme, responsive card layout
  - Filter tabs (All, Hackathon, Grant, Accelerator, Bounty)
  - Sort by deadline/prize/theme fit
  - Tier badges (Must-Do, Should-Do, May-Do)
  - Only shows verified links (no broken/empty links)
  - Past entries collapsed by default

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


def _tier_color(tier: str) -> str:
    return {
        "Must-Do": "#ef4444",
        "Should-Do": "#eab308",
        "May-Do": "#3b82f6",
        "Needs-Review": "#a855f7",
    }.get(tier, "#6b7280")


def _tier_bg(tier: str) -> str:
    return {
        "Must-Do": "rgba(239,68,68,0.15)",
        "Should-Do": "rgba(234,179,8,0.15)",
        "May-Do": "rgba(59,130,246,0.15)",
        "Needs-Review": "rgba(168,85,247,0.15)",
    }.get(tier, "rgba(107,114,128,0.15)")


def _cat_label(cat: str) -> str:
    return cat.capitalize() if cat else "Other"


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def _build_card(opp: dict, tier: str) -> str:
    name = _esc(opp["name"])
    category = _esc(_cat_label(opp.get("category", "")))
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

    tier_color = _tier_color(tier)
    tier_bg = _tier_bg(tier)
    cat_data = _esc(opp.get("category", "all"))

    # Countdown urgency class
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
                 f'data-fit="{fit}">')
    lines.append(f'  <div class="card-header">')
    lines.append(f'    <span class="tier-badge" style="color:{tier_color};background:{tier_bg}">{_esc(tier)}</span>')
    lines.append(f'    <span class="cat-badge">{category}</span>')
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
        lines.append(f'    <span class="no-link">No links available</span>')
    lines.append(f'  </div>')
    lines.append(f'</div>')
    return "\n".join(lines)


def generate() -> str:
    """Generate the full HTML page."""
    today = date.today()
    opps = db.get_all()

    # Split into active and past
    active = []
    past = []
    for o in opps:
        tier = classify(o)
        if tier in ("Closed", "Expired") or o.get("status") in ("closed", "rejected"):
            past.append((o, tier))
        else:
            active.append((o, tier))

    # Sort active: Must-Do first, then by deadline
    tier_rank = {"Must-Do": 0, "Should-Do": 1, "May-Do": 2, "Needs-Review": 3}
    active.sort(key=lambda x: (
        tier_rank.get(x[1], 99),
        x[0].get("deadline") or "9999-12-31",
    ))
    past.sort(key=lambda x: x[0].get("deadline") or "0000", reverse=True)

    # Stats
    active_count = sum(1 for o, t in active if o.get("status") == "active")
    total_prize = sum((o.get("prize_usd") or 0) for o, t in active if o.get("status") == "active")
    prize_str = f"${total_prize // 1_000}K" if total_prize >= 1_000 else f"${total_prize}"

    # Next deadline
    next_dl = ""
    for o, t in active:
        dl = o.get("deadline")
        if dl:
            days = days_until(dl)
            if days >= 0:
                next_dl = f"{o['name']} in {days}d"
                break

    # Build cards
    active_cards = "\n".join(_build_card(o, t) for o, t in active)
    past_cards = "\n".join(_build_card(o, t) for o, t in past)

    updated = today.strftime("%b %d, %Y")

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
  background:#0a0a0a;color:#e5e5e5;line-height:1.5;
  min-height:100vh;
}}
a{{color:#60a5fa;text-decoration:none}}
a:hover{{text-decoration:underline}}

.container{{max-width:1100px;margin:0 auto;padding:1.5rem 1rem}}

header{{text-align:center;margin-bottom:2rem}}
header h1{{font-size:1.5rem;font-weight:700;letter-spacing:0.15em;color:#f5f5f5;margin-bottom:0.25rem}}
header .updated{{font-size:0.8rem;color:#737373}}

.stats{{
  display:flex;gap:1.5rem;justify-content:center;flex-wrap:wrap;
  margin-bottom:1.5rem;font-size:0.85rem;color:#a3a3a3;
}}
.stats span{{white-space:nowrap}}
.stats .value{{color:#e5e5e5;font-weight:600}}

.controls{{
  display:flex;gap:0.75rem;flex-wrap:wrap;align-items:center;
  justify-content:space-between;margin-bottom:1.5rem;
}}
.filters{{display:flex;gap:0.25rem;flex-wrap:wrap}}
.filter-btn{{
  padding:0.35rem 0.75rem;border-radius:6px;border:1px solid #262626;
  background:#171717;color:#a3a3a3;cursor:pointer;font-size:0.8rem;
  transition:all 0.15s;
}}
.filter-btn:hover{{border-color:#404040;color:#e5e5e5}}
.filter-btn.active{{background:#1e3a5f;border-color:#3b82f6;color:#60a5fa}}
.sort-select{{
  padding:0.35rem 0.5rem;border-radius:6px;border:1px solid #262626;
  background:#171717;color:#a3a3a3;font-size:0.8rem;cursor:pointer;
}}
.sort-select:focus{{outline:1px solid #3b82f6}}

.grid{{
  display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));
  gap:1rem;
}}

.card{{
  background:#171717;border:1px solid #262626;border-radius:10px;
  padding:1rem 1.15rem;transition:border-color 0.15s;
}}
.card:hover{{border-color:#404040}}
.card-header{{display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;margin-bottom:0.5rem}}
.tier-badge{{
  font-size:0.7rem;font-weight:700;padding:0.15rem 0.5rem;border-radius:4px;
  text-transform:uppercase;letter-spacing:0.05em;
}}
.cat-badge{{
  font-size:0.65rem;color:#737373;border:1px solid #333;padding:0.1rem 0.4rem;
  border-radius:3px;text-transform:uppercase;letter-spacing:0.04em;
}}
.countdown{{font-size:0.75rem;color:#a3a3a3;margin-left:auto}}
.countdown.urgent{{color:#ef4444;font-weight:700}}
.countdown.soon{{color:#eab308;font-weight:600}}

.card-title{{font-size:0.95rem;font-weight:600;color:#f5f5f5;margin-bottom:0.4rem}}

.card-meta{{display:flex;gap:0.75rem;font-size:0.8rem;color:#a3a3a3;margin-bottom:0.5rem}}
.prize{{color:#10b981;font-weight:600}}
.fit{{color:#a3a3a3}}

.tracks{{display:flex;gap:0.3rem;flex-wrap:wrap;margin-bottom:0.6rem}}
.track-tag{{
  font-size:0.65rem;color:#737373;background:#1a1a1a;border:1px solid #2a2a2a;
  padding:0.1rem 0.35rem;border-radius:3px;
}}

.card-actions{{display:flex;gap:0.5rem;margin-top:auto}}
.btn{{
  padding:0.3rem 0.7rem;border-radius:5px;font-size:0.75rem;font-weight:500;
  transition:all 0.15s;display:inline-block;
}}
.btn-details{{background:#1e3a5f;color:#60a5fa;border:1px solid #2563eb}}
.btn-details:hover{{background:#1e40af;text-decoration:none}}
.btn-submit{{background:#14532d;color:#4ade80;border:1px solid #16a34a}}
.btn-submit:hover{{background:#166534;text-decoration:none}}
.no-link{{font-size:0.7rem;color:#525252;font-style:italic}}

.past-section{{margin-top:2.5rem}}
.past-toggle{{
  cursor:pointer;color:#737373;font-size:0.85rem;
  padding:0.5rem 0;display:flex;align-items:center;gap:0.5rem;
  border:none;background:none;
}}
.past-toggle:hover{{color:#a3a3a3}}
.past-toggle .arrow{{transition:transform 0.2s;display:inline-block}}
.past-toggle.open .arrow{{transform:rotate(90deg)}}
.past-grid{{display:none}}
.past-grid.show{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:1rem;margin-top:0.75rem}}
.past-grid .card{{opacity:0.5}}
.past-grid .card:hover{{opacity:0.8}}

footer{{text-align:center;margin-top:3rem;padding:1rem 0;font-size:0.7rem;color:#525252}}

@media(max-width:400px){{
  .grid,.past-grid.show{{grid-template-columns:1fr}}
  .stats{{flex-direction:column;align-items:center;gap:0.25rem}}
  .controls{{flex-direction:column}}
}}
</style>
</head>
<body>
<div class="container">

<header>
  <h1>TRUTHBOUND ROSTER</h1>
  <div class="updated">Last updated: {updated}</div>
</header>

<div class="stats">
  <span><span class="value">{active_count}</span> active</span>
  <span><span class="value">{prize_str}</span> in scope</span>
  <span>Next: <span class="value">{_esc(next_dl) if next_dl else "none"}</span></span>
</div>

<div class="controls">
  <div class="filters">
    <button class="filter-btn active" data-filter="all">All</button>
    <button class="filter-btn" data-filter="hackathon">Hackathons</button>
    <button class="filter-btn" data-filter="grant">Grants</button>
    <button class="filter-btn" data-filter="accelerator">Accelerators</button>
    <button class="filter-btn" data-filter="bounty">Bounties</button>
  </div>
  <select class="sort-select" id="sort">
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
    <span class="arrow">&#9654;</span> Past &amp; Closed ({len(past)})
  </button>
  <div class="past-grid" id="pastGrid">
{past_cards}
  </div>
</div>

<footer>
  TRUTHBOUND IV &mdash; Hackathon &amp; Grant Tracker
</footer>

</div>

<script>
// Filtering
document.querySelectorAll('.filter-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const filter = btn.dataset.filter;
    document.querySelectorAll('#grid .card').forEach(card => {{
      if (filter === 'all' || card.dataset.category === filter) {{
        card.style.display = '';
      }} else {{
        card.style.display = 'none';
      }}
    }});
  }});
}});

// Sorting
document.getElementById('sort').addEventListener('change', (e) => {{
  const grid = document.getElementById('grid');
  const cards = Array.from(grid.querySelectorAll('.card'));
  const key = e.target.value;
  cards.sort((a, b) => {{
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
