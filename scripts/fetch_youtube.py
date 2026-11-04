"""Use the YouTube Data API key from GitHub Secrets to find election live streams.

Writes live.json, which the war room page reads. The key never leaves Actions.

- pool: live, embeddable election streams (refreshed every 30 minutes)
- related: for a fresh breaking headline, a live stream about the person in it
- status: live / upcoming / ended for every video in pool and related

Daily quota is 10,000 units and a search costs 100, so searches are rationed:
pool 48/day + breaking up to 40/day stays under the limit.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

KEY = next((os.environ.get(k, "").strip() for k in
            ("YOUTUBE_DATA_API", "YOUTUBE_API_KEY", "YT_API_KEY", "YOUTUBE_KEY", "GOOGLE_API_KEY", "API_KEY")
            if os.environ.get(k, "").strip()), "")
API = "https://www.googleapis.com/youtube/v3/"
POOL_EVERY = timedelta(minutes=30)
BRK_EVERY = timedelta(minutes=4)
BRK_PER_DAY = 40
STOP = {"Democrat", "Democrats", "Democratic", "Republican", "Republicans", "GOP", "AP", "Election",
        "Midterm", "Midterms", "Senate", "House", "Governor", "Live", "Breaking", "The", "A", "US",
        "Watch", "Rep", "Sen", "Gov", "Trump", "President", "In", "On", "After", "As"}


def get(path, **params):
    params["key"] = KEY
    url = API + path + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url), timeout=20) as r:
        return json.loads(r.read())


def search(q, n=10):
    d = get("search", part="snippet", type="video", eventType="live", videoEmbeddable="true",
            order="relevance" if n <= 5 else "viewCount", maxResults=str(n), q=q)
    return [{"id": it["id"]["videoId"], "channel": it["snippet"]["channelTitle"],
             "title": it["snippet"]["title"]} for it in d.get("items", [])]


def key_term(title):
    words = re.split(r"[^A-Za-z.\-']+", re.sub(r"['’]s\b", "", title))
    names, cur = [], []
    for w in words:
        if re.fullmatch(r"[A-Z][a-z.\-]+", w or "") and w not in STOP:
            cur.append(w)
        else:
            if len(cur) >= 2:
                names.append(" ".join(cur))
            cur = []
    if len(cur) >= 2:
        names.append(" ".join(cur))
    return names[0] if names else " ".join(title.split()[:6])


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def main():
    now = datetime.now(timezone.utc)
    st = load("live.json", {})
    st.setdefault("pool", [])
    st.setdefault("related", {})
    st.setdefault("status", {})
    q = st.setdefault("quota", {})
    if q.get("day") != now.strftime("%Y-%m-%d"):
        q.update({"day": now.strftime("%Y-%m-%d"), "searches": 0, "brk": 0})

    if not KEY:
        st.update({"updated": now.isoformat(), "error": "no key"})
        json.dump(st, open("live.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("no YouTube key in secrets", file=sys.stderr)
        return
    st.pop("error", None)

    def ts(k):
        v = st.get(k)
        return datetime.fromisoformat(v) if v else datetime.min.replace(tzinfo=timezone.utc)

    try:
        # 1) 선거 라이브 모음
        if now - ts("poolAt") >= POOL_EVERY:
            st["pool"] = search("election results live", 25)
            st["poolAt"] = now.isoformat()
            q["searches"] += 1

        # 2) 새 속보 하나에 대해 관련 라이브
        news = load("news.json", {}).get("items", [])
        fresh = [n for n in news if n.get("breaking") and n.get("time")
                 and now - datetime.fromisoformat(n["time"]) < timedelta(minutes=20)
                 and n["link"] not in st["related"]]
        if fresh and q["brk"] < BRK_PER_DAY and now - ts("brkAt") >= BRK_EVERY:
            it = fresh[0]
            term = key_term(it["title"])
            hits = search(term + " live", 5) or search(term, 5)
            q["searches"] += 1
            q["brk"] += 1
            st["brkAt"] = now.isoformat()
            st["related"][it["link"]] = {"term": term, "video": hits[0] if hits else None, "at": now.isoformat()}
        # 오래된 속보 기록은 정리
        cutoff = now - timedelta(hours=6)
        st["related"] = {k: v for k, v in st["related"].items() if datetime.fromisoformat(v["at"]) > cutoff}

        # 3) 라이브 상태 (1 unit)
        ids = list(dict.fromkeys([p["id"] for p in st["pool"]] +
                                 [v["video"]["id"] for v in st["related"].values() if v.get("video")]))[:50]
        if ids:
            d = get("videos", part="snippet", id=",".join(ids))
            st["status"] = {it["id"]: it["snippet"].get("liveBroadcastContent", "none") for it in d.get("items", [])}
    except urllib.error.HTTPError as e:
        st["error"] = f"youtube {e.code}"
    except Exception as e:
        st["error"] = e.__class__.__name__

    st["updated"] = now.isoformat()
    with open("live.json", "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    print("youtube:", len(st["pool"]), "pool,", len(st["related"]), "related, quota", q, st.get("error", ""), file=sys.stderr)


if __name__ == "__main__":
    main()
