"""§8-3 프록시 검증 — LANES=1 이 「골목」인가, 「방향별(편도) 1차로」인가.

판정(기하·속성만 사용, 추정 없음)
- 짝 링크: 같은 ROAD_NAME · 시점→종점 방향벡터 내적 음수(반대 방향) · 30 m 이내 후보 중
  이 링크의 0.2/0.35/0.5/0.65/0.8 지점에서 상대 링크까지 거리의 중앙값이 가장 작은 것
- 결과: 짝 보유율, 짝까지 거리 분포, 짝의 LANES 분포
- 1차 시도(버퍼 9 m/15 m 상호 피복 80%)는 링크 분절 차이로 결론이 갈려(0~6% / 47~72%) 채택하지 않았다.

범위: 대상 구 4곳(권역코드 102·132·185·284) 전수
출력: data/vworld/national/derived/lanes_direction_check.json
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely

ROOT = Path(__file__).resolve().parents[1]
SHP = ROOT / "data/vworld/national/raw/NODELINKDATA_20260914/MOCT_LINK.shp"
OUT = ROOT / "data/vworld/national/derived/lanes_direction_check.json"
SCOPES = {"서울 용산구": "102", "부산 동구": "132", "대전 서구": "185", "청주 청원구": "284"}
SEARCH = 30.0
BINS = [0, 1, 3, 5, 7, 9, 12, 15, 20, 30]


def _vec(geom):
    c = shapely.get_coordinates(geom)
    return c[-1] - c[0]


def check(s: gpd.GeoDataFrame) -> dict:
    s = s.reset_index(drop=True)
    l1 = s[s.l == 1]
    buf = s[["geometry", "ROAD_NAME", "l"]].rename(columns={"ROAD_NAME": "RN2"})
    buf["geometry"] = s.buffer(SEARCH)
    j = gpd.sjoin(l1[["geometry", "ROAD_NAME"]], buf, predicate="intersects")
    rc = [c for c in j.columns if c.startswith("index_")][0]
    j = j[(j.index != j[rc]) & (j.ROAD_NAME == j.RN2) & j.ROAD_NAME.notna()]
    best = {}
    for i, grp in j.groupby(level=0):
        gi = s.geometry[i]
        vi = _vec(gi)
        pts = [gi.interpolate(t, normalized=True) for t in (0.2, 0.35, 0.5, 0.65, 0.8)]
        bd = bl = None
        for r in grp[rc]:
            gr = s.geometry[r]
            if float(np.dot(vi, _vec(gr))) >= 0:
                continue
            d = float(np.median([gr.distance(p) for p in pts]))
            if bd is None or d < bd:
                bd, bl = d, int(s.l[r])
        if bd is not None:
            best[i] = (bd, bl)
    d = np.array([v[0] for v in best.values()])
    return {
        "l1_links": int(len(l1)),
        "l1_no_road_name": int(l1.ROAD_NAME.isna().sum()),
        "with_opposite_same_name_pair": int(len(d)),
        "pair_pct": round(100 * len(d) / len(l1), 2) if len(l1) else None,
        "pair_distance_bins_m": BINS,
        "pair_distance_hist": np.histogram(d, bins=BINS)[0].tolist(),
        "pair_distance_median_m": round(float(np.median(d)), 2) if len(d) else None,
        "partner_lanes": {str(k): int(v) for k, v in pd.Series([v[1] for v in best.values()]).value_counts().items()},
    }


def main():
    where = " OR ".join(f"LINK_ID LIKE '{p}%'" for p in SCOPES.values())
    g = pyogrio.read_dataframe(SHP, columns=["LINK_ID", "LANES", "ROAD_NAME"], where=where)
    g["l"] = pd.to_numeric(g.LANES, errors="coerce")
    g["p3"] = g.LINK_ID.str[:3]
    res = {"method": "same ROAD_NAME + opposite direction + nearest within 30 m", "scopes": {}}
    for label, pre in SCOPES.items():
        r = check(g[g.p3 == pre])
        res["scopes"][label] = r
        print(label, r)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
