"""007 §11-2 — 브이월드 lt_l_sprd(도로명주소도로) 대전 전체 road_bt 결측률 + 도로명 위계(대로·로·길)와의 관계.

규칙(실행 전 고정, 이 docstring 이 기준)
- 범위: 대전 5개 구 시군구코드 sig_cd ∈ {30110 동구, 30140 중구, 30170 서구, 30200 유성구, 30230 대덕구}
- 조회: 브이월드 WFS `lt_l_sprd` GetFeature, 대전 경계 상자(경도 127.22~127.58 · 위도 36.17~36.51)를 EPSG:900913 2.5 km 격자로 나눠 받음.
  한 칸이 1000건(상한)이면 4등분 재조회. 중복은 rds_man_no(없으면 속성 전체)로 제거. sig_cd 가 위 5개인 것만 남김
  (첫 시도 Data API attrFilter sig_cd 는 「속성명은 [rn,ag_geom] 중 하나」 오류로 불가 — 조회 방법만 바꿈, 집계 규칙 동일)
- 중복 제거 키 = (sig_cd, rds_man_no) — 2026-09-16 정정(첫 실행 rds_man_no 단독 → 구 간 합병 과소 집계)
- 결측 = road_bt 가 없음·빈문자·숫자 변환 불가. 값 0 은 「0 값」으로 따로 센다(결측으로 합치지 않음)
- 위계: 도로명(rn) 끝이 「대로」→대로, 「로」로 끝나고 대로가 아니면 → 로, 「길」로 끝나면 → 길, 그 외 → 기타
- 도로명주소법 시행령(2013.3.23 판 위키문헌 본문) 제6조① 폭 기준: 대로 ≥40 m · 로 12~40 m · 길 그 외(차로 기준 병기 — 「이거나」)
  → road_bt(단위 m 가정 — 명세 미확인)가 위계 폭 구간 안에 드는 비율을 참고로 기록. 판정에 쓰지 않는다
- 키: os.environ["VWORLD_APIKEY"] 만, 출력에 *** 치환
출력: data/vworld/national/derived/road_bt_daejeon.json
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"
KEY = os.environ["VWORLD_APIKEY"].strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
GU = {"30110": "동구", "30140": "중구", "30170": "서구", "30200": "유성구", "30230": "대덕구"}


def mask(s):
    return str(s).replace(KEY, "***")


def wfs_box(x0, y0, x1, y1):
    q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": "lt_l_sprd", "OUTPUT": "application/json",
         "MAXFEATURES": "1000", "SRSNAME": "EPSG:900913", "BBOX": f"{x0},{y0},{x1},{y1},EPSG:900913", "key": KEY, "domain": DOMAIN}
    url = "https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode(q)
    err = None
    for attempt in range(3):
        try:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"}), timeout=90).read())
            if "features" in j:
                return [f["properties"] for f in j["features"]], None
            err = mask(json.dumps(j, ensure_ascii=False)[:200])
        except Exception as e:  # noqa: BLE001
            err = mask(f"{type(e).__name__}: {e}")
        time.sleep(2 * (attempt + 1))
    return None, err


def tier(rn):
    rn = str(rn or "")
    if rn.endswith("대로"):
        return "대로"
    if rn.endswith("로"):
        return "로"
    if rn.endswith("길"):
        return "길"
    return "기타"


def main():
    from pyproj import Transformer
    t = Transformer.from_crs(4326, 3857, always_xy=True)
    X0, Y0 = t.transform(127.22, 36.17)
    X1, Y1 = t.transform(127.58, 36.51)
    STEP = 2500.0
    cells = [(x, y, min(x + STEP, X1), min(y + STEP, Y1)) for x in np.arange(X0, X1, STEP) for y in np.arange(Y0, Y1, STEP)]
    seen, feats, log = set(), [], {"cells": 0, "split": 0, "errors": []}
    while cells:
        c = cells.pop()
        props, err = wfs_box(*c)
        log["cells"] += 1
        if props is None:
            log["errors"].append({"box": [round(v) for v in c], "error": err})
            continue
        if len(props) >= 1000:
            mx, my = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2
            cells += [(c[0], c[1], mx, my), (mx, c[1], c[2], my), (c[0], my, mx, c[3]), (mx, my, c[2], c[3])]
            log["split"] += 1
            continue
        for f in props:
            if str(f.get("sig_cd")) not in GU:
                continue
            # 정정(2026-09-16): rds_man_no 는 시군구 안에서만 고유 — (sig_cd, rds_man_no) 로 중복 제거. 첫 실행은 rds_man_no 만 써서 구 간 구간을 합쳐 3,038 로 과소 집계
            k = (str(f.get("sig_cd")), f.get("rds_man_no")) if f.get("rds_man_no") is not None else json.dumps(f, sort_keys=True, ensure_ascii=False)
            if k in seen:
                continue
            seen.add(k)
            feats.append(f)
        time.sleep(0.15)
    log["by_gu"] = dict(Counter(GU[str(f["sig_cd"])] for f in feats))
    vals = []
    for f in feats:
        v = f.get("road_bt")
        try:
            v = float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            v = None
        vals.append(v)
    n = len(feats)
    missing = sum(v is None for v in vals)
    zero = sum(v == 0 for v in vals)
    bands = {"대로": (40, 1e9), "로": (12, 40), "길": (0, 12)}
    by_tier = {}
    for t in ("대로", "로", "길", "기타"):
        vs = [v for f, v in zip(feats, vals) if tier(f.get("rn")) == t]
        good = [v for v in vs if v is not None and v > 0]
        lo, hi = bands.get(t, (None, None))
        by_tier[t] = {"segments": len(vs), "missing": sum(v is None for v in vs), "zero": sum(v == 0 for v in vs),
                      "p10_p50_p90": [round(float(x), 2) for x in np.percentile(good, [10, 50, 90])] if good else None,
                      "within_law_width_band": (sum(lo <= v < hi for v in good) if lo is not None else None), "valued": len(good),
                      "top_values": Counter(good).most_common(8)}
    all_good = [v for v in vals if v is not None and v > 0]
    out = {"layer": "LT_L_SPRD(도로명주소도로)", "scope": GU, "requests": log, "segments": n,
           "road_bt_missing": missing, "road_bt_missing_rate": round(missing / n, 4) if n else None,
           "road_bt_zero": zero, "road_bt_valued_positive": len(all_good),
           "distinct_values": len(set(all_good)), "integer_share": round(sum(float(v).is_integer() for v in all_good) / len(all_good), 4) if all_good else None,
           "top_values": Counter(all_good).most_common(15), "by_tier": by_tier,
           "unit_assumption": "m 가정 — 명세 미확인", "law_band_source": "도로명주소법 시행령 제6조① (2013.3.23 판 본문)"}
    DER.mkdir(parents=True, exist_ok=True)
    (DER / "road_bt_daejeon.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("requests", "segments", "road_bt_missing", "road_bt_missing_rate", "road_bt_zero",
                                          "distinct_values", "integer_share", "top_values", "by_tier")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
