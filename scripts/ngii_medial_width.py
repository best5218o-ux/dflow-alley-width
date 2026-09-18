"""019 §3 — 도로경계 면 내접폭 · 장애물 차감폭. 기준 docs/판정기준.md §29 (실행 전 커밋 d182518).

산출값은 「도로경계 면 내접폭」이다. 「통과가능폭」이 아니다.
도로경계 면이 무엇을 경계로 삼는지(포장 경계·도로구역 경계 등)는 미확인 — 브이월드가 주는 속성은 id·dycd 뿐(SCLS 미제공).
축선 귀속은 이름이 아니라 거리다(도로중심선 rdnm 이 비어 있음) → 「차이」가 값 오차인지 귀속 오차인지 구분되지 않는다.
키는 os.environ["VWORLD_APIKEY"] 만 참조 · 로그·산출에서 *** 마스킹.
출력: data/vworld/national/derived/ngii_medial_width.json · deliverables/{AI-C_도로경계내접폭_5자대조,도로경계내접폭_26개소}.csv
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
from shapely.ops import transform as sh_transform

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"
DELIV = ROOT / "deliverables"
KEY = os.environ["VWORLD_APIKEY"].strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
T3857 = Transformer.from_crs(4326, 3857, always_xy=True)
T5186 = Transformer.from_crs(4326, 5186, always_xy=True)
T900913_5186 = Transformer.from_crs(3857, 5186, always_xy=True)
BOUND, CENTER = "lt_c_n3a0010000", "lt_l_n3a0020000"
OBST = {"wall": "lt_l_n3b0020000", "retaining": "lt_l_n3f0040000", "stair": "lt_c_n3c0390000"}
HALF = 200.0
STEP, TRIM, MIN_LEN, MIN_PTS = 1.0, 2.0, 10.0, 8


def mask(s):
    return str(s).replace(KEY, "***").replace(urllib.parse.quote(KEY), "***")


def wfs(typename, x, y, half=HALF):
    q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": typename,
         "OUTPUT": "application/json", "MAXFEATURES": "1000", "SRSNAME": "EPSG:900913",
         "BBOX": f"{x-half},{y-half},{x+half},{y+half},EPSG:900913", "key": KEY, "domain": DOMAIN}
    url = "https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode(q)
    last = None
    for a in range(3):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"}), timeout=90).read()
            return json.loads(b.decode("utf-8", "replace"))["features"], None
        except Exception as e:  # noqa: BLE001
            last = mask(f"{type(e).__name__}: {e}")[:160]
            time.sleep(1.5 * (a + 1))
    return None, last


def to5186(features):
    return [sh_transform(lambda a, b: T900913_5186.transform(a, b), shape(f["geometry"])) for f in features]


def band(w):
    if w is None:
        return "UNKNOWN_FAIL_CLOSED"
    if w <= 2.5:
        return "BLOCKED"        # 문헌 인용(소방차 표준 폭 2.2~2.5 m)
    if w <= 3.5:
        return "CONDITIONAL_C"  # 우리 설정(근거 문헌 미확보)
    return "폭축_통과후보"


def piece_width(lon, lat):
    x3, y3 = T3857.transform(lon, lat)
    pt = Point(*T5186.transform(lon, lat))
    r = {}
    bf, e1 = wfs(BOUND, x3, y3)
    cf, e2 = wfs(CENTER, x3, y3)
    if bf is None or cf is None:
        r["error"] = f"미조회: {e1 or ''}{e2 or ''}"
        return r
    polys = to5186(bf)
    area = shapely.union_all(polys) if polys else None
    lines = to5186(cf)
    props = [f["properties"] for f in cf]
    if not lines or area is None or area.is_empty:
        r["error"] = "면 또는 축선 피처 0"
        return r
    i = min(range(len(lines)), key=lambda k: lines[k].distance(pt))
    axis, apr = lines[i], props[i]
    r["axis"] = {"d_to_piece_m": round(axis.distance(pt), 1), "rvwd": apr.get("rvwd"), "rddv": apr.get("rddv"),
                 "rdnm": apr.get("rdnm"), "len_m": round(axis.length, 1),
                 "귀속": "이름 아님 — 거리 기반(도로중심선 rdnm 비어 있음)"}
    inside = axis.intersection(area)
    if inside.is_empty:
        r["error"] = "축선이 도로경계 면 안에 들어가지 않음"
        return r
    parts = list(getattr(inside, "geoms", [inside]))
    parts = [p for p in parts if p.geom_type in ("LineString", "MultiLineString") and p.length > 0]
    if not parts:
        r["error"] = "면 안 축선 구간 없음"
        return r
    seg = min(parts, key=lambda p: p.distance(pt))
    r["inside_len_m"] = round(seg.length, 1)
    if seg.length < MIN_LEN + 2 * TRIM:
        r["band"] = "UNKNOWN_FAIL_CLOSED"
        r["reason"] = f"면 안 축선 {seg.length:.1f} m < {MIN_LEN + 2*TRIM} m"
        return r
    obst = {}
    for k, tn in OBST.items():
        ff, err = wfs(tn, x3, y3)
        if ff is None:
            obst[k] = {"error": err}
        else:
            obst[k] = {"n": len(ff), "geoms": to5186(ff)}
    ogeoms = [g for v in obst.values() for g in v.get("geoms", [])]
    ounion = shapely.union_all(ogeoms) if ogeoms else None
    bnd = area.boundary
    n = int((seg.length - 2 * TRIM) // STEP) + 1
    loc, loc_d, used = [], [], 0
    for k in range(n):
        p = seg.interpolate(TRIM + k * STEP)
        if not area.covers(p):
            continue
        used += 1
        rad = bnd.distance(p)
        loc.append(2 * rad)
        loc_d.append(2 * min(rad, ounion.distance(p)) if ounion is not None else 2 * rad)
    r["samples"] = used
    r["obstacle_counts"] = {k: v.get("n", v.get("error")) for k, v in obst.items()}
    if used < MIN_PTS:
        r["band"] = "UNKNOWN_FAIL_CLOSED"
        r["reason"] = f"유효 표본점 {used} < {MIN_PTS}"
        return r
    s = sorted(loc)
    sd = sorted(loc_d)
    r["inscribed_min_m"] = round(s[0], 2)
    r["inscribed_p10_m"] = round(s[max(0, int(0.1 * len(s)) - 1)], 2)
    r["inscribed_median_m"] = round(s[len(s) // 2], 2)
    r["deducted_min_m"] = round(sd[0], 2)
    r["deducted_median_m"] = round(sd[len(sd) // 2], 2)
    r["band"] = band(r["inscribed_min_m"])
    r["band_deducted"] = band(r["deducted_min_m"])
    return r


def main():
    cc = json.loads((DER / "missing_alley_crosscheck.json").read_text(encoding="utf-8"))
    probe = {x["piece"]: x for x in json.loads((DER / "ngii_width_probe.json").read_text(encoding="utf-8"))["sites_pieces"]}
    rows = []
    for s in cc["sites"]:
        for pc in s["pieces"]:
            if pc["type"] != "road":
                continue
            lon, lat = pc["point"]
            r = {"site": s.get("번호"), "sigg": s.get("시군구"), "piece": pc["piece"], "road_name": pc.get("road_name"),
                 "road_bt_ref": pc.get("ref_road_bt"), "point": [lon, lat]}
            r.update(piece_width(lon, lat))
            pr = probe.get(pc["piece"], {})
            r["rvwd_nearest"] = (pr.get("center_nearest") or [{}])[0].get("rvwd")
            rows.append(r)
            print(json.dumps({k: v for k, v in r.items() if k not in ("point",)}, ensure_ascii=False)[:320], flush=True)
    out = {"rule_doc": "docs/판정기준.md §29", "rule_commit": "d182518",
           "name": "도로경계 면 내접폭 · 장애물 차감폭 (「통과가능폭」 아님)",
           "boundary_definition": "미확인 — 브이월드 제공 속성 id·dycd 뿐(설명서상 SCLS 미제공). 포장 경계인지 도로구역 경계인지 확인하지 못했다",
           "attribution_limit": "축선 귀속은 거리 기반(도로중심선 rdnm 비어 있음) — 「차이」가 값 오차인지 귀속 오차인지 구분되지 않는다",
           "params": {"bbox_half_m": HALF, "step_m": STEP, "trim_m": TRIM, "min_inside_len_m": MIN_LEN, "min_points": MIN_PTS},
           "pieces": rows}
    (DER / "ngii_medial_width.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = [r for r in rows if r.get("inscribed_min_m") is not None]
    print("조각", len(rows), "산출", len(ok), "미산출", len(rows) - len(ok))


if __name__ == "__main__":
    main()
