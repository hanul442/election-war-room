"""한국 종합 상황실 데이터: 뉴스·지역 분류·날씨·미세먼지·지진·특보·교통 → korea/data.json

키가 필요 없는 공개 자료만 쓴다.
- 뉴스: 연합뉴스·뉴시스·JTBC·SBS·경향·조선·구글뉴스 RSS
- 날씨·미세먼지: Open-Meteo (시도별 대표 지점)
- 지진: USGS (한반도 주변)
- 특보·교통: 뉴스 제목에서 분류 (기상청·재난문자 원본 API는 키가 있어야 해서 아직 안 씀)
"""
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 korea-newsroom/1.0"}

FEEDS = [
    ("연합뉴스", "https://www.yna.co.kr/rss/news.xml", False),
    ("뉴시스", "https://www.newsis.com/RSS/sokbo.xml", True),
    ("JTBC", "https://fs.jtbc.co.kr/RSS/newsflash.xml", True),
    ("SBS", "https://news.sbs.co.kr/news/newsflashRssFeed.do?plink=RSSREADER", True),
    ("경향신문", "https://www.khan.co.kr/rss/rssdata/total_news.xml", False),
    ("조선일보", "https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml", False),
    ("구글뉴스", "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko", False),
    ("구글뉴스", "https://news.google.com/rss/search?q=%EC%86%8D%EB%B3%B4+when:1h&hl=ko&gl=KR&ceid=KR:ko", True),
]

REGIONS = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]
# 시군 이름 → 시도
CITY = {
    "경기": "수원 성남 고양 용인 부천 안산 안양 남양주 화성 평택 의정부 시흥 파주 김포 광명 하남 군포 오산 이천 양주 구리 안성 포천 의왕 여주 동두천 과천 가평 연천 양평 판교 일산 분당",
    "강원": "춘천 원주 강릉 동해 태백 속초 삼척 홍천 횡성 영월 평창 정선 철원 화천 양구 인제 고성군 양양",
    "충북": "청주 충주 제천 보은 옥천 영동 증평 진천 괴산 음성 단양 오송",
    "충남": "천안 공주 보령 아산 서산 논산 계룡 당진 금산 부여 서천 청양 홍성 예산 태안 내포",
    "전북": "전주 군산 익산 정읍 남원 김제 완주 진안 무주 장수 임실 순창 고창 부안 새만금",
    "전남": "목포 여수 순천 나주 광양 담양 곡성 구례 고흥 보성 화순 장흥 강진 해남 영암 무안 함평 영광 장성 완도 진도 신안",
    "경북": "포항 경주 김천 안동 구미 영주 영천 상주 문경 경산 의성 청송 영양 영덕 청도 고령 성주 칠곡 예천 봉화 울진 울릉 독도",
    "경남": "창원 진주 통영 사천 김해 밀양 거제 양산 의령 함안 창녕 남해 하동 산청 함양 거창 합천 마산",
    "제주": "서귀포 한라산",
    "부산": "해운대 기장",
    "인천": "송도 영종 강화 옹진 인천공항",
    "서울": "강남 서초 송파 종로 여의도 용산 마포 광화문 홍대 잠실 성수 명동",
}
ALIASES = {
    "서울": ["서울"], "부산": ["부산"], "대구": ["대구"], "인천": ["인천"], "광주": ["광주광역시", "광주시", "광주 "],
    "대전": ["대전"], "울산": ["울산"], "세종": ["세종시", "세종특별"], "경기": ["경기도", "경기 "], "강원": ["강원"],
    "충북": ["충북", "충청북도"], "충남": ["충남", "충청남도"], "전북": ["전북", "전라북도"], "전남": ["전남", "전라남도"],
    "경북": ["경북", "경상북도"], "경남": ["경남", "경상남도"], "제주": ["제주"],
}

CATS = [
    ("재난", r"지진|산불|화재|불이 나|불나|붕괴|침수|홍수|태풍|호우|대설|폭설|한파|폭염|강풍|풍랑|해일|재난|대피령|산사태|정전|특보|경보 발령|주의보|황사|미세먼지 비상|싱크홀|가스 누출"),
    ("교통", r"지하철|전철|열차|KTX|SRT|운행 중단|운행 차질|지연 운행|결항|항공편|고속도로|정체|교통사고|추돌|도로 통제|교통 통제|버스 파업|출근길|퇴근길|귀성|귀경|탈선"),
    ("정치", r"대통령|국회|정부|여당|야당|민주당|국민의힘|장관|총리|선거|의원|청와대|대통령실|탄핵|외교|북한|국방"),
    ("경제", r"코스피|코스닥|환율|금리|증시|주가|물가|부동산|아파트|수출|무역|반도체|삼성|현대차|SK|LG|기업|실적|은행|고용"),
    ("국제", r"미국|중국|일본|러시아|우크라이나|이스라엘|트럼프|유엔|EU|중동|가자"),
    ("사회", r"경찰|검찰|법원|재판|수사|사건|사고|사망|부상|학교|병원|의료"),
]
WARN = re.compile(r"(호우|대설|태풍|강풍|풍랑|한파|폭염|건조|황사|폭풍해일|지진해일|안개)\s*(경보|주의보|특보)")
BREAK_HINT = re.compile(r"^\s*[\[【(]?\s*(속보|1보|긴급|단독)")


def fetch(url, timeout=20):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def ptime(t):
    if not t:
        return None
    try:
        d = parsedate_to_datetime(t)
    except Exception:
        try:
            d = datetime.fromisoformat(t.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=KST)
    return d.astimezone(timezone.utc)


DATELINE = re.compile(r"[\[【(（]\s*([가-힣]{2,4})\s*=\s*[가-힣A-Za-z]+\s*[\]】)）]")


# 일반 낱말과 겹치는 지명은 지역 판정에서 뺀다 (음성=소리, 예산=돈, 양산=대량생산 같은 것)
AMBIG = set("구리 양주 광명 공주 예산 부여 영양 고령 영광 장성 보은 상주 남해 양산 거창 인제 동해 진도 사천 성주 음성 장수 강화 이천 오산".split())
for _k in CITY:
    CITY[_k] = " ".join(w for w in CITY[_k].split() if w not in AMBIG)


def find_regions(text):
    out = []
    for r in REGIONS:
        if any(a in text for a in ALIASES[r]) or any(c in text for c in CITY.get(r, "").split()):
            out.append(r)
    return out


def category(text):
    for name, pat in CATS:
        if re.search(pat, text):
            return name
    return "기타"


def clean(t):
    t = re.sub(r"<[^>]+>", "", t or "").strip()
    return re.sub(r"\s+", " ", t)


def get_news():
    items, seen, errors = [], set(), []
    for src, url, flash in FEEDS:
        try:
            root = ET.fromstring(fetch(url))
        except Exception as e:
            errors.append(f"{src}: {e.__class__.__name__}")
            continue
        for it in root.iter("item"):
            title = clean(it.findtext("title"))
            link = (it.findtext("link") or "").strip()
            when = ptime(it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date"))
            source = src
            if src == "구글뉴스" and " - " in title:
                title, source = title.rsplit(" - ", 1)
            if not title or not link:
                continue
            key = re.sub(r"\W+", "", re.sub(r"^\[[^\]]+\]\s*", "", title))[:40]
            if key in seen:
                continue
            seen.add(key)
            desc = clean(it.findtext("description"))[:200]
            text = title + " " + desc
            # 지역: 제목에서 먼저 찾고, 없으면 기사 머리의 (부산=연합뉴스) 같은 발신지를 쓴다 (서울 발신은 전국 기사라 뺀다)
            regs = find_regions(title)
            if not regs:
                m = DATELINE.search(desc) or DATELINE.search(title)
                if m and m.group(1) != "서울":
                    regs = find_regions(m.group(1) + " ")
            breaking = bool(BREAK_HINT.search(title)) or (flash and "속보" in title)
            cat = category(title)
            items.append({
                "title": title, "source": source, "link": link,
                "time": when.isoformat() if when else None,
                "regions": regs, "cat": cat, "breaking": breaking,
                "warn": (WARN.search(text).group(0) if WARN.search(text) else None),
            })
    now = datetime.now(timezone.utc)
    items = [i for i in items if not i["time"] or now - datetime.fromisoformat(i["time"]) < timedelta(hours=24)]
    items.sort(key=lambda x: x["time"] or "", reverse=True)
    return items[:220], errors


WMO = {0: "맑음", 1: "대체로 맑음", 2: "구름 조금", 3: "흐림", 45: "안개", 48: "안개", 51: "이슬비", 53: "이슬비", 55: "이슬비",
       56: "어는 이슬비", 57: "어는 이슬비", 61: "비", 63: "비", 65: "강한 비", 66: "어는 비", 67: "어는 비", 71: "눈", 73: "눈",
       75: "많은 눈", 77: "싸락눈", 80: "소나기", 81: "소나기", 82: "강한 소나기", 85: "눈", 86: "많은 눈", 95: "뇌우", 96: "뇌우", 99: "뇌우"}


def pm_grade(v, kind):
    if v is None:
        return None
    cuts = (30, 80, 150) if kind == "pm10" else (15, 35, 75)
    return "좋음" if v <= cuts[0] else "보통" if v <= cuts[1] else "나쁨" if v <= cuts[2] else "매우나쁨"


def fetch_json(url, tries=3):
    for i in range(tries):
        try:
            return json.loads(fetch(url, 30))
        except Exception:
            if i == tries - 1:
                raise


def get_weather(points):
    lat = ",".join(str(p["lat"]) for p in points)
    lon = ",".join(str(p["lon"]) for p in points)
    w = fetch_json("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "timezone": "Asia/Seoul",
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max", "forecast_days": 1}))
    a = fetch_json("https://air-quality-api.open-meteo.com/v1/air-quality?" + urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "timezone": "Asia/Seoul", "current": "pm10,pm2_5"}))
    w = w if isinstance(w, list) else [w]
    a = a if isinstance(a, list) else [a]
    out = {}
    for p, wi, ai in zip(points, w, a):
        c, d, q = wi.get("current", {}), wi.get("daily", {}), ai.get("current", {})
        pm10, pm25 = q.get("pm10"), q.get("pm2_5")
        out[p["id"]] = {
            "temp": c.get("temperature_2m"), "feels": c.get("apparent_temperature"), "hum": c.get("relative_humidity_2m"),
            "rain": c.get("precipitation"), "wind": c.get("wind_speed_10m"), "code": c.get("weather_code"),
            "sky": WMO.get(c.get("weather_code"), "-"),
            "max": (d.get("temperature_2m_max") or [None])[0], "min": (d.get("temperature_2m_min") or [None])[0],
            "pop": (d.get("precipitation_probability_max") or [None])[0],
            "pm10": round(pm10) if pm10 is not None else None, "pm25": round(pm25) if pm25 is not None else None,
            "pm10g": pm_grade(pm10, "pm10"), "pm25g": pm_grade(pm25, "pm25"),
        }
    return out


def get_quakes():
    d = json.loads(fetch("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_week.geojson", 30))
    out = []
    for f in d.get("features", []):
        lon, lat = f["geometry"]["coordinates"][:2]
        p = f["properties"]
        if 32 <= lat <= 39.6 and 124 <= lon <= 131.6 and (p.get("mag") or 0) >= 2.0:
            out.append({"mag": p.get("mag"), "place": p.get("place"), "lat": lat, "lon": lon,
                        "time": datetime.fromtimestamp(p["time"] / 1000, timezone.utc).isoformat(), "url": p.get("url")})
    out.sort(key=lambda x: x["time"], reverse=True)
    return out[:20]


def main():
    regions = json.load(open("korea/map.json", encoding="utf-8"))["regions"]
    out = {"updated": datetime.now(timezone.utc).isoformat(), "errors": []}
    news, errs = get_news()
    out["errors"] += errs
    out["news"] = news
    counts = {r: 0 for r in REGIONS}
    for n in news:
        for r in n["regions"]:
            counts[r] += 1
    out["regionCounts"] = counts
    out["alerts"] = [n for n in news if n["cat"] == "재난" or n["warn"]][:40]
    out["traffic"] = [n for n in news if n["cat"] == "교통"][:40]
    try:
        out["weather"] = get_weather(regions)
    except Exception as e:
        out["errors"].append(f"weather: {e.__class__.__name__}")
    try:
        out["quakes"] = get_quakes()
    except Exception as e:
        out["errors"].append(f"quakes: {e.__class__.__name__}")
    with open("korea/data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
    print("korea:", len(news), "news,", len(out["alerts"]), "alerts,", len(out.get("weather", {})), "weather, errors", out["errors"], file=sys.stderr)


if __name__ == "__main__":
    main()
