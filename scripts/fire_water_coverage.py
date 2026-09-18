"""006 §3-1 — 전국소방용수시설표준데이터 수급 결과 집계 + 4개 대상지 커버리지.

원천: 공공데이터포털 15034538 전국소방용수시설표준데이터 → 파일데이터 「소방청_소방용수시설」
      (uddi:d3b8e2ef-f159-43c8-9a9c-cf2effd16941, 제공기관 소방청, 수정일 2024-02-13, 전체 행 수 199507, CSV, 로그인 불요)
      표준데이터 페이지의 XLS/CSV 일괄 내려받기(/tcs/dss/stdFileDown.do · stdExcelDown.do)는 3회 모두 404 → 파일데이터 경로로 우회.
      오픈API 는 공공데이터포털 인증키(회원가입) 필요 — 미사용.

규칙(실행 전 고정, 이 docstring 이 기준)
- 위경도 유효 = 위도 33–39 · 경도 124–132 (숫자 변환 실패는 무효)
- 시도 집계 = `시도명` 그대로. 청주 = 시도명 충청북도 ∧ 시군구명에 「청주」
- 대상지 탐색창 = turn_geometry_census.py 와 같은 시드(브이월드 검색 API 동 대표점, vworld_probe.json) · EPSG:5186 반경 500 m
- `시설유형코드` 값(1~6)의 의미는 파일·포털 항목설명에 정의가 없다 → 코드별 건수만 적고 시설 종류로 옮기지 않는다
  (소화전·급수탑·저수조·비상소화장치 중 무엇인지 단정하지 않음)
- 대상지 창 안 건수 0 이거나 해당 시도 행이 0 이면 water_reach_status = UNKNOWN_FAIL_CLOSED
  (건수가 있어도 도달성 판정은 전개 지점 확정 후 §1-2 2차 단계에서 한다 — 여기서는 커버리지만)

출력: data/vworld/national/derived/fire_water_coverage.json
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/vworld/national/raw/firewater/std_firewater_20240213.csv"
DER = ROOT / "data/vworld/national/derived"
TARGETS = [("서울 이태원동", "서울 용산구 이태원동", "서울특별시", None), ("부산 초량동", "부산 동구 초량동", "부산광역시", None),
           ("대전 변동", "대전 서구 변동", "대전광역시", None), ("청주 내덕동", "청주 청원구 내덕동", "충청북도", "청주")]
R_WIN = 500.0


def main():
    df = pd.read_csv(RAW, encoding="utf-8-sig", dtype=str)
    la, lo = pd.to_numeric(df["위도"], errors="coerce"), pd.to_numeric(df["경도"], errors="coerce")
    df["valid"] = la.between(33, 39) & lo.between(124, 132)
    tr = Transformer.from_crs(4326, 5186, always_xy=True)
    v = df[df.valid].copy()
    v["x"], v["y"] = tr.transform(pd.to_numeric(v["경도"]).values, pd.to_numeric(v["위도"]).values)
    probe = json.loads((DER / "vworld_probe.json").read_text(encoding="utf-8"))["items"]["4_geocoder"]["search_district"]

    by_sido = df.groupby("시도명").agg(rows=("시설번호", "size"), valid=("valid", "sum"))
    out = {"source": {"portal": "data.go.kr 15034538 → fileData uddi:d3b8e2ef-f159-43c8-9a9c-cf2effd16941", "provider": "소방청",
                      "portal_modified": "2024-02-13", "portal_rows": 199507, "file": RAW.name,
                      "sha256": hashlib.sha256(RAW.read_bytes()).hexdigest(), "reference_date_values": sorted(df["데이터기준일자"].dropna().unique().tolist())},
           "national": {"rows": int(len(df)), "valid_latlon": int(df.valid.sum()), "sido_count": int(df["시도명"].nunique())},
           "by_sido": {k: {"rows": int(r.rows), "valid_latlon": int(r.valid)} for k, r in by_sido.iterrows()},
           "facility_type_code_meaning": "미정의(파일·포털 항목설명에 없음) — 코드별 건수만 기록",
           "targets": {}}
    for label, key, sido, sgg_kw in TARGETS:
        sd = df[df["시도명"] == sido]
        if sgg_kw:
            sd = sd[sd["시군구명"].fillna("").str.contains(sgg_kw)]
        x, y = tr.transform(*probe[key]["candidates"][0]["point"])
        w = v[np.hypot(v.x - x, v.y - y) <= R_WIN]
        n = int(len(w))
        out["targets"][label] = {
            "sido_scope": sido + (f" · 시군구명⊃{sgg_kw}" if sgg_kw else ""), "scope_rows": int(len(sd)), "scope_valid_latlon": int(sd.valid.sum()),
            "window_radius_m": R_WIN, "seed_query": key, "within_window": n,
            "within_window_by_type_code": {str(k).strip(): int(c) for k, c in w["시설유형코드"].value_counts().items()},
            "geocoding_needed": int((~sd.valid).sum()),
            "water_reach_status_default": "UNKNOWN_FAIL_CLOSED" if (len(sd) == 0 or n == 0) else "NOT_EVALUATED(전개 지점 확정 후 2차 평가)",
        }
    DER.mkdir(parents=True, exist_ok=True)
    (DER / "fire_water_coverage.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("national", "targets")}, ensure_ascii=False))
    print(json.dumps({s: out["by_sido"][s] for s in ("서울특별시", "부산광역시", "충청북도", "대전광역시")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
