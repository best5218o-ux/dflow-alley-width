"""011 §3 — 이름 단위 포함률 + 대조군(대전). 기준: docs/판정기준.md §19 (실행 전 커밋 561d235).

- 단위: (시군구, 정규화 도로명). 위계 길·번길만
- 처리군 A: 진입곤란 지정 v2 조각 도로명(연계 테이블의 lt_l_sprd sig_cd) / B(참고): 26개소 — 선택 순환으로 검정 안 함
- 대조군: 대전 5개 구 도로명주소도로 길·번길 이름 − 처리군 A
- 포함: 같은 시군구 표준노드링크 ROAD_NAME 집합(링크 중점 × 브이월드 lt_c_adsigg). 「-」·빈값 = 이름 없음
- Fisher 단측 · Wilson 95 % · 민감도 S1(대전 전체) · S2(편집거리 ≤ 1)
키: os.environ["VWORLD_APIKEY"] 만. 출력: data/vworld/national/derived/inclusion_rate.json · deliverables/이름포함률_대전.csv
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from _rawio import open_raw, raw_exists  # 2026-09-18: .jsonl 없으면 .jsonl.gz

import pandas as pd
import pyogrio
import shapely
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as shp_transform

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hierarchy_compare import tier  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]   # 저장소 루트(scripts/ 한 단계 위)
DER = ROOT / "data/vworld/national/derived"
DELIV = ROOT / "deliverables"
RAW = ROOT / "data/vworld/national/raw/road_bt_national_cells.jsonl"
LINK = ROOT / "data/vworld/national/raw/NODELINKDATA_20260914/MOCT_LINK.shp"
KEY = os.environ.get("VWORLD_APIKEY", "").strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
GU = {"30110": "동구", "30140": "중구", "30170": "서구", "30200": "유성구", "30230": "대덕구"}
RULE = "561d235"


def norm(s):
    s = unicodedata.normalize("NFC", str(s or ""))
    s = re.sub(r"\([^)]*\)", "", s)
    s = "".join(s.split())
    return s


def no_name(s):
    return norm(s) in ("", "-")


def wilson(k, n, z=1.959964):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def fisher_one_sided(a, b, c, d):
    """표 [[a,b],[c,d]] (a = 처리군 미포함, b = 처리군 포함, c = 대조군 미포함, d = 대조군 포함).
    H1 처리군 미포함 비율이 더 높음 → P(X ≥ a), X ~ 초기하. 반대 방향 P(X ≤ a) 도 반환."""
    n1, K, N = a + b, a + c, a + b + c + d
    def pmf(x):
        return math.comb(K, x) * math.comb(N - K, n1 - x) / math.comb(N, n1)
    lo, hi = max(0, n1 - (N - K)), min(n1, K)
    greater = sum(pmf(x) for x in range(a, hi + 1))
    less = sum(pmf(x) for x in range(lo, a + 1))
    return round(greater, 6), round(less, 6)


def lev1(a, b):
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    if len(a) > len(b):
        a, b = b, a
    i = j = diff = 0
    while i < len(a) and j < len(b):
        if a[i] != b[j]:
            diff += 1
            if diff > 1:
                return False
            j += 1
        else:
            i += 1
            j += 1
    return True


def adsigg_polys():
    t = Transformer.from_crs(4326, 3857, always_xy=True)
    x0, y0 = t.transform(127.22, 36.17)
    x1, y1 = t.transform(127.58, 36.51)
    q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": "lt_c_adsigg", "OUTPUT": "application/json",
         "MAXFEATURES": "1000", "SRSNAME": "EPSG:900913", "BBOX": f"{x0},{y0},{x1},{y1},EPSG:900913", "key": KEY, "domain": DOMAIN}
    url = "https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode(q)
    j = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"}), timeout=180).read())
    t35 = Transformer.from_crs(3857, 5186, always_xy=True)
    out = []
    for f in j["features"]:
        p = f["properties"]
        code = str(p.get("sig_cd") or "")
        if code in GU:
            out.append((code, shp_transform(lambda x, y, z=None: t35.transform(x, y), shape(f["geometry"]))))
    return out, [sorted(f["properties"].keys()) for f in j["features"][:1]]


def main():
    # 대조군 모집단: 도로명주소도로 대전 길·번길 이름
    seen, pop = set(), defaultdict(set)
    for line in open_raw(RAW):
        for p in json.loads(line)["rows"]:
            sc = str(p.get("sig_cd"))
            if sc not in GU:
                continue
            k = (sc, str(p.get("rds_man_no")))
            if k in seen:
                continue
            seen.add(k)
            nm = norm(p.get("rn"))
            if tier(nm) in ("길", "번길"):
                pop[sc].add(nm)
    # 처리군 A · B
    lt = pd.read_csv(DER / "linkage_table.csv", dtype=str)
    cc = json.loads((DER / "missing_alley_crosscheck.json").read_text(encoding="utf-8"))
    s26 = {str(s["연번"]) for s in cc["sites"]}
    rows = lt[lt.road_name.notna()].copy()
    no_sprd = rows[rows.sig_cd.isna()]
    rows = rows[rows.sig_cd.notna()]
    rows["nm"] = rows.road_name.map(norm)
    rows = rows[rows.nm.map(lambda n: tier(n) in ("길", "번길"))]
    treatA = sorted({(r.sig_cd, r.nm) for r in rows.itertuples()})
    treatB = sorted({(r.sig_cd, r.nm) for r in rows.itertuples() if r.연번 in s26})
    tA = set(treatA)
    control = sorted({(sc, nm) for sc, ns in pop.items() for nm in ns} - tA)
    treat_not_in_pop = [x for x in treatA if x[1] not in pop.get(x[0], set())]
    # 표준노드링크 이름 집합(시군구 귀속)
    links = pyogrio.read_dataframe(LINK, columns=["LINK_ID", "ROAD_NAME"], encoding="cp949", bbox=(215000, 395000, 255000, 435000))
    links = links[links.LINK_ID.astype(str).str[:3].isin([str(i) for i in range(183, 188)])].copy()
    polys, prop_keys = adsigg_polys()
    mids = shapely.line_interpolate_point(links.geometry.values, 0.5, normalized=True)
    tree = shapely.STRtree([g for _, g in polys])
    ip, iq = tree.query(mids, predicate="within")
    gu = pd.Series([None] * len(links), index=links.index, dtype=object)
    gu.iloc[ip] = [polys[i][0] for i in iq]
    links["gu"] = gu.values
    links["nm"] = links.ROAD_NAME.map(norm)
    named = links[~links.ROAD_NAME.map(no_name)]
    nl_by_gu = defaultdict(set)
    for r in named.itertuples():
        if r.gu:
            nl_by_gu[r.gu].add(r.nm)
    nl_all = set(named.nm)
    link_stats = {"daejeon_links": int(len(links)), "no_name_links(-·빈값)": int(links.ROAD_NAME.map(no_name).sum()),
                  "links_unassigned_gu": int(links.gu.isna().sum()), "adsigg_polygons": len(polys), "adsigg_props": prop_keys}

    def evaluate(group):
        inc = [x for x in group if x[1] in nl_by_gu.get(x[0], set())]
        miss = [x for x in group if x not in set(inc)]
        inc_all = [x for x in group if x[1] in nl_all]
        miss_lev = [x for x in miss if any(lev1(x[1], y) for y in nl_by_gu.get(x[0], set()))]
        n = len(group)
        return {"names": n, "included": len(inc), "not_included": len(miss),
                "not_included_rate": round(len(miss) / n, 4) if n else None, "not_included_ci95": wilson(len(miss), n),
                "S1_daejeon_wide_not_included_rate": round(1 - len(inc_all) / n, 4) if n else None,
                "S2_not_included_but_edit1_match": len(miss_lev)}, miss

    rA, missA = evaluate(treatA)
    rC, missC = evaluate(control)
    rB, _ = evaluate(treatB)
    a, b = rA["not_included"], rA["included"]
    c, d = rC["not_included"], rC["included"]
    p_greater, p_less = fisher_one_sided(a, b, c, d)
    verdict = ("처리군 미포함률이 높다" if p_greater < 0.05 else
               ("처리군 미포함률이 낮다(반대 방향)" if p_less < 0.05 else "차이를 검출하지 못함"))
    by_gu = {}
    for code, name in GU.items():
        g_t = [x for x in treatA if x[0] == code]
        g_c = [x for x in control if x[0] == code]
        by_gu[name] = {"treatA": evaluate(g_t)[0] if g_t else None, "control": evaluate(g_c)[0] if g_c else None}
    out = {"rule_doc": "docs/판정기준.md §19", "rule_commit": RULE,
           "unit": "(시군구, 정규화 도로명) · 위계 길·번길", "link_stats": link_stats,
           "treatment_A": {**rA, "pieces_without_lt_l_sprd": int(len(no_sprd)), "names_not_in_control_population": treat_not_in_pop},
           "treatment_B_reference_26_selection_circular": rB, "control": rC,
           "difference_A_minus_control": round(rA["not_included_rate"] - rC["not_included_rate"], 4),
           "fisher_one_sided": {"table": [[a, b], [c, d]], "p_treat_higher": p_greater, "p_treat_lower": p_less}, "verdict": verdict,
           "by_gu": by_gu, "treatment_A_names": [{"sig_cd": s, "name": n, "included": (s, n) not in set(missA)} for s, n in treatA]}
    (DER / "inclusion_rate.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    DELIV.mkdir(parents=True, exist_ok=True)
    with (DELIV / "이름포함률_대전.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["집단", "범위", "이름수", "포함", "미포함", "미포함률", "95%CI", "S1_대전전체_미포함률", "S2_편집거리1_미포함중일치", "비고"])
        for label, r, note in (("처리군A(진입곤란 지정 전체)", rA, "주 분석"), ("대조군(대전 길·번길 − A)", rC, ""),
                               ("처리군B(26개소)", rB, "선택 순환 — 검정 안 함")):
            w.writerow([label, "대전", r["names"], r["included"], r["not_included"], r["not_included_rate"], r["not_included_ci95"],
                        r["S1_daejeon_wide_not_included_rate"], r["S2_not_included_but_edit1_match"], note])
        for g, v in by_gu.items():
            for label, r in (("처리군A", v["treatA"]), ("대조군", v["control"])):
                if r:
                    w.writerow([label, g, r["names"], r["included"], r["not_included"], r["not_included_rate"], r["not_included_ci95"],
                                r["S1_daejeon_wide_not_included_rate"], r["S2_not_included_but_edit1_match"], ""])
    print(json.dumps({k: out[k] for k in ("link_stats", "treatment_A", "treatment_B_reference_26_selection_circular", "control",
                                          "difference_A_minus_control", "fisher_one_sided", "verdict")}, ensure_ascii=False))
    for g, v in by_gu.items():
        print(g, (v["treatA"] or {}).get("names"), (v["treatA"] or {}).get("not_included_rate"), v["control"]["names"], v["control"]["not_included_rate"])


if __name__ == "__main__":
    main()
