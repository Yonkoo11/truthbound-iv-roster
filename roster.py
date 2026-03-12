#!/usr/bin/env python3
from __future__ import annotations

"""
BOUNTYBOARD — Opportunity Roster & Strategy Engine

Commands:
  python roster.py                  weekly focus report (default)
  python roster.py today            urgent items (next 7 days)
  python roster.py list             all active opportunities
  python roster.py list must        filter by tier: must / should / may
  python roster.py search <query>   full-text search
  python roster.py ideas            winning ideas for all Must-Do events
  python roster.py ideas <name>     winning ideas for a specific event
  python roster.py sprint           current sprint plan + build order
  python roster.py reuse            shared component matrix
  python roster.py judge <name>     judge profile for an event
  python roster.py review           triage auto-discovered opportunities
  python roster.py add              interactive add
  python roster.py add-url <url>    add from URL (auto-scrape)
  python roster.py edit <id>        edit an existing opportunity
  python roster.py done <id>        mark as submitted
  python roster.py approve <id>     approve a needs-review opportunity
  python roster.py reject <id>      reject a needs-review opportunity
  python roster.py outcome <id>     record win/loss result
  python roster.py stats            win rate analytics by source
  python roster.py bulk-reject      reject multiple needs-review items
  python roster.py export [csv|json] export all opportunities
  python roster.py undo [N]         undo last N field changes
  python roster.py health           system health status
  python roster.py help             show this help
"""

import json
import re
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path

import db
from db import fmt_day
from classify import classify, enrich, days_until, TIER_RANK, TIER_ICON
from config import REPO_DIR, IDEAS_FILE

SCRIPTS_DIR = REPO_DIR / "scripts"
TODAY       = date.today()

# ─── Rich dependency ──────────────────────────────────────────────────────────

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich import box as rbox
    console = Console()
except ImportError:
    print("ERROR: `rich` not installed. Run: pip3 install rich")
    sys.exit(1)


# ─── Data helpers ─────────────────────────────────────────────────────────────

def load_ideas() -> dict:
    if not IDEAS_FILE.exists():
        return {}
    with open(IDEAS_FILE) as f:
        return json.load(f)


def fmt_deadline(opp: dict) -> str:
    dl = opp.get("deadline")
    if not dl:
        return "rolling"
    try:
        d = datetime.strptime(dl, "%Y-%m-%d").date()
        return f"{d.strftime('%b')} {fmt_day(d)}"
    except ValueError:
        return "invalid"


def fmt_prize(opp: dict) -> str:
    p = opp.get("prize_usd", 0)
    if p >= 100_000:
        return f"${p // 1_000}k+"
    if p >= 1_000:
        return f"${p // 1_000}k"
    return (opp.get("prize_note") or "—")[:20]


# ─── Table renderer ───────────────────────────────────────────────────────────

def days_str(days: int) -> str:
    if days == 9999:
        return "[dim]rolling[/dim]"
    if days <= 3:
        return f"[bold red]{days}d[/bold red]"
    if days <= 7:
        return f"[red]{days}d[/red]"
    if days <= 14:
        return f"[yellow]{days}d[/yellow]"
    return f"[dim]{days}d[/dim]"


def print_table(items: list, title: str, style: str = "bold white") -> None:
    if not items:
        return
    t = Table(
        title=f"[{style}]{title}[/{style}]",
        box=rbox.ROUNDED,
        show_header=True,
        header_style="bold dim",
        expand=True,
    )
    t.add_column("Name",     min_width=28)
    t.add_column("Deadline", justify="center", min_width=10)
    t.add_column("Days",     justify="center", min_width=6)
    t.add_column("Prize",    justify="right",  min_width=9)
    t.add_column("Fit",      justify="center", min_width=5)
    t.add_column("Category", min_width=12)
    t.add_column("Angle",    min_width=38)

    for o in items:
        tier_style, icon = TIER_ICON.get(o["_tier"], ("white", "•"))
        angle = o.get("angle", "")[:55] + ("..." if len(o.get("angle", "")) > 55 else "")
        t.add_row(
            f"[{tier_style}]{icon} {o['name']}[/{tier_style}]",
            fmt_deadline(o),
            days_str(o["_days"]),
            fmt_prize(o),
            f"{o.get('theme_fit') or '?'}/10",
            o.get("category", ""),
            f"[dim]{angle}[/dim]",
        )
    console.print(t)
    console.print()


def _wrap(text: str, width: int) -> list[str]:
    if not text:
        return []
    words = text.split()
    lines, current = [], ""
    for word in words:
        if len(current) + len(word) + 1 <= width:
            current = (current + " " + word).strip()
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# ─── Weekly report ────────────────────────────────────────────────────────────

def cmd_weekly() -> None:
    ideas_db = load_ideas()
    data = enrich(db.get_all())

    active  = [o for o in data if o["_tier"] not in ("Closed", "Expired", "Won", "Submitted")]
    must    = sorted([o for o in active if o["_tier"] == "Must-Do"],    key=lambda x: x["_days"])
    should  = sorted([o for o in active if o["_tier"] == "Should-Do"],  key=lambda x: x["_days"])
    may     = [o for o in active if o["_tier"] == "May-Do"]
    review  = [o for o in active if o["_tier"] == "Needs-Review"]
    subs    = [o for o in data if o["_tier"] == "Submitted"]

    scope_prize = sum(o.get("prize_usd", 0) or 0 for o in must + should)

    # Current sprint phase — data-driven from ideas.json
    phases = ideas_db.get("strategic_sprint_plan", {}).get("phases", [])
    current_phase = None
    for phase in phases:
        start_str = phase.get("start_date")
        end_str   = phase.get("end_date")
        if start_str and end_str:
            try:
                start = datetime.strptime(start_str, "%Y-%m-%d").date()
                end   = datetime.strptime(end_str, "%Y-%m-%d").date()
                if start <= TODAY <= end:
                    current_phase = phase
                    break
            except ValueError:
                pass

    console.print()
    phase_str = (
        f"  Sprint: Phase {current_phase['phase']} — {current_phase['label']}"
        if current_phase else ""
    )
    console.print(Panel(
        f"[bold white]BOUNTYBOARD — Weekly Opportunity Roster[/bold white]\n"
        f"[dim]Week of {TODAY.strftime('%B')} {fmt_day(TODAY)}, {TODAY.year}   |   "
        f"Must-Do: {len(must)}   Should-Do: {len(should)}   May-Do: {len(may)}   "
        f"Prize pool in scope: ${scope_prize:,}[/dim]"
        + (f"\n[bold yellow]{phase_str}[/bold yellow]" if current_phase else ""),
        style="blue",
        expand=True,
    ))
    console.print()

    if must:
        print_table(must, f"MUST-DO ({len(must)}) — Act immediately", "bold red")
    else:
        console.print("[green]No Must-Do items right now.[/green]\n")

    if should:
        print_table(should, f"SHOULD-DO ({len(should)}) — Next 3 weeks", "yellow")

    if review:
        console.print(f"[magenta]Needs Review ({len(review)} items discovered by scout) — run `python roster.py review`[/magenta]\n")

    if may:
        console.print(f"[dim]May-Do ({len(may)} items): run `python roster.py list may`[/dim]\n")

    if subs:
        console.print("[green]Submitted: " + ", ".join(o["name"] for o in subs) + "[/green]\n")

    console.print("[dim]Run `python roster.py sprint` for build order  |  `python roster.py ideas` for winning ideas[/dim]")
    console.print()


# ─── Today's urgent items ─────────────────────────────────────────────────────

def cmd_today() -> None:
    data = enrich(db.get_all())
    urgent = sorted(
        [o for o in data if 0 <= o["_days"] <= 7 and o.get("status") == "active"],
        key=lambda x: x["_days"],
    )
    console.print()
    if not urgent:
        console.print(Panel("[green]Nothing due in the next 7 days.[/green]", style="green"))
        return
    console.print(Panel(f"[bold red]URGENT — {len(urgent)} items due within 7 days[/bold red]", style="red"))
    print_table(urgent, "DUE THIS WEEK", "bold red")


# ─── List all opportunities ───────────────────────────────────────────────────

def cmd_list(tier_filter: str | None) -> None:
    data = enrich(db.get_all())
    tier_map = {
        "must": "Must-Do", "should": "Should-Do", "may": "May-Do",
        "review": "Needs-Review", "submitted": "Submitted", "closed": "Closed", "won": "Won",
    }
    if tier_filter:
        tier_name = tier_map.get(tier_filter.lower(), tier_filter)
        items = [o for o in data if o["_tier"] == tier_name]
        title = tier_name.upper()
    else:
        items = [o for o in data if o["_tier"] not in ("Closed", "Expired")]
        title = "ALL ACTIVE OPPORTUNITIES"
    items.sort(key=lambda x: (TIER_RANK.get(x["_tier"], 9), x["_days"]))
    console.print()
    print_table(items, title)


# ─── Search ───────────────────────────────────────────────────────────────────

def cmd_search(query: str) -> None:
    results = enrich(db.search(query))
    console.print()
    if not results:
        console.print(f"[yellow]No results for '{query}'[/yellow]")
        return
    print_table(results, f"SEARCH: '{query}' ({len(results)} results)")


# ─── Winning ideas ────────────────────────────────────────────────────────────

def cmd_ideas(event_filter: str | None) -> None:
    ideas_db = load_ideas()
    events   = ideas_db.get("events", {})
    data     = enrich(db.get_all())

    if event_filter:
        matched = {k: v for k, v in events.items() if event_filter.lower() in k}
        if not matched:
            for o in data:
                if event_filter.lower() in o["name"].lower():
                    matched = {o["id"]: events.get(o["id"], {})}
                    break
        if not matched:
            console.print(f"[red]No ideas found for '{event_filter}'.[/red]")
            return
    else:
        must_ids = {o["id"] for o in data if o["_tier"] == "Must-Do"}
        matched  = {k: v for k, v in events.items() if k in must_ids}

    if not matched:
        console.print("[yellow]No ideas data for current Must-Do events.[/yellow]")
        return

    console.print()
    console.print(Panel(
        "[bold]BOUNTYBOARD — Winning Ideas & Judge Intelligence[/bold]\n"
        "[dim]Ideas ranked by: novelty + judge fit + build achievability[/dim]",
        style="blue",
    ))

    opp_map = {o["id"]: o for o in data}
    sorted_events = sorted(matched.items(), key=lambda x: opp_map.get(x[0], {}).get("_days", 9999))

    for event_id, event_data in sorted_events:
        opp = opp_map.get(event_id)
        if not opp:
            continue

        console.print(f"\n{'─'*80}")
        console.print(
            f"[bold white]{opp['name']}[/bold white]   "
            f"[dim]Deadline: {fmt_deadline(opp)} ({days_str(opp['_days'])})  "
            f"Prize: {fmt_prize(opp)}  Fit: {opp.get('theme_fit') or '?'}/10[/dim]"
        )

        judge_str = event_data.get("judge_profile", "")
        if judge_str:
            console.print("\n[bold yellow]Judge Profile:[/bold yellow]")
            for line in _wrap(judge_str, 76):
                console.print(f"  [dim]{line}[/dim]")

        tracks = event_data.get("underserved_tracks", [])
        if tracks:
            console.print("\n[bold green]Target these underserved tracks:[/bold green]")
            for t in tracks:
                console.print(f"  [green]→ {t}[/green]")

        avoid = event_data.get("generic_to_avoid", [])
        if avoid:
            console.print("\n[bold red]Avoid (every other team will submit these):[/bold red]")
            for a in avoid[:3]:
                console.print(f"  [red]✗ {a}[/red]")

        for idea in event_data.get("ideas", []):
            rec   = idea.get("recommended", False)
            risk  = idea.get("risk", "medium")
            mvp_h = idea.get("mvp_hours", "?")
            risk_color = {"low": "green", "medium": "yellow", "high": "red"}.get(risk, "white")
            star = "[bold yellow]★ RECOMMENDED[/bold yellow]  " if rec else ""

            console.print(f"\n  {'━'*70}")
            console.print(f"  {star}[bold cyan]{idea['title']}[/bold cyan]  "
                          f"[dim]Risk: [{risk_color}]{risk}[/{risk_color}]  MVP: ~{mvp_h}h[/dim]")
            console.print(f"  [bold italic]\"{idea.get('hook','')}\"[/bold italic]")
            console.print()
            for line in _wrap(idea.get("concept", ""), 70):
                console.print(f"  {line}")
            console.print()
            console.print("  [bold]Why judges won't see this from others:[/bold]")
            for line in _wrap(idea.get("why_different", ""), 70):
                console.print(f"  [green]{line}[/green]")
            demo = idea.get("demo_moment", "")
            if demo:
                console.print("\n  [bold]Demo moment:[/bold]")
                for line in _wrap(demo, 70):
                    console.print(f"  [yellow]{line}[/yellow]")
            tech = idea.get("core_tech", [])
            if tech:
                console.print(f"\n  [bold]Stack:[/bold] [dim]{' · '.join(tech)}[/dim]")

        insight = event_data.get("key_judge_insight", "")
        if insight:
            console.print("\n  [bold magenta]Key insight:[/bold magenta]")
            for line in _wrap(insight, 72):
                console.print(f"  [magenta]{line}[/magenta]")

    console.print(f"\n{'─'*80}\n")


# ─── Sprint planner ───────────────────────────────────────────────────────────

def cmd_sprint() -> None:
    ideas_db   = load_ideas()
    plan       = ideas_db.get("strategic_sprint_plan", {})
    phases     = plan.get("phases", [])
    components = ideas_db.get("shared_components", [])

    console.print()
    console.print(Panel(
        f"[bold]BOUNTYBOARD — Sprint Plan[/bold]\n"
        f"[dim]{plan.get('description', '')}[/dim]",
        style="blue",
    ))

    first = [c for c in components if c.get("build_first")]
    if first:
        console.print("\n[bold yellow]BUILD THESE FIRST — Shared components unlock all events:[/bold yellow]")
        for c in first:
            used = ", ".join(c.get("used_by", []))
            console.print(f"  [cyan]▸ {c['name']}[/cyan]  [dim]{c['hours_to_build']}h  →  {used}[/dim]")
            console.print(f"    [dim]{c['description'][:80]}[/dim]")
        total_h = sum(c["hours_to_build"] for c in first)
        console.print(f"\n  [bold]Total foundation:[/bold] ~{total_h}h\n")

    console.print("[bold]Sprint Phases:[/bold]\n")
    for phase in phases:
        p_num  = phase.get("phase", 0)
        label  = phase.get("label", "")
        goal   = phase.get("goal", "")
        tasks  = phase.get("tasks", [])
        hours  = phase.get("total_hours", 0)
        note   = phase.get("note", "")
        exit_c = phase.get("exit_criteria", "")

        # Data-driven current phase detection
        is_current = False
        start_str  = phase.get("start_date")
        end_str    = phase.get("end_date")
        if start_str and end_str:
            try:
                start = datetime.strptime(start_str, "%Y-%m-%d").date()
                end   = datetime.strptime(end_str, "%Y-%m-%d").date()
                is_current = start <= TODAY <= end
            except ValueError:
                pass

        style  = "bold green" if is_current else "dim"
        prefix = "◉ NOW" if is_current else "○"
        dates  = phase.get("dates", f"{start_str} – {end_str}" if start_str else "")

        console.print(f"[{style}]{prefix}  Phase {p_num}: {label}  [{dates}]  ~{hours}h[/{style}]")
        console.print(f"  [dim]Goal: {goal}[/dim]")
        for task in tasks:
            console.print(f"    [dim]• {task}[/dim]")
        if exit_c:
            console.print(f"  [cyan]Done when: {exit_c}[/cyan]")
        if note:
            console.print(f"  [yellow]⚡ {note}[/yellow]")
        console.print()

    console.print(Panel(
        f"[bold]Total estimated:[/bold] ~{plan.get('total_hours_estimate', '?')}h\n"
        f"[bold red]Critical path:[/bold red] {plan.get('critical_path', '')}",
        style="yellow",
    ))


# ─── Component reuse matrix ───────────────────────────────────────────────────

def cmd_reuse() -> None:
    ideas_db   = load_ideas()
    components = ideas_db.get("shared_components", [])
    all_event_ids = sorted({eid for c in components for eid in c.get("used_by", [])})

    console.print()
    t = Table(title="[bold]Component Reuse Matrix[/bold]", box=rbox.ROUNDED,
              show_header=True, header_style="bold dim")
    t.add_column("Component",  min_width=28, style="cyan")
    t.add_column("Build (h)",  justify="center", min_width=8)
    for eid in all_event_ids:
        t.add_column(eid.replace("-", " ").title()[:12], justify="center", min_width=8)

    for comp in components:
        used_by = set(comp.get("used_by", []))
        cells   = ["[green]✓[/green]" if eid in used_by else "[dim]·[/dim]" for eid in all_event_ids]
        t.add_row(comp["name"][:28], str(comp["hours_to_build"]), *cells)
    console.print(t)

    total = sum(c["hours_to_build"] for c in components)
    console.print(f"\n[dim]Building shared components saves ~{total}h of duplicated work.[/dim]\n")


# ─── Judge profile ────────────────────────────────────────────────────────────

def cmd_judge(event_filter: str) -> None:
    ideas_db = load_ideas()
    events   = ideas_db.get("events", {})
    data     = enrich(db.get_all())
    opp_map  = {o["id"]: o for o in data}

    matched = {k: v for k, v in events.items() if event_filter.lower() in k}
    if not matched:
        for o in data:
            if event_filter.lower() in o["name"].lower():
                matched = {o["id"]: events.get(o["id"], {})}
                break

    if not matched:
        console.print(f"[red]No judge data for '{event_filter}'[/red]")
        return

    for event_id, event_data in matched.items():
        opp = opp_map.get(event_id, {})
        console.print()
        console.print(Panel(f"[bold]Judge Intelligence: {opp.get('name', event_id)}[/bold]", style="blue"))

        for line in _wrap(event_data.get("judge_profile", "No data."), 76):
            console.print(f"  {line}")

        criteria = event_data.get("judging_criteria", {})
        if criteria:
            console.print("\n[bold]Judging criteria:[/bold]")
            for criterion, weight in sorted(criteria.items(), key=lambda x: -x[1]):
                bar = "█" * (weight // 5)
                console.print(f"  {criterion:<30} {bar} {weight}%")

        for t in event_data.get("underserved_tracks", []):
            console.print(f"  [green]→ {t}[/green]")
        for a in event_data.get("generic_to_avoid", []):
            console.print(f"  [red]✗ {a}[/red]")

        insight = event_data.get("key_judge_insight", "")
        if insight:
            console.print(f"\n[bold magenta]Key insight:[/bold magenta]")
            for line in _wrap(insight, 76):
                console.print(f"  [magenta]{line}[/magenta]")
        console.print()


# ─── Review auto-discovered ───────────────────────────────────────────────────

def cmd_review() -> None:
    to_review = [o for o in enrich(db.get_all(status="needs_review")) if True]
    if not to_review:
        console.print("[green]No new opportunities to review. Run `python scripts/scout.py` first.[/green]")
        return

    console.print()
    console.print(Panel(
        f"[bold]{len(to_review)} Auto-Discovered Opportunities to Review[/bold]\n"
        "[dim][a]ccept / [r]eject / [s]kip[/dim]",
        style="yellow",
    ))

    for o in to_review:
        console.print(f"\n[bold cyan]{o['name']}[/bold cyan]")
        console.print(f"  Score: [yellow]{o.get('theme_fit') or '?'}/10[/yellow]  "
                      f"Deadline: {fmt_deadline(o)}  Prize: {fmt_prize(o)}")
        if o.get("url"):
            console.print(f"  URL: [dim]{o['url']}[/dim]")
        if o.get("notes"):
            console.print(f"  [dim]{o['notes']}[/dim]")

        try:
            choice = input("  [a]ccept / [r]eject / [s]kip  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Review cancelled.[/yellow]")
            break

        if choice == "a":
            fit_input = input(f"  Theme fit 1-10 (current: {o.get('theme_fit', 5)}): ").strip()
            if fit_input.isdigit():
                db.update_field(o["id"], "theme_fit", int(fit_input))
            angle = input("  Angle (Enter to skip): ").strip()
            if angle:
                db.update_field(o["id"], "angle", angle)
            db.update_field(o["id"], "status", "active")
            db.update_field(o["id"], "calendar_synced", 0)
            console.print(f"  [green]Accepted.[/green]")
            _trigger_calendar_sync(o["id"])

        elif choice == "r":
            db.update_field(o["id"], "status", "rejected")
            console.print("  [dim]Rejected.[/dim]")
        else:
            console.print("  [dim]Skipped.[/dim]")

    console.print("\n[green]Review complete.[/green]")


# ─── Add new opportunity ──────────────────────────────────────────────────────

def cmd_add(extra_args: list | None = None) -> None:
    """Add an opportunity. Supports flags for quick-add:
    roster add "Name" --deadline 2026-04-15 --prize 50000 --fit 8 --cat hackathon
    Or run with no flags for interactive mode.
    """
    args = extra_args or []

    # Quick-add: first positional arg is the name, rest are flags
    name = None
    deadline = None
    prize = 0
    fit = None
    category = "hackathon"
    angle = ""
    notes = ""
    url = ""

    # Parse flags
    i = 0
    positionals = []
    while i < len(args):
        if args[i] == "--deadline" and i + 1 < len(args):
            deadline = args[i + 1]; i += 2
        elif args[i] == "--prize" and i + 1 < len(args):
            prize = int(args[i + 1]); i += 2
        elif args[i] == "--fit" and i + 1 < len(args):
            fit = int(args[i + 1]); i += 2
        elif args[i] == "--cat" and i + 1 < len(args):
            category = args[i + 1]; i += 2
        elif args[i] == "--angle" and i + 1 < len(args):
            angle = args[i + 1]; i += 2
        elif args[i] == "--url" and i + 1 < len(args):
            url = args[i + 1]; i += 2
        elif args[i] == "--notes" and i + 1 < len(args):
            notes = args[i + 1]; i += 2
        else:
            positionals.append(args[i]); i += 1

    if positionals:
        name = " ".join(positionals)

    # Fall back to interactive for missing required field
    if not name:
        console.print("\n[bold]Add New Opportunity[/bold]")
        name = input("  Name: ").strip()
        if not name:
            console.print("[red]Name is required.[/red]")
            return
        deadline = input("  Deadline YYYY-MM-DD (blank = rolling): ").strip() or None
        prize = int(input("  Prize USD (0 if none): ").strip() or "0")
        fit_raw = input("  Theme fit 1-10: ").strip()
        fit = int(fit_raw) if fit_raw.isdigit() else None
        category = input("  Category (hackathon/grant/accelerator/bounty): ").strip() or "hackathon"
        angle = input("  Angle: ").strip()
        notes = input("  Notes: ").strip()
        url = input("  URL: ").strip()

    opp_id = re.sub(r"[^a-z0-9]+", "-", name.lower())[:40].strip("-")
    # Ensure unique ID
    if db.get_by_id(opp_id):
        opp_id = f"{opp_id}-2"

    opp = {
        "id":            opp_id,
        "name":          name,
        "category":      category if category in ("hackathon", "grant", "accelerator", "bounty") else "hackathon",
        "deadline":      deadline,
        "prize_usd":     prize,
        "prize_note":    f"${prize:,}" if prize else "",
        "theme_fit":     fit,
        "status":        "active",
        "angle":         angle,
        "notes":         notes,
        "url":           url,
        "resubmittable": True,
        "calendar_synced": False,
        "source":        "manual",
    }

    try:
        db.upsert(opp)
    except ValueError as e:
        console.print(f"[red]Validation error: {e}[/red]")
        return

    console.print(f"\n[green]Added '{name}' → Tier: [bold]{classify(opp)}[/bold][/green]")
    _trigger_calendar_sync(opp_id)


# ─── Add from URL ─────────────────────────────────────────────────────────────

def cmd_add_url(url: str) -> None:
    console.print(f"\n[dim]Fetching {url}...[/dim]")
    scraped = _scrape_url(url)
    if scraped:
        console.print(f"  [green]Found:[/green] {scraped.get('name', '?')}")
        if scraped.get("deadline"):
            console.print(f"  Deadline: {scraped['deadline']}")
        if scraped.get("prize_usd"):
            console.print(f"  Prize: ${scraped['prize_usd']:,}")

    # Pre-fill with scraped values, user confirms/edits
    console.print("\n[bold]Confirm details (Enter to keep scraped value):[/bold]")
    name     = input(f"  Name [{scraped.get('name', '')}]: ").strip() or scraped.get("name", "")
    deadline = input(f"  Deadline [{scraped.get('deadline', 'rolling')}]: ").strip() or scraped.get("deadline")
    prize    = input(f"  Prize USD [{scraped.get('prize_usd', 0)}]: ").strip()
    prize    = int(prize) if prize.isdigit() else scraped.get("prize_usd", 0)
    fit_raw  = input("  Theme fit 1-10: ").strip()
    fit      = int(fit_raw) if fit_raw.isdigit() else None
    category = input("  Category (hackathon/grant/accelerator/bounty) [hackathon]: ").strip() or "hackathon"
    angle    = input("  BOUNTYBOARD angle: ").strip()

    if not name:
        console.print("[red]Name is required.[/red]")
        return

    opp_id = re.sub(r"[^a-z0-9]+", "-", name.lower())[:40].strip("-")
    if db.get_by_id(opp_id):
        opp_id = f"{opp_id}-2"

    opp = {
        "id":            opp_id,
        "name":          name,
        "category":      category if category in ("hackathon", "grant", "accelerator", "bounty") else "hackathon",
        "deadline":      deadline or None,
        "prize_usd":     prize,
        "prize_note":    f"${prize:,}" if prize else "",
        "theme_fit":     fit,
        "status":        "active",
        "angle":         angle,
        "url":           url,
        "resubmittable": True,
        "calendar_synced": False,
        "source":        "manual",
    }

    try:
        db.upsert(opp)
    except ValueError as e:
        console.print(f"[red]Validation error: {e}[/red]")
        return

    console.print(f"\n[green]Added '{name}' → Tier: [bold]{classify(opp)}[/bold][/green]")
    _trigger_calendar_sync(opp_id)


def _scrape_url(url: str) -> dict:
    """Best-effort scrape of title/deadline/prize from a hackathon URL."""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return {}
    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except Exception:
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    result: dict = {}

    # Title
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        result["name"] = str(og_title["content"]).strip()
    elif soup.title:
        result["name"] = soup.title.string.strip() if soup.title.string else ""

    # Prize — look for $ amounts in meta or body text
    text = soup.get_text(" ", strip=True)[:3000]
    prize_match = re.search(r"\$([\d,]+(?:\.\d+)?)[kK]?\s*(?:in\s+prizes?|prize|total)", text, re.IGNORECASE)
    if prize_match:
        raw = prize_match.group(1).replace(",", "")
        try:
            result["prize_usd"] = int(float(raw) * 1000) if "k" in prize_match.group(0).lower() else int(float(raw))
        except ValueError:
            pass

    # Deadline — look for ISO dates or "Month Day, Year"
    date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if date_match:
        result["deadline"] = date_match.group(1)
    else:
        month_match = re.search(
            r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+(\d{1,2}),?\s+(20\d{2})\b", text
        )
        if month_match:
            try:
                d = datetime.strptime(f"{month_match.group(1)} {month_match.group(2)} {month_match.group(3)}", "%B %d %Y")
                result["deadline"] = d.strftime("%Y-%m-%d")
            except ValueError:
                pass

    return result


# ─── Edit opportunity ─────────────────────────────────────────────────────────

def cmd_edit(opp_id: str) -> None:
    opp = db.get_by_id(opp_id)
    if not opp:
        # Try fuzzy match
        matches = [o for o in db.get_all() if opp_id.lower() in o["name"].lower()]
        if len(matches) == 1:
            opp = matches[0]
        elif len(matches) > 1:
            console.print(f"[yellow]Multiple matches for '{opp_id}':[/yellow]")
            for m in matches:
                console.print(f"  {m['id']} — {m['name']}")
            console.print("Use exact ID.")
            return
        else:
            console.print(f"[red]Not found: '{opp_id}'[/red]")
            return

    console.print(f"\n[bold]Editing: {opp['name']}[/bold]  [dim](Enter to keep current value)[/dim]\n")

    editable = [
        ("name",       "Name"),
        ("deadline",   "Deadline (YYYY-MM-DD)"),
        ("prize_usd",  "Prize USD"),
        ("theme_fit",  "Theme fit (1-10)"),
        ("category",   "Category"),
        ("angle",      "Angle"),
        ("notes",      "Notes"),
        ("url",        "URL"),
        ("status",     "Status"),
    ]

    changed = {}
    for field, label in editable:
        current = opp.get(field, "")
        new_val = input(f"  {label} [{current}]: ").strip()
        if new_val and new_val != str(current):
            # Type coerce
            if field in ("prize_usd", "theme_fit") and new_val.isdigit():
                changed[field] = int(new_val)
            elif field == "theme_fit":
                console.print(f"  [yellow]Skipped {field}: must be integer[/yellow]")
            else:
                changed[field] = new_val

    if not changed:
        console.print("[dim]No changes made.[/dim]")
        return

    for field, value in changed.items():
        db.update_field(opp["id"], field, value)

    console.print(f"\n[green]Updated {len(changed)} field(s): {', '.join(changed.keys())}[/green]")

    if "deadline" in changed and not opp.get("calendar_synced"):
        _trigger_calendar_sync(opp["id"])


# ─── Mark done ────────────────────────────────────────────────────────────────

def cmd_done(query: str) -> None:
    # Exact ID first
    opp = db.get_by_id(query)
    if not opp:
        # Fuzzy match
        matches = [o for o in db.get_all() if query.lower() in o["name"].lower()]
        if len(matches) == 0:
            console.print(f"[red]Not found: '{query}'. Run `python roster.py list` to see IDs.[/red]")
            return
        if len(matches) > 1:
            console.print(f"[yellow]Multiple matches for '{query}':[/yellow]")
            for m in matches:
                console.print(f"  {m['id']} — {m['name']}")
            console.print("Use exact ID: `python roster.py done <id>`")
            return
        opp = matches[0]

    project = input(f"  Project submitted for '{opp['name']}' (Enter to skip): ").strip()
    db.update_field(opp["id"], "status", "submitted")
    if project:
        db.update_field(opp["id"], "submitted_project", project)
    console.print(f"[green]Marked as submitted: {opp['name']}[/green]")


# ─── Record outcome ───────────────────────────────────────────────────────────

def cmd_outcome(query: str) -> None:
    opp = db.get_by_id(query)
    if not opp:
        matches = [o for o in db.get_all() if query.lower() in o["name"].lower()]
        if not matches:
            console.print(f"[red]Not found: '{query}'[/red]")
            return
        if len(matches) > 1:
            for m in matches:
                console.print(f"  {m['id']} — {m['name']}")
            return
        opp = matches[0]

    console.print(f"\n[bold]Recording outcome for: {opp['name']}[/bold]")
    outcome = input("  Outcome (won/runner_up/not_selected): ").strip().lower()
    if outcome not in ("won", "runner_up", "not_selected"):
        console.print("[red]Must be: won, runner_up, or not_selected[/red]")
        return

    db.update_field(opp["id"], "outcome", outcome)
    db.update_field(opp["id"], "status", "won" if outcome == "won" else "submitted")

    if outcome == "won":
        prize_input = input("  Prize won (USD, Enter to skip): ").strip()
        if prize_input.isdigit():
            db.update_field(opp["id"], "prize_won", int(prize_input))

    console.print(f"[green]Outcome recorded: {outcome}[/green]")


# ─── Calendar sync trigger ────────────────────────────────────────────────────

def _trigger_calendar_sync(opp_id: str | None = None) -> None:
    sync_script = SCRIPTS_DIR / "sync_calendar.py"
    if not sync_script.exists():
        return
    args = [sys.executable, str(sync_script)]
    if opp_id:
        args += ["--sync-id", opp_id]
    console.print("[dim]Syncing to Calendar...[/dim]")
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"[yellow]Calendar sync warning: {result.stderr.strip() or result.stdout.strip()}[/yellow]")


# ─── Stats ────────────────────────────────────────────────────────────────────

def cmd_stats() -> None:
    from rich.table import Table
    all_opps = db.get_all()
    if not all_opps:
        console.print("[yellow]No opportunities in DB.[/yellow]")
        return

    # Counts by status
    from collections import defaultdict
    by_source: dict[str, dict] = defaultdict(lambda: {"active": 0, "submitted": 0, "won": 0, "rejected": 0, "total": 0})
    prize_submitted = 0
    prize_won_total = 0
    theme_6plus = theme_8plus = theme_10 = 0

    for o in all_opps:
        src = o.get("source", "manual")
        s   = o.get("status", "")
        by_source[src]["total"] += 1
        if s in ("active", "needs_review", "closed"):
            by_source[src]["active"] += 1
        elif s == "submitted":
            by_source[src]["submitted"] += 1
            prize_submitted += o.get("prize_usd", 0) or 0
        elif s == "won":
            by_source[src]["won"] += 1
            prize_won_total += o.get("prize_won", 0) or 0
        elif s == "rejected":
            by_source[src]["rejected"] += 1
        tf = o.get("theme_fit") or 0
        if tf >= 6:  theme_6plus += 1
        if tf >= 8:  theme_8plus += 1
        if tf == 10: theme_10   += 1

    t = Table(title="Opportunity Stats by Source", show_lines=True)
    t.add_column("Source",    style="cyan")
    t.add_column("Total",     justify="right")
    t.add_column("Active",    justify="right")
    t.add_column("Submitted", justify="right")
    t.add_column("Won",       justify="right")
    t.add_column("Rejected",  justify="right")
    t.add_column("Win Rate",  justify="right")

    for src, c in sorted(by_source.items()):
        denom    = c["submitted"] + c["won"]
        win_rate = f"{c['won']/denom*100:.0f}%" if denom else "—"
        t.add_row(src, str(c["total"]), str(c["active"]), str(c["submitted"]),
                  str(c["won"]), str(c["rejected"]), win_rate)

    console.print(t)
    console.print(f"\n[bold]Theme fit:[/bold] {theme_6plus} at 6+, {theme_8plus} at 8+, {theme_10} at 10")
    if prize_submitted:
        console.print(f"[bold]Prize pool submitted:[/bold] ${prize_submitted:,}")
    if prize_won_total:
        console.print(f"[bold]Prize won total:[/bold] [green]${prize_won_total:,}[/green]")


# ─── Bulk Reject ──────────────────────────────────────────────────────────────

def cmd_bulk_reject() -> None:
    items = db.get_all(status="needs_review")
    if not items:
        console.print("[green]No items need review.[/green]")
        return

    from rich.table import Table
    t = Table(title="Needs Review", show_lines=False)
    t.add_column("#", style="dim", width=3)
    t.add_column("ID", style="cyan")
    t.add_column("Name")
    t.add_column("Score", justify="right")
    t.add_column("Source", style="dim")
    for i, o in enumerate(items, 1):
        t.add_row(str(i), o["id"], o["name"], str(o.get("theme_fit") or "—"), o.get("source", ""))
    console.print(t)

    raw = console.input("\n[bold]Enter IDs to reject (comma-separated, or Enter to skip):[/bold] ").strip()
    if not raw:
        console.print("[dim]Nothing rejected.[/dim]")
        return

    rejected = 0
    for part in raw.split(","):
        opp_id = part.strip()
        if not opp_id:
            continue
        opp = db.get_by_id(opp_id)
        if not opp:
            console.print(f"[red]Not found:[/red] {opp_id}")
            continue
        db.update_field(opp_id, "status", "rejected")
        console.print(f"[yellow]Rejected:[/yellow] {opp['name']}")
        rejected += 1
    console.print(f"\n[bold]{rejected}[/bold] item(s) rejected.")


# ─── Export ───────────────────────────────────────────────────────────────────

def cmd_export(fmt: str = "csv") -> None:
    import csv
    all_opps = db.get_all()
    if not all_opps:
        console.print("[yellow]No opportunities to export.[/yellow]")
        return

    REPO_DIR = Path(__file__).parent
    if fmt == "json":
        out = REPO_DIR / "data" / "export.json"
        out.write_text(json.dumps(all_opps, indent=2, default=str))
        console.print(f"[green]Exported {len(all_opps)} opportunities to[/green] {out}")
        return

    # CSV
    out = REPO_DIR / "data" / "export.csv"
    cols = ["id", "name", "category", "deadline", "prize_usd", "status", "theme_fit", "url", "source", "notes"]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_opps)
    console.print(f"[green]Exported {len(all_opps)} opportunities to[/green] {out}")


# ─── Undo ─────────────────────────────────────────────────────────────────────

def cmd_undo(n: int = 1) -> None:
    entries = db.get_audit_log(limit=50)
    field_changes = [e for e in entries if e.get("action") == "update_field"]
    if not field_changes:
        console.print("[yellow]No reversible changes in audit log.[/yellow]")
        return

    to_reverse = field_changes[:n]
    console.print(f"[bold]Reversing {len(to_reverse)} change(s):[/bold]")
    for e in to_reverse:
        opp  = db.get_by_id(e["id"])
        label = opp["name"] if opp else e["id"]
        console.print(f"  {label} · {e['field']}: [red]{e.get('new')}[/red] → [green]{e.get('old')}[/green]")

    confirm = console.input("\n[bold]Confirm undo? (y/N):[/bold] ").strip().lower()
    if confirm != "y":
        console.print("[dim]Cancelled.[/dim]")
        return

    for e in to_reverse:
        try:
            db.update_field(e["id"], e["field"], e.get("old"))
            console.print(f"[green]Restored[/green] {e['id']}.{e['field']} = {e.get('old')!r}")
        except Exception as exc:
            console.print(f"[red]Failed[/red] {e['id']}.{e['field']}: {exc}")


# ─── Health ───────────────────────────────────────────────────────────────────

def cmd_health() -> None:
    REPO_DIR = Path(__file__).parent

    lines: list[str] = []

    # DB counts
    counts = db.count()
    total  = sum(counts.values())
    lines.append(f"[bold]DB:[/bold] {total} total — " +
                 " / ".join(f"{s}: {n}" for s, n in sorted(counts.items())))

    # Launchd agents status
    agents = {
        "com.bountyboard.scout":    ("Scout",    "Sunday 9AM"),
        "com.bountyboard.calendar": ("Calendar", "Daily 8AM"),
        "com.bountyboard.morning":  ("Morning",  "Daily 6AM"),
    }
    for label, (name, schedule) in agents.items():
        result = subprocess.run(["launchctl", "list", label], capture_output=True, text=True)
        if result.returncode == 0:
            lines.append(f"[bold]{name}:[/bold] [green]loaded[/green] ({schedule})")
        else:
            lines.append(f"[bold]{name}:[/bold] [red]not loaded[/red] — launchctl load ~/Library/LaunchAgents/{label}.plist")

    # Last scout run (check log file)
    scout_log = REPO_DIR / "logs" / "scout_launchd.log"
    if scout_log.exists() and scout_log.stat().st_size > 0:
        mtime = datetime.fromtimestamp(scout_log.stat().st_mtime)
        ago = datetime.now() - mtime
        h = int(ago.total_seconds() // 3600)
        color = "green" if h < 24 else ("yellow" if h < 168 else "red")
        lines.append(f"[bold]Last scout:[/bold] [{color}]{mtime.strftime('%Y-%m-%d %H:%M')} ({h}h ago)[/{color}]")
    else:
        # Fallback: check old scout logs
        scout_logs = sorted(REPO_DIR.glob("logs/scout_*.log"), reverse=True)
        if scout_logs:
            latest = scout_logs[0]
            mtime = datetime.fromtimestamp(latest.stat().st_mtime)
            ago = datetime.now() - mtime
            h = int(ago.total_seconds() // 3600)
            color = "green" if h < 24 else ("yellow" if h < 168 else "red")
            lines.append(f"[bold]Last scout:[/bold] [{color}]{mtime.strftime('%Y-%m-%d %H:%M')} ({h}h ago)[/{color}]")
        else:
            lines.append("[bold]Last scout:[/bold] [dim]no logs found[/dim]")

    # Last calendar sync
    cal_sync_log = REPO_DIR / "logs" / "calendar_sync.jsonl"
    if cal_sync_log.exists():
        last_line = cal_sync_log.read_text().strip().splitlines()[-1:]
        if last_line:
            try:
                entry = json.loads(last_line[0])
                lines.append(f"[bold]Last calendar sync:[/bold] {entry.get('ts', 'unknown')[:19]}")
            except json.JSONDecodeError:
                lines.append("[bold]Last calendar sync:[/bold] [dim]log parse error[/dim]")
    else:
        lines.append("[bold]Last calendar sync:[/bold] [dim]no sync log[/dim]")

    # Backup age
    backups_dir = REPO_DIR / "data" / "backups"
    if backups_dir.exists():
        dated = sorted(backups_dir.glob("*.json"), reverse=True)
        if dated:
            latest = dated[0].stem  # YYYY-MM-DD
            try:
                backup_dt = datetime.strptime(latest, "%Y-%m-%d").date()
                days_ago  = (date.today() - backup_dt).days
                color = "green" if days_ago <= 1 else ("yellow" if days_ago <= 3 else "red")
                lines.append(f"[bold]Latest backup:[/bold] [{color}]{latest} ({days_ago}d ago)[/{color}]")
            except ValueError:
                lines.append(f"[bold]Latest backup:[/bold] {latest}")
        else:
            lines.append("[bold]Latest backup:[/bold] [yellow]no dated backups found[/yellow]")
    else:
        lines.append("[bold]Latest backup:[/bold] [dim]data/backups/ not created yet[/dim]")

    # Source health
    sh_file = REPO_DIR / "data" / ".source_health.json"
    if sh_file.exists():
        try:
            sh = json.loads(sh_file.read_text())
            lines.append("[bold]Source health (last run):[/bold]")
            for src, info in sorted(sh.items()):
                cnt   = info.get("count", "?")
                hist  = info.get("history", [])
                avg   = sum(hist) / len(hist) if hist else 0
                color = "green" if cnt and cnt > 0 else ("yellow" if avg < 5 else "red")
                lines.append(f"  [{color}]{src}: {cnt} results[/{color}] (avg {avg:.1f})")
        except Exception:
            lines.append("[bold]Source health:[/bold] [dim]parse error[/dim]")
    else:
        lines.append("[bold]Source health:[/bold] [dim].source_health.json not yet written[/dim]")

    # Needs review count
    review_count = counts.get("needs_review", 0)
    if review_count:
        lines.append(f"[bold]Needs review:[/bold] [yellow]{review_count} item(s)[/yellow] — run: python roster.py review")

    console.print(Panel("\n".join(lines), title="System Health", style="blue"))


# ─── Help ─────────────────────────────────────────────────────────────────────

def cmd_help() -> None:
    console.print(Panel(
        "[bold]BOUNTYBOARD Opportunity Roster[/bold]\n\n"
        "  [cyan]python roster.py[/cyan]                  Weekly report\n"
        "  [cyan]python roster.py today[/cyan]             Due this week\n"
        "  [cyan]python roster.py list[/cyan]              All active\n"
        "  [cyan]python roster.py list must[/cyan]         Must-Do tier\n"
        "  [cyan]python roster.py search <query>[/cyan]    Full-text search\n"
        "  [cyan]python roster.py ideas[/cyan]             Winning ideas (Must-Do events)\n"
        "  [cyan]python roster.py ideas chainlink[/cyan]   Ideas for specific event\n"
        "  [cyan]python roster.py sprint[/cyan]            Sprint plan + build order\n"
        "  [cyan]python roster.py reuse[/cyan]             Shared component matrix\n"
        "  [cyan]python roster.py judge <name>[/cyan]      Judge profile\n"
        "  [cyan]python roster.py review[/cyan]            Triage auto-discovered\n"
        "  [cyan]python roster.py approve <id>[/cyan]      Approve needs_review item\n"
        "  [cyan]python roster.py reject <id>[/cyan]       Reject needs_review item\n"
        "  [cyan]python roster.py add[/cyan]               Add manually\n"
        "  [cyan]python roster.py add-url <url>[/cyan]     Add from URL (auto-scrape)\n"
        "  [cyan]python roster.py edit <id>[/cyan]         Edit existing\n"
        "  [cyan]python roster.py done <id>[/cyan]         Mark as submitted\n"
        "  [cyan]python roster.py outcome <id>[/cyan]      Record win/loss\n"
        "  [cyan]python roster.py stats[/cyan]             Win rate analytics\n"
        "  [cyan]python roster.py bulk-reject[/cyan]       Reject multiple needs-review\n"
        "  [cyan]python roster.py export[/cyan]            Export to CSV\n"
        "  [cyan]python roster.py undo[/cyan]              Undo last change\n"
        "  [cyan]python roster.py health[/cyan]            System health status\n"
        "\n[bold]Scout & Calendar:[/bold]\n"
        "  [cyan]python scripts/scout.py[/cyan]              Find new opportunities\n"
        "  [cyan]python scripts/sync_calendar.py[/cyan]      Sync deadlines to Calendar\n"
        "  [cyan]bash scripts/setup_cron.sh[/cyan]           Set up weekly auto-scout\n"
        "  [cyan]python scripts/notify.py info[/cyan]        Test notifications\n"
        "  [cyan]streamlit run streamlit_app.py[/cyan]       Web dashboard",
        title="Commands",
        style="blue",
    ))


# ─── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    cmd  = args[0].lower() if args else "today"

    match cmd:
        case "weekly" | "":
            cmd_weekly()
        case "today":
            cmd_today()
        case "list":
            cmd_list(args[1] if len(args) > 1 else None)
        case "search":
            if len(args) < 2:
                console.print("[red]Usage: python roster.py search <query>[/red]")
            else:
                cmd_search(" ".join(args[1:]))
        case "ideas":
            cmd_ideas(args[1] if len(args) > 1 else None)
        case "sprint":
            cmd_sprint()
        case "reuse":
            cmd_reuse()
        case "judge":
            if len(args) < 2:
                console.print("[red]Usage: python roster.py judge <event-name>[/red]")
            else:
                cmd_judge(" ".join(args[1:]))
        case "review":
            cmd_review()
        case "add":
            cmd_add(args[1:])
        case "add-url":
            if len(args) < 2:
                console.print("[red]Usage: python roster.py add-url <url>[/red]")
            else:
                cmd_add_url(args[1])
        case "edit":
            if len(args) < 2:
                console.print("[red]Usage: python roster.py edit <id>[/red]")
            else:
                cmd_edit(args[1])
        case "done":
            if len(args) < 2:
                console.print("[red]Usage: python roster.py done <name-or-id>[/red]")
            else:
                cmd_done(" ".join(args[1:]))
        case "outcome":
            if len(args) < 2:
                console.print("[red]Usage: python roster.py outcome <id>[/red]")
            else:
                cmd_outcome(args[1])
        case "approve":
            if len(args) < 2:
                console.print("[red]Usage: python roster.py approve <id>[/red]")
            else:
                opp = db.get_by_id(args[1])
                if not opp:
                    console.print(f"[red]Not found: {args[1]}[/red]")
                else:
                    db.update_field(args[1], "status", "active")
                    console.print(f"[green]Approved:[/green] {opp['name']} → active")
        case "reject":
            if len(args) < 2:
                console.print("[red]Usage: python roster.py reject <id>[/red]")
            else:
                opp = db.get_by_id(args[1])
                if not opp:
                    console.print(f"[red]Not found: {args[1]}[/red]")
                else:
                    db.update_field(args[1], "status", "rejected")
                    console.print(f"[yellow]Rejected:[/yellow] {opp['name']}")
        case "stats":
            cmd_stats()
        case "bulk-reject":
            cmd_bulk_reject()
        case "export":
            cmd_export(args[1] if len(args) > 1 else "csv")
        case "undo":
            n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
            cmd_undo(n)
        case "health":
            cmd_health()
        case "help" | "--help" | "-h":
            cmd_help()
        case _:
            console.print(f"[red]Unknown command: {cmd}[/red]")
            cmd_help()


if __name__ == "__main__":
    main()
