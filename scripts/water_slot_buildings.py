"""021 §1-2·§1-3 · 022 §2-2 — 용수 도달성(직선거리) · 슬롯 순서(시간 미계산) · 접한 건물 수.
기준 docs/판정기준.md §30·§31·§32 (실행 전 커밋 35281c0).

- 용수 거리는 **직선거리**다. 경로거리가 아니다
- 호스 연장 한계값을 보유 자료에서 확인하지 못하면 판정하지 않는다(거리만)
- 슬롯은 순서만 배정한다. seconds: NOT_COMPUTED
- 「접한 건물」이다. 세대·주민으로 바꾸지 않는다. 인구는 원천 확보 시에만
키는 os.environ["VWORLD_APIKEY"] 만 참조 · 로그·산출 *** 마스킹
"""
from __future__ import annotations

import csv
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from _rawio import raw_path  # 2026-09-18: 평문 없으면 .gz

import pandas as pd
import shapely
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform as sh_transform

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"
DELIV = ROOT / "deliverables"
KEY = os.environ["VWORLD_APIKEY"].strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
T3857 = Transformer.from_crs(4326, 3857, always_xy=True)
T5186 = Transformer.from_crs(4326, 5186, always_xy=True)
T900913_5186 = Transformer.from_crs(3857, 5186, always_xy=True)
RULE = "docs/판정기준.md §30·§31·§32 (실행 전 커밋 35281c0)"
HOSE_LIMIT_M = None  # 보유 자료(ch09 제원 · SOP 208 · 통계)에서 거리 한계 수치 확인 못 함 → 판정하지 않음


def mask(s):
    return str(s).replace(KEY, "***").replace(urllib.parse.quote(KEY), "***")


def wfs(typename, x, y, half=200.0):
    q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": typename,
         "OUTPUT": "application/json", "MAXFEATURES": "1000", "SRSNAME": "EPSG:900913",
         "BBOX": f"{x-half},{y-half},{x+half},{y+half},EPSG:900913", "key": KEY, "domain": DOMAIN}
    url = "https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode(q)
    last = None
    for a in range(3):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"}), timeout=90).read()
            return json.loads(b.decode("utf-8", "replace"))["features"], None
        except Exception as e:  # noqa: BLE001
            last = mask(f"{type(e).__name__}: {e}")[:160]
            time.sleep(1.5 * (a + 1))
    return None, last


def norm(s):
    return "".join(str(s or "").split())


def tier(name):
    n = norm(name)
    if n.endswith("번길"):
        return "번길"
    if n.endswith("길"):
        return "길"
    if n.endswith("대로"):
        return "대로"
    if n.endswith("로"):
        return "로"
    return "기타"


def to5186(feature):
    return sh_transform(lambda a, b: T900913_5186.transform(a, b), shape(feature["geometry"]))


def main():
    cc = json.loads((DER / "missing_alley_crosscheck.json").read_text(encoding="utf-8"))
    mw = {r["piece"]: r for r in json.loads((DER / "ngii_medial_width.json").read_text(encoding="utf-8"))["pieces"]}
    fw = pd.read_csv(raw_path(ROOT / "data/vworld/national/raw/firewater/std_firewater_20240213.csv"), dtype=str, encoding="utf-8-sig")   # 2026-09-18: .csv 없으면 .csv.gz(pandas 가 확장자로 압축 해제)
    fw = fw[fw["시도명"] == "대전광역시"].copy()
    lat = pd.to_numeric(fw["위도"], errors="coerce")
    lon = pd.to_numeric(fw["경도"], errors="coerce")
    ok = lat.between(33, 39) & lon.between(124, 132)
    fw, lat, lon = fw[ok], lat[ok], lon[ok]
    wpts = [Point(*T5186.transform(a, b)) for a, b in zip(lon, lat)]
    wtree = shapely.STRtree(wpts)
    wcode = list(fw["시설유형코드"].str.strip())
    wname = list(fw["시설번호"])
    water_rows, slot_rows, bld_rows, by_site = [], [], [], {}
    for si, s in enumerate(cc["sites"], 1):
        pieces = [p for p in s["pieces"] if p["type"] == "road"]
        if not pieces:
            continue
        rep = pieces[0]["point"]
        repp = Point(*T5186.transform(*rep))
        cand = [p for p in pieces if mw.get(p["piece"], {}).get("band") in ("CONDITIONAL_C", "폭축_통과후보")]
        if cand:
            dep = min(cand, key=lambda p: Point(*T5186.transform(*p["point"])).distance(repp))
            dep_pt, dep_piece = dep["point"], dep["piece"]
            dep_status = "전개 후보지점(1차)"
        else:
            dep_pt, dep_piece = rep, pieces[0]["piece"]
            dep_status = "UNKNOWN_FAIL_CLOSED(개소 조각이 전부 BLOCKED·UNKNOWN) — 거리는 대표점 기준 병기"
        dp = Point(*T5186.transform(*dep_pt))
        i = int(wtree.nearest(dp))
        d = round(wpts[i].distance(dp), 1)
        water_rows.append({"연번": si, "시군구": s.get("시군구"), "개소": s.get("지정현황"),
                           "전개 후보지점": dep_piece, "전개지점 상태": dep_status,
                           "최근접 용수 직선거리(m)": d, "시설유형코드(의미 미정의)": wcode[i], "시설번호": wname[i],
                           "water_reach_status": "UNKNOWN_FAIL_CLOSED(기준 미확보 — 호스 연장 한계 수치 확인 못 함)",
                           "등급 상한": "C(전개 후보지점이 C 등급 폭 판정에 기반)"})
        x3, y3 = T3857.transform(*dep_pt)
        f, err = wfs("lt_l_sprd", x3, y3, 300.0)
        big = None
        if f:
            cands = []
            for ft in f:
                nm = ft["properties"].get("rn")
                if tier(nm) in ("로", "대로"):
                    cands.append((to5186(ft).distance(dp), nm))
            if cands:
                dd, nm = min(cands, key=lambda z: z[0])
                big = {"도로명": nm, "거리(m)": round(dd, 1)}
        blocked_all = all(mw.get(p["piece"], {}).get("band") in ("BLOCKED", "UNKNOWN_FAIL_CLOSED", None) for p in pieces)
        slot_rows.append({"연번": si, "개소": s.get("지정현황"),
                          "폭 판정(전개지점 조각)": mw.get(dep_piece, {}).get("band"),
                          "큰 길(대기)": (big or {}).get("도로명"), "큰 길 거리(m)": (big or {}).get("거리(m)"),
                          "큰 길 조회": "미조회" if f is None else "조회됨",
                          "순서": ("배정하지 않음(fail-closed — 개소의 모든 조각이 BLOCKED 또는 UNKNOWN)" if blocked_all
                                 else "1 펌프차 진입·전개 → 2 구조차 대기 후 진입 → 3 구급차 대기 후 진입"),
                          "대기 규칙": "구조차·구급차는 골목 진입 전 큰 길에서 대기(펌프 통행 비간섭)",
                          "seconds": "NOT_COMPUTED"})
        ids_site, ids_blocked = set(), set()
        for p in pieces:
            xx, yy = T3857.transform(*p["point"])
            lines, e1 = wfs("lt_l_sprd", xx, yy, 200.0)
            blds, e2 = wfs("lt_c_spbd", xx, yy, 200.0)
            if lines is None or blds is None:
                bld_rows.append({"연번": si, "조각": p["piece"], "error": "미조회"})
                continue
            tgt = norm(p.get("road_name"))
            segs = [to5186(ft) for ft in lines if norm(ft["properties"].get("rn")) == tgt]
            if not segs:
                bld_rows.append({"연번": si, "조각": p["piece"], "error": "같은 도로명 선형 없음"})
                continue
            buf = shapely.union_all(segs).buffer(20.0)
            hit = set()
            for ft in blds:
                g = to5186(ft)
                if g.intersects(buf):
                    pr = ft["properties"]
                    key = pr.get("bdmgt_sn") or pr.get("id") or pr.get("ufid") or f"{g.centroid.x:.1f},{g.centroid.y:.1f}"
                    hit.add(key)
            ids_site |= hit
            if mw.get(p["piece"], {}).get("band") == "BLOCKED":
                ids_blocked |= hit
            bld_rows.append({"연번": si, "조각": p["piece"], "접한 건물": len(hit),
                             "폭 판정": mw.get(p["piece"], {}).get("band")})
        by_site[si] = {"개소 접한 건물(중복 제거)": len(ids_site), "BLOCKED 조각 접한 건물": len(ids_blocked),
                       "ids": sorted(ids_site), "blocked_ids": sorted(ids_blocked)}
        print(si, d, slot_rows[-1]["순서"][:14], by_site[si]["개소 접한 건물(중복 제거)"], flush=True)
    all_ids = set().union(*[set(v["ids"]) for v in by_site.values()]) if by_site else set()
    all_blocked = set().union(*[set(v["blocked_ids"]) for v in by_site.values()]) if by_site else set()
    ds = sorted(r["최근접 용수 직선거리(m)"] for r in water_rows)
    water = {"rule": RULE, "distance_type": "직선거리(EPSG:5186) — 경로거리 아님",
             "source": f"전국소방용수시설표준데이터(소방청, 포털 수정일 2024-02-13) 대전 {len(fw)}건",
             "hose_limit": "기준 미확보 — 보유 자료(ch09 제원·SOP 208·통계)에서 호스 연장 거리 한계 수치를 확인하지 못했다",
             "facility_code_note": "시설유형코드의 의미가 원천 항목설명에 정의돼 있지 않다. 코드만 적고 시설 종류로 옮기지 않는다",
             "grade_cap": "C — 전개 후보지점이 §29 C 등급 폭 판정에 기반",
             "summary": {"n": len(water_rows), "min_m": ds[0], "median_m": ds[len(ds) // 2], "max_m": ds[-1],
                         "전개지점 UNKNOWN": sum(1 for r in water_rows if r["전개지점 상태"].startswith("UNKNOWN"))},
             "rows": water_rows}
    slots = {"rule": RULE, "note": "순서가 배정됐다. 시간은 계산하지 않았다(seconds: NOT_COMPUTED)",
             "summary": {"순서 배정": sum(1 for r in slot_rows if r["순서"].startswith("1 ")),
                         "배정하지 않음(fail-closed)": sum(1 for r in slot_rows if r["순서"].startswith("배정하지")),
                         "큰 길 미확인": sum(1 for r in slot_rows if not r["큰 길(대기)"])},
             "rows": slot_rows}
    blds_out = {"rule": RULE, "term": "「접한 건물」 — 세대·주민으로 바꾸지 않는다",
                "population": "원천 미확보 — 인구를 추정하지 않는다",
                "rule_detail": "같은 도로명 lt_l_sprd 선형 양측 20 m 버퍼와 교차하는 lt_c_spbd 건물, 식별자로 중복 제거",
                "summary": {"26개소 합계(중복 제거)": len(all_ids), "BLOCKED 조각 접한 건물(중복 제거)": len(all_blocked)},
                "by_site": {k: {kk: vv for kk, vv in v.items() if kk not in ("ids", "blocked_ids")} for k, v in by_site.items()},
                "by_piece": bld_rows}
    (DER / "water_reach_26.json").write_text(json.dumps(water, ensure_ascii=False, indent=1), encoding="utf-8")
    (DER / "slot_order_26.json").write_text(json.dumps(slots, ensure_ascii=False, indent=1), encoding="utf-8")
    (DER / "adjacent_buildings_26.json").write_text(json.dumps(blds_out, ensure_ascii=False, indent=1), encoding="utf-8")
    DELIV.mkdir(parents=True, exist_ok=True)
    for name, rows in (("용수도달성_26개소.csv", water_rows), ("슬롯순서_26개소.csv", slot_rows)):
        with (DELIV / name).open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    with (DELIV / "접한건물수_26개소.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["연번", "개소 접한 건물(중복 제거)", "BLOCKED 조각 접한 건물"])
        for k, v in by_site.items():
            w.writerow([k, v["개소 접한 건물(중복 제거)"], v["BLOCKED 조각 접한 건물"]])
    print(json.dumps({"water": water["summary"], "slots": slots["summary"], "buildings": blds_out["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
