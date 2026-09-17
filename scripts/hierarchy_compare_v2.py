"""010 §1-2 추가 측정 — 기준 §16-5 (실행 전 커밋 5a2e4c1). §16-1~4 건수 결과(hierarchy_compare.py)는 그대로 둔다.

1. 길이 구성비: 표준노드링크 LENGTH 합 · 도로명주소도로 road_lt 합(단위 미확인) — 원천 안 위계별 비율만
2. 가지도로 = 「길+번길」 합산 병기
3. 시도: LINK_ID 앞 3자리마다 링크 20개 중점을 브이월드 lt_c_adsido 에 점 조회 → 20개 모두 같으면 배정, 아니면 「혼재」
4. 도로명주소도로 시도 = sig_cd 앞 2자리를 lt_c_adsido ctprvn_cd·ctp_kor_nm 로 표기

실행: python hierarchy_compare_v2.py fetch  (도로명주소도로 road_lt 재수급, §10 격자 방식 동일)
      python hierarchy_compare_v2.py sido   (앞자리 시도 배정)
      python hierarchy_compare_v2.py agg
키: os.environ["VWORLD_APIKEY"] 만. 출력: data/vworld/national/derived/hierarchy_compare_v2.json · deliverables/도로명위계_전국대조_길이.csv
"""
from __future__ import annotations

import csv
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
import pyogrio
import shapely
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hierarchy_compare import TIERS, tier  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]   # 저장소 루트(scripts/ 한 단계 위)
RAW2 = ROOT / "data/vworld/national/raw/sprd_national_lt_cells.jsonl"
FAIL2 = ROOT / "data/vworld/national/raw/sprd_national_lt_failed.jsonl"
PREFIX = ROOT / "data/vworld/national/derived/nodelink_prefix_sido.json"
LINK = ROOT / "data/vworld/national/raw/NODELINKDATA_20260914/MOCT_LINK.shp"
DER = ROOT / "data/vworld/national/derived"
DELIV = ROOT / "deliverables"
KEY = os.environ.get("VWORLD_APIKEY", "")
CAP = 1000
lock = threading.Lock()


def mask(s):
    return str(s).replace(KEY, "***") if KEY else str(s)


def wfs(typename, bbox, props, maxf=CAP):
    q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": typename, "OUTPUT": "application/json",
         "MAXFEATURES": str(maxf), "SRSNAME": "EPSG:900913", "PROPERTYNAME": props, "BBOX": ",".join(f"{v}" for v in bbox) + ",EPSG:900913", "key": KEY}
    url = "https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode(q)
    err = None
    for attempt in range(3):
        try:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"}), timeout=120).read())
            if "features" in j:
                return [f["properties"] for f in j["features"]], None
            err = mask(json.dumps(j, ensure_ascii=False)[:200])
        except Exception as e:  # noqa: BLE001
            err = mask(f"{type(e).__name__}: {e}")[:200]
        time.sleep(3 * (attempt + 1))
    return None, err


def fetch():
    t = Transformer.from_crs(4326, 3857, always_xy=True)
    X0, Y0 = t.transform(124.5, 33.0)
    X1, Y1 = t.transform(132.0, 38.7)
    STEP = 20000.0
    done = {json.loads(l)["cell"] for l in RAW2.open(encoding="utf-8")} if RAW2.exists() else set()
    if FAIL2.exists():
        FAIL2.unlink()
    queue = [(x, y, min(x + STEP, X1), min(y + STEP, Y1)) for x in np.arange(X0, X1, STEP) for y in np.arange(Y0, Y1, STEP)]
    st = Counter()

    def key_of(c):
        return ",".join(f"{v:.1f}" for v in c)

    def work(c):
        props, err = wfs("lt_l_sprd", c, "rn,road_lt,sig_cd,rds_man_no")
        with lock:
            st["requests"] += 1
            if props is None:
                FAIL2.open("a", encoding="utf-8").write(json.dumps({"cell": key_of(c), "error": err}, ensure_ascii=False) + "\n")
                st["failed"] += 1
                return []
            if len(props) >= CAP:
                st["split"] += 1
                mx, my = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2
                return [(c[0], c[1], mx, my), (mx, c[1], c[2], my), (c[0], my, mx, c[3]), (mx, my, c[2], c[3])]
            RAW2.open("a", encoding="utf-8").write(json.dumps({"cell": key_of(c), "rows": props}, ensure_ascii=False) + "\n")
            st["leaves"] += 1
            return []

    with ThreadPoolExecutor(max_workers=4) as ex:
        while queue:
            batch = [c for c in queue if key_of(c) not in done]
            queue = []
            for ch in ex.map(work, batch):
                queue += ch
            print(json.dumps(dict(st)), flush=True)


def sido():
    links = pyogrio.read_dataframe(LINK, columns=["LINK_ID"], encoding="cp949")
    links["p3"] = links.LINK_ID.astype(str).str[:3]
    t53 = Transformer.from_crs(5186, 3857, always_xy=True)
    out, jobs = {}, []
    for p3, g in links.groupby("p3"):
        idx = np.linspace(0, len(g) - 1, min(20, len(g))).astype(int)
        mids = shapely.line_interpolate_point(g.geometry.values[idx], 0.5, normalized=True)
        for m in mids:
            x, y = t53.transform(m.x, m.y)
            jobs.append((p3, (x - 5, y - 5, x + 5, y + 5)))

    def work(job):
        p3, bb = job
        props, err = wfs("lt_c_adsido", bb, "ctprvn_cd,ctp_kor_nm", maxf=10)
        return p3, (sorted({f"{p.get('ctprvn_cd')}|{p.get('ctp_kor_nm')}" for p in props}) if props is not None else ["조회실패"])

    res = defaultdict(list)
    with ThreadPoolExecutor(max_workers=4) as ex:
        for p3, v in ex.map(work, jobs):
            res[p3].append(v)
    for p3, vs in res.items():
        flat = Counter("+".join(v) if v else "없음" for v in vs)
        single = len(flat) == 1 and "+" not in next(iter(flat)) and next(iter(flat)) not in ("없음", "조회실패")
        out[p3] = {"samples": len(vs), "values": dict(flat), "assigned": next(iter(flat)) if single else "혼재"}
    PREFIX.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"prefixes": len(out), "assigned": sum(v["assigned"] != "혼재" for v in out.values()),
                      "mixed": [k for k, v in out.items() if v["assigned"] == "혼재"]}, ensure_ascii=False))


def agg():
    # 도로명주소도로(길이)
    seen, sprd = set(), []
    for line in RAW2.open(encoding="utf-8"):
        for p in json.loads(line)["rows"]:
            k = (str(p.get("sig_cd")), str(p.get("rds_man_no")))
            if k in seen:
                continue
            seen.add(k)
            try:
                lt = float(p.get("road_lt")) if p.get("road_lt") not in (None, "") else None
            except (TypeError, ValueError):
                lt = None
            sprd.append((str(p.get("sig_cd"))[:2], tier(p.get("rn")), lt))
    fail2 = sum(1 for _ in FAIL2.open(encoding="utf-8")) if FAIL2.exists() else 0
    links = pyogrio.read_dataframe(LINK, columns=["LINK_ID", "ROAD_NAME", "LENGTH"], encoding="cp949", read_geometry=False)
    links["t"] = [tier(n) for n in links.ROAD_NAME.fillna("")]
    links["p3"] = links.LINK_ID.astype(str).str[:3]
    pref = json.loads(PREFIX.read_text(encoding="utf-8"))
    code_name = {}
    for v in pref.values():
        if v["assigned"] != "혼재":
            c, n = v["assigned"].split("|", 1)
            code_name[c] = n
    links["sido"] = links.p3.map(lambda p: pref.get(p, {}).get("assigned", "미상"))
    links["sido"] = links.sido.map(lambda s: s.split("|", 1)[1] if "|" in s else s)

    def comp_count(ts):
        c = Counter(t for t in ts if t is not None)
        tot = sum(c[t] for t in TIERS)
        r = {t: round(c[t] / tot, 4) if tot else None for t in TIERS}
        r["길+번길"] = round((c["길"] + c["번길"]) / tot, 4) if tot else None
        return r, tot

    def comp_len(pairs):
        s = defaultdict(float)
        miss = 0
        for t, l in pairs:
            if t is None:
                continue
            if l is None:
                miss += 1
                continue
            s[t] += l
        tot = sum(s[t] for t in TIERS)
        r = {t: round(s[t] / tot, 4) if tot else None for t in TIERS}
        r["길+번길"] = round((s["길"] + s["번길"]) / tot, 4) if tot else None
        return r, round(tot), miss

    out = {"rule_commit": "5a2e4c1", "sprd_fetch_failed_cells": fail2, "sprd_segments": len(sprd),
           "limits": "구간 수와 링크 수는 단위가 다르다 · road_lt 단위 미확인 · 원천 안 구성비만 비교 · 「번길」은 이름 관행이 지역마다 달라 골목 위계의 충분한 대리 지표가 아님"}
    sc, _ = comp_count([t for _, t, _ in sprd])
    sl, slt, slm = comp_len([(t, l) for _, t, l in sprd])
    nc, _ = comp_count(list(links.t))
    nl, nlt, nlm = comp_len(list(zip(links.t, links.LENGTH)))
    out["national"] = {"sprd_count_share": sc, "sprd_length_share": sl, "sprd_length_total": slt, "sprd_length_missing": slm,
                       "nodelink_count_share": nc, "nodelink_length_share": nl, "nodelink_length_total_m": nlt}
    by = {}
    sp_by = defaultdict(list)
    for s, t, l in sprd:
        sp_by[code_name.get(s, s)].append((t, l))
    nl_by = {k: g for k, g in links.groupby("sido")}
    for s in sorted(set(sp_by) | set(nl_by)):
        a = sp_by.get(s, [])
        g = nl_by.get(s)
        by[s] = {"sprd_segments": len(a), "sprd_length_share": comp_len(a)[0] if a else None,
                 "nodelink_links": 0 if g is None else int(len(g)), "nodelink_length_share": comp_len(list(zip(g.t, g.LENGTH)))[0] if g is not None else None}
    out["by_sido"] = by
    out["prefix_assignment"] = {"prefixes": len(pref), "mixed": [k for k, v in pref.items() if v["assigned"] == "혼재"],
                                "mixed_links": int((links.sido == "혼재").sum())}
    (DER / "hierarchy_compare_v2.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    with (DELIV / "도로명위계_전국대조_길이.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        cols = TIERS + ["길+번길"]
        w.writerow(["범위", "원천", "기준"] + cols + ["비고"])
        w.writerow(["전국", "도로명주소도로", "길이(road_lt, 단위 미확인)"] + [sl[c] for c in cols] + [f"결측 {slm}"])
        w.writerow(["전국", "표준노드링크", "길이(LENGTH m)"] + [nl[c] for c in cols] + [""])
        w.writerow(["전국", "도로명주소도로", "건수"] + [sc[c] for c in cols] + [""])
        w.writerow(["전국", "표준노드링크", "건수"] + [nc[c] for c in cols] + [""])
        for s, v in by.items():
            if v["sprd_length_share"]:
                w.writerow([s, "도로명주소도로", "길이"] + [v["sprd_length_share"][c] for c in cols] + [f"구간 {v['sprd_segments']}"])
            if v["nodelink_length_share"]:
                w.writerow([s, "표준노드링크", "길이"] + [v["nodelink_length_share"][c] for c in cols] + [f"링크 {v['nodelink_links']}"])
    print(json.dumps({k: out[k] for k in ("sprd_fetch_failed_cells", "sprd_segments", "national", "prefix_assignment")}, ensure_ascii=False))
    for s, v in by.items():
        print(s, v["sprd_segments"], (v["sprd_length_share"] or {}).get("번길"), (v["sprd_length_share"] or {}).get("길+번길"),
              v["nodelink_links"], (v["nodelink_length_share"] or {}).get("번길"), (v["nodelink_length_share"] or {}).get("길+번길"))


if __name__ == "__main__":
    {"fetch": fetch, "sido": sido, "agg": agg}[sys.argv[1]]()
