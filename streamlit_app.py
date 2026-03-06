"""
TRUTHBOUND IV — Opportunity Dashboard
Run: streamlit run streamlit_app.py
"""

from datetime import date, datetime
from pathlib import Path

import streamlit as st
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).parent))
import db

IDEAS_FILE = Path(__file__).parent / "data" / "ideas.json"
TODAY      = date.today()

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TRUTHBOUND IV Roster",
    page_icon="🔱",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  .stExpander { border: 1px solid #333 !important; border-radius: 6px; margin: 4px 0; }
  .tag-must   { background:#2d0000; border-left:4px solid #ff4444; padding:6px 12px; border-radius:4px; display:inline-block; }
  .tag-should { background:#2d2200; border-left:4px solid #ffaa00; padding:6px 12px; border-radius:4px; display:inline-block; }
  .idea-card  { background:#111827; border:1px solid #374151; border-radius:8px; padding:16px; margin:8px 0; }
  .rec-badge  { background:#7c3aed; color:white; border-radius:4px; padding:2px 8px; font-size:0.75rem; font-weight:700; }
</style>
""", unsafe_allow_html=True)


# ─── Data helpers ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_data():
    return db.get_all()

@st.cache_data(ttl=30)
def load_ideas():
    if not IDEAS_FILE.exists():
        return {}
    import json
    with open(IDEAS_FILE) as f:
        return json.load(f)

def days_until(deadline_str):
    if not deadline_str:
        return 9999
    try:
        return (datetime.strptime(deadline_str, "%Y-%m-%d").date() - TODAY).days
    except ValueError:
        return 9999

def classify(opp):
    status = opp.get("status", "active")
    if status in ("closed", "submitted", "won", "needs_review", "rejected"):
        return status.replace("_", " ").title()
    days  = days_until(opp.get("deadline"))
    if days < 0:
        return "Expired"
    prize = opp.get("prize_usd", 0) or 0
    fit   = opp.get("theme_fit", 0) or 0
    cat   = opp.get("category", "")
    if days <= 7:
        return "Must-Do"
    if prize >= 50_000 and fit >= 7:
        return "Must-Do"
    if cat == "accelerator" and fit >= 7:
        return "Must-Do"
    if days <= 21 and (prize >= 20_000 or fit >= 5):
        return "Should-Do"
    return "May-Do"

def fmt_prize(o):
    p = o.get("prize_usd", 0) or 0
    note = o.get("prize_note", "") or ""
    if p >= 100_000: return f"${p // 1_000}k+"
    if p >= 1_000:   return f"${p // 1_000}k"
    return note[:25] if note else "—"

def fmt_dl(o):
    dl = o.get("deadline")
    if not dl:
        return "rolling"
    try:
        d = datetime.strptime(dl, "%Y-%m-%d").date()
        return f"{d.strftime('%b')} {db.fmt_day(d)}"
    except ValueError:
        return dl


# ─── Load & enrich ─────────────────────────────────────────────────────────────

raw   = load_data()
ideas = load_ideas()

for o in raw:
    o["tier"]         = classify(o)
    o["days_until"]   = days_until(o.get("deadline"))
    o["prize_fmt"]    = fmt_prize(o)
    o["deadline_fmt"] = fmt_dl(o)

df       = pd.DataFrame(raw) if raw else pd.DataFrame()
INACTIVE = {"Closed", "Expired", "Submitted", "Won", "Needs Review", "Rejected"}
active   = df[~df["tier"].isin(INACTIVE)] if not df.empty else df
must_df  = active[active["tier"] == "Must-Do"] if not active.empty else active
shd_df   = active[active["tier"] == "Should-Do"] if not active.empty else active
review_df = (
    df[df["tier"] == "Needs Review"] if not df.empty else df
)


# ─── Header ────────────────────────────────────────────────────────────────────

st.title("🔱 TRUTHBOUND IV — Opportunity Roster")
today_fmt = TODAY.strftime("%B ") + db.fmt_day(TODAY) + TODAY.strftime(", %Y")
st.caption(f"Today: {today_fmt} — SENTINEL / AI Truth Layer / Privacy")
st.divider()


# ─── Metrics ───────────────────────────────────────────────────────────────────

scope_prize = int(active[active["tier"].isin(["Must-Do", "Should-Do"])]["prize_usd"].sum()) if not active.empty else 0
near = must_df.sort_values("days_until") if not must_df.empty else must_df

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("🔴 Must-Do",   len(must_df),  help="Act immediately")
c2.metric("🟡 Should-Do", len(shd_df),   help="Next 3 weeks")
c3.metric("🔵 May-Do",    len(active[active["tier"] == "May-Do"]) if not active.empty else 0)
c4.metric("🔍 Needs Review", len(review_df), help="Scout-discovered, needs triage")
c5.metric("💰 Prize Scope", f"${scope_prize:,}")

if not near.empty:
    first = near.iloc[0]
    c6.metric("⏰ Next Deadline", first["deadline_fmt"],
              delta=f"{first['days_until']}d", delta_color="inverse")
else:
    c6.metric("⏰ Next Deadline", "—")

st.divider()


# ─── Main tabs ──────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🔴 Must-Do", "🟡 Should-Do", "💡 Winning Ideas",
    "📅 Sprint Plan", "📋 All Active", "🔍 Needs Review",
])


# ─── Shared card renderer ─────────────────────────────────────────────────────

def render_opp_cards(tier_df):
    if tier_df.empty:
        st.info("Nothing here right now.")
        return
    for _, row in tier_df.sort_values("days_until").iterrows():
        days   = row["days_until"]
        days_s = f"{days}d" if days != 9999 else "rolling"
        urg    = "🚨 " if days <= 3 else ("⚡ " if days <= 7 else "📅 ")
        label  = f"{urg}**{row['name']}** — {row['deadline_fmt']} ({days_s}) — {row['prize_fmt']} — fit {row.get('theme_fit', '?')}/10"
        with st.expander(label):
            c1, c2 = st.columns([2, 1])
            with c1:
                st.markdown(f"**Angle:**\n\n{row.get('angle', '—') or '—'}")
                if row.get("notes"):
                    st.markdown(f"**Notes:**\n\n{row['notes']}")
                if row.get("url"):
                    st.markdown(f"[Open →]({row['url']})")
            with c2:
                st.markdown(f"**Category:** {row.get('category','—')}")
                st.markdown(f"**Theme fit:** {row.get('theme_fit','—')}/10")
                st.markdown(f"**Prize:** {row.get('prize_note', '') or row['prize_fmt']}")
                tracks = row.get("tracks", [])
                if isinstance(tracks, list) and tracks:
                    st.markdown("**Tracks:** " + ", ".join(tracks))


with tab1:
    render_opp_cards(must_df)

with tab2:
    render_opp_cards(shd_df)


# ─── Winning Ideas tab ─────────────────────────────────────────────────────────

with tab3:
    st.subheader("💡 Winning Ideas — Differentiated, Research-Backed")
    st.caption("Ideas that won't be suggested to the 50 other teams by generic AI prompts.")

    events_data = ideas.get("events", {})
    opp_map     = {o["id"]: o for o in raw}

    sorted_events = sorted(
        [(k, v) for k, v in events_data.items() if k in opp_map],
        key=lambda x: opp_map[x[0]].get("days_until", 9999)
    )

    for event_id, event_data in sorted_events:
        opp  = opp_map.get(event_id, {})
        tier = opp.get("tier", "")
        if tier in ("Closed", "Expired"):
            continue

        days   = opp.get("days_until", 9999)
        days_s = f"{days}d" if days != 9999 else "rolling"
        tier_icon = {"Must-Do": "🔴", "Should-Do": "🟡", "May-Do": "🔵"}.get(tier, "•")

        with st.expander(
            f"{tier_icon} **{opp.get('name', event_id)}** — {opp.get('deadline_fmt','rolling')} ({days_s}) — {opp.get('prize_fmt','—')} — fit {opp.get('theme_fit','?')}/10"
        ):
            judge_str = event_data.get("judge_profile", "")
            if judge_str:
                st.markdown("**🎯 Judge Profile (research-verified):**")
                st.info(judge_str)

            criteria = event_data.get("judging_criteria", {})
            if criteria:
                st.markdown("**Judging weights:**")
                cols = st.columns(len(criteria))
                for i, (k, v) in enumerate(sorted(criteria.items(), key=lambda x: -x[1])):
                    cols[i].metric(k.replace("_", " ").title()[:20], f"{v}%")

            tracks = event_data.get("underserved_tracks", [])
            if tracks:
                st.markdown("**✅ Target these underserved tracks:**")
                for t in tracks:
                    st.success(f"→ {t}")

            avoid = event_data.get("generic_to_avoid", [])
            if avoid:
                st.markdown("**❌ Avoid (generic, saturated):**")
                for a in avoid:
                    st.error(f"✗ {a}")

            event_ideas = event_data.get("ideas", [])
            for idea in event_ideas:
                rec   = idea.get("recommended", False)
                risk  = idea.get("risk", "medium")
                hours = idea.get("mvp_hours", "?")
                risk_color  = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(risk, "⚪")
                border_color = "#7c3aed" if rec else "#374151"
                rec_badge = '<span class="rec-badge">★ RECOMMENDED</span>' if rec else ""

                st.markdown(f"""
<div class="idea-card" style="border-color:{border_color}">
  {rec_badge}
  <h4 style="margin-top:4px">{idea['title']}</h4>
  <em>"{idea.get('hook','')}"</em>
  <p style="margin-top:8px">{idea.get('concept','')}</p>
  <p><strong>Why judges won't see this from others:</strong><br>{idea.get('why_different','')}</p>
  <p><strong>Demo moment:</strong> {idea.get('demo_moment','')}</p>
  <p><strong>Stack:</strong> {' · '.join(idea.get('core_tech',[]))}</p>
  <p>{risk_color} Risk: {risk} &nbsp;|&nbsp; ⏱ MVP: ~{hours}h</p>
</div>
""", unsafe_allow_html=True)

            insight = event_data.get("key_judge_insight", "")
            if insight:
                st.markdown(f"**💡 Key judge insight:** {insight}")

    st.divider()
    st.subheader("🔧 Shared Components — Build Once, Reuse Everywhere")
    comps = ideas.get("shared_components", [])
    if comps:
        comp_df = pd.DataFrame([{
            "Component": c["name"],
            "Hours":     c["hours_to_build"],
            "Used By":   ", ".join(c.get("used_by", [])),
            "Build First": "✅" if c.get("build_first") else "—",
            "Stack":     ", ".join(c.get("stack", [])[:2]),
        } for c in comps])
        st.dataframe(comp_df, use_container_width=True, hide_index=True)
        total_h = sum(c["hours_to_build"] for c in comps if c.get("build_first"))
        st.caption(f"Foundation build (build-first components): ~{total_h}h total. Unlocks 5+ events.")


# ─── Sprint Plan tab ──────────────────────────────────────────────────────────

with tab4:
    st.subheader("📅 Sprint Plan — Build Order for Maximum Wins")

    plan   = ideas.get("strategic_sprint_plan", {})
    phases = plan.get("phases", [])

    st.info(f"**Total estimated:** ~{plan.get('total_hours_estimate','?')}h across 18 days  |  "
            f"**Critical path:** {plan.get('critical_path','')}")

    for phase in phases:
        p      = phase.get("phase", 0)
        lbl    = phase.get("label", "")
        dates  = phase.get("dates", "")
        goal   = phase.get("goal", "")
        tasks  = phase.get("tasks", [])
        hours  = phase.get("total_hours", 0)
        note   = phase.get("note", "")
        exit_  = phase.get("exit_criteria", "")

        # Data-driven current phase detection
        try:
            phase_start = datetime.strptime(phase["start_date"], "%Y-%m-%d").date()
            phase_end   = datetime.strptime(phase["end_date"],   "%Y-%m-%d").date()
            is_current  = phase_start <= TODAY <= phase_end
        except (KeyError, ValueError):
            is_current  = False

        prefix = "◉ **NOW →** " if is_current else "○ "

        with st.expander(f"{prefix}Phase {p}: {lbl}  [{dates}]  ~{hours}h", expanded=is_current):
            st.markdown(f"**Goal:** {goal}")
            if note:
                st.warning(f"⚡ {note}")
            for task in tasks:
                st.markdown(f"- {task}")
            if exit_:
                st.success(f"**Done when:** {exit_}")


# ─── All Active tab ────────────────────────────────────────────────────────────

with tab5:
    search_q = st.text_input("🔍 Search", placeholder="name, notes, angle...", key="search_all")

    if search_q and not active.empty:
        q = search_q.lower()
        mask = (
            active["name"].str.lower().str.contains(q, na=False) |
            active.get("notes", pd.Series(dtype=str)).str.lower().str.contains(q, na=False) |
            active.get("angle", pd.Series(dtype=str)).str.lower().str.contains(q, na=False)
        )
        display_df = active[mask]
    else:
        display_df = active

    if display_df.empty:
        st.info("No results." if search_q else "No active opportunities.")
    else:
        cols = ["name", "tier", "deadline_fmt", "days_until", "prize_fmt", "theme_fit", "category", "resubmittable"]
        avail_cols = [c for c in cols if c in display_df.columns]
        tbl = display_df[avail_cols].copy()
        tbl.columns = ["Name", "Tier", "Deadline", "Days", "Prize", "Fit", "Category", "Resubmit"][:len(avail_cols)]
        tbl = tbl.sort_values("Days", key=lambda x: x.map(lambda v: 9999 if v == 9999 else v))

        def tier_color(val):
            return {
                "Must-Do":   "background-color:#3d0000;color:#ff6666",
                "Should-Do": "background-color:#3d2e00;color:#ffcc44",
                "May-Do":    "background-color:#001f3d;color:#44aaff",
            }.get(val, "")

        st.dataframe(
            tbl.style.map(tier_color, subset=["Tier"]),
            use_container_width=True,
            hide_index=True,
        )

    # Timeline chart
    st.divider()
    st.subheader("Deadline Timeline")
    try:
        import plotly.express as px
        if not active.empty and "deadline" in active.columns:
            tl = active[active["deadline"].notna()].copy()
            tl["deadline_date"] = pd.to_datetime(tl["deadline"])
            prize_col = tl["prize_usd"] if "prize_usd" in tl.columns else pd.Series(0, index=tl.index)
            tl["prize_size"] = prize_col.clip(lower=1000)
            fig = px.scatter(
                tl, x="deadline_date", y="theme_fit",
                color="tier", size="prize_size", size_max=40,
                hover_name="name",
                hover_data={"prize_fmt": True, "deadline_fmt": True},
                color_discrete_map={"Must-Do": "#ff4444", "Should-Do": "#ffaa00", "May-Do": "#4499ff"},
                labels={"deadline_date": "Deadline", "theme_fit": "Theme Fit (1-10)"},
                height=320,
            )
            fig.update_layout(paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font_color="white")
            # add_vline on datetime axis needs ms-since-epoch; pd.Timestamp arithmetic
            # broken in pandas 2.0+ with newer plotly — convert explicitly
            today_ms = int(pd.Timestamp(TODAY).timestamp() * 1000)
            fig.add_vline(x=today_ms, line_dash="dash", line_color="white", opacity=0.4,
                          annotation_text="Today", annotation_font_color="white")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No deadline data to plot.")
    except ImportError:
        st.info("Install plotly for timeline: `pip3 install plotly`")


# ─── Needs Review tab ─────────────────────────────────────────────────────────

with tab6:
    st.subheader("🔍 Needs Review — Scout-Discovered Opportunities")
    st.caption("Auto-discovered by scout.py. Triage these: approve (roster.py approve <id>) or reject.")

    if review_df.empty:
        st.success("Nothing to review. Run `python3 scripts/scout.py` to discover new opportunities.")
    else:
        for _, row in review_df.sort_values("days_until").iterrows():
            days   = row["days_until"]
            days_s = f"{days}d" if days != 9999 else "rolling"
            score  = row.get("theme_fit", "?")
            src    = row.get("source", "?")
            label  = f"**{row['name']}** — {row['deadline_fmt']} ({days_s}) — fit {score}/10 — via {src}"

            with st.expander(label):
                c1, c2 = st.columns([2, 1])
                with c1:
                    desc = row.get("notes", "") or ""
                    if desc:
                        st.markdown(desc)
                    if row.get("url"):
                        st.markdown(f"[Open →]({row['url']})")
                with c2:
                    st.markdown(f"**Prize:** {row['prize_fmt']}")
                    st.markdown(f"**Source:** {src}")
                    st.code(f"python3 roster.py approve {row['id']}", language="bash")
                    st.code(f"python3 roster.py reject {row['id']}",  language="bash")
