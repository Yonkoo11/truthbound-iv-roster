"""
firecrawl.py — JS-rendered web scraping via stableenrich.dev Firecrawl API.

Returns markdown text of rendered pages. Useful for:
  - SPA sites (DoraHacks, Devpost) where BeautifulSoup gets empty HTML
  - Verification of Exa results (cross-check deadlines/prizes against source pages)

Cost: $0.013 per page.

Usage:
    from scripts.firecrawl import scrape
    md = scrape("https://dorahacks.io/hackathon/123")
"""

import ipaddress
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.cost_monitor import agentcash_fetch

FIRECRAWL_URL = "https://stableenrich.dev/api/firecrawl/scrape"


def _is_safe_url(url: str) -> bool:
    """Reject file://, private IPs, localhost. Only https:// allowed."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme != "https":
        return False

    host = parsed.hostname or ""
    if not host:
        return False

    # Block localhost variants
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False

    # Block private IP ranges
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_reserved:
            return False
    except ValueError:
        pass  # hostname, not IP -- that's fine

    return True


def scrape(url: str, timeout: int = 30) -> str | None:
    """
    Scrape a URL via Firecrawl (JS-rendered). Returns markdown or None.

    Args:
        url: Must be https://. Private IPs and localhost are rejected.
        timeout: Max seconds for the request.

    Returns:
        Markdown text of the rendered page, or None on failure.
    """
    if not _is_safe_url(url):
        return None

    body = json.dumps({"url": url})

    try:
        data = agentcash_fetch(
            FIRECRAWL_URL,
            body=body,
            estimated_cost=0.015,
            timeout=timeout,
        )
    except Exception:
        return None

    # Extract markdown from response
    content = data.get("data", {})
    if isinstance(content, dict):
        return content.get("markdown") or content.get("content") or None
    return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/firecrawl.py <url>")
        sys.exit(1)

    url = sys.argv[1]
    result = scrape(url)
    if result:
        print(f"Got {len(result)} chars of markdown")
        print(result[:500])
    else:
        print("Scrape failed or URL rejected")
