from __future__ import annotations

"""
generate_site.py — Static site generator for BountyBoard.

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


def _score_color_class(score: int) -> str:
    """Returns CSS class for a priority score badge."""
    if score >= 75:
        return "score-critical"
    if score >= 55:
        return "score-high"
    if score >= 35:
        return "score-medium"
    return "score-low"


def _score_bar_class(score: int) -> str:
    """Returns CSS class for score bar fill color."""
    if score >= 75:
        return "fill-critical"
    if score >= 55:
        return "fill-high"
    if score >= 35:
        return "fill-medium"
    return "fill-low"


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


def _tier_class(tier: str) -> str:
    """Returns CSS class for a tier badge."""
    return {
        "Must-Do":       "tier-must",
        "Should-Do":     "tier-should",
        "May-Do":        "tier-may",
        "Needs-Review":  "tier-review",
        "Closed":        "tier-closed",
    }.get(tier, "tier-closed")


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

    tier_cls = _tier_class(tier)
    score_cls = _score_color_class(score)
    fill_cls = _score_bar_class(score)
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
    lines.append(f'    <div class="score-fill {fill_cls}" style="width:{score}%"></div>')
    lines.append(f'  </div>')

    lines.append(f'  <div class="card-header">')
    lines.append(f'    <span class="tier-badge {tier_cls}">{_esc(tier)}</span>')
    lines.append(f'    <span class="cat-badge">{category}</span>')
    lines.append(f'    <span class="score-badge {score_cls}">{score}</span>')
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
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BOUNTYBOARD</title>
<script>
// Apply saved theme before paint to prevent flash
(function(){{var t=localStorage.getItem('tb-theme');if(t)document.documentElement.setAttribute('data-theme',t);else if(matchMedia('(prefers-color-scheme:dark)').matches)document.documentElement.setAttribute('data-theme','dark')}})();
</script>
<style>
/* ── Theme variables ────────────────────────────────────── */
:root,[data-theme="light"]{{
  --bg:#fafafa;--bg-card:#fff;--bg-hero:#fff;--bg-input:#fff;
  --bg-pipeline:#f9fafb;--bg-track:#f9fafb;
  --border:#e5e7eb;--border-hover:#d1d5db;--border-track:#f3f4f6;
  --border-section:#f3f4f6;
  --text:#1a1a1a;--text-heading:#111;--text-secondary:#6b7280;
  --text-muted:#9ca3af;--text-faint:#d1d5db;
  --link:#2563eb;--link-hover:#1d4ed8;
  --accent:#2563eb;--accent-hover:#1d4ed8;
  --green:#059669;--green-hover:#047857;
  --score-bar-bg:#f3f4f6;
  --shadow:0 1px 3px rgba(0,0,0,0.04);--shadow-hover:0 2px 8px rgba(0,0,0,0.04);
  --filter-active-bg:#2563eb;--filter-active-text:#fff;
  --btn-details-bg:#eff6ff;--btn-details-text:#2563eb;--btn-details-border:#dbeafe;
  --btn-submit-bg:#ecfdf5;--btn-submit-text:#059669;--btn-submit-border:#d1fae5;
  /* Tier badges */
  --tier-must-text:#b91c1c;--tier-must-bg:#fef2f2;
  --tier-should-text:#92400e;--tier-should-bg:#fffbeb;
  --tier-may-text:#1e40af;--tier-may-bg:#eff6ff;
  --tier-review-text:#6b21a8;--tier-review-bg:#faf5ff;
  --tier-closed-text:#6b7280;--tier-closed-bg:#f3f4f6;
  /* Score badges */
  --score-critical-text:#b91c1c;--score-critical-bg:#fef2f2;
  --score-high-text:#92400e;--score-high-bg:#fffbeb;
  --score-medium-text:#1e40af;--score-medium-bg:#eff6ff;
  --score-low-text:#374151;--score-low-bg:#f3f4f6;
  /* Score bar fills */
  --fill-critical:#b91c1c;--fill-high:#92400e;--fill-medium:#1e40af;--fill-low:#6b7280;
  --urgent-color:#dc2626;--soon-color:#d97706;
}}

[data-theme="dark"]{{
  --bg:#0a0a0a;--bg-card:#141414;--bg-hero:#141414;--bg-input:#141414;
  --bg-pipeline:#111;--bg-track:#111;
  --border:#262626;--border-hover:#404040;--border-track:#1e1e1e;
  --border-section:#1e1e1e;
  --text:#e5e5e5;--text-heading:#f5f5f5;--text-secondary:#a3a3a3;
  --text-muted:#737373;--text-faint:#404040;
  --link:#60a5fa;--link-hover:#93bbfd;
  --accent:#3b82f6;--accent-hover:#60a5fa;
  --green:#34d399;--green-hover:#6ee7b7;
  --score-bar-bg:#1e1e1e;
  --shadow:0 1px 3px rgba(0,0,0,0.3);--shadow-hover:0 2px 8px rgba(0,0,0,0.3);
  --filter-active-bg:#1e3a5f;--filter-active-text:#60a5fa;
  --btn-details-bg:#172554;--btn-details-text:#60a5fa;--btn-details-border:#1e3a5f;
  --btn-submit-bg:#052e16;--btn-submit-text:#4ade80;--btn-submit-border:#14532d;
  /* Tier badges */
  --tier-must-text:#fca5a5;--tier-must-bg:rgba(239,68,68,0.15);
  --tier-should-text:#fcd34d;--tier-should-bg:rgba(234,179,8,0.12);
  --tier-may-text:#93c5fd;--tier-may-bg:rgba(59,130,246,0.15);
  --tier-review-text:#d8b4fe;--tier-review-bg:rgba(168,85,247,0.15);
  --tier-closed-text:#6b7280;--tier-closed-bg:rgba(107,114,128,0.15);
  /* Score badges */
  --score-critical-text:#fca5a5;--score-critical-bg:rgba(239,68,68,0.15);
  --score-high-text:#fcd34d;--score-high-bg:rgba(234,179,8,0.12);
  --score-medium-text:#93c5fd;--score-medium-bg:rgba(59,130,246,0.15);
  --score-low-text:#a3a3a3;--score-low-bg:rgba(107,114,128,0.15);
  /* Score bar fills */
  --fill-critical:#ef4444;--fill-high:#eab308;--fill-medium:#3b82f6;--fill-low:#6b7280;
  --urgent-color:#ef4444;--soon-color:#eab308;
}}

/* ── Base ───────────────────────────────────────────────── */
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--text);line-height:1.6;min-height:100vh;
  transition:background 0.2s,color 0.2s;
}}
a{{color:var(--link);text-decoration:none}}
a:hover{{color:var(--link-hover);text-decoration:underline}}

.container{{max-width:1100px;margin:0 auto;padding:2rem 1.25rem}}

/* Header */
header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:1.75rem}}
.header-left h1{{
  font-size:1.35rem;font-weight:800;letter-spacing:0.12em;
  color:var(--text-heading);margin-bottom:0.15rem;
}}
.header-left .updated{{font-size:0.75rem;color:var(--text-muted)}}

/* Theme toggle */
.theme-toggle{{
  background:var(--bg-card);border:1px solid var(--border);border-radius:8px;
  padding:0.4rem 0.5rem;cursor:pointer;font-size:1rem;line-height:1;
  transition:all 0.15s;display:flex;align-items:center;justify-content:center;
  width:36px;height:36px;
}}
.theme-toggle:hover{{border-color:var(--border-hover)}}
.theme-toggle .icon-sun,.theme-toggle .icon-moon{{display:none}}
[data-theme="light"] .theme-toggle .icon-moon{{display:block}}
[data-theme="dark"] .theme-toggle .icon-sun{{display:block}}

/* Stats strip */
.stats{{
  display:flex;gap:1.5rem;flex-wrap:wrap;
  margin-bottom:1.75rem;font-size:0.8rem;color:var(--text-secondary);
}}
.stats span{{white-space:nowrap}}
.stats .value{{color:var(--text-heading);font-weight:700}}
.stats .divider{{color:var(--text-faint)}}

/* Hero */
.hero{{
  background:var(--bg-hero);border:2px solid var(--border);border-radius:12px;
  padding:1.5rem 1.75rem;margin-bottom:2rem;
  box-shadow:var(--shadow);transition:background 0.2s,border-color 0.2s;
}}
.hero-label{{
  font-size:0.65rem;font-weight:700;letter-spacing:0.1em;
  color:var(--text-muted);text-transform:uppercase;margin-bottom:0.35rem;
}}
.hero-title{{font-size:1.2rem;font-weight:700;color:var(--text-heading);margin-bottom:0.5rem}}
.hero-stats{{display:flex;gap:1rem;flex-wrap:wrap;font-size:0.8rem;margin-bottom:0.5rem}}
.hero-urgency{{font-weight:700}}
.hero-prize{{color:var(--green);font-weight:600}}
.hero-fit,.hero-score{{color:var(--text-secondary)}}
.hero-angle{{
  font-size:0.8rem;color:var(--text-secondary);font-style:italic;
  margin-bottom:0.75rem;line-height:1.5;
}}
.hero-actions{{display:flex;gap:0.5rem;flex-wrap:wrap}}
.btn-hero{{
  padding:0.45rem 1rem;border-radius:7px;font-size:0.8rem;font-weight:600;
  display:inline-block;transition:all 0.15s;
}}
.btn-hero-details{{background:var(--accent);color:#fff}}
.btn-hero-details:hover{{background:var(--accent-hover);text-decoration:none}}
.btn-hero-submit{{background:var(--green);color:#fff}}
.btn-hero-submit:hover{{background:var(--green-hover);text-decoration:none}}

/* Controls */
.controls{{
  display:flex;gap:0.75rem;flex-wrap:wrap;align-items:center;
  justify-content:space-between;margin-bottom:1.25rem;
}}
.filters{{display:flex;gap:0.3rem;flex-wrap:wrap}}
.filter-btn{{
  padding:0.35rem 0.75rem;border-radius:7px;border:1px solid var(--border);
  background:var(--bg-card);color:var(--text-secondary);cursor:pointer;
  font-size:0.78rem;transition:all 0.15s;font-weight:500;
}}
.filter-btn:hover{{border-color:var(--border-hover);color:var(--text-heading)}}
.filter-btn.active{{
  background:var(--filter-active-bg);border-color:var(--filter-active-bg);
  color:var(--filter-active-text);
}}
.sort-select{{
  padding:0.35rem 0.5rem;border-radius:7px;border:1px solid var(--border);
  background:var(--bg-input);color:var(--text-secondary);font-size:0.78rem;cursor:pointer;
}}
.sort-select:focus{{outline:2px solid var(--accent);outline-offset:1px}}

/* Grid */
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:0.85rem}}

/* Cards */
.card{{
  background:var(--bg-card);border:1px solid var(--border);border-radius:10px;
  padding:1rem 1.15rem;transition:all 0.2s;position:relative;
  display:flex;flex-direction:column;
}}
.card:hover{{border-color:var(--border-hover);box-shadow:var(--shadow-hover)}}

.score-bar{{height:3px;background:var(--score-bar-bg);border-radius:2px;margin-bottom:0.65rem;overflow:hidden}}
.score-fill{{height:100%;border-radius:2px;transition:width 0.3s}}
.fill-critical{{background:var(--fill-critical)}}
.fill-high{{background:var(--fill-high)}}
.fill-medium{{background:var(--fill-medium)}}
.fill-low{{background:var(--fill-low)}}

.card-header{{display:flex;align-items:center;gap:0.4rem;flex-wrap:wrap;margin-bottom:0.4rem}}
.tier-badge{{
  font-size:0.65rem;font-weight:700;padding:0.12rem 0.45rem;border-radius:4px;
  text-transform:uppercase;letter-spacing:0.04em;
}}
.tier-must{{color:var(--tier-must-text);background:var(--tier-must-bg)}}
.tier-should{{color:var(--tier-should-text);background:var(--tier-should-bg)}}
.tier-may{{color:var(--tier-may-text);background:var(--tier-may-bg)}}
.tier-review{{color:var(--tier-review-text);background:var(--tier-review-bg)}}
.tier-closed{{color:var(--tier-closed-text);background:var(--tier-closed-bg)}}

.cat-badge{{
  font-size:0.6rem;color:var(--text-muted);border:1px solid var(--border);
  padding:0.08rem 0.35rem;border-radius:3px;text-transform:uppercase;letter-spacing:0.03em;
}}
.score-badge{{font-size:0.6rem;font-weight:700;padding:0.08rem 0.35rem;border-radius:3px}}
.score-critical{{color:var(--score-critical-text);background:var(--score-critical-bg)}}
.score-high{{color:var(--score-high-text);background:var(--score-high-bg)}}
.score-medium{{color:var(--score-medium-text);background:var(--score-medium-bg)}}
.score-low{{color:var(--score-low-text);background:var(--score-low-bg)}}

.countdown{{font-size:0.73rem;color:var(--text-muted);margin-left:auto;font-weight:500}}
.countdown.urgent{{color:var(--urgent-color);font-weight:700}}
.countdown.soon{{color:var(--soon-color);font-weight:600}}

.card-title{{font-size:0.9rem;font-weight:600;color:var(--text-heading);margin-bottom:0.35rem}}

.card-meta{{display:flex;gap:0.75rem;font-size:0.78rem;color:var(--text-secondary);margin-bottom:0.4rem}}
.prize{{color:var(--green);font-weight:600}}

.tracks{{display:flex;gap:0.25rem;flex-wrap:wrap;margin-bottom:0.5rem}}
.track-tag{{
  font-size:0.6rem;color:var(--text-muted);background:var(--bg-track);
  border:1px solid var(--border-track);padding:0.08rem 0.3rem;border-radius:3px;
}}

.card-actions{{display:flex;gap:0.4rem;margin-top:auto;padding-top:0.25rem}}
.btn{{
  padding:0.3rem 0.65rem;border-radius:6px;font-size:0.72rem;font-weight:500;
  transition:all 0.15s;display:inline-block;
}}
.btn-details{{background:var(--btn-details-bg);color:var(--btn-details-text);border:1px solid var(--btn-details-border)}}
.btn-details:hover{{opacity:0.85;text-decoration:none}}
.btn-submit{{background:var(--btn-submit-bg);color:var(--btn-submit-text);border:1px solid var(--btn-submit-border)}}
.btn-submit:hover{{opacity:0.85;text-decoration:none}}
.no-link{{font-size:0.68rem;color:var(--text-faint);font-style:italic}}

/* Past section */
.past-section{{margin-top:2.5rem;border-top:1px solid var(--border-section);padding-top:1rem}}
.past-toggle{{
  cursor:pointer;color:var(--text-muted);font-size:0.8rem;font-weight:500;
  padding:0.5rem 0;display:flex;align-items:center;gap:0.5rem;
  border:none;background:none;
}}
.past-toggle:hover{{color:var(--text-secondary)}}
.past-toggle .arrow{{transition:transform 0.2s;display:inline-block;font-size:0.7rem}}
.past-toggle.open .arrow{{transform:rotate(90deg)}}
.past-grid{{display:none}}
.past-grid.show{{
  display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));
  gap:0.85rem;margin-top:0.75rem;
}}
.past-grid .card{{opacity:0.45}}
.past-grid .card:hover{{opacity:0.7}}

/* Pipeline */
.pipeline{{
  margin-top:2rem;padding:1rem 1.25rem;background:var(--bg-pipeline);
  border:1px solid var(--border-section);border-radius:8px;
  font-size:0.72rem;color:var(--text-muted);
}}
.pipeline strong{{color:var(--text-secondary);font-weight:600}}

footer{{text-align:center;margin-top:2rem;padding:1rem 0;font-size:0.68rem;color:var(--text-faint)}}

@media(max-width:400px){{
  .grid,.past-grid.show{{grid-template-columns:1fr}}
  .stats{{flex-direction:column;gap:0.2rem}}
  .controls{{flex-direction:column}}
  .hero{{padding:1rem 1.15rem}}
  header{{flex-direction:column;align-items:flex-start;gap:0.5rem}}
}}
</style>
</head>
<body>
<div class="container">

<header>
  <div class="header-left">
    <h1>BOUNTYBOARD</h1>
    <div class="updated">Updated {updated}</div>
  </div>
  <button class="theme-toggle" id="themeToggle" title="Toggle theme">
    <span class="icon-sun">&#9728;&#65039;</span>
    <span class="icon-moon">&#9790;&#65039;</span>
  </button>
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

<footer>BOUNTYBOARD</footer>

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

// Theme toggle
document.getElementById('themeToggle').addEventListener('click', () => {{
  const html = document.documentElement;
  const current = html.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  localStorage.setItem('tb-theme', next);
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
