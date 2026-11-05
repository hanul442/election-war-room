"""한국 방송사 유튜브 라이브 찾기 → korea/live.json (키는 GitHub Secrets에만 있음)

한 시간에 한 번 "뉴스 라이브"를 검색해서 방송사 공식 채널만 남긴다 (검색 1번 = 100 units, 하루 2,400).
각 영상이 지금도 라이브인지는 2분마다 videos 조회로 확인한다 (1 unit).
"""
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

KEY = next((os.environ.get(k, "").strip() for k in
            ("YOUTUBE_DATA_API", "YOUTUBE_API_KEY", "YT_API_KEY", "YOUTUBE_KEY", "GOOGLE_API_KEY", "API_KEY")
            if os.environ.get(k, "").strip()), "")
API = "https://www.googleapis.com/youtube/v3/"
OUT = "korea/live.json"
EVERY = timedelta(minutes=60)
OUTLETS = re.compile(
    r"YTN|연합뉴스|Yonhap|KBS|MBC|SBS|JTBC|MBN|채널\s?A|Channel A|TV\s?조선|TVCHOSUN|뉴스TVCHOSUN|OBS|"
    r"아리랑|Arirang|KTV|국민방송|국회방송|NATV|뉴스1|뉴시스|한국경제TV|매일경제TV|서울경제TV|이데일리TV|머니투데이방송|MTN|"
    r"G1|KNN|TBC|TJB|JIBS|kbc|광주방송|CJB|UBC|JTV|부산MBC|대구MBC|대전MBC|전주MBC|제주MBC|안동MBC|포항MBC", re.I)


NOT_NEWS = re.compile(r"드라마|Drama|빽드|예능|Classic|클래식|오락|음악|Music|Kids|키즈|사극|무한", re.I)


def get(path, **params):
    params["key"] = KEY
    with urllib.request.urlopen(API + path + "?" + urllib.parse.urlencode(params), timeout=20) as r:
        return json.loads(r.read())


def main():
    now = datetime.now(timezone.utc)
    try:
        st = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        st = {}
    st.setdefault("pool", [])
    if not KEY:
        st.update({"updated": now.isoformat(), "error": "no key"})
    else:
        st.pop("error", None)
        try:
            last = datetime.fromisoformat(st["poolAt"]) if st.get("poolAt") else datetime.min.replace(tzinfo=timezone.utc)
            if now - last >= EVERY:
                d = get("search", part="snippet", type="video", eventType="live", videoEmbeddable="true",
                        regionCode="KR", relevanceLanguage="ko", order="viewCount", maxResults="50", q="뉴스 라이브")
                pool = [{"id": it["id"]["videoId"], "channel": html.unescape(it["snippet"]["channelTitle"]),
                         "title": html.unescape(it["snippet"]["title"])}
                        for it in d.get("items", [])
                        if OUTLETS.search(it["snippet"]["channelTitle"])
                        and not NOT_NEWS.search(it["snippet"]["channelTitle"] + " " + it["snippet"]["title"])]
                if pool:
                    st["pool"] = pool
                st["poolAt"] = now.isoformat()
            ids = [p["id"] for p in st["pool"]][:50]
            if ids:
                d = get("videos", part="snippet,liveStreamingDetails", id=",".join(ids))
                st["status"] = {it["id"]: it["snippet"].get("liveBroadcastContent", "none") for it in d.get("items", [])}
                st["viewers"] = {it["id"]: int(it.get("liveStreamingDetails", {}).get("concurrentViewers") or 0) for it in d.get("items", [])}
        except urllib.error.HTTPError as e:
            st["error"] = f"youtube {e.code}"
        except Exception as e:
            st["error"] = e.__class__.__name__
    st["updated"] = now.isoformat()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    print("korea youtube:", len(st["pool"]), st.get("error", ""), file=sys.stderr)


if __name__ == "__main__":
    main()
