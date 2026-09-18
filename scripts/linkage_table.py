"""009 §7-2 — 연계 테이블: 브이월드 도로명주소도로(lt_l_sprd) ↔ 표준노드링크(MOCT_LINK 2026-09-14).

기준: docs/판정기준.md §14 (실행 전 커밋 3a36588). 결과를 보고 기준을 바꾸지 않는다.
- 행 단위: 진입곤란 v2 33개소의 도로명 조각 × 조각 100 m 이내 같은 도로명 lt_l_sprd 피처
- 매칭: 같은 ROAD_NAME 링크와 최단거리 ≤ 30 m / 신뢰도 상(≤15 m ∧ 링크 중점 30 m 이내)·중
- 미매칭 사유 U1~U4 · 참고 최근접 링크(도로명 무관)
- 키: os.environ["VWORLD_APIKEY"] 만, 출력에 키 없음
출력: data/vworld/national/derived/linkage_table.csv · linkage_table.json
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd
import pyogrio
import shapely
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform as shp_transform

ROOT = Path(__file__).resolve().parents[1]   # 저장소 루트(scripts/ 한 단계 위)
DER = ROOT / "data/vworld/national/derived"
LINK = ROOT / "data/vworld/national/raw/NODELINKDATA_20260914/MOCT_LINK.shp"
KEY = os.environ.get("VWORLD_APIKEY", "").strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
if not KEY:
    # 2026-09-18: 네트워크 단계(브이월드 WFS/WMS 조회)라 키 없이는 재수급할 수 없다. 원 실행(2026-09-15~16) 산출은
    # data/vworld/national/derived/linkage_table.json · linkage_table.csv 에 있고, 검증은 scripts/verify_deliverables.py 로 한다.
    sys.exit("VWORLD_APIKEY 없음 — 이 스크립트는 브이월드 API 조회 단계다. 원 실행 산출: data/vworld/national/derived/linkage_table.json · linkage_table.csv")
RULE = "3a36588"
T43 = Transformer.from_crs(4326, 3857, always_xy=True)
T45 = Transformer.from_crs(4326, 5186, always_xy=True)
T35 = Transformer.from_crs(3857, 5186, always_xy=True)
DAEJEON = tuple(str(i) for i in range(183, 188))


def norm(s):
    return "".join(str(s or "").split())


def wfs(lon, lat, half=300.0):
    x, y = T43.transform(lon, lat)
    q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": "lt_l_sprd", "OUTPUT": "application/json",
         "MAXFEATURES": "1000", "SRSNAME": "EPSG:900913", "BBOX": f"{x-half},{y-half},{x+half},{y+half},EPSG:900913", "key": KEY, "domain": DOMAIN}
    url = "https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode(q)
    err = None
    for attempt in range(3):
        try:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"}), timeout=60).read())
            if "features" in j:
                return j["features"], None
            err = "features 없음"
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}"
        time.sleep(1.5 * (attempt + 1))
    return None, err


def main():
    today = dt.date.today().isoformat()
    links = pyogrio.read_dataframe(LINK, columns=["LINK_ID", "ROAD_NAME"], encoding="cp949",
                                   bbox=(215000, 395000, 255000, 435000))  # 대전 권역 상자(EPSG:5186 근사) — 아래에서 LINK_ID 앞 3자리로 다시 거름
    links = links[links.LINK_ID.astype(str).str[:3].isin(DAEJEON)].copy()
    links["nm"] = links.ROAD_NAME.map(norm)
    by_name = {k: g for k, g in links.groupby("nm")}
    tree = shapely.STRtree(links.geometry.values)
    geo = json.loads((DER / "access37_geocode_v2.json").read_text(encoding="utf-8"))
    rows = []
    for r in geo["rows"]:
        if not r["site_success"]:
            continue
        for p in [p for p in r["pieces"] if p.get("v2_accepted")]:
            base = {"연번": r["연번"], "piece": p["piece"], "기준커밋": RULE, "조회일": today}
            if p["type"] != "road":
                rows.append({**base, "road_name": None, "unmatched_reason": "U4 지번 조각(도로명 없음)"})
                continue
            parts = p["refined"].split(" ") if p.get("refined") else []
            name = norm(parts[2]) if len(parts) > 2 else norm(p["piece"])
            pt5186 = Point(*T45.transform(*p["point"]))
            feats, err = wfs(*p["point"])
            if feats is None:
                rows.append({**base, "road_name": name, "unmatched_reason": f"U3 도로명주소도로 조회 실패({err})"})
                continue
            same = []
            for f in feats:
                if norm(f["properties"].get("rn")) != name:
                    continue
                g = shp_transform(lambda x, y, z=None: T35.transform(x, y), shape(f["geometry"]))
                if g.distance(pt5186) <= 100:
                    same.append((g, f["properties"]))
            if not same:
                rows.append({**base, "road_name": name, "unmatched_reason": "U3 조각 100 m 이내 같은 도로명 도로명주소도로 없음"})
                continue
            cand = by_name.get(name)
            for g, pr in same:
                rec = {**base, "road_name": name, "rds_man_no": pr.get("rds_man_no"), "sig_cd": pr.get("sig_cd"),
                       "road_bt_단위미확인": pr.get("road_bt"), "road_lt": pr.get("road_lt")}
                ni = int(tree.nearest(g))
                rec.update(ref_nearest_link_id=str(links.LINK_ID.iloc[ni]), ref_nearest_link_road_name=links.ROAD_NAME.iloc[ni],
                           ref_nearest_link_dist_m=round(float(links.geometry.iloc[ni].distance(g)), 1))
                if cand is None or cand.empty:
                    rec["unmatched_reason"] = "U1 대전 표준노드링크 전체에 같은 도로명 링크 없음"
                else:
                    d = cand.geometry.distance(g)
                    j = d.idxmin()
                    dmin = float(d.min())
                    if dmin <= 30:
                        mid = cand.geometry.loc[j].interpolate(0.5, normalized=True)
                        conf = "상" if (dmin <= 15 and mid.distance(g) <= 30) else "중"
                        rec.update(link_id=str(cand.LINK_ID.loc[j]), link_road_name=cand.ROAD_NAME.loc[j], dist_m=round(dmin, 1), confidence=conf)
                    else:
                        rec.update(unmatched_reason="U2 같은 도로명 링크는 있으나 30 m 밖", ref_same_name_link_dist_m=round(dmin, 1))
                rows.append(rec)
            time.sleep(0.2)
    df = pd.DataFrame(rows)
    df.to_csv(DER / "linkage_table.csv", index=False, encoding="utf-8-sig")
    matched = df[df.get("link_id").notna()] if "link_id" in df else df.iloc[0:0]
    summary = {
        "rule_doc": "docs/판정기준.md §14", "rule_commit": RULE, "date": today,
        "nodelink": "MOCT_LINK 2026-09-14 대전 권역(LINK_ID 183~187)", "nodelink_links": int(len(links)),
        "rows": int(len(df)), "matched_rows": int(len(matched)),
        "confidence": matched["confidence"].value_counts().to_dict() if len(matched) else {},
        "unmatched_rows": int(df["unmatched_reason"].notna().sum()) if "unmatched_reason" in df else 0,
        "unmatched_by_reason": df["unmatched_reason"].str[:2].value_counts().to_dict() if "unmatched_reason" in df else {},
        "sites_with_any_match": int(matched["연번"].nunique()) if len(matched) else 0,
        "schema": list(df.columns),
    }
    (DER / "linkage_table.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
