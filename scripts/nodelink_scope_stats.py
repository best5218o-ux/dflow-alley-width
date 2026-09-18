"""연번 2 표준노드링크 — (1) 도시 범위별 컬럼 결측률 (2) 후보지 탐색창 링크 구성.

- 범위는 LINK_ID 앞 3자리(권역코드)로 자른다. 권역코드↔시군구 대응은 공개 주소 좌표(교량·터널
  표준데이터 소재지)와 링크 중점의 근접으로 확인했다(nodelink_prefix_extent.csv).
- 탐색창은 **경계가 아니다.** 반경 R 원 안 링크 중점 수를 세어 후보 비교에만 쓴다.
  대상지 경계는 승인 후 도로망 연결성 기준으로 따로 잡는다.
- 좌표 출처: 교량·터널 표준데이터 소재지 주소 좌표(공공), 없으면 「수기 근사」로 표시.
  상용 지오코더는 쓰지 않는다.
- ROAD_RANK 는 광역시에서 지역도로를 104(특별·광역시도)로 코딩하므로 등급으로 골목 여부를 가르지 않는다.
- 결측 정의: null(빈칸) / zero(0) 분리. 표준노드링크의 REST_W·REST_H·REST_VEH 는 0 이
  「제한 없음」인지 「미조사」인지 파일만으로 구분되지 않는다 → zero 를 결측으로 합치지 않고 따로 적는다.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
SHP = ROOT / "data/vworld/national/raw/NODELINKDATA_20260914/MOCT_LINK.shp"
OUT = ROOT / "data/vworld/national/derived"
COLS = ["LINK_ID", "LANES", "ROAD_RANK", "ROAD_NAME", "MAX_SPD", "REST_VEH", "REST_W", "REST_H", "LENGTH"]

SCOPES = {"서울 용산구": ["102"], "부산 동래구": ["135"], "부산 전체": [str(i) for i in range(130, 146)],
          "청주시(270·271·283·284)": ["270", "271", "283", "284"], "대전 서구": ["185"], "전국": None}

R = 500  # m
SEEDS = [  # (라벨, lon, lat, 좌표 출처)
    ("서울 용산구 이태원동", 126.9946, 37.5345, "수기 근사(이태원역)"),
    ("대전 서구 변동", 127.38577, 36.32333, "교량표준데이터 소재지 '서구 변동'(태평교)"),
    ("부산 후보1 동래구 온천동", 129.06769, 35.21157, "교량표준데이터 소재지 '동래구 온천동' 6건 평균"),
    ("부산 후보2 동구 초량동 산복도로", 129.0370, 35.1190, "수기 근사"),
    ("부산 후보3 부산진구 전포동", 129.0650, 35.1540, "수기 근사"),
    ("청주 후보1 상당구 수동(수암골)", 127.4960, 36.6405, "수기 근사"),
    ("청주 후보2 서원구 모충동", 127.4800, 36.6250, "수기 근사"),
    ("청주 후보3 청원구 내덕동", 127.47426, 36.6591, "교량표준데이터 소재지 '청원구 내덕동' 3건 평균"),
]

VW_KEYS = ["서울 용산구 이태원동", "대전 서구 변동", "부산 동래구 온천동", "부산 동구 초량동", "부산 부산진구 전포동",
           "청주 상당구 수동", "청주 서원구 모충동", "청주 청원구 내덕동"]  # SEEDS 순서와 같게


def col_rates(df: pd.DataFrame) -> dict:
    n = len(df)
    r = {"rows": n}
    for c in COLS[1:]:
        s = df[c].astype("string").str.strip()
        null = s.isna() | (s == "") | (s == "-")
        num = pd.to_numeric(s.where(~null), errors="coerce")
        r[c] = {"null_pct": round(100 * null.sum() / n, 2) if n else None,
                "zero_pct": round(100 * (num.eq(0) & ~null).sum() / n, 2) if n else None}
    return r


def main():
    g = pyogrio.read_dataframe(SHP, columns=COLS)
    b = shapely.bounds(g.geometry.values)
    g["mx"], g["my"] = (b[:, 0] + b[:, 2]) / 2, (b[:, 1] + b[:, 3]) / 2
    g["p3"] = g.LINK_ID.str[:3]
    bus = pd.read_csv(glob.glob(str(ROOT / "docs/busan/raw/*링크정보*"))[0], encoding="cp949", dtype=str)
    busan_ids = set(bus["링크번호"])

    scopes = {}
    for label, pre in SCOPES.items():
        sub = g if pre is None else g[g.p3.isin(pre)]
        scopes[label] = col_rates(sub)

    tr = Transformer.from_crs(4326, 5186, always_xy=True)
    windows = []
    for label, lon, lat, src in SEEDS:
        x, y = tr.transform(lon, lat)
        w = g[np.hypot(g.mx - x, g.my - y) <= R]
        rank = w.ROAD_RANK.value_counts().to_dict()
        windows.append({"label": label, "seed_src": src, "radius_m": R, "links": len(w),
                        "rank_counts": {k: int(v) for k, v in sorted(rank.items())},
                        "prefixes": w.p3.value_counts().head(3).to_dict(),
                        "busan_its_csv_links": int(w.LINK_ID.isin(busan_ids).sum()) if "부산" in label else None,
                        "rest_h_nonzero": int((pd.to_numeric(w.REST_H, errors="coerce") > 0).sum()),
                        "lanes_1": int((pd.to_numeric(w.LANES, errors="coerce") == 1).sum())})

    # §9-3 재확인 — 같은 창을 브이월드 검색 API(type=district) 동 대표점으로 다시 센다(키 불요, probe 결과 읽기)
    probe = ROOT / "data/vworld/national/derived/vworld_probe.json"
    windows_vw = []
    if probe.exists():
        sd = json.loads(probe.read_text(encoding="utf-8"))["items"]["4_geocoder"]["search_district"]
        for (label, lon0, lat0, src), key in zip(SEEDS, VW_KEYS):
            c = sd[key]["candidates"][0]
            x, y = tr.transform(*c["point"])
            w = g[np.hypot(g.mx - x, g.my - y) <= R]
            windows_vw.append({"label": label, "seed_src": "브이월드 검색 API type=district", "title": c["title"],
                               "lonlat": c["point"], "shift_m": sd[key].get("shift_from_old_seed_m"), "links": len(w),
                               "busan_its_csv_links": int(w.LINK_ID.isin(busan_ids).sum()) if "부산" in label else None,
                               "rest_h_nonzero": int((pd.to_numeric(w.REST_H, errors="coerce") > 0).sum()),
                               "lanes_1": int((pd.to_numeric(w.LANES, errors="coerce") == 1).sum())})
        for w in windows_vw:
            print("VW", w)

    res = {"source": SHP.name, "scopes": scopes, "seed_windows": windows, "seed_windows_vworld": windows_vw,
           "busan_its_csv": {"ids": len(busan_ids), "matched_in_20260914": int(g.LINK_ID.isin(busan_ids).sum()),
                              "rank_of_matched": g[g.LINK_ID.isin(busan_ids)].ROAD_RANK.value_counts().to_dict()}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "nodelink_scope_stats.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in scopes.items():
        print(k, v["rows"], {c: (v[c]["null_pct"], v[c]["zero_pct"]) for c in ("LANES", "ROAD_NAME", "MAX_SPD", "REST_W", "REST_H")})
    for w in windows:
        print(w)
    print(res["busan_its_csv"])


if __name__ == "__main__":
    main()
