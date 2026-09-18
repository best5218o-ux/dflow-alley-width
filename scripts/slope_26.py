"""031 §1 — 경사 축 실증. 기준 docs/판정기준.md §33 (실행 전 커밋 5f33956).

원천: 연속수치지형도 1:5,000 표고점 `lt_p_n3f0020000`(nume) · 등고선 `lt_l_n3f0010000`(cont, divi_nm)
방법: P 표고점 회귀 · C 등고선 교차 — 둘을 각각 내고 병기한다(합치지 않는다)
판정: 소방차 등판능력 기준값을 확인하지 못하면 전부 UNKNOWN_FAIL_CLOSED(기준 미확보). 추정하지 않는다
출력: data/vworld/national/derived/slope_26.json · deliverables/경사_26개소.csv
"""
from __future__ import annotations

import csv
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

import shapely
import shapely.ops
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
ELEV_PT, CONTOUR = "lt_p_n3f0020000", "lt_l_n3f0010000"
HALF, BUF, TRIM = 400.0, 40.0, 2.0
GRADEABILITY = None   # 등판능력 기준값 — 공개 문서에서 확인하지 못했다(§33-2)


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
            last = mask(f"{type(e).__name__}: {e}")[:140]
            time.sleep(1.4 * (a + 1))
    return None, last


def to5186(f):
    return sh_transform(lambda a, b: T900913_5186.transform(a, b), shape(f["geometry"]))


def axis_of(lon, lat):
    x3, y3 = T3857.transform(lon, lat)
    pt = Point(*T5186.transform(lon, lat))
    bf, e1 = wfs(BOUND, x3, y3)
    cf, e2 = wfs(CENTER, x3, y3)
    if bf is None or cf is None:
        return None, pt, (x3, y3), f"미조회: {e1 or ''}{e2 or ''}"
    lines = [to5186(f) for f in cf]
    if not lines:
        return None, pt, (x3, y3), "축선 피처 0"
    axis = min(lines, key=lambda g: g.distance(pt))
    area = shapely.union_all([to5186(f) for f in bf]) if bf else None
    seg = axis
    if area is not None and not area.is_empty:
        inter = axis.intersection(area)
        parts = [p for p in getattr(inter, "geoms", [inter]) if p.geom_type in ("LineString", "MultiLineString") and p.length > 0]
        if parts:
            seg = min(parts, key=lambda p: p.distance(pt))
    if seg.geom_type == "MultiLineString":
        seg = max(seg.geoms, key=lambda g: g.length)
    if seg.geom_type == "LineString" and seg.length > 2 * TRIM + 2:
        seg = shapely.ops.substring(seg, TRIM, seg.length - TRIM)
    return seg, pt, (x3, y3), None


def regress(points):
    n = len(points)
    sx = sum(p[0] for p in points); sy = sum(p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points); sxy = sum(p[0] * p[1] for p in points)
    den = n * sxx - sx * sx
    if den == 0:
        return None
    return (n * sxy - sx * sy) / den


def main():
    import shapely.ops  # noqa: F401
    cc = json.loads((DER / "missing_alley_crosscheck.json").read_text(encoding="utf-8"))
    rows, contour_gaps = [], []
    for s in cc["sites"]:
        for pc in s["pieces"]:
            if pc["type"] != "road":
                continue
            lon, lat = pc["point"]
            seg, pt, (x3, y3), err = axis_of(lon, lat)
            r = {"연번": s.get("연번"), "조각": pc["piece"], "축선 길이(m)": None,
                 "표고점 수": 0, "P 경사(%)": None, "등고선 교차": 0, "C 경사(%)": None,
                 "등고선 간격(m)": None, "판정": "UNKNOWN_FAIL_CLOSED(기준 미확보)", "비고": ""}
            if err or seg is None:
                r["비고"] = err or "축선 없음"
                rows.append(r)
                print(json.dumps(r, ensure_ascii=False), flush=True)
                continue
            r["축선 길이(m)"] = round(seg.length, 1)
            ep, e1 = wfs(ELEV_PT, x3, y3)
            ct, e2 = wfs(CONTOUR, x3, y3)
            if ep is None or ct is None:
                r["비고"] = f"미조회: {e1 or ''}{e2 or ''}"
                rows.append(r)
                continue
            buf = seg.buffer(BUF)
            samples = []
            for f in ep:
                g = to5186(f)
                z = f["properties"].get("nume")
                if z is None or not g.intersects(buf):
                    continue
                samples.append((seg.project(g), float(z)))
            r["표고점 수"] = len(samples)
            if len(samples) >= 3:
                b = regress(samples)
                if b is not None:
                    r["P 경사(%)"] = round(abs(b) * 100, 2)
            else:
                r["비고"] = (r["비고"] + " P: 표고점 3개 미만 → NOT_COMPUTED").strip()
            conts = []
            vals = sorted({float(f["properties"]["cont"]) for f in ct if f["properties"].get("cont") is not None})
            gap = min((b - a for a, b in zip(vals, vals[1:])), default=None)
            if gap:
                contour_gaps.append(gap)
                r["등고선 간격(m)"] = gap
            for f in ct:
                g = to5186(f)
                z = f["properties"].get("cont")
                if z is None:
                    continue
                inter = seg.intersection(g)
                for p in getattr(inter, "geoms", [inter]):
                    if p.is_empty or p.geom_type != "Point":
                        continue
                    conts.append((seg.project(p), float(z)))
            r["등고선 교차"] = len(conts)
            if len(conts) >= 2 and (gap is None or seg.length >= gap):
                ds = max(c[0] for c in conts) - min(c[0] for c in conts)
                dz = max(c[1] for c in conts) - min(c[1] for c in conts)
                if ds > 0:
                    r["C 경사(%)"] = round(abs(dz / ds) * 100, 2)
            elif gap is not None and seg.length < gap:
                r["비고"] = (r["비고"] + f" C: 축선 {seg.length:.0f} m < 등고선 간격 {gap:g} m → NOT_COMPUTED").strip()
            else:
                r["비고"] = (r["비고"] + " C: 교차 2개 미만 → NOT_COMPUTED").strip()
            rows.append(r)
            print(json.dumps(r, ensure_ascii=False)[:220], flush=True)
    p_vals = [r["P 경사(%)"] for r in rows if r["P 경사(%)"] is not None]
    c_vals = [r["C 경사(%)"] for r in rows if r["C 경사(%)"] is not None]
    out = {"rule_doc": "docs/판정기준.md §33", "rule_commit": "5f33956",
           "원천": {"표고점": f"{ELEV_PT} (nume) 연속수치지형도 1:5,000",
                  "등고선": f"{CONTOUR} (cont·divi_nm) 연속수치지형도 1:5,000",
                  "수직 정확도": "미확인 — 원천 문서에서 확인하지 못했다",
                  "등고선 간격 실측(m)": sorted(set(contour_gaps))},
           "등판능력 기준": "미확보 — 소방청 소방펌프차 표준규격(KFS 0008-2019-01)이 있다는 것은 확인했으나 등판능력 수치는 공개 페이지에서 확인하지 못했다. 추정하지 않는다",
           "판정": "37조각 전부 UNKNOWN_FAIL_CLOSED(기준 미확보)",
           "등급": "대조 불가 — 경사에는 사람 판독 대조군이 없다(§33-3)",
           "요약": {"조각": len(rows), "P 산출": len(p_vals), "C 산출": len(c_vals),
                  "P 경사 최소/중앙/최대": [min(p_vals), sorted(p_vals)[len(p_vals) // 2], max(p_vals)] if p_vals else None,
                  "C 경사 최소/중앙/최대": [min(c_vals), sorted(c_vals)[len(c_vals) // 2], max(c_vals)] if c_vals else None},
           "rows": rows}
    (DER / "slope_26.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    DELIV.mkdir(parents=True, exist_ok=True)
    with (DELIV / "경사_26개소.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(json.dumps(out["요약"], ensure_ascii=False))


if __name__ == "__main__":
    main()
