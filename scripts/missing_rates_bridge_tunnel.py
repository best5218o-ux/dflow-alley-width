"""연번 5 교량·터널 표준데이터 — 도시별 컬럼 결측률.

결측 정의(분리 집계, 합치지 않는다)
- null : 빈칸·NaN
- zero : 값이 숫자 0 (높이·폭 컬럼에서 실측 0 인지 미기재 대체값인지 판별 불가 → 결측으로 세지 않고 따로 적는다)

출력: data/vworld/national/derived/missing_bridge_tunnel.json (+ 콘솔 요약)
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "vworld" / "national" / "raw"
OUT = ROOT / "data" / "vworld" / "national" / "derived"

FILES = {
    "bridge": ("국토교통부_전국교량표준데이터_20251231.csv", ["하부통과제한높이", "교량높이", "교량폭", "차로수", "허용통행하중"]),
    "tunnel": ("국토교통부_전국도로터널정보표준데이터_20251231.csv", ["터널높이", "터널폭", "차로수"]),
}

# (라벨, 시도명, 시군구명 접두 — None 이면 시도 전체)
SCOPES = [
    ("전국", None, None),
    ("서울특별시", "서울특별시", None),
    ("서울 용산구", "서울특별시", "용산구"),
    ("부산광역시", "부산광역시", None),
    ("충북 청주시", "충청북도", "청주시"),
    ("대전광역시", "대전광역시", None),
    ("대전 서구", "대전광역시", "서구"),
]


def rates(df: pd.DataFrame, cols: list[str]) -> dict:
    n = len(df)
    out = {"rows": n}
    for c in cols:
        s = df[c].astype("string").str.strip()
        null = s.isna() | (s == "")
        num = pd.to_numeric(s.where(~null), errors="coerce")
        zero = num.eq(0) & ~null
        out[c] = {
            "null": int(null.sum()),
            "null_pct": round(100 * null.sum() / n, 1) if n else None,
            "zero": int(zero.sum()),
            "non_numeric": int((num.isna() & ~null).sum()),
        }
    return out


def main():
    result = {}
    for key, (fname, cols) in FILES.items():
        df = pd.read_csv(RAW / fname, encoding="utf-8-sig", dtype=str)
        result[key] = {"file": fname, "scopes": {}}
        for label, sido, sgg in SCOPES:
            sub = df
            if sido:
                sub = sub[sub["시도명"].str.strip() == sido]
            if sgg:
                sub = sub[sub["시군구명"].fillna("").str.strip().str.startswith(sgg)]
            result[key]["scopes"][label] = rates(sub, cols)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "missing_bridge_tunnel.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for key, (_, cols) in FILES.items():
        print(f"== {key}")
        for label, r in result[key]["scopes"].items():
            cells = " | ".join(f"{c} null {r[c]['null_pct']}% zero {r[c]['zero']}" for c in cols[:2])
            print(f"{label:10s} rows {r['rows']:6d} | {cells}")


if __name__ == "__main__":
    main()
