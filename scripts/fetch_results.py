"""Pull House, Senate and governor results from NBC News results pages into results.json.

NBC's pages carry their data as JSON in a __NEXT_DATA__ script tag. We read
only the totals and per-state table, and always keep the source and time so
the page can show where the numbers came from.
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone

BASE = "https://www.nbcnews.com/politics/2026-elections/{}-results"


def page_props(office):
    req = urllib.request.Request(BASE.format(office), headers={"User-Agent": "Mozilla/5.0 election-war-room"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "ignore")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("no __NEXT_DATA__")
    return json.loads(m.group(1))["props"]["pageProps"]


def party_totals(bar):
    out = {}
    for k, key in (("dem", "D"), ("rep", "R"), ("ind", "O")):
        p = bar.get(k) or {}
        out[key] = {
            "called": int(p.get("total") or 0),
            "notUp": int(p.get("notUpForElection") or 0),
            "flips": int(p.get("flips") or 0),
            "netGain": int(p.get("netGain") or 0),
        }
    return out


def states_table(pp):
    rows = []
    for s in (pp.get("tableData") or {}).get("states", []):
        cands = []
        winner = None
        for k, key in (("dem", "D"), ("rep", "R"), ("ind", "O")):
            c = s.get(k) or {}
            if not c.get("lastName"):
                continue
            cands.append({"party": key, "name": c["lastName"], "pct": c.get("percentVote") or 0, "flip": bool(c.get("isFlip"))})
            if c.get("isWinner"):
                winner = key
        rows.append({"st": s.get("stateAbbr"), "name": s.get("stateName"), "in": s.get("percentIn") or 0, "winner": winner, "cands": cands})
    return rows


def reporting_from_rows(pcts, votes=None):
    """개표율 요약: 선거구 평균, 거의 다 센(95%+) 곳 수, 센 표 수."""
    pcts = [float(p or 0) for p in pcts]
    if not pcts:
        return None
    out = {"avgIn": round(sum(pcts) / len(pcts), 1), "races": len(pcts),
           "started": sum(1 for p in pcts if p > 0), "nearlyAll": sum(1 for p in pcts if p >= 95)}
    if votes is not None:
        out["totalVote"] = int(sum(votes))
    return out


def map_reporting(pp):
    tips = [v.get("tooltip") or {} for v in (pp.get("mapData") or {}).values() if isinstance(v, dict)]
    tips = [t for t in tips if "percentIn" in t]
    return reporting_from_rows([t.get("percentIn") for t in tips], [t.get("totalVote") or 0 for t in tips])


PARTY = {"Dem": "D", "Rep": "R"}
OFFICE_KO = {"H": "하원", "S": "상원", "G": "주지사"}


def calls_from(pp, office, flips=None):
    """당선 확정된 선거 목록: 지역, 당선자, 2위와의 차이."""
    out = []
    for key, v in (pp.get("mapData") or {}).items():
        t = (v or {}).get("tooltip") or {}
        cands = sorted(t.get("candidates") or [], key=lambda c: -(c.get("percentVote") or 0))
        win = next((c for c in cands if c.get("isWinner")), None)
        if not win:
            continue
        run = next((c for c in cands if c is not win), None)
        wp = PARTY.get(win.get("party"), "O")
        out.append({
            "id": f"{office}:{key}", "office": office, "officeKo": OFFICE_KO[office],
            "race": t.get("raceName") or key, "in": t.get("percentIn") or 0,
            "winner": win.get("name") or win.get("lastName"), "party": wp,
            "pct": win.get("percentVote") or 0, "incumbent": bool(win.get("isIncumbent")),
            "runner": (run or {}).get("name"), "runnerParty": PARTY.get((run or {}).get("party"), "O") if run else None,
            "runnerPct": (run or {}).get("percentVote") or 0,
            "flip": bool(flips and flips.get(key) == wp),
        })
    return out


def main():
    out = {"source": "NBC News Decision Desk", "updated": datetime.now(timezone.utc).isoformat(), "errors": []}

    try:
        h = page_props("house")
        bar = (h.get("bopData") or {}).get("bar") or {}
        model = h.get("houseModelData") or {}
        out["house"] = {
            "total": int(bar.get("maxValue") or 435),
            "majority": int(bar.get("indicatorValue") or 218),
            "parties": party_totals(bar),
            # NBC 하원 예측 모델: 최종 의석 추정치 (확정 아님)
            "model": {"D": model.get("dem"), "R": model.get("rep")} if model else None,
            "reporting": map_reporting(h),
        }
    except Exception as e:
        out["errors"].append(f"house: {e}")

    try:
        s = page_props("senate")
        bar = (s.get("bopData") or {}).get("bar") or {}
        out["senate"] = {
            "total": int(bar.get("maxValue") or 100),
            "majority": int(bar.get("indicatorValue") or 50) + 1,
            "upForElection": bar.get("upForElection"),
            "parties": party_totals(bar),
            "states": states_table(s),
            "reporting": map_reporting(s) or reporting_from_rows([r["in"] for r in states_table(s)]),
        }
    except Exception as e:
        out["errors"].append(f"senate: {e}")

    try:
        g = page_props("governor")
        rows = states_table(g)
        won = {"D": 0, "R": 0, "O": 0}
        for r in rows:
            if r["winner"]:
                won[r["winner"]] += 1
        out["governor"] = {"races": len(rows), "won": won, "states": rows,
                           "reporting": map_reporting(g) or reporting_from_rows([r["in"] for r in rows])}
    except Exception as e:
        out["errors"].append(f"governor: {e}")

    # 당선 확정 목록: 처음 확인한 시각을 기억해서 최근 확정 순으로
    try:
        prev = {c["id"]: c.get("calledAt") for c in json.load(open("results.json", encoding="utf-8")).get("calls", [])}
    except Exception:
        prev = {}
    calls = []
    for office, key in (("H", "house"), ("S", "senate"), ("G", "governor")):
        try:
            pp = page_props(key)
            flips = {r["st"]: r["winner"] for r in states_table(pp) if r["winner"] and any(c["flip"] and c["party"] == r["winner"] for c in r["cands"])}
            calls += calls_from(pp, office, flips)
        except Exception as e:
            out["errors"].append(f"calls {key}: {e}")
    now = out["updated"]
    for c in calls:
        c["calledAt"] = prev.get(c["id"]) or now
    calls.sort(key=lambda c: (c["calledAt"], {"S": 2, "G": 1, "H": 0}[c["office"]]), reverse=True)
    out["calls"] = calls

    with open("results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("errors:", out["errors"], file=sys.stderr)


if __name__ == "__main__":
    main()
