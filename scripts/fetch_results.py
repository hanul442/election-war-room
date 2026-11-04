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
        out["governor"] = {"races": len(rows), "won": won, "states": rows}
    except Exception as e:
        out["errors"].append(f"governor: {e}")

    with open("results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("errors:", out["errors"], file=sys.stderr)


if __name__ == "__main__":
    main()
