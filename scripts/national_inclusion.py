"""014 P1-7 — 전국 대조군: 시도별 길·번길 도로명의 표준노드링크 포함률. 기준 §20 (실행 전 커밋 cadef64), 정규화·판정은 §19.

실행: python national_inclusion.py sigg   (LINK_ID 앞 3자리 → 시군구 배정, 브이월드 lt_c_adsigg 점 조회)
      python national_inclusion.py agg
키: os.environ["VWORLD_APIKEY"] 만. 출력: data/vworld/national/derived/national_inclusion.json · deliverables/전국대조군_길번길포함률.csv
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from _rawio import open_raw, raw_exists  # 2026-09-18: .jsonl 없으면 .jsonl.gz

import numpy as np
import pyogrio
import shapely
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hierarchy_compare import tier  # noqa: E402
from hierarchy_compare_v2 import wfs  # noqa: E402
from inclusion_rate import no_name, norm, wilson  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]   # 저장소 루트(scripts/ 한 단계 위)
RAW = ROOT / "data/vworld/national/raw/road_bt_national_cells.jsonl"
LINK = ROOT / "data/vworld/national/raw/NODELINKDATA_20260914/MOCT_LINK.shp"
DER = ROOT / "data/vworld/national/derived"
DELIV = ROOT / "deliverables"
MAP = DER / "nodelink_prefix_sigg.json"
SIDO = {"11": "서울특별시", "12": "전남광주통합특별시", "26": "부산광역시", "27": "대구광역시", "28": "인천광역시", "30": "대전광역시",
        "31": "울산광역시", "36": "세종특별자치시", "41": "경기도", "43": "충청북도", "44": "충청남도", "47": "경상북도", "48": "경상남도",
        "50": "제주특별자치도", "51": "강원특별자치도", "52": "전북특별자치도"}


def sigg():
    links = pyogrio.read_dataframe(LINK, columns=["LINK_ID"], encoding="cp949")
    links["p3"] = links.LINK_ID.astype(str).str[:3]
    t53 = Transformer.from_crs(5186, 3857, always_xy=True)
    jobs = []
    for p3, g in links.groupby("p3"):
        idx = np.linspace(0, len(g) - 1, min(20, len(g))).astype(int)
        for m in shapely.line_interpolate_point(g.geometry.values[idx], 0.5, normalized=True):
            x, y = t53.transform(m.x, m.y)
            jobs.append((p3, (x - 5, y - 5, x + 5, y + 5)))

    def work(job):
        p3, bb = job
        props, err = wfs("lt_c_adsigg", bb, "sig_cd,sig_kor_nm", maxf=10)
        return p3, (sorted({str(p.get("sig_cd")) for p in props}) if props is not None else ["조회실패"])

    res = defaultdict(list)
    with ThreadPoolExecutor(max_workers=4) as ex:
        for p3, v in ex.map(work, jobs):
            res[p3].append(v)
    out = {}
    for p3, vs in res.items():
        flat = Counter("+".join(v) if v else "없음" for v in vs)
        key = next(iter(flat))
        single = len(flat) == 1 and "+" not in key and key not in ("없음", "조회실패")
        sidos = sorted({s[:2] for v in vs for s in v if s not in ("조회실패",)})
        out[p3] = {"samples": len(vs), "values": dict(flat), "assigned_sig": key if single else None,
                   "sido_candidates": sidos, "all_failed": all(v == ["조회실패"] for v in vs)}
    MAP.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"prefixes": len(out), "assigned": sum(1 for v in out.values() if v["assigned_sig"]),
                      "mixed": sum(1 for v in out.values() if not v["assigned_sig"] and not v["all_failed"]),
                      "failed": [k for k, v in out.items() if v["all_failed"]]}, ensure_ascii=False))


def agg():
    # 모집단
    seen, pop = set(), defaultdict(set)
    for line in open_raw(RAW):
        for p in json.loads(line)["rows"]:
            k = (str(p.get("sig_cd")), str(p.get("rds_man_no")))
            if k in seen:
                continue
            seen.add(k)
            nm = norm(p.get("rn"))
            t = tier(nm)
            if t in ("길", "번길"):
                pop[str(p.get("sig_cd"))].add((nm, t))
    pref = json.loads(MAP.read_text(encoding="utf-8"))
    links = pyogrio.read_dataframe(LINK, columns=["LINK_ID", "ROAD_NAME"], encoding="cp949", read_geometry=False)
    links["p3"] = links.LINK_ID.astype(str).str[:3]
    links["nm"] = links.ROAD_NAME.map(norm)
    named = links[~links.ROAD_NAME.map(no_name)]
    by_sig, mixed_by_sido, mixed_links_by_sido = defaultdict(set), defaultdict(set), Counter()
    nl_links_by_sido = Counter()
    for p3, g in named.groupby("p3"):
        info = pref.get(p3, {})
        names = set(g.nm)
        if info.get("assigned_sig"):
            sig = info["assigned_sig"]
            by_sig[sig] |= names
            nl_links_by_sido[sig[:2]] += len(g)
        else:
            for s in info.get("sido_candidates", []):
                mixed_by_sido[s] |= names
                mixed_links_by_sido[s] += len(g)
                nl_links_by_sido[s] += len(g)
    rows, tot_n, tot_inc = [], 0, 0
    per_sido = {}
    for s2, sname in SIDO.items():
        sigs = [s for s in pop if s[:2] == s2]
        n = inc = n_bg = inc_bg = n_g = inc_g = 0
        for sig in sigs:
            ref = by_sig.get(sig, set()) | mixed_by_sido.get(s2, set())
            for nm, t in pop[sig]:
                hit = nm in ref
                n += 1
                inc += hit
                if t == "번길":
                    n_bg += 1
                    inc_bg += hit
                else:
                    n_g += 1
                    inc_g += hit
        failed = nl_links_by_sido.get(s2, 0) == 0
        per_sido[sname] = {"sido_code": s2, "names": n, "included": inc, "inclusion_rate": round(inc / n, 4) if n else None,
                           "not_included_rate": round(1 - inc / n, 4) if n else None, "inclusion_ci95": wilson(inc, n),
                           "gil_names": n_g, "gil_inclusion": round(inc_g / n_g, 4) if n_g else None,
                           "beongil_names": n_bg, "beongil_inclusion": round(inc_bg / n_bg, 4) if n_bg else None,
                           "beongil_share_of_names": round(n_bg / n, 4) if n else None,
                           "nodelink_links_assigned": nl_links_by_sido.get(s2, 0), "mixed_prefix_links": mixed_links_by_sido.get(s2, 0),
                           "status": "실패(표준노드링크 링크 배정 0)" if failed else ("시군구 혼재 앞자리 있음" if mixed_links_by_sido.get(s2) else "정상")}
        if not failed:
            tot_n += n
            tot_inc += inc
    ok = [v for v in per_sido.values() if not v["status"].startswith("실패") and v["names"]]
    out = {"rule_doc": "docs/판정기준.md §20 (정규화·판정 §19)", "rule_commit": "cadef64",
           "unit": "(시군구, 정규화 도로명) · 길·번길", "prefix_assignment": {"prefixes": len(pref), "assigned": sum(1 for v in pref.values() if v["assigned_sig"]),
                                                                            "mixed": sum(1 for v in pref.values() if not v["assigned_sig"] and not v["all_failed"]),
                                                                            "failed": [k for k, v in pref.items() if v["all_failed"]]},
           "nodelink_no_name_links": int(links.ROAD_NAME.map(no_name).sum()),
           "national_pooled": {"names": tot_n, "included": tot_inc, "inclusion_rate": round(tot_inc / tot_n, 4) if tot_n else None,
                               "not_included_rate": round(1 - tot_inc / tot_n, 4) if tot_n else None, "ci95": wilson(tot_inc, tot_n)},
           "sido_mean_inclusion": round(float(np.mean([v["inclusion_rate"] for v in ok])), 4) if ok else None,
           "failed_sido": [k for k, v in per_sido.items() if v["status"].startswith("실패")],
           "daejeon_reproduction_note": "§19 대전 대조군(처리군 제외) 미포함 79.1 % 와 방식 차이: 이번은 처리군 포함 전체 이름 · 앞자리 시군구 배정",
           "by_sido": per_sido}
    (DER / "national_inclusion.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    DELIV.mkdir(parents=True, exist_ok=True)
    with (DELIV / "전국대조군_길번길포함률.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["시도", "이름수", "포함", "포함률", "미포함률", "포함률95CI", "길 이름", "길 포함률", "번길 이름", "번길 포함률", "번길 이름 비중", "표준노드링크 배정 링크", "혼재 앞자리 링크", "상태"])
        for k, v in sorted(per_sido.items(), key=lambda kv: (kv[1]["inclusion_rate"] is None, kv[1]["inclusion_rate"] or 0)):
            w.writerow([k, v["names"], v["included"], v["inclusion_rate"], v["not_included_rate"], v["inclusion_ci95"], v["gil_names"], v["gil_inclusion"],
                        v["beongil_names"], v["beongil_inclusion"], v["beongil_share_of_names"], v["nodelink_links_assigned"], v["mixed_prefix_links"], v["status"]])
        w.writerow(["전국(합산)", tot_n, tot_inc, out["national_pooled"]["inclusion_rate"], out["national_pooled"]["not_included_rate"], out["national_pooled"]["ci95"]])
        w.writerow(["시도 단순 평균", "", "", out["sido_mean_inclusion"]])
    print(json.dumps({k: out[k] for k in ("prefix_assignment", "national_pooled", "sido_mean_inclusion", "failed_sido")}, ensure_ascii=False))
    for k, v in sorted(per_sido.items(), key=lambda kv: kv[1]["inclusion_rate"] or 0):
        print(k, v["names"], v["inclusion_rate"], v["gil_inclusion"], v["beongil_inclusion"], v["beongil_share_of_names"], v["mixed_prefix_links"], v["status"])


if __name__ == "__main__":
    {"sigg": sigg, "agg": agg}[sys.argv[1]]()
