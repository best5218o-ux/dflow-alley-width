"""009 §5·§7-3 — 전국 폭 속성 교차표 산출물(표 A 요약 · 표 B 값 구간 분포) + 명세.

기준: docs/판정기준.md §15 (실행 전 커밋 3a36588). 입력은 §10 원시(미수급 칸 0).
- 중복 제거 키 (sig_cd, rds_man_no) — rds_man_no 는 시군구 안에서만 고유
- 값 구간(단위 미확인): 결측 · 0 · (0,2] · (2,3) · =3 · (3,4] · (4,6] · (6,8] · (8,12) · [12,20) · [20,40) · ≥40
출력: deliverables/전국폭속성교차표_A_요약.csv · _B_값구간.csv (커밋 대상 — 개인정보·키 없음)
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/vworld/national/raw/road_bt_national_cells.jsonl"
OUT = ROOT / "deliverables"
SIDO = {"11": "서울", "12": "전남광주통합특별시(12)", "26": "부산", "27": "대구", "28": "인천", "29": "광주(29)", "30": "대전", "31": "울산",
        "36": "세종", "41": "경기", "42": "강원(42)", "43": "충북", "44": "충남", "45": "전북(45)", "46": "전남(46)", "47": "경북",
        "48": "경남", "50": "제주", "51": "강원특별자치도(51)", "52": "전북특별자치도(52)"}
BINS = ["결측", "0", "(0,2]", "(2,3)", "=3", "(3,4]", "(4,6]", "(6,8]", "(8,12)", "[12,20)", "[20,40)", "≥40"]


def tier(rn):
    rn = str(rn or "")
    return "대로" if rn.endswith("대로") else "로" if rn.endswith("로") else "길" if rn.endswith("길") else "기타"


def num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def bin_of(v):
    if v is None:
        return "결측"
    if v == 0:
        return "0"
    if v <= 2:
        return "(0,2]"
    if v < 3:
        return "(2,3)"
    if v == 3:
        return "=3"
    if v <= 4:
        return "(3,4]"
    if v <= 6:
        return "(4,6]"
    if v <= 8:
        return "(6,8]"
    if v < 12:
        return "(8,12)"
    if v < 20:
        return "[12,20)"
    if v < 40:
        return "[20,40)"
    return "≥40"


def main():
    seen = set()
    groups = defaultdict(list)
    for line in RAW.open(encoding="utf-8"):
        for p in json.loads(line)["rows"]:
            k = (str(p.get("sig_cd")), str(p.get("rds_man_no")))
            if k in seen:
                continue
            seen.add(k)
            s = SIDO.get(str(p.get("sig_cd"))[:2], str(p.get("sig_cd"))[:2])
            groups[(s, tier(p.get("rn")))].append(num(p.get("road_bt")))
    OUT.mkdir(parents=True, exist_ok=True)
    sidos = sorted({s for s, _ in groups}) + ["전국"]
    tiers = ["대로", "로", "길", "기타", "전체"]

    def vals(s, t):
        keys = [k for k in groups if (s == "전국" or k[0] == s) and (t == "전체" or k[1] == t)]
        return [v for k in keys for v in groups[k]]

    with (OUT / "전국폭속성교차표_A_요약.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["시도", "위계", "구간", "결측", "0값", "3.0단일값", "3.0비율", "40미만", "40미만비율", "12~40밖", "12~40밖비율", "p10", "p50", "p90", "단위"])
        for s in sidos:
            for t in tiers:
                v = vals(s, t)
                if not v:
                    continue
                vv = [x for x in v if x is not None]
                n = len(v)
                lt40 = sum(x < 40 for x in vv)
                out1240 = sum(not (12 <= x < 40) for x in vv)
                pc = np.percentile(vv, [10, 50, 90]) if vv else [None] * 3
                w.writerow([s, t, n, n - len(vv), sum(x == 0 for x in vv), sum(x == 3 for x in vv), f"{sum(x == 3 for x in vv) / n:.4f}",
                            lt40 if t == "대로" else "", f"{lt40 / len(vv):.4f}" if t == "대로" and vv else "",
                            out1240 if t == "로" else "", f"{out1240 / len(vv):.4f}" if t == "로" and vv else "",
                            *[round(float(x), 2) if x is not None else "" for x in pc], "미확인"])
    with (OUT / "전국폭속성교차표_B_값구간.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["시도", "위계", "구간"] + BINS + ["단위"])
        for s in sidos:
            for t in tiers:
                v = vals(s, t)
                if not v:
                    continue
                c = defaultdict(int)
                for x in v:
                    c[bin_of(x)] += 1
                w.writerow([s, t, len(v)] + [c[b] for b in BINS] + ["미확인"])
    tot = vals("전국", "전체")
    print(json.dumps({"segments": len(tot), "missing": sum(x is None for x in tot), "eq3": sum(x == 3 for x in tot),
                      "daero_eq3": sum(x == 3 for x in vals("전국", "대로")), "sidos": len(sidos) - 1}, ensure_ascii=False))


if __name__ == "__main__":
    main()
