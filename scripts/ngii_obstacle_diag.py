"""019 §3 보조 진단 — 장애물 차감이 한 조각도 일어나지 않은 이유 확인(기준 §29-4 그대로, 규칙 변경 없음).

조각마다: 도로경계 면 합집합과 담장·옹벽·계단 피처의 교차 여부 · 축선 표본점에서 (장애물까지 거리 − 경계까지 거리) 최솟값
출력: data/vworld/national/derived/ngii_obstacle_diag.json
"""
from __future__ import annotations

import json
from pathlib import Path

import shapely
from shapely.geometry import Point

from ngii_medial_width import (BOUND, CENTER, OBST, STEP, T3857, T5186, TRIM, to5186, wfs)

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"


def main():
    cc = json.loads((DER / "missing_alley_crosscheck.json").read_text(encoding="utf-8"))
    rows = []
    for s in cc["sites"]:
        for pc in s["pieces"]:
            if pc["type"] != "road":
                continue
            lon, lat = pc["point"]
            x3, y3 = T3857.transform(lon, lat)
            pt = Point(*T5186.transform(lon, lat))
            bf, e1 = wfs(BOUND, x3, y3)
            cf, e2 = wfs(CENTER, x3, y3)
            if bf is None or cf is None:
                rows.append({"piece": pc["piece"], "error": "미조회"})
                continue
            area = shapely.union_all(to5186(bf))
            lines = to5186(cf)
            axis = min(lines, key=lambda g: g.distance(pt))
            og, counts, inter = [], {}, {}
            for k, tn in OBST.items():
                ff, err = wfs(tn, x3, y3)
                if ff is None:
                    counts[k] = err
                    continue
                gs = to5186(ff)
                counts[k] = len(gs)
                inter[k] = sum(1 for g in gs if g.intersects(area))
                og += gs
            r = {"piece": pc["piece"], "obstacle_counts": counts, "obstacles_intersecting_road_area": inter}
            seg = axis.intersection(area)
            seg = min(list(getattr(seg, "geoms", [seg])), key=lambda g: g.distance(pt)) if not seg.is_empty else None
            if og and seg is not None and seg.length > 2 * TRIM:
                ou = shapely.union_all(og)
                bnd = area.boundary
                gaps = []
                for i in range(int((seg.length - 2 * TRIM) // STEP) + 1):
                    p = seg.interpolate(TRIM + i * STEP)
                    if area.covers(p):
                        gaps.append(ou.distance(p) - bnd.distance(p))
                r["min_obstacle_minus_boundary_m"] = round(min(gaps), 2) if gaps else None
                r["median_obstacle_dist_minus_boundary_m"] = round(sorted(gaps)[len(gaps) // 2], 2) if gaps else None
            rows.append(r)
            print(json.dumps(r, ensure_ascii=False), flush=True)
    out = {"note": "값이 0보다 크면 그 표본점에서 장애물이 도로경계보다 멀다 = 차감이 일어나지 않는다",
           "pieces": rows,
           "obstacles_intersecting_road_area_total": sum(v for r in rows for v in (r.get("obstacles_intersecting_road_area") or {}).values())}
    (DER / "ngii_obstacle_diag.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("교차 장애물 총합", out["obstacles_intersecting_road_area_total"])


if __name__ == "__main__":
    main()
