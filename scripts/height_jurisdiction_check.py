"""010 §2-2 높이 L1 · §2-3 연번 37 관할 — 기준 docs/판정기준.md §17·§18 (실행 전 커밋 8a58784).

- 높이: 26개소 도로명 조각 좌표 반경 300 m 상자로 lt_l_c5heightbarrier(높이장애물) 조회, 100 m 이내 피처 유무·속성
- 노면: lt_c_b3surfacemark · lt_l_b2surfacelinemark 조회 건수만(노면 표시 — 노면 상태 속성 아님)
- 연번 37: lt_c_usfsffb(소방서관할구역) 을 조각 좌표로 조회, 포함 폴리곤 속성 전부
키: os.environ["VWORLD_APIKEY"] 만. 출력: data/vworld/national/derived/height_jurisdiction_check.json
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

import shapely
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform as shp_transform

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"
KEY = os.environ["VWORLD_APIKEY"].strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
T43 = Transformer.from_crs(4326, 3857, always_xy=True)
T45 = Transformer.from_crs(4326, 5186, always_xy=True)
T35 = Transformer.from_crs(3857, 5186, always_xy=True)


def wfs(typename, lon, lat, half):
    x, y = T43.transform(lon, lat)
    q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": typename, "OUTPUT": "application/json",
         "MAXFEATURES": "1000", "SRSNAME": "EPSG:900913", "BBOX": f"{x-half},{y-half},{x+half},{y+half},EPSG:900913", "key": KEY, "domain": DOMAIN}
    url = "https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode(q)
    err = None
    for attempt in range(3):
        try:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"}), timeout=60).read())
            if "features" in j:
                return j["features"], None
            err = json.dumps(j, ensure_ascii=False)[:200].replace(KEY, "***")
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}"
        time.sleep(1.5 * (attempt + 1))
    return None, err


def main():
    cc = json.loads((DER / "missing_alley_crosscheck.json").read_text(encoding="utf-8"))
    geo = json.loads((DER / "access37_geocode_v2.json").read_text(encoding="utf-8"))
    height, surface = [], []
    for s in cc["sites"]:
        for p in s["pieces"]:
            if p["type"] != "road":
                continue
            lon, lat = p["point"]
            pt = Point(*T45.transform(lon, lat))
            feats, err = wfs("lt_l_c5heightbarrier", lon, lat, 300)
            rec = {"연번": s["연번"], "piece": p["piece"], "error": err}
            if feats is not None:
                near = []
                for f in feats:
                    g = shp_transform(lambda x, y, z=None: T35.transform(x, y), shape(f["geometry"]))
                    if g.distance(pt) <= 100:
                        near.append(f["properties"])
                rec.update(in_box=len(feats), within_100m=len(near), sample_props=near[:2])
            height.append(rec)
            sm, e1 = wfs("lt_c_b3surfacemark", lon, lat, 100)
            sl, e2 = wfs("lt_l_b2surfacelinemark", lon, lat, 100)
            surface.append({"연번": s["연번"], "piece": p["piece"], "surfacemark_in_box": None if sm is None else len(sm),
                            "surfacelinemark_in_box": None if sl is None else len(sl), "sample_props": (sm or sl or [{}])[0].get("properties") if (sm or sl) else None})
            time.sleep(0.15)
    # 연번 37
    r37 = next(r for r in geo["rows"] if r["연번"] == 37)
    juris = []
    for p in [p for p in r37["pieces"] if p.get("v2_accepted")]:
        lon, lat = p["point"]
        pt = Point(*T45.transform(lon, lat))
        feats, err = wfs("lt_c_usfsffb", lon, lat, 50)
        props = []
        for f in feats or []:
            g = shp_transform(lambda x, y, z=None: T35.transform(x, y), shape(f["geometry"]))
            if g.contains(pt):
                props.append(f["properties"])
        juris.append({"piece": p["piece"], "refined": p.get("refined"), "error": err, "containing_polygons": props,
                      "features_in_box": None if feats is None else len(feats)})
    sites_with_height = sorted({h["연번"] for h in height if h.get("within_100m")})
    out = {"rule_commit": "8a58784",
           "height": {"layer": "lt_l_c5heightbarrier(높이장애물)", "pieces": len(height), "query_errors": sum(1 for h in height if h["error"]),
                      "pieces_with_features_in_box": sum(1 for h in height if h.get("in_box")), "sites_with_feature_within_100m": sites_with_height,
                      "rows": height},
           "surface": {"layers": ["lt_c_b3surfacemark(노면표시)", "lt_l_b2surfacelinemark(노면선표시)"], "note": "노면 표시 — 포장·노면 상태 속성 아님",
                       "pieces_with_any": sum(1 for s in surface if (s["surfacemark_in_box"] or 0) + (s["surfacelinemark_in_box"] or 0) > 0), "rows": surface},
           "site37": {"세부현황": r37["세부현황"], "시군구": r37["시군구"], "관할서": r37.get("관할서"), "pieces": juris}}
    (DER / "height_jurisdiction_check.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"height": {k: out["height"][k] for k in ("pieces", "query_errors", "pieces_with_features_in_box", "sites_with_feature_within_100m")},
                      "surface_pieces_with_any": out["surface"]["pieces_with_any"], "surface_sample": next((s["sample_props"] for s in surface if s["sample_props"]), None),
                      "site37": out["site37"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
