from __future__ import annotations

"""
scout.py — Automated opportunity discovery for BountyBoard.

Sources:
  - ETHGlobal (events API)
  - Devpost (JSON search API)
  - DoraHacks (public API)

Scores each opportunity against BountyBoard themes.
Deduplicates via DB URLs + seen_urls.json fallback.
Notifies via notify.py on completion or failure.

Usage:
    python scripts/scout.py                    # full scout
    python scripts/scout.py --dry-run          # preview, no writes
    python scripts/scout.py --source ethglobal # single source
"""

import json
import logging
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

REPO_DIR        = Path(__file__).parent.parent
CANDIDATES_FILE = REPO_DIR / "data" / "scout_candidates.json"
LOGS_DIR        = REPO_DIR / "logs"
TODAY_ISO       = date.today().isoformat()

sys.path.insert(0, str(REPO_DIR))
import db
from scripts.notify import send as notify

# ── Logging ───────────────────────────────────────────────────────────────────

LOGS_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / f"scout_{TODAY_ISO}.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("scout")


# ── Scoring ───────────────────────────────────────────────────────────────────

PHRASE_WEIGHTS: dict[str, int] = {
    # Core BountyBoard themes — highest weight
    "ai agent":             3,
    "zero knowledge proof": 3,
    "verifiable compute":   3,
    "trustless ai":         3,
    "truth verif":          3,
    # High value
    "zkp":                  2,
    "zkml":                 2,
    "attestation":          2,
    "verifiable":           2,
    "llm agent":            2,
    "truth verification":   2,
    "ethglobal":            2,
    "zero knowledge":       2,
    "zk proof":             2,
    "ai agents":            2,
    # Mid value
    "artificial intelligence": 1,
    "machine learning":     1,
    "blockchain":           1,
    "web3":                 1,
    "chainlink":            1,
    "filecoin":             1,
    "starknet":             1,
    "on-chain":             1,
    "oracle":               1,
    "privacy":              1,
    "data integrity":       1,
    "hackathon":            1,
    "protocol labs":        1,
    "solana":               1,
    "ipfs":                 1,
    "decentralized":        1,
    "autonomous":           1,
    "llm":                  1,
    "proof":                1,
}
NEG_PHRASES: dict[str, int] = {
    "defi only":    -2,
    "nft only":     -2,
    "play-to-earn": -2,
    "meme coin":    -2,
    "gaming":       -1,
    "metaverse":    -1,
    "nft":          -1,
}


def score_opportunity(title: str, description: str,
                      prize_usd: int = 0, deadline: Optional[str] = None) -> int:
    text = (title + " " + description).lower()
    score = 0
    for phrase, weight in PHRASE_WEIGHTS.items():
        if phrase in text:
            score += weight
    for phrase, weight in NEG_PHRASES.items():
        if phrase in text:
            score += weight
    # Boost for prize size
    if prize_usd >= 100_000:
        score += 2
    elif prize_usd >= 50_000:
        score += 1
    # Boost for near deadline (urgency)
    if deadline:
        try:
            dl = datetime.strptime(deadline, "%Y-%m-%d").date()
            days_left = (dl - date.today()).days
            if 0 < days_left <= 30:
                score += 1
        except ValueError:
            pass
    return max(0, min(10, score))


# ── Date helpers ───────────────────────────────────────────────────────────────

def _normalize_date(raw: str) -> Optional[str]:
    if not raw:
        return None
    # ISO 8601 / datetime variants — fromisoformat handles YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS, etc.
    try:
        return datetime.fromisoformat(raw[:19].rstrip("Z")).strftime("%Y-%m-%d")
    except ValueError:
        pass
    # Unix timestamp (int)
    try:
        ts = int(raw)
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OSError):
        pass

    # Pre-process for fuzzy parsing:
    # 1. Strip ordinal suffixes: "3rd" → "3", "21st" → "21"
    clean = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", raw)
    # 2. Date ranges: "Mar 31 - Apr 06, 2026" or "Mar 14 - 15, 2026" → use end date
    #    Split on dash/endash surrounded by spaces
    parts = re.split(r"\s*[–—-]\s*", clean, maxsplit=1)
    if len(parts) == 2:
        end_part = parts[1].strip()
        # Same-month range: end part is just "15, 2026" — prepend month from start
        if re.match(r"^\d{1,2}[,\s]", end_part):
            month_m = re.search(
                r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
                r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b",
                parts[0], re.IGNORECASE)
            if month_m:
                end_part = month_m.group(0) + " " + end_part
        clean = end_part

    # Long month name: "March 8, 2026" or "March 8 2026"
    m = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2}),?\s+(20\d{2})\b", clean, re.IGNORECASE
    )
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Abbreviated month: "Mar 08, 2026" or "Mar 8 2026"
    m = re.search(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+(\d{1,2}),?\s+(20\d{2})\b",
        clean, re.IGNORECASE
    )
    if m:
        try:
            return datetime.strptime(
                f"{m.group(1)[:3].capitalize()} {int(m.group(2)):02d} {m.group(3)}", "%b %d %Y"
            ).strftime("%Y-%m-%d")
        except ValueError:
            pass

    log.warning(f"Could not parse date: '{raw}'")
    return None


def _is_future(deadline_str: Optional[str]) -> bool:
    if not deadline_str:
        return True  # rolling — include
    try:
        return datetime.strptime(deadline_str, "%Y-%m-%d").date() >= date.today()
    except ValueError:
        return True


# ── Rate-limited requests ─────────────────────────────────────────────────────

_last_request_time: float = 0.0

def _fetch(url: str, **kwargs) -> Optional["requests.Response"]:  # type: ignore[name-defined]
    global _last_request_time
    import requests
    elapsed = time.time() - _last_request_time
    if elapsed < 2.0:
        time.sleep(2.0 - elapsed)
    try:
        resp = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36", "Accept": "application/json, text/html,*/*"}, **kwargs)
        _last_request_time = time.time()
        resp.raise_for_status()
        return resp
    except Exception as e:
        log.warning(f"Request failed for {url}: {e}")
        _last_request_time = time.time()
        return None


# ── Source: ETHGlobal ─────────────────────────────────────────────────────────

def fetch_ethglobal() -> list[dict]:
    log.info("Fetching ETHGlobal events...")
    resp = _fetch("https://ethglobal.com/events")
    if not resp:
        return []
    try:
        from bs4 import BeautifulSoup  # type: ignore[import-untyped]
    except ImportError:
        log.warning("beautifulsoup4 not installed — skipping ETHGlobal")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    seen_hrefs: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        if not href.startswith("/events/") or href in seen_hrefs:
            continue
        seen_hrefs.add(href)
        url   = f"https://ethglobal.com{href}"
        title = a.get_text(strip=True)
        if not title or len(title) < 3:
            continue

        # Look for date in nearby text
        parent_text = a.parent.get_text(" ", strip=True) if a.parent else ""
        deadline = _normalize_date(parent_text[:200]) if parent_text else None

        results.append({
            "source":    "ethglobal",
            "url":       url,
            "name":      f"ETHGlobal {title}",
            "description": f"ETHGlobal hackathon: {title}. {parent_text[:200]}",
            "deadline":  deadline,
            "prize_usd": 0,
            "prize_note": "ETHGlobal prize pool (TBD)",
        })

    log.info(f"ETHGlobal: {len(results)} entries")
    return results


# ── Source: Devpost ────────────────────────────────────────────────────────────

def fetch_devpost() -> list[dict]:
    log.info("Fetching Devpost hackathons...")
    results = []
    seen: set[str] = set()

    # Devpost search API (JSON) for relevant tags
    for tag in ["ai", "blockchain", "web3"]:
        resp = _fetch(
            "https://devpost.com/api/hackathons",
            params={"challenge_type[]": "online", "search": tag, "status[]": "upcoming"},
        )
        if not resp:
            continue
        try:
            data = resp.json()
        except Exception:
            continue
        for item in data.get("hackathons", []):
            url   = str(item.get("url", ""))
            title = str(item.get("title", ""))
            desc  = str(item.get("tagline", "") or "")
            if not url or not title or url in seen:
                continue
            seen.add(url)
            prize    = item.get("prize_amount", 0) or 0
            deadline = _normalize_date(str(item.get("submission_period_dates", "") or ""))
            results.append({
                "source":     "devpost",
                "url":        url,
                "name":       title,
                "description": desc,
                "deadline":   deadline,
                "prize_usd":  int(prize) if str(prize).isdigit() else 0,
                "prize_note": f"${prize}" if prize else "",
            })

    log.info(f"Devpost: {len(results)} entries")
    return results


# ── Source: DoraHacks ─────────────────────────────────────────────────────────

def fetch_dorahacks() -> list[dict]:
    log.info("Fetching DoraHacks...")
    results = []
    # DoraHacks REST API — paginated via next cursor
    page_size = 24
    url_base = "https://dorahacks.io/api/hackathon/"
    page = 1
    while True:
        resp = _fetch(url_base, params={"page_size": page_size, "page": page, "type": 0})
        if not resp:
            break
        try:
            data = resp.json()
        except Exception:
            break

        items = data.get("results", []) if isinstance(data, dict) else data
        if not items:
            break

        for item in items:
            uname    = item.get("uname", "") or str(item.get("id", ""))
            url      = f"https://dorahacks.io/hackathon/{uname}/detail"
            title    = str(item.get("title", "")).strip()
            desc     = str(item.get("description", "")).strip()
            prize    = item.get("bonus_price", 0) or 0
            deadline = _normalize_date(str(item.get("end_time", "") or ""))
            if not title:
                continue
            results.append({
                "source":     "dorahacks",
                "url":        url,
                "name":       title,
                "description": desc,
                "deadline":   deadline,
                "prize_usd":  int(prize) if str(prize).isdigit() else 0,
                "prize_note": f"${prize}" if prize else "",
            })

        # Stop if fewer results than requested or no next page
        if len(items) < page_size or not data.get("next"):
            break
        page += 1
        if page > 5:  # max 5 pages = 120 results
            break

    log.info(f"DoraHacks: {len(results)} entries")
    return results


# ── Source: Gitcoin ────────────────────────────────────────────────────────────

def fetch_gitcoin() -> list[dict]:
    log.info("Fetching Gitcoin Grants Stack rounds...")
    results = []
    # Try multiple chain IDs: Ethereum (1), Optimism (10), Arbitrum (42161), Base (8453)
    chain_ids = ["1", "10", "42161", "8453"]
    seen: set[str] = set()
    for chain_id in chain_ids:
        resp = _fetch(
            "https://grants-stack-indexer-v2.gitcoin.co/data/rounds.json",
            params={"chainId": chain_id},
        )
        if not resp:
            # Try alternate endpoint
            resp = _fetch("https://grants-stack.gitcoin.co/api/v1/rounds",
                          params={"chainId": chain_id, "status": "active"})
        if not resp:
            continue
        try:
            data = resp.json()
        except Exception:
            continue

        items = data if isinstance(data, list) else data.get("rounds", []) or data.get("data", [])
        for item in items:
            # Extract metadata — structure varies by API version
            meta   = item.get("roundMetadata") or item.get("metadata") or {}
            name   = str(meta.get("name") or item.get("name") or "").strip()
            desc   = str(meta.get("description") or meta.get("eligibility", {}).get("description") or "").strip()
            app_end = str(item.get("applicationsEndTime") or item.get("roundEndTime") or "")
            prize  = item.get("matchAmount") or item.get("matchingFunds") or 0
            try:
                prize = int(float(str(prize).replace(",", ""))) if prize else 0
            except (ValueError, TypeError):
                prize = 0
            round_id = str(item.get("id") or item.get("roundId") or "")
            url = f"https://explorer.gitcoin.co/#/round/{chain_id}/{round_id}" if round_id else ""
            if not name or not url or url in seen:
                continue
            seen.add(url)
            deadline = _normalize_date(app_end[:19] if app_end else "")
            results.append({
                "source":      "gitcoin",
                "url":         url,
                "name":        name,
                "description": desc,
                "deadline":    deadline,
                "prize_usd":   prize,
                "prize_note":  f"${prize:,} matching" if prize else "Gitcoin grants round",
            })

    log.info(f"Gitcoin: {len(results)} entries")
    return results


# ── Source: Solana Foundation ──────────────────────────────────────────────────

def fetch_solana() -> list[dict]:
    log.info("Fetching Solana Foundation hackathons...")
    resp = _fetch("https://solana.com/hackathon")
    if not resp:
        return []
    try:
        from bs4 import BeautifulSoup  # type: ignore[import-untyped]
    except ImportError:
        log.warning("beautifulsoup4 not installed — skipping Solana")
        return []

    soup    = BeautifulSoup(resp.text, "html.parser")
    results = []
    seen_hrefs: set[str] = set()

    for a in soup.find_all("a", href=True):
        href  = str(a["href"])
        title = a.get_text(strip=True)
        if not title or len(title) < 5:
            continue
        # Look for hackathon/event links
        lower = href.lower()
        if not any(kw in lower for kw in ("hackathon", "event", "build", "grants")):
            continue
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)
        url = href if href.startswith("http") else f"https://solana.com{href}"
        parent_text = a.parent.get_text(" ", strip=True) if a.parent else ""
        deadline = _normalize_date(parent_text[:200]) if parent_text else None
        results.append({
            "source":      "solana",
            "url":         url,
            "name":        f"Solana {title}",
            "description": f"Solana Foundation event: {title}. {parent_text[:300]}",
            "deadline":    deadline,
            "prize_usd":   0,
            "prize_note":  "Solana Foundation prize pool (TBD)",
        })

    log.info(f"Solana: {len(results)} entries")
    return results


# ── Source: Twitter/X signals (best-effort) ────────────────────────────────────

def fetch_twitter_signals() -> list[dict]:
    """Best-effort DuckDuckGo search for hackathon announcements on Twitter/X.
    Returns low-confidence candidates only (score floor of 3).
    Skips gracefully if DuckDuckGo rate-limits."""
    log.info("Fetching Twitter/X signals via DuckDuckGo...")
    results = []
    queries = [
        '"hackathon" "AI agent" site:twitter.com OR site:x.com',
        '"hackathon" "zero knowledge" site:twitter.com OR site:x.com',
    ]
    seen_urls: set[str] = set()

    for query in queries:
        resp = _fetch(
            "https://html.duckduckgo.com/html/",
            params={"q": query, "kl": "us-en"},
        )
        if not resp:
            log.info("DuckDuckGo: rate-limited or blocked — skipping Twitter/X source")
            return results

        try:
            from bs4 import BeautifulSoup  # type: ignore[import-untyped]
        except ImportError:
            return results

        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.select("a.result__a"):
            href  = str(a.get("href") or "")
            title = a.get_text(strip=True)
            if not href or not title:
                continue
            if "twitter.com" not in href and "x.com" not in href:
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)
            snippet_el = a.find_next("a", class_="result__snippet")
            desc = snippet_el.get_text(strip=True) if snippet_el else title
            results.append({
                "source":      "twitter",
                "url":         href,
                "name":        title[:80],
                "description": desc[:400],
                "deadline":    None,
                "prize_usd":   0,
                "prize_note":  "",
            })

    log.info(f"Twitter/X signals: {len(results)} entries")
    return results


# ── Source health tracking ─────────────────────────────────────────────────────

SOURCE_HEALTH_FILE = REPO_DIR / "data" / ".source_health.json"


def _update_source_health(source_counts: dict[str, int]) -> None:
    """Persist per-source result counts and alert if a source appears dead."""
    try:
        data: dict[str, dict] = {}
        if SOURCE_HEALTH_FILE.exists():
            data = json.loads(SOURCE_HEALTH_FILE.read_text())
    except Exception:
        data = {}

    now = datetime.now().isoformat(timespec="seconds")
    for src, count in source_counts.items():
        entry = data.get(src, {"count": 0, "history": []})
        entry["last_run"] = now
        entry["count"]    = count
        history            = entry.get("history", [])
        history.append(count)
        entry["history"]  = history[-10:]  # keep last 10
        data[src] = entry

        # Alert if source returned 0 but historically returns results
        avg = sum(history[:-1]) / len(history[:-1]) if len(history) > 1 else 0
        if count == 0 and avg > 5:
            notify(
                f"Scout — source '{src}' returned 0 results",
                f"Historical average: {avg:.1f}. Source may be down.",
                level="warning",
            )
            log.warning(f"Source '{src}' returned 0 (avg was {avg:.1f})")

    try:
        SOURCE_HEALTH_FILE.parent.mkdir(exist_ok=True)
        SOURCE_HEALTH_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        log.warning(f"Could not write source health: {e}")


# ── Name-based dedup ────────────────────────────────────────────────────────────

def _name_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower())[:30].strip("-")


def _build_name_slugs(existing_ids: set[str], candidates: list[dict]) -> set[str]:
    """Build set of name slugs from existing DB IDs and candidates."""
    slugs: set[str] = set()
    for eid in existing_ids:
        slugs.add(eid[:30].strip("-"))
    for c in candidates:
        name = c.get("name", "")
        if name:
            slugs.add(_name_slug(name))
    return slugs


# ── Source: Exa (via stableenrich.dev) ────────────────────────────────────────

EXA_QUERIES = [
    "blockchain hackathon 2026 prize",
    "web3 AI agent hackathon grant accelerator 2026",
    "crypto developer bounty program 2026",
]


def fetch_exa() -> list[dict]:
    """Neural web search via stableenrich.dev Exa API (x402 micropayments).
    ~$0.027 per query (search + summaries). Catches hackathons announced on
    news sites, blogs, and smaller platforms that our scrapers miss."""
    log.info("Fetching Exa search results via stableenrich.dev...")
    results = []
    seen_urls: set[str] = set()

    for query in EXA_QUERIES:
        body = json.dumps({
            "query": query,
            "numResults": 15,
            "startPublishedDate": f"{date.today().year}-01-01",
            "contents": {
                "summary": {
                    "query": "Extract: hackathon name, organizer, deadline date, prize pool, accepted chains/languages, submission URL"
                },
            },
        })
        try:
            from scripts.cost_monitor import BudgetExceeded, agentcash_fetch
            data = agentcash_fetch(
                "https://stableenrich.dev/api/exa/search",
                body=body, estimated_cost=0.03,
            )
        except BudgetExceeded as e:
            log.warning(f"Exa budget exceeded: {e}")
            break
        except Exception as e:
            log.warning(f"Exa fetch error: {e}")
            continue

        items = data.get("data", {}).get("results", [])
        cost = data.get("data", {}).get("costDollars", {}).get("total", 0)
        log.info(f"Exa query '{query[:40]}': {len(items)} results (${cost:.3f})")

        for item in items:
            url = item.get("url", "").strip()
            title = item.get("title", "").strip()
            if not url or not title or url in seen_urls:
                continue
            seen_urls.add(url)

            summary = item.get("summary", "") or ""
            pub_date = _normalize_date(item.get("publishedDate", "") or "")

            # Extract prize from summary (look for $X,XXX or $XK patterns)
            prize_usd = 0
            prize_match = re.search(r"\$(\d[\d,]*(?:\.\d+)?)\s*(?:K|k)", summary)
            if prize_match:
                prize_usd = int(float(prize_match.group(1).replace(",", "")) * 1000)
            else:
                prize_match = re.search(r"\$(\d[\d,]+)", summary)
                if prize_match:
                    val = int(prize_match.group(1).replace(",", ""))
                    if val >= 1000:  # ignore small dollar amounts
                        prize_usd = val

            # Extract deadline from summary
            deadline = None
            dl_patterns = [
                r"deadline[:\s]+(?:is\s+)?(\w+ \d{1,2},?\s*\d{4})",
                r"(?:runs?|running)\s+(?:from\s+)?\w+ \d{1,2}[^,]*?(?:to|through|until)\s+(\w+ \d{1,2},?\s*\d{4})",
                r"(\w+ \d{1,2},?\s*\d{4})\s*(?:deadline|submission)",
            ]
            for pat in dl_patterns:
                m = re.search(pat, summary, re.IGNORECASE)
                if m:
                    deadline = _normalize_date(m.group(1))
                    if deadline:
                        break

            results.append({
                "source":     "exa",
                "url":        url,
                "name":       title[:100],
                "description": summary[:500],
                "deadline":   deadline,
                "prize_usd":  prize_usd,
                "prize_note": f"${prize_usd:,}" if prize_usd else "",
            })

    log.info(f"Exa: {len(results)} entries total")
    return results


# ── Find-Similar (competitive intelligence) ──────────────────────────────────

FIND_SIMILAR_URL = "https://stableenrich.dev/api/exa/find-similar"


def _run_find_similar(
    existing_urls: set[str],
    existing_ids: set[str],
    name_slugs: set[str],
    new_opps: list[dict],
) -> None:
    """Query Exa find-similar for top-prize opportunities. Adds results as needs_review."""
    from scripts.cost_monitor import BudgetExceeded, agentcash_fetch

    # Get top 3 active opportunities by prize (>$50K, with URLs)
    all_opps = db.get_all()
    top = sorted(
        [o for o in all_opps if o.get("prize_usd", 0) >= 50_000
         and o.get("url") and o.get("status") in ("active", "needs_review")],
        key=lambda o: o.get("prize_usd", 0),
        reverse=True,
    )[:3]

    if not top:
        log.info("Find-similar: no high-prize entries to query")
        return

    log.info(f"Find-similar: querying {len(top)} top-prize entries")
    found = 0

    for opp in top:
        body = json.dumps({
            "url": opp["url"],
            "numResults": 5,
            "startPublishedDate": f"{date.today().year}-01-01",
            "contents": {
                "summary": {
                    "query": "Extract: hackathon name, deadline date, prize pool"
                },
            },
        })

        try:
            data = agentcash_fetch(FIND_SIMILAR_URL, body=body, estimated_cost=0.01)
        except BudgetExceeded as e:
            log.warning(f"Find-similar budget exceeded: {e}")
            break
        except Exception as e:
            log.warning(f"Find-similar failed for {opp['name']}: {e}")
            continue

        items = data.get("data", {}).get("results", [])
        for item in items:
            url = item.get("url", "").strip()
            title = item.get("title", "").strip()
            if not url or not title or url in existing_urls:
                continue

            slug = _name_slug(title)
            if slug and slug in name_slugs:
                continue

            existing_urls.add(url)
            if slug:
                name_slugs.add(slug)

            opp_id = re.sub(r"[^a-z0-9]+", "-", title.lower())[:40].strip("-")
            if opp_id in existing_ids:
                opp_id = f"{opp_id}-similar"
            existing_ids.add(opp_id)

            summary = item.get("summary", "") or ""
            new_opp = {
                "id": opp_id,
                "name": title[:100],
                "category": "hackathon",
                "status": "needs_review",
                "url": url,
                "description": summary[:500],
                "notes": f"Found via find-similar from {opp['name']} on {TODAY_ISO}",
                "source": "exa_similar",
            }
            new_opps.append(new_opp)
            try:
                db.upsert(new_opp)
                found += 1
                log.info(f"[SIMILAR] {title} (from {opp['name']})")
            except Exception as e:
                log.warning(f"Failed to add similar: {e}")

    log.info(f"Find-similar: added {found} new entries")


# ── Sources registry ──────────────────────────────────────────────────────────

SOURCES = {
    "ethglobal": fetch_ethglobal,
    "devpost":   fetch_devpost,
    "dorahacks": fetch_dorahacks,
    "gitcoin":   fetch_gitcoin,
    "solana":    fetch_solana,
    "twitter":   fetch_twitter_signals,
    "exa":       fetch_exa,
    # encode: JS SPA — cannot scrape without headless browser
}


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv
    source_filter: Optional[str] = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--source" and i < len(sys.argv) - 1:
            source_filter = sys.argv[i + 1]
        elif arg.startswith("--source="):
            source_filter = arg.split("=", 1)[1]

    # Load dedup state
    existing_urls = db.get_urls()
    existing_ids  = {o["id"] for o in db.get_all()}

    # Load candidates file
    CANDIDATES_FILE.parent.mkdir(exist_ok=True)
    if CANDIDATES_FILE.exists():
        with open(CANDIDATES_FILE) as f:
            candidates: list[dict] = json.load(f)
    else:
        candidates = []

    # TTL cleanup: remove expired + stale candidates before this run
    before_ttl = len(candidates)
    cutoff_date = date.today().isoformat()
    cutoff_scout = (
        datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        - __import__("datetime").timedelta(days=90)
    ).date().isoformat()
    candidates = [
        c for c in candidates
        if (not c.get("deadline") or c["deadline"] >= cutoff_date)
        and (not c.get("scout_date") or c["scout_date"] >= cutoff_scout)
    ]
    if len(candidates) < before_ttl:
        log.info(f"TTL cleanup: removed {before_ttl - len(candidates)} stale candidates")

    # Build name slug dedup set
    name_slugs = _build_name_slugs(existing_ids, candidates)

    # Fetch all sources
    all_raw: list[dict] = []
    errors: list[str] = []
    source_counts: dict[str, int] = {}
    for src_name, fn in SOURCES.items():
        if source_filter and src_name != source_filter:
            continue
        try:
            results = fn()
            source_counts[src_name] = len(results)
            all_raw.extend(results)
        except Exception as e:
            msg = f"{src_name} fetch failed: {e}"
            log.error(msg)
            errors.append(msg)
            source_counts[src_name] = 0

    # Update source health (skip if single-source filter run)
    if not source_filter:
        _update_source_health(source_counts)

    stats = {"new_review": 0, "candidate": 0, "skipped": 0, "already_seen": 0, "past": 0}
    new_opps: list[dict] = []
    new_candidates: list[dict] = []

    for item in all_raw:
        url = item.get("url", "").strip()
        if not url or url in existing_urls:
            stats["already_seen"] += 1
            continue

        existing_urls.add(url)

        # Name-based dedup (catches same event at different URLs)
        name = item.get("name", "")
        slug = _name_slug(name)
        if slug and slug in name_slugs:
            log.debug(f"[DEDUP] '{name}' matches existing slug '{slug}'")
            stats["already_seen"] += 1
            continue
        if slug:
            name_slugs.add(slug)

        if not _is_future(item.get("deadline")):
            stats["past"] += 1
            continue

        s = score_opportunity(
            item.get("name", ""),
            item.get("description", ""),
            prize_usd=item.get("prize_usd", 0) or 0,
            deadline=item.get("deadline"),
        )
        # ETHGlobal events are always blockchain hackathons — floor at 4 (candidate)
        if item.get("source") == "ethglobal":
            s = max(s, 4)
        # Twitter signals are low-confidence — floor at 3 (candidate only, never auto-review)
        if item.get("source") == "twitter":
            s = min(s, 5)
        item["theme_fit"] = s

        if s >= 6:
            opp_id = re.sub(r"[^a-z0-9]+", "-", item["name"].lower())[:40].strip("-")
            if opp_id in existing_ids:
                opp_id = f"{opp_id}-{item['source']}"
            if opp_id in existing_ids:
                opp_id = f"{opp_id}-2"
            existing_ids.add(opp_id)

            new_opp = {
                "id":             opp_id,
                "name":           item["name"],
                "category":       "hackathon",
                "deadline":       item.get("deadline"),
                "prize_usd":      item.get("prize_usd", 0),
                "prize_note":     item.get("prize_note", ""),
                "theme_fit":      s,
                "status":         "needs_review",
                "url":            url,
                "notes":          f"Auto-discovered via {item['source']} on {TODAY_ISO}. Score: {s}/10.",
                "source":         item["source"],
                "calendar_synced": False,
            }
            new_opps.append(new_opp)
            stats["new_review"] += 1
            log.info(f"[REVIEW] {item['name']} (score={s}) from {item['source']}")

        elif s >= 4:
            item["scout_date"] = TODAY_ISO
            new_candidates.append(item)
            stats["candidate"] += 1

        else:
            stats["skipped"] += 1

    summary = (
        f"{stats['new_review']} new for review, "
        f"{stats['candidate']} candidates, "
        f"{stats['already_seen']} already seen, "
        f"{stats['past']} past deadline, "
        f"{stats['skipped']} below threshold"
    )
    log.info(f"Scout complete: {summary}")

    if errors:
        notify("Scout — source errors", "\n".join(errors), level="warning")

    if dry_run:
        log.info("[dry-run] No files written.")
        return

    # Write new opportunities to DB
    for opp in new_opps:
        try:
            db.upsert(opp)
        except ValueError as e:
            log.warning(f"Skipped {opp.get('id', '?')}: {e}")

    # Append to candidates file (write back even if only TTL-cleaned)
    with open(CANDIDATES_FILE, "w") as f:
        json.dump(candidates + new_candidates, f, indent=2)

    # Find-similar: discover related opportunities from top-prize entries
    if not source_filter and not dry_run:
        _run_find_similar(existing_urls, existing_ids, name_slugs, new_opps)

    # Versioned daily backup
    try:
        db.backup()
    except Exception as e:
        log.warning(f"Backup failed: {e}")

    print(f"\nSummary: {summary}")
    if stats["new_review"] > 0:
        notify(
            "Scout found new opportunities",
            f"{stats['new_review']} new items need review.\nRun: python roster.py review",
            level="info",
        )
        print("Run: python roster.py review — to triage")
    elif not errors:
        notify("Scout complete — nothing new", summary, level="info")


if __name__ == "__main__":
    main()
