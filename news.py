"""Latest market news (RSS) and this week's economic calendar (ForexFactory feed)."""
import calendar
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import feedparser
import requests

from config import INSTRUMENTS

log = logging.getLogger(__name__)

RSS_FEEDS = {
    "ForexLive": "https://www.forexlive.com/feed/news",
    "FXStreet": "https://www.fxstreet.com/rss/news",
    "Investing.com Forex": "https://www.investing.com/rss/news_1.rss",
    "Investing.com Commodities": "https://www.investing.com/rss/news_11.rss",
    "Investing.com Economy": "https://www.investing.com/rss/news_14.rss",
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Reuters (Google News)": "https://news.google.com/rss/search?q=reuters+markets+when:1d&hl=en-US&gl=US&ceid=US:en",
    "Trump / tariffs (Google News)": "https://news.google.com/rss/search?q=Trump+(tariff+OR+%22Truth+Social%22+OR+Fed)+when:1d&hl=en-US&gl=US&ceid=US:en",
}
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (ProTraderAI research tool)"}

# Words that usually mean the headline moves markets
HIGH_IMPACT_WORDS = ["trump", "truth social", "fed", "fomc", "powell", "rate cut", "rate hike", "cpi", "inflation", "nfp", "payroll",
                     "ecb", "boj", "boe", "intervention", "tariff", "war", "missile", "sanction", "recession",
                     "default", "etf", "sec ", "gdp", "emergency", "crash", "surge", "plunge"]


def _fetch_feed(name: str, url: str) -> List[Dict]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        feed = feedparser.parse(r.content)
    except Exception as e:  # noqa: BLE001
        log.warning("feed %s failed: %s", name, e)
        return []
    items = []
    for e in feed.entries[:40]:
        t = e.get("published_parsed") or e.get("updated_parsed")
        ts = datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc) if t else None
        items.append({"source": name, "title": e.get("title", "").strip(), "link": e.get("link", ""),
                      "summary": (e.get("summary") or "")[:300], "time": ts})
    return items


def fetch_news(max_age_hours: int = 48) -> List[Dict]:
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = ex.map(lambda kv: _fetch_feed(*kv), RSS_FEEDS.items())
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    seen, out = set(), []
    for items in results:
        for it in items:
            key = it["title"].lower()[:80]
            if key in seen or (it["time"] and it["time"] < cutoff):
                continue
            seen.add(key)
            out.append(it)
    out.sort(key=lambda x: x["time"] or cutoff, reverse=True)
    return out


def relevant_news(news: List[Dict], symbol: str, limit: int = 25) -> List[Dict]:
    kws = INSTRUMENTS[symbol].news_keywords
    scored = []
    for it in news:
        text = f" {it['title']} {it['summary']} ".lower()
        hits = sum(k in text for k in kws)
        if hits == 0:
            continue
        impact = sum(w in text for w in HIGH_IMPACT_WORDS)
        scored.append({**it, "relevance": hits, "impact": "HIGH" if impact >= 1 and hits >= 2 else
                       "MEDIUM" if impact or hits >= 2 else "LOW"})
    # newest first, but push highly relevant items up
    scored.sort(key=lambda x: (x["time"] or datetime.min.replace(tzinfo=timezone.utc)).timestamp()
                + 3600 * 6 * x["relevance"], reverse=True)
    return scored[:limit]


CALENDAR_CACHE = os.path.join(os.path.dirname(__file__), "calendar_cache.json")


def fetch_calendar() -> List[Dict]:
    """ForexFactory weekly feed; the host rate-limits hard, so keep a disk copy (refreshed every 30 min)."""
    raw = None
    fresh = os.path.exists(CALENDAR_CACHE) and time.time() - os.path.getmtime(CALENDAR_CACHE) < 1800
    if not fresh:
        try:
            r = requests.get(CALENDAR_URL, headers=HEADERS, timeout=8)
            r.raise_for_status()
            raw = r.json()
            with open(CALENDAR_CACHE, "w", encoding="utf-8") as fh:
                json.dump(raw, fh)
        except Exception as e:  # noqa: BLE001
            log.warning("calendar fetch failed, using cache: %s", e)
    if raw is None:
        try:
            with open(CALENDAR_CACHE, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return []
    out = []
    for ev in raw:
        try:
            t = datetime.fromisoformat(ev["date"]).astimezone(timezone.utc)
        except (KeyError, ValueError):
            continue
        out.append({"time": t, "ccy": ev.get("country", ""), "title": ev.get("title", ""),
                    "impact": ev.get("impact", ""), "forecast": ev.get("forecast", ""),
                    "previous": ev.get("previous", ""), "actual": ev.get("actual", "")})
    return sorted(out, key=lambda e: e["time"])


def relevant_events(events: List[Dict], symbol: str) -> List[Dict]:
    ccys = INSTRUMENTS[symbol].calendar_ccys
    return [e for e in events if e["ccy"] in ccys and e["impact"] in ("High", "Medium")]


def upcoming_high_impact(events: List[Dict], within_minutes: int = 60) -> List[Dict]:
    now = datetime.now(timezone.utc)
    return [e for e in events if e["impact"] == "High"
            and now - timedelta(minutes=15) <= e["time"] <= now + timedelta(minutes=within_minutes)]


def news_prompt_text(news: List[Dict], events: List[Dict]) -> str:
    now = datetime.now(timezone.utc)
    lines = ["## Latest relevant headlines (newest first)"]
    for n in news[:20]:
        age = f"{(now - n['time']).total_seconds() / 3600:.1f}h ago" if n["time"] else "time n/a"
        lines.append(f"- [{n['impact']}] ({age}, {n['source']}) {n['title']}")
    lines.append("\n## Economic calendar this week (UTC, High/Medium impact)")
    for e in events:
        status = f"actual {e['actual']}" if e.get("actual") else ("PAST" if e["time"] < now else "upcoming")
        lines.append(f"- {e['time']:%a %d %b %H:%M} {e['ccy']} [{e['impact']}] {e['title']} "
                     f"(fcst {e['forecast'] or '-'}, prev {e['previous'] or '-'}; {status})")
    return "\n".join(lines)
