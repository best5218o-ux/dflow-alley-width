"""018 §2 — 연속수치지형도 계열 브이월드 노출·속성 확인. 키는 os.environ 만 참조, 로그·산출에 *** 마스킹.

단계 1 probe : WFS DescribeFeatureType(도로중심선 lt_l_n3a0020000) + 도로경계 면·담장·옹벽·계단 후보 타입명 노출 여부
단계 2 sites : 26개소 조각 지점 반경에서 도로중심선 GetFeature → RVWD 채움·값·도로구분 코드
단계 3 fill  : 대전 격자 표본에서 소로 구간 RVWD 채움률
출력: data/vworld/national/derived/ngii_width_probe.json
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"
KEY = os.environ["VWORLD_APIKEY"].strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
T3857 = Transformer.from_crs(4326, 3857, always_xy=True)
CENTER = "lt_l_n3a0020000"
CANDIDATES = ["lt_a_n3a0010000", "lt_l_n3a0010000", "lt_c_n3a0010000", "lt_a_n3a0020000",
              "lt_l_n3b0020000", "lt_l_n3f0040000", "lt_a_n3c0390000", "lt_c_n3c0390000",
              "lt_l_n3l_a0010000", "lt_a_n3a_a0010000"]


def mask(s):
    return str(s).replace(KEY, "***").replace(urllib.parse.quote(KEY), "***")


def req(params, timeout=60):
    url = "https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode({**params, "key": KEY, "domain": DOMAIN})
    last = None
    for a in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"}), timeout=timeout) as r:
                return r.read().decode("utf-8", "replace"), None
        except Exception as e:  # noqa: BLE001
            last = mask(f"{type(e).__name__}: {e}")[:200]
            time.sleep(1.2 * (a + 1))
    return None, last


def getfeat(typename, lon, lat, half=200.0, props=None):
    x, y = T3857.transform(lon, lat)
    q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": typename,
         "OUTPUT": "application/json", "MAXFEATURES": "1000", "SRSNAME": "EPSG:900913",
         "BBOX": f"{x-half},{y-half},{x+half},{y+half},EPSG:900913"}
    if props:
        q["PROPERTYNAME"] = props
    t, err = req(q)
    if t is None:
        return None, err
    try:
        j = json.loads(t)
    except Exception:  # noqa: BLE001
        return None, mask(t[:200])
    if "features" not in j:
        return None, mask(json.dumps(j, ensure_ascii=False)[:200])
    return j["features"], None


def probe():
    out = {}
    t, err = req({"SERVICE": "WFS", "REQUEST": "DescribeFeatureType", "VERSION": "1.1.0", "TYPENAME": CENTER})
    out["describe_center"] = {"error": err, "text": mask(t)[:4000] if t else None}
    cand = {}
    for c in CANDIDATES:
        f, e = getfeat(c, 127.4200, 36.3400, 200.0)
        cand[c] = {"features": None if f is None else len(f), "error": e}
    out["candidate_typenames"] = cand
    return out



BOUND = "lt_c_n3a0010000"   # 도로경계(면) — probe 에서 응답 확인
WALL, RETW, STAIR = "lt_l_n3b0020000", "lt_l_n3f0040000", "lt_c_n3c0390000"  # 담장·옹벽·계단
CPROPS = "rdnu,rddv,rdln,rvwd,rdnm,scls,rest,pvqt"


def sites():
    import shapely
    from shapely.ops import transform as sh_transform
    from shapely.geometry import shape, Point
    cc = json.loads((DER / "missing_alley_crosscheck.json").read_text(encoding="utf-8"))
    T5186 = Transformer.from_crs(4326, 5186, always_xy=True)
    T900913_5186 = Transformer.from_crs(3857, 5186, always_xy=True)
    rows = []
    for s in cc["sites"]:
        for pc in s["pieces"]:
            if pc["type"] != "road":
                continue
            lon, lat = pc["point"]
            px, py = T5186.transform(lon, lat)
            pt = Point(px, py)
            r = {"site": s.get("번호"), "piece": pc["piece"], "road_name": pc.get("road_name"), "point": [lon, lat]}
            f, e = getfeat(CENTER, lon, lat, 120.0)
            if f is None:
                r["center_error"] = e
            else:
                items = []
                for ft in f:
                    g = sh_transform(lambda x, y: T900913_5186.transform(x, y), shape(ft["geometry"]))
                    pr = ft["properties"]
                    items.append({"d": round(g.distance(pt), 1), "rvwd": pr.get("rvwd"), "rddv": pr.get("rddv"),
                                  "scls": pr.get("scls"), "rdnm": pr.get("rdnm"), "rdln": pr.get("rdln"), "pvqt": pr.get("pvqt")})
                items.sort(key=lambda z: z["d"])
                r["center_n"] = len(items)
                r["center_nearest"] = items[:3]
                r["center_rvwd_filled_within_30m"] = sum(1 for i in items if i["d"] <= 30 and i["rvwd"] not in (None, "", 0))
                r["center_within_30m"] = sum(1 for i in items if i["d"] <= 30)
            b, e2 = getfeat(BOUND, lon, lat, 120.0)
            if b is None:
                r["bound_error"] = e2
            else:
                polys = [sh_transform(lambda x, y: T900913_5186.transform(x, y), shape(ft["geometry"])) for ft in b]
                ds = sorted(round(g.distance(pt), 1) for g in polys)
                r["bound_n"] = len(polys)
                r["bound_nearest_m"] = ds[0] if ds else None
                r["bound_contains_point"] = any(g.covers(pt) for g in polys)
                r["bound_props_nearest"] = b[int(min(range(len(polys)), key=lambda i: polys[i].distance(pt)))]["properties"] if polys else None
            for key, tn in (("wall", WALL), ("retw", RETW), ("stair", STAIR)):
                ff, ee = getfeat(tn, lon, lat, 120.0)
                r[key] = None if ff is None else len(ff)
                if ff is None:
                    r[key + "_error"] = ee
            rows.append(r)
            print(json.dumps(r, ensure_ascii=False)[:300], flush=True)
    return {"sites_pieces": rows}


def fill():
    import random
    import shapely
    from shapely.geometry import shape, Point
    T3857 = Transformer.from_crs(4326, 3857, always_xy=True)
    gu, e = getfeat("lt_c_adsigg", 127.40, 36.34, 30000.0)
    polys = [shape(f["geometry"]) for f in gu if str(f["properties"].get("sig_cd", "")).startswith("30")] if gu else []
    if not polys:
        return {"fill": {"error": e or "대전 시군구 폴리곤 미조회"}}
    area = shapely.union_all(polys)
    minx, miny, maxx, maxy = area.bounds
    random.seed(18)
    cells, tries = [], 0
    while len(cells) < 40 and tries < 400:
        tries += 1
        x = random.uniform(minx, maxx); y = random.uniform(miny, maxy)
        if area.covers(Point(x, y)):
            cells.append((x, y))
    stats = {}
    errs = []
    for x, y in cells:
        q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": CENTER,
             "OUTPUT": "application/json", "MAXFEATURES": "1000", "SRSNAME": "EPSG:900913",
             "PROPERTYNAME": CPROPS,
             "BBOX": f"{x-250},{y-250},{x+250},{y+250},EPSG:900913"}
        t, err = req(q)
        if t is None:
            errs.append(err); continue
        try:
            fs = json.loads(t)["features"]
        except Exception:  # noqa: BLE001
            errs.append(mask(t[:150])); continue
        for ft in fs:
            pr = ft["properties"]
            k = f"{pr.get('rddv')}|{pr.get('scls')}"
            d = stats.setdefault(k, {"n": 0, "rvwd_filled": 0, "vals": []})
            d["n"] += 1
            v = pr.get("rvwd")
            if v not in (None, "", 0):
                d["rvwd_filled"] += 1
                d["vals"].append(float(v))
    for k, d in stats.items():
        v = sorted(d["vals"])
        d["min"], d["max"] = (v[0], v[-1]) if v else (None, None)
        d["median"] = v[len(v) // 2] if v else None
        d["vals"] = v[:0]
    return {"fill": {"cells": len(cells), "cell_half_m": 250, "errors": errs[:5], "by_rddv_scls": stats}}


def main():
    step = sys.argv[1] if len(sys.argv) > 1 else "probe"
    p = DER / "ngii_width_probe.json"
    out = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    if step == "probe":
        out.update(probe())
    elif step == "sites":
        out.update(sites())
    elif step == "fill":
        out.update(fill())
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k not in ("describe_center", "sites_pieces")}, ensure_ascii=False)[:4000])


if __name__ == "__main__":
    main()
