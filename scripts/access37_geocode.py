"""001 §10 · 003 §4 B-1 — 대전 소방차 진입곤란 37개소 브이월드 좌표화 + 공간정보 SHP 대조.

규칙은 docs/판정기준.md §4-1 (산출 전 커밋 d93d3d6) 그대로.
키: os.environ["VWORLD_APIKEY"] 만 참조, 로그·파일에 키 없음(assert).
출력: data/vworld/national/derived/access37_geocode.json (v1) · access37_geocode_v2.json (--v2)
v2(§4-1-v2, 커밋 c1740bf): 줄기 상속 + refined 도로명 완전 일치만 인정.
"""
from __future__ import annotations

import glob
import json
import os
import sys
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd
import pyogrio
import shapely
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "data/vworld/national/raw/대전광역시_소방차 진입곤란지역 현황.csv"
SHP_GLOB = str(ROOT / "data/vworld/national/raw/daejeon_access_geo/*.shp")
V2 = "--v2" in sys.argv
OUT = ROOT / ("data/vworld/national/derived/access37_geocode_v2.json" if V2 else "data/vworld/national/derived/access37_geocode.json")
ROAD = re.compile(r"^([가-힣0-9]+?(?:대로|로|길))(\d+번안?길)?")
KEY = os.environ["VWORLD_APIKEY"].strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
API = "https://api.vworld.kr/req/address"
SGG = {"동구": "동구", "중구": "중구", "서구": "서구", "대덕": "대덕구", "유성": "유성구"}
TAIL = re.compile(r"\s*(일원|일대|일원지역|인근|주변)\s*$")


def pieces(text: str) -> list[str]:
    body = re.sub(r"\([^)]*\)", "", text)
    out = []
    for p in re.split(r"[~,/]", body):
        p = TAIL.sub("", p.strip())
        p = re.sub(r"^(대전\s*)?(동구|중구|서구|대덕구|유성구)\s+", "", p)
        p = re.sub(r"([가-힣0-9]+(?:로|길))\s+(\d+(?:번안?길))", r"\1\2", p)  # 대종로 601번길 → 대종로601번길
        p = re.sub(r"\s+", " ", p).strip()
        if p:
            if V2 and re.fullmatch(r"\d+(번안?길|길)", p) and out:  # 줄기 상속
                m = ROAD.match(out[-1].replace(" ", ""))
                if m:
                    p = m.group(1) + p
            out.append(p)
    return out


def road_of(p: str) -> str | None:
    m = ROAD.match(p.replace(" ", ""))
    return (m.group(1) + (m.group(2) or "")) if m else None


def v2_accept(piece: str, g: dict, sgg: str) -> bool:
    if not g.get("point") or not g.get("refined"):
        return False
    ref = g["refined"]
    if g["type"] == "parcel":
        dong = piece.split()[0]
        return dong in ref
    after = ref.split(sgg, 1)[-1].strip()
    tok = after.split(" ")[0] if after else ""
    return road_of(piece) is not None and tok == road_of(piece)


def geocode(address: str, kind: str) -> dict:
    q = urllib.parse.urlencode({"service": "address", "request": "getcoord", "version": "2.0", "crs": "epsg:4326",
                                "address": address, "refine": "true", "simple": "false", "format": "json",
                                "type": kind, "key": KEY, "domain": DOMAIN})
    last = None
    for attempt in range(1, 4):  # 재시도 3회
        try:
            b = urllib.request.urlopen(urllib.request.Request(f"{API}?{q}", headers={"User-Agent": "dflow-contest"}), timeout=30).read()
            r = json.loads(b.decode("utf-8"))["response"]
            pt = (r.get("result") or {}).get("point")
            return {"status": r.get("status"), "type": kind, "attempt": attempt,
                    "point": [float(pt["x"]), float(pt["y"])] if pt else None,
                    "refined": (r.get("refined") or {}).get("text"),
                    "error": ((r.get("error") or {}).get("text"))}
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}"
            time.sleep(1)
    return {"status": "EXCEPTION", "type": kind, "attempt": 3, "point": None, "error": last}


def key_of(s: str) -> str:
    m = re.search(r"\(([^)]*)\)", s or "")
    return re.sub(r"\s+", "", m.group(1) if m else (s or ""))


def main():
    df = pd.read_csv(CSV, encoding="cp949", dtype=str)
    shp = pyogrio.read_dataframe(glob.glob(SHP_GLOB)[0]).to_crs(5186)
    shp["k"] = shp["상세명"].map(key_of)
    tr = Transformer.from_crs(4326, 5186, always_xy=True)
    rows = []
    for _, r in df.iterrows():
        sgg = SGG[r["시군구"].strip()]
        text = r["소방차 진입 곤란(불가) 구간 세부현황"]
        res = []
        for p in pieces(text):
            kind = "parcel" if ("산" in p.split()[0][:2] or "번지" in p or re.search(r"\b산\s*\d", p)) else "road"
            g = geocode(f"대전광역시 {sgg} {p}", kind)
            g["piece"] = p
            g["v2_accepted"] = v2_accept(p, g, sgg) if V2 else None
            res.append(g)
        ok = [g for g in res if (g["v2_accepted"] if V2 else g["point"])]
        k = key_of(text)
        match = shp[shp.k == k]
        dists = []
        if len(match) and ok:
            line = match.geometry.iloc[0]
            for g in ok:
                x, y = tr.transform(*g["point"])
                dists.append(round(float(line.distance(shapely.Point(x, y))), 1))
        rows.append({"연번": int(r["연번"]), "시군구": sgg, "관할서": r["관할서"], "세부현황": text,
                     "사유": r["진입 곤란 사유"], "유형3": r["세부 구분"], "pieces": res,
                     "site_success": bool(ok), "n_pieces": len(res), "n_ok": len(ok),
                     "shp_match_key": k if len(match) else None, "dist_to_shp_line_m": dists})
    summary = {
        "sites": len(rows), "site_success": sum(x["site_success"] for x in rows),
        "pieces": sum(x["n_pieces"] for x in rows), "pieces_ok": sum(x["n_ok"] for x in rows),
        "shp_features": len(shp), "sites_matched_to_shp": sum(1 for x in rows if x["shp_match_key"]),
        "dist_all_m": sorted(d for x in rows for d in x["dist_to_shp_line_m"]),
    }
    res = {"rule_doc": "docs/판정기준.md §4-1" + ("-v2" if V2 else ""), "rule_commit": "c1740bf" if V2 else "d93d3d6",
           "summary": summary, "rows": rows}
    txt = json.dumps(res, ensure_ascii=False, indent=1)
    assert KEY not in txt
    OUT.write_text(txt, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    for x in rows:
        print(x["연번"], x["site_success"], f'{x["n_ok"]}/{x["n_pieces"]}', x["shp_match_key"], x["dist_to_shp_line_m"],
              [(g["piece"], g["status"], (g.get("refined") or "")[:30]) for g in x["pieces"]])


if __name__ == "__main__":
    main()
