"""뉴스 얼럿 데스크: 통신사식 얼럿·SNS 신호·검색 급상승 → korea/alerts.json

1) 뉴스 얼럿: korea/data.json 기사를 사건 단위로 묶고, 통신사처럼 얼럿 → 1보 → 2보 → 종합 흐름과 긴급도를 붙인다.
   긴급도  FLASH(최상) > BULLETIN > URGENT > ALERT
2) SNS 신호: 블루스카이 한국어 글에서 지켜볼 낱말(지진·화재·정전 등)이 최근 30분에 평소보다 많이 나오면 급증으로 표시.
   (X/트위터는 유료 API라 쓰지 않음. SNS 글은 확인되지 않은 정보로 표시한다.)
3) 검색 급상승: 구글 트렌드 한국 실시간 검색어와 관련 기사.
상태(이미 본 사건, SNS 평소 수준)는 같은 파일에 같이 저장해서 2분마다 이어서 쓴다.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

OUT = "korea/alerts.json"
UA = {"User-Agent": "Mozilla/5.0 korea-newsroom/1.0"}
NOW = datetime.now(timezone.utc)

# ---------- 긴급도 ----------
FLASH = re.compile(r"계엄|선전포고|전쟁 발발|핵실험|대통령.{0,6}(사망|피격|서거|탄핵 인용)|규모\s?[5-9](\.\d)?\s?지진|지진해일|"
                   r"\d{2,}명\s?(사망|숨져)|대규모 정전|비상사태|대피령")
BULLETIN = re.compile(r"미사일|탄도|북한.{0,8}(발사|도발)|지진|탄핵|구속|체포영장|사망|숨져|붕괴|폭발|대형 화재|산불.{0,4}(확산|대응)|"
                      r"경보 발령|태풍|호우경보|대설경보|기준금리|사퇴|별세|피습|총격|추락|침몰|테러")
STAGE = re.compile(r"[\[【(]\s*(속보|1보|2보|3보|종합\d?|긴급|단독|2신|3신)\s*[\]】)]")
STOP = set("속보 단독 종합 1보 2보 3보 긴급 뉴스 기자 오늘 내일 어제 관련 이번 지난 올해 정부 발표 사실 상황 결과 가능 예정 전망 의혹 논란".split())


def fetch(url, timeout=20):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def tokens(title):
    t = STAGE.sub(" ", title)
    t = re.sub(r"[^\w가-힣]+", " ", t)
    out = set()
    for w in t.split():
        if len(w) >= 3 and re.search(r"[가-힣]$", w) and w[-1] in "은는이가을를의에도와과로만":
            w = w[:-1]
        if len(w) >= 2 and w not in STOP and not w.isdigit():
            out.add(w)
    return out


def stage_of(title, first):
    m = STAGE.search(title)
    s = m.group(1) if m else ""
    if s.startswith("종합"):
        return "종합"
    if s in ("2보", "2신"):
        return "2보"
    if s in ("3보", "3신"):
        return "3보"
    if s in ("속보", "긴급"):
        return "얼럿" if first else "속보"
    if s == "단독":
        return "단독"
    return "1보" if first else "후속"


def level_of(text, n_sources, breaking):
    if FLASH.search(text):
        return "FLASH"
    if BULLETIN.search(text) and (breaking or n_sources >= 2):
        return "BULLETIN"
    if breaking or n_sources >= 3:
        return "URGENT"
    return "ALERT"


RANK = {"FLASH": 4, "BULLETIN": 3, "URGENT": 2, "ALERT": 1}


def build_events(news, prev_events):
    # 이전 사건을 이어 받는다 (같은 사건에 새 보도가 붙으면 업데이트로)
    events = [e for e in prev_events if NOW - datetime.fromisoformat(e["last"]) < timedelta(hours=6)]
    for e in events:
        e["_tok"] = set(e.get("tok", []))
    seen_links = {u["link"] for e in events for u in e["updates"]}
    items = sorted([n for n in news if n.get("time")], key=lambda n: n["time"])
    for n in items:
        if n["link"] in seen_links:
            continue
        if NOW - datetime.fromisoformat(n["time"]) > timedelta(hours=3):
            continue
        tk = tokens(n["title"])
        if len(tk) < 2:
            continue
        best, score = None, 0
        for e in events:
            inter = len(tk & e["_tok"])
            if inter < 2:
                continue
            sc = inter / max(1, min(len(tk), len(e["_tok"])))
            if sc > score:
                best, score = e, sc
        # 속보거나, 이미 있는 사건에 붙는 기사만 얼럿 데스크로 올린다
        if best and score >= 0.5:
            stage = stage_of(n["title"], False)
            best["updates"].append({"title": n["title"], "source": n["source"], "link": n["link"], "time": n["time"], "stage": stage})
            best["_tok"] |= tk
            best["last"] = max(best["last"], n["time"])
            best["sources"] = sorted(set(best["sources"]) | {n["source"]})
            best["regions"] = sorted(set(best["regions"]) | set(n.get("regions", [])))
            best["updated"] = NOW.isoformat()
        elif n.get("breaking") or n.get("warn") or n.get("cat") == "재난":
            events.append({
                "id": re.sub(r"\W", "", n["link"])[-24:] + n["time"][11:16].replace(":", ""),
                "first": n["time"], "last": n["time"], "updated": NOW.isoformat(),
                "headline": re.sub(r"\s+[-–—|]\s+[^-–—|]{1,15}$", "", STAGE.sub("", n["title"])).strip(), "cat": n.get("cat"),
                "regions": n.get("regions", []), "sources": [n["source"]], "_tok": tk,
                "updates": [{"title": n["title"], "source": n["source"], "link": n["link"], "time": n["time"], "stage": stage_of(n["title"], True)}],
            })
    for e in events:
        text = " ".join(u["title"] for u in e["updates"])
        lv = level_of(text, len(e["sources"]), any(STAGE.search(u["title"]) for u in e["updates"]))
        # 긴급도는 한 번 올라가면 내려가지 않게
        e["level"] = max(lv, e.get("level", "ALERT"), key=lambda x: RANK[x])
        e["updates"].sort(key=lambda u: u["time"])
        e["latest"] = re.sub(r"\s+[-–—|]\s+[^-–—|]{1,15}$", "", STAGE.sub("", e["updates"][-1]["title"])).strip()
        e["tok"] = sorted(e.pop("_tok"))[:40]
    events.sort(key=lambda e: (e["last"], RANK[e["level"]]), reverse=True)
    return events[:60]


# ---------- SNS (블루스카이) ----------
WATCH = ["지진", "화재", "불났", "정전", "폭발", "붕괴", "대피", "미사일", "속보", "지하철", "사고", "실종", "단수", "통신 장애", "먹통", "산불"]


def bsky(term, since):
    q = urllib.parse.urlencode({"q": term, "limit": "50", "sort": "latest", "lang": "ko", "since": since})
    d = json.loads(fetch("https://api.bsky.app/xrpc/app.bsky.feed.searchPosts?" + q, 15))
    out = []
    for p in d.get("posts", []):
        txt = (p.get("record") or {}).get("text", "")
        if not txt or term.replace(" ", "") not in txt.replace(" ", ""):
            continue
        h = p["author"]["handle"]
        out.append({"text": txt[:220], "handle": h, "name": p["author"].get("displayName") or h,
                    "time": p.get("indexedAt"), "likes": p.get("likeCount", 0), "reposts": p.get("repostCount", 0),
                    "url": f"https://bsky.app/profile/{h}/post/{p['uri'].rsplit('/', 1)[-1]}"})
    return out


# ---------- SNS (유튜브 새 업로드) ----------
YT_KEY = next((os.environ.get(k, "").strip() for k in ("YOUTUBE_DATA_API", "YOUTUBE_API_KEY", "YT_API_KEY") if os.environ.get(k, "").strip()), "")


def youtube_recent(prev):
    """30분마다 한 번, 최근 1시간 한국 업로드 중 사건 낱말이 든 영상 (검색 1번 = 100 units)."""
    last = prev.get("ytAt")
    if not YT_KEY or (last and NOW - datetime.fromisoformat(last) < timedelta(minutes=30)):
        return prev.get("ytPosts", []), last
    q = urllib.parse.urlencode({"part": "snippet", "type": "video", "order": "date", "maxResults": "25", "regionCode": "KR",
                                "relevanceLanguage": "ko", "q": "|".join(WATCH[:10]),
                                "publishedAfter": (NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), "key": YT_KEY})
    d = json.loads(fetch("https://www.googleapis.com/youtube/v3/search?" + q, 20))
    import html as _h
    out = []
    for it in d.get("items", []):
        sn = it["snippet"]; title = _h.unescape(sn["title"])
        term = next((t for t in WATCH if t in title), None)
        if not term:
            continue
        out.append({"platform": "YouTube", "text": title, "handle": sn["channelId"], "name": _h.unescape(sn["channelTitle"]),
                    "time": sn["publishedAt"], "term": term, "url": f"https://www.youtube.com/watch?v={it['id']['videoId']}"})
    return out, NOW.isoformat()


def sns(prev):
    since = (NOW - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    base = prev.get("baseline", {})
    terms, posts, errors = {}, [], []
    for t in WATCH:
        try:
            ps = bsky(t, since)
        except Exception as e:
            errors.append(f"{t}: {e.__class__.__name__}")
            continue
        n = len(ps)
        b = base.get(t, n)
        # 평소 수준은 천천히 따라간다
        base[t] = round(b * 0.9 + n * 0.1, 2)
        spike = n >= 5 and n >= 3 * max(1.0, b)
        terms[t] = {"n30": n, "base": round(b, 1), "spike": spike}
        for p in ps[:4]:
            p["term"] = t
            posts.append(p)
    posts.sort(key=lambda p: p["time"] or "", reverse=True)
    uniq, seen = [], set()
    for p in posts:
        if p["url"] in seen:
            continue
        seen.add(p["url"])
        uniq.append(p)
    try:
        yt, yt_at = youtube_recent(prev)
    except Exception as e:
        yt, yt_at = prev.get("ytPosts", []), prev.get("ytAt")
        errors.append(f"youtube: {e.__class__.__name__}")
    # 유튜브 영상도 낱말별 개수에 더한다 (최근 30분 업로드만)
    for p in yt:
        if p["time"] and NOW - datetime.fromisoformat(p["time"].replace("Z", "+00:00")) < timedelta(minutes=30) and p["term"] in terms:
            terms[p["term"]]["n30"] += 1
    for t, v in terms.items():
        v["spike"] = v["n30"] >= 5 and v["n30"] >= 3 * max(1.0, v["base"])
    merged = sorted(uniq + yt, key=lambda p: p["time"] or "", reverse=True)
    spikes = [{"term": t, **v, "since": NOW.isoformat()} for t, v in terms.items() if v["spike"]]
    return {"terms": terms, "posts": merged[:40], "spikes": spikes, "baseline": base, "errors": errors, "ytPosts": yt, "ytAt": yt_at}


# ---------- 검색 급상승 (구글 트렌드) ----------
def trends(prev_seen):
    root = ET.fromstring(fetch("https://trends.google.com/trending/rss?geo=KR"))
    ns = {"ht": "https://trends.google.com/trending/rss"}
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        traffic = it.findtext("ht:approx_traffic", namespaces=ns) or ""
        try:
            when = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc).isoformat()
        except Exception:
            when = None
        news = [{"title": x.findtext("ht:news_item_title", namespaces=ns), "source": x.findtext("ht:news_item_source", namespaces=ns),
                 "link": x.findtext("ht:news_item_url", namespaces=ns)} for x in it.findall("ht:news_item", ns)][:2]
        out.append({"term": title, "traffic": traffic, "time": when, "news": news, "new": title not in prev_seen})
    return out[:20]


def main():
    try:
        prev = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        prev = {}
    data = json.load(open("korea/data.json", encoding="utf-8"))
    out = {"updated": NOW.isoformat(), "errors": []}
    out["events"] = build_events(data.get("news", []), prev.get("events", []))
    # 한반도 지진은 사건으로 바로 올린다
    for q in data.get("quakes", []):
        if NOW - datetime.fromisoformat(q["time"]) > timedelta(hours=6):
            continue
        qid = "quake" + q["time"][:16].replace("-", "").replace(":", "")
        if any(e["id"] == qid for e in out["events"]):
            continue
        lv = "FLASH" if q["mag"] >= 5 else "BULLETIN" if q["mag"] >= 3.5 else "URGENT"
        out["events"].insert(0, {"id": qid, "first": q["time"], "last": q["time"], "updated": NOW.isoformat(),
                                 "headline": f"규모 {q['mag']} 지진 · {q['place']}", "latest": f"규모 {q['mag']} 지진 · {q['place']}",
                                 "cat": "재난", "regions": [], "sources": ["USGS"], "level": lv, "tok": [],
                                 "updates": [{"title": f"규모 {q['mag']} 지진 · {q['place']}", "source": "USGS", "link": q.get("url"), "time": q["time"], "stage": "얼럿"}]})
    try:
        out["sns"] = sns(prev.get("sns", {}))
    except Exception as e:
        out["sns"] = prev.get("sns", {})
        out["errors"].append(f"sns: {e.__class__.__name__}")
    try:
        seen = set(prev.get("trendSeen", []))
        out["trends"] = trends(seen)
        out["trendSeen"] = sorted((seen | {t["term"] for t in out["trends"]}))[-300:]
    except Exception as e:
        out["trends"] = prev.get("trends", [])
        out["trendSeen"] = prev.get("trendSeen", [])
        out["errors"].append(f"trends: {e.__class__.__name__}")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
    from collections import Counter
    print("alerts:", Counter(e["level"] for e in out["events"]), "sns spikes", len(out["sns"].get("spikes", [])),
          "posts", len(out["sns"].get("posts", [])), "trends", len(out["trends"]), out["errors"], file=sys.stderr)


if __name__ == "__main__":
    main()
