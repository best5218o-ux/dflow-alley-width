"""브이월드 WFS 레이어 커버리지 실측 — 진입곤란 26개소 37조각 반경 100 m.

무엇을 하나
- 37개 도로 조각(data/vworld/national/derived/missing_alley_crosscheck.json, type=="road")마다
  점 중심 100 m 정사각 bbox 로 각 레이어를 WFS GetFeature 조회한다.
- 기록: 조각별 피처 건수 + (0건이 아닐 때) 첫 피처의 속성 키 목록. 지오메트리는 저장하지 않는다.

규칙(이 스크립트의 핵심)
- "조회했고 0건"과 "조회하지 못함"을 절대 섞지 않는다. 예외·오류·invalid TYPENAME 은
  count 0 이 아니라 err="레이어 조회 실패(사유)" 로 남기고, 집계에서도 분모에서 뺀다.
  미조회를 "없다"로 쓰지 않기 위한 장치다.
- 키: os.environ["VWORLD_APIKEY"] 만. 코드·출력·로그·산출물 어디에도 키 값을 남기지 않는다(_mask).

출력: data/vworld/national/derived/vworld_layer_probe_26.json
      deliverables/브이월드_레이어_커버리지_26개소.csv
실행: VWORLD_APIKEY 가 보이는 프로세스에서  python scripts/vworld_layer_probe_26.py
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]   # 저장소 루트(scripts/ 한 단계 위)
DER = ROOT / "data/vworld/national/derived"
DELIV = ROOT / "deliverables"
OUT = DER / "vworld_layer_probe_26.json"
CSV = DELIV / "브이월드_레이어_커버리지_26개소.csv"
KEY = os.environ.get("VWORLD_APIKEY", "").strip()
# 개발키는 발급 시 등록한 도메인에서만 동작한다(2026-09 기준 기본 localhost). 필요하면 VWORLD_DOMAIN 으로 바꾼다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
UA = "D-FLOW contest"
RADIUS = 100.0        # m — 조각 점 중심 정사각 bbox 반변
MAXFEATURES = "50"
T39 = Transformer.from_crs(4326, 3857, always_xy=True)   # EPSG:900913 == 3857 (기존 스크립트와 동일)

# (레이어명, 한글명, 계열)
LAYERS = [
    ("lt_c_a3drivewaysection", "차도구간", "A_정밀도로지도"),
    ("lt_c_a4subsidiarysection", "보도구간", "A_정밀도로지도"),
    ("lt_c_a5parkinglot", "주차면", "A_정밀도로지도"),
    ("lt_l_c5heightbarrier", "높이장애물", "A_정밀도로지도"),
    ("lt_c_c4speedbump", "과속방지턱", "A_정밀도로지도"),
    ("lt_l_a2link", "주행경로링크", "A_정밀도로지도"),
    ("lt_p_a1node", "주행경로노드", "A_정밀도로지도"),
    ("lt_c_b3surfacemark", "노면표시", "A_정밀도로지도"),
    ("lt_l_b2surfacelinemark", "노면선표시", "A_정밀도로지도"),
    ("lt_c_b1safetysign", "안전표지", "A_정밀도로지도"),
    ("lt_c_up401", "급경사재해예방지역", "B_맥락"),
    ("lt_c_usfsffb", "소방서관할구역", "B_맥락"),
    ("lt_p_utiscctv", "교통CCTV", "B_맥락"),
    ("lt_c_uq125", "방재지구", "B_맥락"),
    ("lt_c_up201", "재해위험지구", "B_맥락"),
    ("lt_c_uq128", "취락지구", "B_맥락"),
]


def _mask(s: str) -> str:
    if not KEY:
        return s
    return s.replace(KEY, "***").replace(urllib.parse.quote(KEY), "***")


def norm(s):
    return "".join(str(s or "").split())


def pieces():
    """sam_vehicle_width.pieces() 와 같은 규칙 — type=="road" 조각만(37개)."""
    cc = json.loads((DER / "missing_alley_crosscheck.json").read_text(encoding="utf-8"))
    out = []
    for s in cc["sites"]:
        for p in s["pieces"]:
            if p["type"] == "road":
                out.append({"연번": s["연번"], "시군구": s["시군구"], "조각": p["piece"],
                            "road_name": p.get("road_name") or norm(p["piece"]), "point": p["point"]})
    return out


def bbox900913(lon, lat, r=RADIUS):
    x, y = T39.transform(lon, lat)
    return x - r, y - r, x + r, y + r


def wfs_url(typename, lon, lat):
    x0, y0, x1, y1 = bbox900913(lon, lat)
    q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": typename,
         "OUTPUT": "application/json", "MAXFEATURES": MAXFEATURES, "SRSNAME": "EPSG:900913",
         "BBOX": f"{x0},{y0},{x1},{y1},EPSG:900913", "key": KEY, "domain": DOMAIN}
    return "https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode(q)


def query(typename, lon, lat, timeout=60):
    """(count, prop_keys, err) — err 가 None 이 아니면 '조회하지 못함'이다(0건 아님)."""
    url = wfs_url(typename, lon, lat)
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout).read()
    except Exception as e:  # noqa: BLE001
        return None, None, f"{type(e).__name__}: {_mask(str(e))[:200]}"
    try:
        j = json.loads(raw.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001  — XML ServiceException 등
        t = _mask(raw.decode("utf-8", "replace"))
        m = re.search(r"<ServiceException[^>]*>(.*?)</ServiceException>", t, re.S)
        return None, None, ("서비스예외: " + " ".join(m.group(1).split())[:300]) if m else f"비JSON응답: {t[:300]}"
    if isinstance(j, dict) and ("error" in j or j.get("type") == "ServiceExceptionReport"):
        return None, None, f"서비스오류: {_mask(json.dumps(j, ensure_ascii=False))[:200]}"
    feats = j.get("features")
    if feats is None:
        return None, None, f"features 없음: {_mask(json.dumps(j, ensure_ascii=False))[:200]}"
    keys = sorted(feats[0].get("properties", {}).keys()) if feats else None
    return len(feats), keys, None


def main():
    ps = pieces()
    print(f"조각 수: {len(ps)}  (type=='road' 만)")
    for p in ps[:3]:
        print(f"  샘플: 연번{p['연번']} {p['시군구']} {p['조각']} @ {p['point']}")
    if not KEY:
        sys.exit("VWORLD_APIKEY 없음 — 이 스크립트는 브이월드 WFS 조회 단계다. 조회 없이 0건으로 기록하지 않는다.")

    rows, detail = [], {}
    for tn, ko, fam in LAYERS:
        hit = tot = ok = 0
        errs, keys, first_err = [], None, None
        per = []
        for p in ps:
            lon, lat = p["point"]
            c, k, e = query(tn, lon, lat)
            per.append({"연번": p["연번"], "조각": p["조각"], "count": c, "err": e})
            if e is not None:
                errs.append(e)
                first_err = first_err or e
            else:
                ok += 1
                tot += c
                if c:
                    hit += 1
                    keys = keys or k
            time.sleep(0.15)
        note = "정상 조회" if not errs else ("전건 조회 실패 — 없다고 쓰지 말 것" if ok == 0 else f"일부 조회 실패 {len(errs)}건")
        rows.append({"레이어명": tn, "레이어 한글명": ko, "조회 조각 수": ok, "피처 있는 조각 수": hit,
                     "피처 합계": tot, "속성 항목(있을 때)": ",".join(keys) if keys else "",
                     "조회 실패 수": len(errs), "비고": note + (f" | {first_err}" if first_err else "")})
        detail[tn] = {"한글명": ko, "계열": fam, "조각별": per, "속성키": keys, "오류표본": first_err}
        print(f"{tn:28s} {ko:12s} 조회 {ok:2d}/{len(ps)} · 피처있음 {hit:2d} · 합계 {tot:4d} · 실패 {len(errs):2d}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"규칙": "미조회는 0건이 아니다", "반경_m": RADIUS, "조각수": len(ps),
                               "요약": rows, "상세": detail}, ensure_ascii=False, indent=1), encoding="utf-8")
    CSV.parent.mkdir(parents=True, exist_ok=True)
    cols = ["레이어명", "레이어 한글명", "조회 조각 수", "피처 있는 조각 수", "피처 합계", "속성 항목(있을 때)", "조회 실패 수", "비고"]
    with CSV.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"\n출력: {OUT}\n      {CSV}")


if __name__ == "__main__":
    main()
