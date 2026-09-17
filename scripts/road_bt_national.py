"""008 §4 — 전국 도로명주소도로(lt_l_sprd) 「도로명 위계 × road_bt」 교차표.

기준: docs/판정기준.md §10 (실행 전 커밋 cd9998c). 결과를 보고 기준을 바꾸지 않는다.
- 수집: WFS PROPERTYNAME(rn,road_bt,sig_cd,rds_man_no) · 20 km 격자 → 1,000건이면 4등분 · 칸 3회 실패는 미수급 기록
- 재개 가능: 끝난 잎 칸은 data/vworld/national/raw/road_bt_national_cells.jsonl 에 쌓고 다시 받지 않는다
- 키: os.environ["VWORLD_APIKEY"] 만, 기록에 *** 치환
실행: python road_bt_national.py fetch   → python road_bt_national.py agg
출력: data/vworld/national/derived/road_bt_national.json
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]   # 저장소 루트(scripts/ 한 단계 위)
RAW = ROOT / "data/vworld/national/raw/road_bt_national_cells.jsonl"
FAIL = ROOT / "data/vworld/national/raw/road_bt_national_failed.jsonl"
DER = ROOT / "data/vworld/national/derived"
KEY = os.environ.get("VWORLD_APIKEY", "")
CAP = 1000
SIDO = {"11": "서울", "26": "부산", "27": "대구", "28": "인천", "29": "광주", "30": "대전", "31": "울산", "36": "세종", "41": "경기",
        "42": "강원(42)", "51": "강원특별자치도(51)", "43": "충북", "44": "충남", "45": "전북(45)", "52": "전북특별자치도(52)",
        "46": "전남(46)", "12": "전남광주통합특별시(12)", "47": "경북", "48": "경남", "50": "제주"}
lock = threading.Lock()


def mask(s):
    return str(s).replace(KEY, "***") if KEY else str(s)


def fetch_box(c):
    x0, y0, x1, y1 = c
    q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": "lt_l_sprd", "OUTPUT": "application/json",
         "MAXFEATURES": str(CAP), "SRSNAME": "EPSG:900913", "PROPERTYNAME": "rn,road_bt,sig_cd,rds_man_no",
         "BBOX": f"{x0},{y0},{x1},{y1},EPSG:900913", "key": KEY}
    url = "https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode(q)
    err = None
    for attempt in range(3):
        try:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"}), timeout=120).read())
            if "features" in j:
                return [f["properties"] for f in j["features"]], None
            err = mask(json.dumps(j, ensure_ascii=False)[:300])
        except Exception as e:  # noqa: BLE001
            err = mask(f"{type(e).__name__}: {e}")[:300]
        time.sleep(3 * (attempt + 1))
    return None, err


def key_of(c):
    return ",".join(f"{v:.1f}" for v in c)


def fetch():
    from pyproj import Transformer
    t = Transformer.from_crs(4326, 3857, always_xy=True)
    X0, Y0 = t.transform(124.5, 33.0)
    X1, Y1 = t.transform(132.0, 38.7)
    STEP = 20000.0
    done = set()
    if RAW.exists():
        for line in RAW.open(encoding="utf-8"):
            done.add(json.loads(line)["cell"])
    if FAIL.exists():
        FAIL.unlink()  # 실패 칸은 재시도
    queue = [(x, y, min(x + STEP, X1), min(y + STEP, Y1)) for x in np.arange(X0, X1, STEP) for y in np.arange(Y0, Y1, STEP)]
    stats = Counter()

    def work(c):
        props, err = fetch_box(c)
        with lock:
            stats["requests"] += 1
            if props is None:
                with FAIL.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"cell": key_of(c), "error": err}, ensure_ascii=False) + "\n")
                stats["failed"] += 1
                return []
            if len(props) >= CAP:
                stats["split"] += 1
                mx, my = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2
                return [(c[0], c[1], mx, my), (mx, c[1], c[2], my), (c[0], my, mx, c[3]), (mx, my, c[2], c[3])]
            with RAW.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"cell": key_of(c), "n": len(props), "rows": props}, ensure_ascii=False) + "\n")
            stats["leaves"] += 1
            stats["rows"] += len(props)
            return []

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=4) as ex:
        while queue:
            batch = [c for c in queue if key_of(c) not in done]
            queue = []
            for children in ex.map(work, batch):
                queue += children
            print(json.dumps({**stats, "pending_next_level": len(queue), "elapsed_s": round(time.time() - t0)}), flush=True)
    print(json.dumps({"fetch_done": dict(stats)}), flush=True)


def tier(rn):
    rn = str(rn or "")
    return "대로" if rn.endswith("대로") else "로" if rn.endswith("로") else "길" if rn.endswith("길") else "기타"


def num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def summarize(rows):
    n = len(rows)
    vals = [r["v"] for r in rows]
    valued = [v for v in vals if v is not None]
    out = {"segments": n, "missing": sum(v is None for v in vals), "missing_rate": round(sum(v is None for v in vals) / n, 4) if n else None,
           "zero": sum(v == 0 for v in vals), "eq_3_0": sum(v == 3.0 for v in vals), "eq_3_0_rate": round(sum(v == 3.0 for v in vals) / n, 4) if n else None}
    by = defaultdict(list)
    for r in rows:
        by[r["t"]].append(r["v"])
    dl = [v for v in by["대로"] if v is not None]
    ro = [v for v in by["로"] if v is not None]
    gil = [v for v in by["길"] if v is not None]
    out.update({
        "tier_segments": {k: len(v) for k, v in by.items()},
        "daero_valued": len(dl), "daero_lt40": sum(v < 40 for v in dl), "daero_lt40_rate": round(sum(v < 40 for v in dl) / len(dl), 4) if dl else None,
        "daero_eq_3_0": sum(v == 3.0 for v in dl),
        "ro_valued": len(ro), "ro_outside_12_40": sum(not (12 <= v < 40) for v in ro),
        "ro_outside_12_40_rate": round(sum(not (12 <= v < 40) for v in ro) / len(ro), 4) if ro else None, "ro_eq_3_0": sum(v == 3.0 for v in ro),
        "gil_valued": len(gil), "gil_p10_p50_p90": [round(float(x), 2) for x in np.percentile(gil, [10, 50, 90])] if gil else None,
        "gil_top": Counter(gil).most_common(6),
    })
    return out


def agg():
    seen, rows, conflicts, dup_rows, no_id = {}, [], 0, 0, 0
    cells = 0
    for line in RAW.open(encoding="utf-8"):
        rec = json.loads(line)
        cells += 1
        for p in rec["rows"]:
            v = num(p.get("road_bt"))
            if p.get("rds_man_no") in (None, "", "None"):
                # 관리번호가 없으면 중복 판정 불가 — 행 그대로 두고 건수 기록(합치지 않음)
                no_id += 1
                rows.append({"sido": str(p.get("sig_cd"))[:2], "t": tier(p.get("rn")), "v": v})
                continue
            k = (str(p.get("sig_cd")), str(p.get("rds_man_no")))
            if k in seen:
                dup_rows += 1
                if seen[k] != v:
                    conflicts += 1
                continue
            seen[k] = v
            rows.append({"sido": str(p.get("sig_cd"))[:2], "t": tier(p.get("rn")), "v": v})
    failed = [json.loads(l) for l in FAIL.open(encoding="utf-8")] if FAIL.exists() else []
    by_sido = defaultdict(list)
    for r in rows:
        by_sido[r["sido"]].append(r)
    out = {"rule_doc": "docs/판정기준.md §10", "rule_commit": "cd9998c", "layer": "lt_l_sprd(도로명주소도로)",
           "leaf_cells": cells, "failed_cells": len(failed), "failed_examples": failed[:5],
           "coverage_note": "미수급 칸 0 이면 격자 기준 전수, 아니면 걸친 시도는 부분(표본)" ,
           "dedup": {"duplicate_rows": dup_rows, "conflicting_road_bt": conflicts, "rows_without_rds_man_no": no_id}, "unit_assumption": "m 가정 — 명세 미확인",
           "interpretation_constraint": "시행령 제3조①1호나목(폭 또는 차로 수) · 제8조②1호 단서(대로↔로, 로↔길 호환) — 끝말·폭 불일치는 모순·오류가 아님",
           "national": summarize(rows),
           "by_sido": {SIDO.get(s, s): summarize(v) for s, v in sorted(by_sido.items())}}
    DER.mkdir(parents=True, exist_ok=True)
    (DER / "road_bt_national.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("leaf_cells", "failed_cells", "dedup", "national")}, ensure_ascii=False))
    for s, v in out["by_sido"].items():
        print(s, {k: v[k] for k in ("segments", "missing_rate", "eq_3_0_rate", "daero_valued", "daero_lt40", "daero_lt40_rate", "ro_valued", "ro_outside_12_40_rate")})


if __name__ == "__main__":
    {"fetch": fetch, "agg": agg}[sys.argv[1]]()
