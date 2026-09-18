"""D-061 Part E-2 · 기준 §35 — 대중교통 유입 지점(버스정류장·도시철도 역사) 반경 100 m.

- 위치를 연결한다. 조각 기준점 = §34 와 같은 규칙(같은 도로명 도로구간 선형 위 조각 최근접점, 못 찾으면 조각 좌표)
- 2026-09-18 확장: 반경 안 정류장·역사의 목록(번호·이름·거리)을 따로 쓴다 → 유입 규모 결합(transit_inflow_volume.py)의 키
입력: data/vworld/원천/대전_버스정류장_15067528.csv · 대전_도시철도역사_15013205.csv (공공데이터포털 파일데이터 사본)
      data/vworld/national/derived/missing_alley_crosscheck.json (조각·기준점) · raw/daejeon_sprd_geom.jsonl(.gz) (도로구간 선형)
출력: deliverables/대중교통유입_26개소.csv · deliverables/대중교통유입_정류장목록_26개소.csv
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import shapely.wkt
from pyproj import Transformer
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sam_vehicle_width import DELIV, ROOT, lines_of, load_roads, pieces  # noqa: E402

RADIUS = 100.0
SRC = ROOT / "data/vworld/원천"
T45 = Transformer.from_crs(4326, 5186, always_xy=True)


def load_points(path, lat_key, lon_key, name_key, id_key, extra_key=None):
    out = []
    for r in csv.DictReader(path.open(encoding="utf-8-sig")):
        try:
            x, y = T45.transform(float(r[lon_key]), float(r[lat_key]))
        except (TypeError, ValueError):
            continue
        out.append((Point(x, y), r[name_key], r[id_key], r.get(extra_key, "") if extra_key else ""))
    return out


def main():
    bus = load_points(SRC / "대전_버스정류장_15067528.csv", "위도", "경도", "정류장명", "정류장번호", "모바일단축번호")
    rail = load_points(SRC / "대전_도시철도역사_15013205.csv", "역위도", "역경도", "역사명", "역번호")
    roads = load_roads()
    rows, lst, tb, tr = [], [], 0, 0
    for pc in pieces():
        lon, lat = pc["point"]
        p = Point(*T45.transform(lon, lat))
        note = ""
        cands = roads.get(pc["road_name"], [])
        if cands:
            row = min(cands, key=lambda r: shapely.wkt.loads(r["wkt"]).distance(p))
            g = shapely.wkt.loads(row["wkt"])
            ln = min(lines_of(g), key=lambda l: l.distance(p))
            p = ln.interpolate(ln.project(p))
        else:
            note = "같은 도로명 도로구간 없음 — 조각 좌표 사용"
        inb = sorted(((q.distance(p), n, i, a) for q, n, i, a in bus if q.distance(p) <= RADIUS))
        inr = sorted(((q.distance(p), n, i, a) for q, n, i, a in rail if q.distance(p) <= RADIUS))
        nb, nr = len(inb), len(inr)
        db, nbn, _, _ = min(((q.distance(p), n, i, a) for q, n, i, a in bus), default=(None, "", "", ""))
        dr, nrn, _, _ = min(((q.distance(p), n, i, a) for q, n, i, a in rail), default=(None, "", "", ""))
        tb += nb
        tr += nr
        rows.append({"시군구": pc["시군구"], "조각": pc["조각"], "반경(m)": int(RADIUS), "버스정류장수": nb, "도시철도역사수": nr,
                     "최근접정류장(m)": round(db, 1) if db is not None else "", "최근접정류장명": nbn,
                     "최근접역사(m)": round(dr, 1) if dr is not None else "", "최근접역사명": nrn, "미산출사유": note})
        for d, n, i, a in inb:
            lst.append({"시군구": pc["시군구"], "조각": pc["조각"], "유형": "버스정류장", "번호": i, "이름": n, "모바일단축번호": a, "거리(m)": round(d, 1), "반경안": "Y"})
        for d, n, i, a in inr:
            lst.append({"시군구": pc["시군구"], "조각": pc["조각"], "유형": "도시철도역사", "번호": i, "이름": n, "모바일단축번호": "", "거리(m)": round(d, 1), "반경안": "Y"})
        # 반경 밖이라도 최근접 1곳은 기록(유입 규모 참고용 · 반경안 N)
        if nb == 0 and db is not None:
            d, n, i, a = min(((q.distance(p), n, i, a) for q, n, i, a in bus))
            lst.append({"시군구": pc["시군구"], "조각": pc["조각"], "유형": "버스정류장", "번호": i, "이름": n, "모바일단축번호": a, "거리(m)": round(d, 1), "반경안": "N"})
        if nr == 0 and dr is not None:
            d, n, i, a = min(((q.distance(p), n, i, a) for q, n, i, a in rail))
            lst.append({"시군구": pc["시군구"], "조각": pc["조각"], "유형": "도시철도역사", "번호": i, "이름": n, "모바일단축번호": "", "거리(m)": round(d, 1), "반경안": "N"})
    with_any = sum(1 for r in rows if r["버스정류장수"] or r["도시철도역사수"])
    rows.append({"시군구": "합계", "조각": f"{len(rows)}조각 · 반경 안 유입 지점 있는 조각 {with_any}", "반경(m)": int(RADIUS),
                 "버스정류장수": tb, "도시철도역사수": tr, "최근접정류장(m)": "", "최근접정류장명": "", "최근접역사(m)": "", "최근접역사명": "",
                 "미산출사유": "위치 연결 · 유입 규모는 대중교통유입규모_26개소.csv(transit_inflow_volume.py)"})
    with (DELIV / "대중교통유입_26개소.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with (DELIV / "대중교통유입_정류장목록_26개소.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(lst[0].keys()))
        w.writeheader()
        w.writerows(lst)
    print(rows[-1])
    print("목록", len(lst), "행 · 반경안 Y", sum(1 for r in lst if r["반경안"] == "Y"))


if __name__ == "__main__":
    main()
