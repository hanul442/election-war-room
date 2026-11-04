"""Collect US election headlines from public RSS feeds into news.json.

Runs in GitHub Actions every few minutes. The war room page reads news.json
from the same site, so it needs no API key and no cross-site requests.
"""
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

FEEDS = {
    "AP (Google News)": "https://news.google.com/rss/search?q=site:apnews.com+election&hl=en-US&gl=US&ceid=US:en",
    "Google News": "https://news.google.com/rss/search?q=midterm+election+results+when:1d&hl=en-US&gl=US&ceid=US:en",
    "NPR": "https://feeds.npr.org/1014/rss.xml",
    "NYT": "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml",
    "Politico": "https://rss.politico.com/politics-news.xml",
    "NBC": "https://feeds.nbcnews.com/nbcnews/public/politics",
    "CBS": "https://www.cbsnews.com/latest/rss/politics",
    "ABC": "https://abcnews.go.com/abcnews/politicsheadlines",
    "Fox News": "https://moxie.foxnews.com/google-publisher/politics.xml",
    "BBC": "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml",
    "The Hill": "https://thehill.com/homenews/campaign/feed/",
}

# 선거와 관련된 기사만 남긴다
ELECTION = re.compile(
    r"elect|midterm|ballot|vote|voter|polls?\b|senate|house|governor|race|"
    r"democrat|republican|gop|concede|victory|wins|projected|projects|recount|turnout",
    re.I,
)
# 속보로 표시할 표현
BREAKING = re.compile(
    r"breaking|projected|projects|\bwins?\b|\bwon\b|majority|defeats|concede|declares victory|"
    r"flips|holds .* seat|control of the (house|senate)|race call|AP (calls|declares)",
    re.I,
)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "election-war-room/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def parse_time(text):
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def items_from(source, raw):
    root = ET.fromstring(raw)
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        when = parse_time(it.findtext("pubDate"))
        # Google News 제목은 "제목 - 매체" 꼴이라 매체명을 떼어 출처로 쓴다
        src = source
        if source.startswith(("Google", "AP (")) and " - " in title:
            title, src = title.rsplit(" - ", 1)
        if title and link and ELECTION.search(title):
            out.append({
                "title": title,
                "source": src,
                "link": link,
                "time": when.isoformat() if when else None,
                "breaking": bool(BREAKING.search(title)),
            })
    return out


def main():
    seen, items, errors = set(), [], []
    for source, url in FEEDS.items():
        try:
            for it in items_from(source, fetch(url)):
                key = re.sub(r"\W+", "", it["title"].lower())[:80]
                if key not in seen:
                    seen.add(key)
                    items.append(it)
        except Exception as e:  # 한 매체가 실패해도 나머지는 계속
            errors.append(f"{source}: {e.__class__.__name__}")
    items.sort(key=lambda x: x["time"] or "", reverse=True)
    data = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "items": items[:80],
        "errors": errors,
    }
    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"{len(items)} items, {len(errors)} feed errors", file=sys.stderr)


if __name__ == "__main__":
    main()
