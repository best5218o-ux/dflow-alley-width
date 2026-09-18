"""006 §3-2(b) — 표준노드링크에 없는 진입곤란 26개소 × 브이월드 WFS lt_l_sprd(도로명주소도로) 대조.

기준: docs/판정기준.md §8 (실행 전 커밋 ab6e651). 결과를 보고 기준을 바꾸지 않는다.
키: os.environ["VWORLD_APIKEY"] 만 참조, 저장·출력에서 *** 치환.
출력: data/vworld/national/derived/missing_alley_crosscheck.json · missing_alley_crosscheck.csv
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd
import shapely
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as shp_transform

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"
KEY = os.environ["VWORLD_APIKEY"].strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
MATCH_M, HALF_M = 100.0, 300.0
T3857 = Transformer.from_crs(4326, 3857, always_xy=True)
T5186 = Transformer.from_crs(4326, 5186, always_xy=True)
T3857_5186 = Transformer.from_crs(3857, 5186, always_xy=True)


def mask(s):
    return str(s).replace(KEY, "***").replace(urllib.parse.quote(KEY), "***")


def wfs(typename, lon, lat):
    x, y = T3857.transform(lon, lat)
    q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": typename, "OUTPUT": "application/json",
         "MAXFEATURES": "1000", "SRSNAME": "EPSG:900913", "BBOX": f"{x-HALF_M},{y-HALF_M},{x+HALF_M},{y+HALF_M},EPSG:900913", "key": KEY, "domain": DOMAIN}
    url = "https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode(q)
    last = None
    for attempt in range(3):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"}), timeout=60).read()
            j = json.loads(b.decode("utf-8", "replace"))
            if "features" not in j:
                raise ValueError(mask(json.dumps(j, ensure_ascii=False)[:200]))
            return j["features"], None
        except Exception as e:  # noqa: BLE001
            last = mask(f"{type(e).__name__}: {e}")[:200]
            time.sleep(1.5 * (attempt + 1))
    return None, last


def norm(s):
    return "".join(str(s or "").split())


def main():
    links = pd.read_csv(DER / "access37_links.csv", dtype={"LINK_ID": str})
    geo = json.loads((DER / "access37_geocode_v2.json").read_text(encoding="utf-8"))
    present_sites = set(links[links.road_in_daejeon_nodelink == True].연번)  # noqa: E712
    rows_out, sites = [], []
    for r in geo["rows"]:
        if not r["site_success"] or r["연번"] in present_sites:
            continue
        pieces = [p for p in r["pieces"] if p.get("v2_accepted")]
        site = {"연번": r["연번"], "시군구": r["시군구"], "세부현황": r["세부현황"], "사유": r["사유"], "pieces": []}
        for p in pieces:
            rec = {"piece": p["piece"], "type": p["type"], "point": p["point"]}
            if p["type"] != "road":
                rec["result"] = "대조 대상 아님(지번)"
                site["pieces"].append(rec)
                continue
            name = norm(p["refined"].split(" ")[2]) if p.get("refined") and len(p["refined"].split(" ")) > 2 else norm(p["piece"])
            rec["road_name"] = name
            pt = shapely.Point(*T5186.transform(*p["point"]))
            feats, err = wfs("lt_l_sprd", *p["point"])
            if feats is None:
                rec.update(result="판정불가", error=err)
            else:
                same = []
                for f in feats:
                    if norm(f["properties"].get("rn")) == name:
                        g = shp_transform(lambda x, y, z=None: T3857_5186.transform(x, y), shape(f["geometry"]))
                        same.append({"dist_m": round(pt.distance(g), 1), "road_bt": f["properties"].get("road_bt"),
                                     "road_lt": f["properties"].get("road_lt"), "rds_man_no": f["properties"].get("rds_man_no")})
                same.sort(key=lambda d: d["dist_m"])
                near = [d for d in same if d["dist_m"] <= MATCH_M]
                rec.update(result="있음" if near else "없음", features_in_bbox=len(feats), same_name_features=len(same),
                           nearest_same_name_m=same[0]["dist_m"] if same else None,
                           ref_road_bt=[d["road_bt"] for d in near], ref_road_lt=[d["road_lt"] for d in near])
            c_feats, c_err = wfs("lt_l_n3a0020000", *p["point"])
            if c_feats is None:
                rec["ref_centerline_rdnm_match"] = f"조회 실패: {c_err}"
            else:
                rec["ref_centerline_rdnm_match"] = any(norm(f["properties"].get("rdnm")) == name for f in c_feats)
                rec["ref_centerline_features_in_bbox"] = len(c_feats)
            site["pieces"].append(rec)
            rows_out.append({"연번": r["연번"], "piece": p["piece"], "road_name": name, "result": rec["result"],
                             "nearest_same_name_m": rec.get("nearest_same_name_m"), "ref_road_bt": rec.get("ref_road_bt"),
                             "ref_centerline_rdnm_match": rec.get("ref_centerline_rdnm_match"), "error": rec.get("error")})
            time.sleep(0.2)
        rs = [p["result"] for p in site["pieces"] if p["type"] == "road"]
        if not rs:
            site["site_result"] = "판정불가"
            site["site_reason"] = "도로명 조각 없음(지번뿐)"
        elif "있음" in rs:
            site["site_result"] = "있음"
        elif all(x == "없음" for x in rs):
            site["site_result"] = "없음"
        else:
            site["site_result"] = "판정불가"
            site["site_reason"] = "조회 실패 조각 존재"
        sites.append(site)
    counts = pd.Series([s["site_result"] for s in sites]).value_counts().to_dict()
    bt = [b for s in sites for p in s["pieces"] for b in (p.get("ref_road_bt") or [])]
    out = {"rule_doc": "docs/판정기준.md §8", "rule_commit": "ab6e651", "layer": "lt_l_sprd(도로명주소도로)",
           "sites_total": len(sites), "site_counts": counts,
           "piece_counts": pd.Series([p["result"] for s in sites for p in s["pieces"]]).value_counts().to_dict(),
           "ref_road_bt_on_matched": {"values": bt, "non_null": sum(1 for b in bt if b not in (None, "", 0)), "n": len(bt)},
           "sites": sites}
    (DER / "missing_alley_crosscheck.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    pd.DataFrame(rows_out).to_csv(DER / "missing_alley_crosscheck.csv", index=False, encoding="utf-8-sig")
    print(json.dumps({k: out[k] for k in ("sites_total", "site_counts", "piece_counts", "ref_road_bt_on_matched")}, ensure_ascii=False))
    for s in sites:
        print(s["연번"], s["site_result"], s.get("site_reason", ""), [(p["piece"], p["result"], p.get("nearest_same_name_m"), p.get("ref_road_bt"), p.get("ref_centerline_rdnm_match")) for p in s["pieces"]])


if __name__ == "__main__":
    main()
