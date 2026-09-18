"""010 §1-2 — 도로명 위계 전국 대조: 도로명주소도로(lt_l_sprd 875,892구간) × 표준노드링크(MOCT_LINK 1,562,356링크).

기준: docs/판정기준.md §16 (실행 전 커밋 8a58784). 결과를 보고 기준을 바꾸지 않는다.
- 위계: 번길(\\d+번안?길$) → 대로 → 로 → 길 → 기타
- 표준노드링크 ROAD_NAME 결측을 먼저 세고 위계 판정에서 뺀다(「이름 없음」)
- 구간 수 vs 링크 수는 단위가 다르다 → 원천 안 구성비만 비교
- 시도별: 도로명주소도로 sig_cd 앞 2자리 · 표준노드링크 링크 중점 × 브이월드 lt_c_adsido
- 키: os.environ["VWORLD_APIKEY"] 만(시도 폴리곤 조회), 출력에 키 없음
출력: data/vworld/national/derived/hierarchy_compare.json · deliverables/도로명위계_전국대조.csv
"""
from __future__ import annotations

import csv
import json
import os
import re
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from _rawio import open_raw, raw_exists  # 2026-09-18: .jsonl 없으면 .jsonl.gz

import numpy as np
import pyogrio
import shapely
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as shp_transform

ROOT = Path(__file__).resolve().parents[1]   # 저장소 루트(scripts/ 한 단계 위)
RAW = ROOT / "data/vworld/national/raw/road_bt_national_cells.jsonl"
LINK = ROOT / "data/vworld/national/raw/NODELINKDATA_20260914/MOCT_LINK.shp"
DER = ROOT / "data/vworld/national/derived"
DELIV = ROOT / "deliverables"
KEY = os.environ.get("VWORLD_APIKEY", "").strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
TIERS = ["대로", "로", "길", "번길", "기타"]
BEONGIL = re.compile(r"\d+번안?길$")
SPRD_SIDO = {"11": "서울", "12": "광주·전남", "26": "부산", "27": "대구", "28": "인천", "29": "광주·전남", "30": "대전", "31": "울산",
             "36": "세종", "41": "경기", "42": "강원", "51": "강원", "43": "충북", "44": "충남", "45": "전북", "52": "전북", "46": "광주·전남",
             "47": "경북", "48": "경남", "50": "제주"}


def tier(name):
    n = "".join(str(name or "").split())
    if not n:
        return None
    if BEONGIL.search(n):
        return "번길"
    if n.endswith("대로"):
        return "대로"
    if n.endswith("로"):
        return "로"
    if n.endswith("길"):
        return "길"
    return "기타"


def sido_norm(nm):
    nm = str(nm or "")
    for k, v in (("서울", "서울"), ("부산", "부산"), ("대구", "대구"), ("인천", "인천"), ("광주", "광주·전남"), ("전라남", "광주·전남"),
                 ("대전", "대전"), ("울산", "울산"), ("세종", "세종"), ("경기", "경기"), ("강원", "강원"), ("충청북", "충북"),
                 ("충청남", "충남"), ("전북", "전북"), ("전라북", "전북"), ("경상북", "경북"), ("경상남", "경남"), ("제주", "제주")):
        if k in nm:
            return v
    return nm or "미상"


def sido_polygons():
    t = Transformer.from_crs(4326, 3857, always_xy=True)
    x0, y0 = t.transform(124.0, 32.8)
    x1, y1 = t.transform(132.2, 38.9)
    q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": "lt_c_adsido", "OUTPUT": "application/json",
         "MAXFEATURES": "100", "SRSNAME": "EPSG:900913", "BBOX": f"{x0},{y0},{x1},{y1},EPSG:900913", "key": KEY, "domain": DOMAIN}
    url = "https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode(q)
    j = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"}), timeout=300).read())
    t35 = Transformer.from_crs(3857, 5186, always_xy=True)
    out = []
    for f in j.get("features", []):
        g = shp_transform(lambda x, y, z=None: t35.transform(x, y), shape(f["geometry"]))
        props = f["properties"]
        name = next((v for k, v in props.items() if "nm" in k.lower() and isinstance(v, str)), None)
        out.append((g, name, props))
    return out


def main():
    # 도로명주소도로
    seen, sprd = set(), []
    for line in open_raw(RAW):
        for p in json.loads(line)["rows"]:
            k = (str(p.get("sig_cd")), str(p.get("rds_man_no")))
            if k in seen:
                continue
            seen.add(k)
            sprd.append((SPRD_SIDO.get(str(p.get("sig_cd"))[:2], str(p.get("sig_cd"))[:2]), tier(p.get("rn"))))
    # 표준노드링크
    links = pyogrio.read_dataframe(LINK, columns=["LINK_ID", "ROAD_NAME"], encoding="cp949")
    names = links.ROAD_NAME.fillna("").astype(str).str.strip()
    missing = names.eq("")
    links["tier"] = [tier(n) for n in names]
    n_links = len(links)
    # 시도 공간 결합
    polys, sido_err = [], None
    try:
        polys = sido_polygons()
    except Exception as e:  # noqa: BLE001
        sido_err = f"{type(e).__name__}"
    link_sido = None
    if polys:
        mids = shapely.line_interpolate_point(links.geometry.values, 0.5, normalized=True)
        tree = shapely.STRtree([g for g, _, _ in polys])
        idx_pt, idx_poly = tree.query(mids, predicate="within")
        arr = np.full(n_links, "미결합", dtype=object)
        arr[idx_pt] = [sido_norm(polys[i][1]) for i in idx_poly]
        link_sido = arr

    def comp(tiers_list):
        c = Counter(tiers_list)
        tot = sum(c[t] for t in TIERS)
        return {t: {"n": c[t], "share_named": round(c[t] / tot, 4) if tot else None} for t in TIERS}, tot

    sprd_comp, sprd_named = comp([t for _, t in sprd])
    nl_comp, nl_named = comp(list(links.tier[~missing]))
    out = {
        "rule_doc": "docs/판정기준.md §16", "rule_commit": "8a58784",
        "nodelink": {"links": n_links, "road_name_missing": int(missing.sum()), "road_name_missing_rate": round(float(missing.mean()), 4),
                     "named_links": int(nl_named), "tiers": nl_comp,
                     "beongil_share_of_all_links": round(nl_comp["번길"]["n"] / n_links, 4)},
        "sprd": {"segments": len(sprd), "rn_missing": sum(t is None for _, t in sprd), "named": sprd_named, "tiers": sprd_comp,
                 "beongil_share_of_all_segments": round(sprd_comp["번길"]["n"] / len(sprd), 4)},
        "limits": "구간 수(도로명주소도로)와 링크 수(표준노드링크, 방향별 링크 포함)는 단위가 다르다 — 원천 안 구성비만 비교",
        "sido_join": {"polygons": len(polys), "error": sido_err,
                      "unjoined_links": int((link_sido == "미결합").sum()) if link_sido is not None else None},
    }
    by = {}
    if link_sido is not None:
        s_by = defaultdict(list)
        for s, t in sprd:
            s_by[s].append(t)
        n_by = defaultdict(list)
        for s, t, m in zip(link_sido, links.tier, missing):
            n_by[s].append(None if m else t)
        for s in sorted(set(s_by) | set(n_by)):
            sc, sn = comp(s_by.get(s, []))
            nv = n_by.get(s, [])
            nc, nn = comp([t for t in nv if t is not None])
            by[s] = {"sprd_named": sn, "sprd_beongil_share": sc["번길"]["share_named"], "nodelink_links": len(nv),
                     "nodelink_name_missing_rate": round(sum(t is None for t in nv) / len(nv), 4) if nv else None,
                     "nodelink_named": nn, "nodelink_beongil_share": nc["번길"]["share_named"],
                     "sprd_tiers": {t: sc[t]["share_named"] for t in TIERS}, "nodelink_tiers": {t: nc[t]["share_named"] for t in TIERS}}
    out["by_sido"] = by
    DER.mkdir(parents=True, exist_ok=True)
    (DER / "hierarchy_compare.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    DELIV.mkdir(parents=True, exist_ok=True)
    with (DELIV / "도로명위계_전국대조.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["범위", "원천", "단위", "전체", "이름없음", "이름있음"] + [f"{t}_건수" for t in TIERS] + [f"{t}_구성비(이름있음 기준)" for t in TIERS])
        w.writerow(["전국", "도로명주소도로(lt_l_sprd)", "구간", out["sprd"]["segments"], out["sprd"]["rn_missing"], sprd_named]
                   + [sprd_comp[t]["n"] for t in TIERS] + [sprd_comp[t]["share_named"] for t in TIERS])
        w.writerow(["전국", "표준노드링크(MOCT_LINK 2026-09-14)", "링크", n_links, int(missing.sum()), nl_named]
                   + [nl_comp[t]["n"] for t in TIERS] + [nl_comp[t]["share_named"] for t in TIERS])
        for s, v in by.items():
            w.writerow([s, "도로명주소도로", "구간", "", "", v["sprd_named"], "", "", "", "", ""] + [v["sprd_tiers"][t] for t in TIERS])
            w.writerow([s, "표준노드링크", "링크", v["nodelink_links"], "", v["nodelink_named"], "", "", "", "", ""] + [v["nodelink_tiers"][t] for t in TIERS])
    print(json.dumps({k: out[k] for k in ("nodelink", "sprd", "sido_join")}, ensure_ascii=False))
    for s, v in by.items():
        print(s, v["sprd_beongil_share"], v["nodelink_beongil_share"], v["nodelink_name_missing_rate"], v["nodelink_links"])


if __name__ == "__main__":
    main()
