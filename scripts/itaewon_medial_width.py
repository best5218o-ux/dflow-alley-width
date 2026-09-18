"""096 §5 D-2 — 이태원 참사 지점 인근 4개 도로의 「도로경계 면 내접폭」. 기준 docs/판정기준.md §29 · §29-5.

목적: 이태원 권역의 폭 출처를 대전 26개소와 **같은 출처·같은 방법**으로 맞춘다.
  기존 deliverables/이태원_도로구간폭_판정.csv 는 도로명주소 도로구간 속성폭(road_bt) 이다 — 대전과 출처가 다르다.
  이 스크립트는 대전에서 쓴 scripts/ngii_medial_width.py 와 **같은 값**을 이태원에서 산출한다.

대전과 같은 점 (그대로 재사용):
  - WFS 레이어: 도로경계 면 lt_c_n3a0010000 · 도로중심선 lt_l_n3a0020000 (국토지리정보원 수치지형도 계열)
  - 좌표계 처리: 요청 BBOX EPSG:900913(3857) · 계측은 EPSG:5186 평면좌표
  - 상수: STEP 1.0 m · TRIM 2.0 m · MIN_LEN 10.0 m · MIN_PTS 8 · BBOX 반폭 200 m
  - 값 정의: 축선 위 표본점에서 도로경계 면 경계까지 최단거리 × 2 = 내접원 지름 = 「내접폭」. 「통과가능폭」이 아니다.
  - 판정 §29-5: ≤2.5 BLOCKED(문헌 — 소방차 표준 폭 2.2~2.5 m) · ≤3.5 CONDITIONAL_C(우리 설정, 근거 문헌 미확보) · 그 외 폭축_통과후보
  - 긴급차량 전폭 E: KFS 전폭 상한(경형 1.9 · 소형 2.2 · 중형/대형 2.5) 중 W 이하 최대. 일반차량 G = 2.0. 슬롯 2.5 / 3.7 / 5.7
  - 키는 os.environ 만 참조 · 로그·산출물에서 mask() 로 *** 치환

대전과 다른 점 (감추지 않는다):
  1) 대상 선정: 대전은 미확보 골목 26개소의 좌표 조각(piece)이었다. 이태원은 **도로명 4개**(참사 골목 이태원로27가길 우선)이고,
     좌표는 VWorld 지오코더(도로명주소 → 점)로 도로별 여러 점을 받아 쓴다. → 표본점 구성이 다르다.
  2) 장애물 차감폭(벽·옹벽·계단 레이어)은 이 실행에서 **산출하지 않는다**. 대전 산출물의 deducted_* 에 해당하는 열이 없다.
  3) SAM 차량 차감폭은 대전과 마찬가지로 이 권역에 미적용이다.

한계 (대전과 공통):
  - 도로경계 면이 무엇을 경계로 삼는지(포장 경계·도로구역 경계 등) 미확인 — 브이월드 제공 속성은 id·dycd 뿐(SCLS 미제공).
  - 축선 귀속은 이름이 아니라 거리다(도로중심선 rdnm 이 비어 있음) → road_bt 와의 「차이」가 값 오차인지 귀속 오차인지 구분되지 않는다.
  - 산출 못 한 구간은 값을 만들지 않는다. 빈 값 + 미산출사유로 남긴다. 조회 실패와 0건은 구분해 기록한다.

출처: 폭 = 국토지리정보원 도로경계 면(VWorld WFS). 대조용 속성폭 = 도로명주소 도로구간 road_bt(오프라인 수집분, sig_cd=11170).
출력: deliverables/이태원_도로경계내접폭.csv · data/vworld/national/derived/itaewon_medial_width.json
"""
from __future__ import annotations

import csv
import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import shapely
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform as sh_transform

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _rawio import open_raw  # noqa: E402

DER = ROOT / "data/vworld/national/derived"
DELIV = ROOT / "deliverables"
RAW_BT = ROOT / "data/vworld/national/raw/road_bt_national_cells.jsonl"

KEY = os.environ["VWORLD_APIKEY"].strip()
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost").strip()

T3857 = Transformer.from_crs(4326, 3857, always_xy=True)
T5186 = Transformer.from_crs(4326, 5186, always_xy=True)
T900913_5186 = Transformer.from_crs(3857, 5186, always_xy=True)
BOUND, CENTER = "lt_c_n3a0010000", "lt_l_n3a0020000"
HALF = 200.0
STEP, TRIM, MIN_LEN, MIN_PTS = 1.0, 2.0, 10.0, 8

SIG_CD = "11170"  # 서울 용산구
ROADS = ["이태원로27가길", "이태원로27길", "이태원로27나길", "이태원로"]  # 1번이 참사 골목
BLDG_NOS = [1, 3, 5, 7, 9, 11, 15, 19, 23, 27, 33, 40, 49, 55, 63, 77, 90, 110, 130, 150, 179, 200]
MAX_PTS_PER_ROAD = 6
MIN_SEP_M = 25.0  # 같은 도로 안에서 표본점끼리 최소 이격


def mask(s):
    return str(s).replace(KEY, "***").replace(urllib.parse.quote(KEY), "***")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"})
    return urllib.request.urlopen(req, timeout=90).read()


def geocode(addr):
    q = {"service": "address", "request": "getcoord", "version": "2.0", "crs": "epsg:4326",
         "address": addr, "refine": "true", "simple": "false", "format": "json",
         "type": "road", "key": KEY, "domain": DOMAIN}
    url = "https://api.vworld.kr/req/address?" + urllib.parse.urlencode(q)
    try:
        d = json.loads(_get(url).decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        return None, mask(f"{type(e).__name__}: {e}")[:160]
    res = d.get("response", {})
    if res.get("status") != "OK":
        return None, f"geocoder status={res.get('status')}"
    p = res.get("result", {}).get("point", {})
    try:
        return (float(p["x"]), float(p["y"])), None
    except Exception:  # noqa: BLE001
        return None, "geocoder point 없음"


def wfs(typename, x, y, half=HALF):
    q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": typename,
         "OUTPUT": "application/json", "MAXFEATURES": "1000", "SRSNAME": "EPSG:900913",
         "BBOX": f"{x-half},{y-half},{x+half},{y+half},EPSG:900913", "key": KEY, "domain": DOMAIN}
    url = "https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode(q)
    last = None
    for a in range(3):
        try:
            return json.loads(_get(url).decode("utf-8", "replace"))["features"], None
        except Exception as e:  # noqa: BLE001
            last = mask(f"{type(e).__name__}: {e}")[:160]
            time.sleep(1.5 * (a + 1))
    return None, last


def to5186(features):
    return [sh_transform(lambda a, b: T900913_5186.transform(a, b), shape(f["geometry"])) for f in features]


def band(w):
    if w is None:
        return "UNKNOWN_FAIL_CLOSED"
    if w <= 2.5:
        return "BLOCKED"
    if w <= 3.5:
        return "CONDITIONAL_C"
    return "폭축_통과후보"


def emergency_E(w):
    if w is None:
        return None
    for e in (2.5, 2.2, 1.9):
        if w >= e:
            return e
    return None


def piece_width(lon, lat):
    """대전 scripts/ngii_medial_width.py 의 piece_width 와 같은 절차(장애물 차감 제외)."""
    x3, y3 = T3857.transform(lon, lat)
    pt = Point(*T5186.transform(lon, lat))
    r = {"point": [round(lon, 7), round(lat, 7)]}
    bf, e1 = wfs(BOUND, x3, y3)
    cf, e2 = wfs(CENTER, x3, y3)
    if bf is None or cf is None:
        r["error"] = f"미조회(조회실패): {e1 or ''} {e2 or ''}".strip()
        return r
    r["n_boundary_features"] = len(bf)
    r["n_center_features"] = len(cf)
    polys = to5186(bf)
    area = shapely.union_all(polys) if polys else None
    lines = to5186(cf)
    props = [f["properties"] for f in cf]
    if not lines or area is None or area.is_empty:
        r["error"] = "조회성공_0건: 면 또는 축선 피처 0"
        return r
    i = min(range(len(lines)), key=lambda k: lines[k].distance(pt))
    axis = lines[i]
    r["axis"] = {"d_to_point_m": round(axis.distance(pt), 1), "rvwd": props[i].get("rvwd"),
                 "rddv": props[i].get("rddv"), "rdnm": props[i].get("rdnm"),
                 "len_m": round(axis.length, 1),
                 "귀속": "이름 아님 — 거리 기반(도로중심선 rdnm 비어 있음)"}
    inside = axis.intersection(area)
    if inside.is_empty:
        r["error"] = "축선이 도로경계 면 안에 들어가지 않음"
        return r
    parts = [p for p in list(getattr(inside, "geoms", [inside]))
             if p.geom_type in ("LineString", "MultiLineString") and p.length > 0]
    if not parts:
        r["error"] = "면 안 축선 구간 없음"
        return r
    seg = min(parts, key=lambda p: p.distance(pt))
    r["inside_len_m"] = round(seg.length, 1)
    if seg.length < MIN_LEN + 2 * TRIM:
        r["error"] = f"면 안 축선 {seg.length:.1f} m < {MIN_LEN + 2*TRIM} m"
        return r
    bnd = area.boundary
    n = int((seg.length - 2 * TRIM) // STEP) + 1
    loc = []
    for k in range(n):
        p = seg.interpolate(TRIM + k * STEP)
        if not area.covers(p):
            continue
        loc.append(2 * bnd.distance(p))
    r["samples"] = len(loc)
    if len(loc) < MIN_PTS:
        r["error"] = f"유효 표본점 {len(loc)} < {MIN_PTS}"
        return r
    s = sorted(loc)
    r["inscribed_min_m"] = round(s[0], 2)
    r["inscribed_p10_m"] = round(s[max(0, int(0.1 * len(s)) - 1)], 2)
    r["inscribed_median_m"] = round(s[len(s) // 2], 2)
    return r


def road_bt_ref():
    """오프라인 수집분에서 대상 도로의 도로명주소 속성폭(road_bt) 을 모은다. API 호출 없음."""
    tgt = set(ROADS)
    acc, seen = {t: [] for t in tgt}, set()
    for line in open_raw(RAW_BT):
        for row in json.loads(line)["rows"]:
            if row.get("sig_cd") != SIG_CD or row.get("rn") not in tgt:
                continue
            k = (row.get("rds_man_no"), row.get("rn"))
            if k in seen:
                continue
            seen.add(k)
            acc[row["rn"]].append(float(row["road_bt"]))
    return acc


def collect_points(rn):
    pts, errs = [], []
    for no in BLDG_NOS:
        if len(pts) >= MAX_PTS_PER_ROAD:
            break
        p, err = geocode(f"서울특별시 용산구 {rn} {no}")
        if p is None:
            errs.append(f"{no}: {err}")
            continue
        x, y = T5186.transform(*p)
        if any(((x - a) ** 2 + (y - b) ** 2) ** 0.5 < MIN_SEP_M for a, b in [T5186.transform(*q) for q in pts]):
            continue
        pts.append(p)
    return pts, errs


def main():
    bt = road_bt_ref()
    roads, fail_reasons = [], {}
    for rn in ROADS:
        pts, gerrs = collect_points(rn)
        rec = {"도로명": rn, "geocode_points": len(pts), "geocode_errors": gerrs[:6],
               "road_bt_n": len(bt.get(rn, [])),
               "road_bt_min_m": min(bt[rn]) if bt.get(rn) else None,
               "road_bt_median_m": statistics.median(bt[rn]) if bt.get(rn) else None,
               "pieces": []}
        for lon, lat in pts:
            r = piece_width(lon, lat)
            rec["pieces"].append(r)
            print(json.dumps({"도로명": rn, **{k: v for k, v in r.items() if k != "axis"}},
                             ensure_ascii=False)[:300], flush=True)
        ok = [p["inscribed_min_m"] for p in rec["pieces"] if p.get("inscribed_min_m") is not None]
        med = [p["inscribed_median_m"] for p in rec["pieces"] if p.get("inscribed_median_m") is not None]
        rec["산출성공_표본점"] = len(ok)
        rec["산출실패_표본점"] = len(rec["pieces"]) - len(ok)
        if ok:
            rec["내접폭_최소m"] = round(min(ok), 2)          # fail-closed: 가장 좁은 표본점
            rec["내접폭_중앙값m"] = round(statistics.median(med), 2) if med else None
            rec["판정"] = band(rec["내접폭_최소m"])
            rec["E"] = emergency_E(rec["내접폭_최소m"])
            w = rec["내접폭_최소m"]
            rec["슬롯"] = {"E_2.5": "Y" if w >= 2.5 else "N", "E+P_3.7": "Y" if w >= 3.7 else "N",
                          "E+P+G_5.7": "Y" if w >= 5.7 else "N"}
            rec["차이_내접폭최소-속성폭최소_m"] = (round(w - rec["road_bt_min_m"], 2)
                                            if rec["road_bt_min_m"] is not None else None)
            rec["미산출사유"] = ""
        else:
            why = ([p.get("error") for p in rec["pieces"] if p.get("error")]
                   or ([f"지오코딩 실패: {gerrs[0]}"] if gerrs else ["표본점 0"]))
            rec["판정"] = "UNKNOWN_FAIL_CLOSED"
            rec["미산출사유"] = why[0]
            fail_reasons[why[0]] = fail_reasons.get(why[0], 0) + 1
        roads.append(rec)

    DELIV.mkdir(exist_ok=True)
    cols = ["도로명", "표본점수", "산출성공_표본점", "내접폭_최소m", "내접폭_중앙값m", "판정_§29-5",
            "긴급차량_전폭상한E", "슬롯_E_2.5", "슬롯_E+P_3.7", "슬롯_E+P+G_5.7",
            "속성폭_road_bt_최소m", "속성폭_road_bt_중앙값m", "차이_내접폭최소-속성폭최소_m",
            "폭출처", "미산출사유"]
    with (DELIV / "이태원_도로경계내접폭.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in roads:
            sl = r.get("슬롯", {})
            w.writerow([r["도로명"], len(r["pieces"]), r["산출성공_표본점"],
                        r.get("내접폭_최소m", ""), r.get("내접폭_중앙값m", ""), r["판정"],
                        r.get("E", ""), sl.get("E_2.5", ""), sl.get("E+P_3.7", ""), sl.get("E+P+G_5.7", ""),
                        r.get("road_bt_min_m", ""), r.get("road_bt_median_m", ""),
                        r.get("차이_내접폭최소-속성폭최소_m", ""),
                        "국토지리정보원 도로경계 면 내접폭(VWorld WFS lt_c_n3a0010000) — 대전 26개소와 같은 출처",
                        r["미산출사유"]])

    okr = [r for r in roads if r.get("내접폭_최소m") is not None]
    vals = [r["내접폭_최소m"] for r in okr]
    summary = {
        "rule_doc": "docs/판정기준.md §29 · §29-5",
        "name": "이태원 참사 지점 인근 4개 도로 — 도로경계 면 내접폭 (「통과가능폭」 아님)",
        "대상": ROADS,
        "대전과_같은_출처_같은_방법": "레이어 lt_c_n3a0010000 / lt_l_n3a0020000 · STEP 1.0 · TRIM 2.0 · MIN_LEN 10.0 · MIN_PTS 8 · EPSG:5186 계측",
        "대전과_다른_점": ["대상이 좌표 조각이 아니라 도로명 4개 — 표본점은 지오코더로 받는다",
                       "장애물 차감폭(벽·옹벽·계단) 미산출", "SAM 차량 차감폭 미적용"],
        "boundary_definition": "미확인 — 브이월드 제공 속성 id·dycd 뿐(SCLS 미제공)",
        "attribution_limit": "축선 귀속은 거리 기반(rdnm 비어 있음) — road_bt 와의 차이가 값 오차인지 귀속 오차인지 구분되지 않는다",
        "params": {"bbox_half_m": HALF, "step_m": STEP, "trim_m": TRIM,
                   "min_inside_len_m": MIN_LEN, "min_points": MIN_PTS},
        "구간수": len(roads), "산출성공": len(okr), "산출실패": len(roads) - len(okr),
        "내접폭_최소m": min(vals) if vals else None, "내접폭_최대m": max(vals) if vals else None,
        "내접폭_중앙값m": statistics.median(vals) if vals else None,
        "판정분포": {b: sum(1 for r in roads if r["판정"] == b) for b in
                  ("BLOCKED", "CONDITIONAL_C", "폭축_통과후보", "UNKNOWN_FAIL_CLOSED")},
        "실패사유별_건수": fail_reasons,
        "실행환경_한계": ("2026-09-18 실행: api.vworld.kr 로의 CONNECT 가 이 실행 환경의 이그레스 정책에서 403 으로 거부되어 "
                     "지오코딩·WFS 조회를 한 건도 하지 못했다. 값이 0 이거나 없다는 뜻이 아니라 「조회 실패」다. "
                     "네트워크가 열린 환경에서 같은 스크립트를 그대로 실행하면 산출된다."),
        "무결성": "조회 실패와 0건은 구분해 기록한다. 산출 못 한 도로는 빈 값 + 미산출사유로 남기고 값을 만들지 않는다.",
        "roads": roads,
    }
    DER.mkdir(parents=True, exist_ok=True)
    (DER / "itaewon_medial_width.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print("도로", len(roads), "산출", len(okr), "미산출", len(roads) - len(okr))
    print(json.dumps(summary["실패사유별_건수"], ensure_ascii=False))


if __name__ == "__main__":
    main()
