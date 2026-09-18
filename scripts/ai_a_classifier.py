"""016 E — AI-A 진입곤란 분류 모델 M1·M2. 기준 docs/판정기준.md §24 (실행 전 커밋 f8d26dd).

탐색적 결과(양성 42, 대전 한정). 사람 판독 11조각 미사용. 성능이 낮아도 특징을 바꾸지 않는다.
실행: python ai_a_classifier.py fetch   (대전 lt_l_sprd 선형 포함 재수급 — 키 os.environ["VWORLD_APIKEY"])
      python ai_a_classifier.py run
출력: data/vworld/national/derived/ai_a_classifier.json · deliverables/AI-A_모델유사골목_상위.csv
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform as shp_transform

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hierarchy_compare import tier  # noqa: E402
from inclusion_rate import norm  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"
DELIV = ROOT / "deliverables"
GEOM = ROOT / "data/vworld/national/raw/daejeon_sprd_geom.jsonl"
KEY = os.environ.get("VWORLD_APIKEY", "").strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
GU = {"30110": "동구", "30140": "중구", "30170": "서구", "30200": "유성구", "30230": "대덕구"}
RULE = "f8d26dd"


def fetch():
    t = Transformer.from_crs(4326, 3857, always_xy=True)
    t35 = Transformer.from_crs(3857, 5186, always_xy=True)
    X0, Y0 = t.transform(127.22, 36.17)
    X1, Y1 = t.transform(127.58, 36.51)
    STEP = 2500.0
    cells = [(x, y, min(x + STEP, X1), min(y + STEP, Y1)) for x in np.arange(X0, X1, STEP) for y in np.arange(Y0, Y1, STEP)]
    n_fail = 0
    with GEOM.open("w", encoding="utf-8") as out:
        while cells:
            c = cells.pop()
            q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": "lt_l_sprd", "OUTPUT": "application/json",
                 "MAXFEATURES": "1000", "SRSNAME": "EPSG:900913", "BBOX": f"{c[0]},{c[1]},{c[2]},{c[3]},EPSG:900913", "key": KEY, "domain": DOMAIN}
            url = "https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode(q)
            feats = None
            for attempt in range(3):
                try:
                    feats = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"}), timeout=90).read())["features"]
                    break
                except Exception:  # noqa: BLE001
                    time.sleep(2 * (attempt + 1))
            if feats is None:
                n_fail += 1
                continue
            if len(feats) >= 1000:
                mx, my = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2
                cells += [(c[0], c[1], mx, my), (mx, c[1], c[2], my), (c[0], my, mx, c[3]), (mx, my, c[2], c[3])]
                continue
            for f in feats:
                p = f["properties"]
                if str(p.get("sig_cd")) not in GU:
                    continue
                g = shp_transform(lambda x, y, z=None: t35.transform(x, y), shape(f["geometry"]))
                out.write(json.dumps({"sig_cd": str(p.get("sig_cd")), "rds_man_no": p.get("rds_man_no"), "rn": p.get("rn"),
                                      "road_bt": p.get("road_bt"), "road_lt": p.get("road_lt"), "wkt": g.wkt}, ensure_ascii=False) + "\n")
            time.sleep(0.1)
    print(json.dumps({"failed_cells": n_fail}))


def features():
    rows, seen = [], {}
    for line in GEOM.open(encoding="utf-8"):
        r = json.loads(line)
        k = (r["sig_cd"], str(r["rds_man_no"]))
        g = shapely.from_wkt(r["wkt"])
        if k in seen:
            rows[seen[k]]["geoms"].append(g)
            continue
        seen[k] = len(rows)
        rows.append({**r, "geoms": [g]})
    segs = pd.DataFrame(rows)
    segs["geom"] = [shapely.union_all(gs) for gs in segs.geoms]
    geoms = segs.geom.values
    tree = shapely.STRtree(geoms)
    deg = []
    for i, g in enumerate(geoms):
        parts = getattr(g, "geoms", [g])
        ends = []
        for ln in parts:
            cs = list(ln.coords)
            ends += [Point(cs[0]), Point(cs[-1])]
        touching = set()
        for e in ends:
            for j in tree.query(e, predicate="dwithin", distance=2.0):
                if j != i:
                    touching.add(int(j))
        deg.append(len(touching))
    segs["deg"] = deg
    segs["nm"] = segs.rn.map(norm)
    segs["t"] = segs.nm.map(tier)
    segs = segs[segs.t.isin(["길", "번길"])]
    num = lambda s: pd.to_numeric(s, errors="coerce")
    segs["bt"] = num(segs.road_bt)
    segs["lt"] = num(segs.road_lt)
    agg = segs.groupby(["sig_cd", "nm"]).agg(bt_mean=("bt", "mean"), bt_min=("bt", "min"), bt_max=("bt", "max"), lt_sum=("lt", "sum"),
                                             n_seg=("bt", "size"), deg_mean=("deg", "mean"), is_beongil=("t", lambda s: int((s == "번길").any()))).reset_index()
    for code in GU:
        agg[f"gu_{code}"] = (agg.sig_cd == code).astype(int)
    return agg


def run():
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.inspection import permutation_importance
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import average_precision_score, roc_auc_score
    from sklearn.model_selection import LeaveOneGroupOut
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    inc = json.loads((DER / "inclusion_rate.json").read_text(encoding="utf-8"))
    pos = {(x["sig_cd"], x["name"]): x["included"] for x in inc["treatment_A_names"]}
    X = features()
    X["y"] = [int((s, n) in pos) for s, n in zip(X.sig_cd, X.nm)]
    # 음성 = §19 대조군과 같은 정의(같은 5개 구 길·번길 − A). in_nodelink: §19 판정 재사용 위해 표준노드링크 이름 집합 재계산
    import pyogrio
    from inclusion_rate import adsigg_polys, no_name
    links = pyogrio.read_dataframe(ROOT / "data/vworld/national/raw/NODELINKDATA_20260914/MOCT_LINK.shp", columns=["LINK_ID", "ROAD_NAME"],
                                   encoding="cp949", bbox=(215000, 395000, 255000, 435000))
    links = links[links.LINK_ID.astype(str).str[:3].isin([str(i) for i in range(183, 188)])].copy()
    polys, _ = adsigg_polys()
    mids = shapely.line_interpolate_point(links.geometry.values, 0.5, normalized=True)
    ip, iq = shapely.STRtree([g for _, g in polys]).query(mids, predicate="within")
    gu = np.array([None] * len(links), dtype=object)
    gu[ip] = [polys[i][0] for i in iq]
    names_by = defaultdict(set)
    for g_, n_, bad in zip(gu, links.ROAD_NAME.map(norm), links.ROAD_NAME.map(no_name)):
        if g_ and not bad:
            names_by[g_].add(n_)
    X["in_nodelink"] = [int(n in names_by.get(s, set())) for s, n in zip(X.sig_cd, X.nm)]
    missing_pos = [k for k in pos if not ((X.sig_cd == k[0]) & (X.nm == k[1])).any()]
    base_feats = ["bt_mean", "bt_min", "bt_max", "lt_sum", "n_seg", "is_beongil", "deg_mean"] + [f"gu_{c}" for c in GU]
    X[base_feats] = X[base_feats].fillna(X[base_feats].median())
    y = X.y.values
    groups = X.sig_cd.values
    logo = LeaveOneGroupOut()
    res = {}
    oof_store = {}
    for mname, feats in (("M1", base_feats), ("M2", base_feats + ["in_nodelink"])):
        for cname, make in (("logistic", lambda: make_pipeline(StandardScaler(), LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000))),
                            ("random_forest", lambda: RandomForestClassifier(n_estimators=500, min_samples_leaf=5, class_weight="balanced_subsample", random_state=0, n_jobs=1))):
            oof = np.zeros(len(X))
            for tr, te in logo.split(X, y, groups):
                m = make()
                m.fit(X.iloc[tr][feats].values, y[tr])
                oof[te] = m.predict_proba(X.iloc[te][feats].values)[:, 1]
            k = int(y.sum())
            top = np.argsort(-oof)[:k]
            tp = int(y[top].sum())
            res[f"{mname}_{cname}"] = {"pr_auc": round(float(average_precision_score(y, oof)), 4), "roc_auc": round(float(roc_auc_score(y, oof)), 4),
                                       "precision_at_k": round(tp / k, 4), "confusion_at_top_k": {"tp": tp, "fp": k - tp, "fn": int(y.sum()) - tp, "tn": int(len(y) - y.sum() - (k - tp))}}
            oof_store[f"{mname}_{cname}"] = oof
    rng = np.random.RandomState(0)
    pi, ni = np.where(y == 1)[0], np.where(y == 0)[0]
    diffs = {}
    for cname in ("logistic", "random_forest"):
        a, b = oof_store[f"M1_{cname}"], oof_store[f"M2_{cname}"]
        ds = []
        for _ in range(1000):
            idx = np.concatenate([rng.choice(pi, len(pi)), rng.choice(ni, len(ni))])
            ds.append(average_precision_score(y[idx], b[idx]) - average_precision_score(y[idx], a[idx]))
        diffs[cname] = {"pr_auc_M2_minus_M1": round(res[f"M2_{cname}"]["pr_auc"] - res[f"M1_{cname}"]["pr_auc"], 4),
                        "bootstrap_ci95": [round(float(np.percentile(ds, 2.5)), 4), round(float(np.percentile(ds, 97.5)), 4)]}
    importance = {}
    for mname, feats in (("M1", base_feats), ("M2", base_feats + ["in_nodelink"])):
        lr = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000)).fit(X[feats].values, y)
        coefs = dict(zip(feats, [round(float(c), 4) for c in lr[-1].coef_[0]]))
        rf = RandomForestClassifier(n_estimators=500, min_samples_leaf=5, class_weight="balanced_subsample", random_state=0, n_jobs=1).fit(X[feats].values, y)
        pim = permutation_importance(rf, X[feats].values, y, scoring="average_precision", n_repeats=10, random_state=0, n_jobs=1)
        importance[mname] = {"logistic_std_coef": coefs, "rf_permutation_pr_auc": dict(zip(feats, [round(float(v), 4) for v in pim.importances_mean]))}
    X["M1_logistic_oof"] = oof_store["M1_logistic"]
    X["M2_logistic_oof"] = oof_store["M2_logistic"]
    neg = X[X.y == 0]
    top1 = neg.sort_values("M1_logistic_oof", ascending=False).head(20)
    top2 = neg.sort_values("M2_logistic_oof", ascending=False).head(20)
    DELIV.mkdir(parents=True, exist_ok=True)
    with (DELIV / "AI-A_모델유사골목_상위.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["표현", "모델이 지정 개소와 유사하다고 본 골목 — 지정되어야 한다는 뜻이 아님 · 탐색적 결과(양성 42, 대전 한정)"])
        w.writerow(["모델", "순위", "구", "도로명", "OOF확률", "표준노드링크포함", "bt_mean(단위미확인)", "n_seg", "deg_mean"])
        for mname, tb, col in (("M1_logistic", top1, "M1_logistic_oof"), ("M2_logistic", top2, "M2_logistic_oof")):
            for i, r in enumerate(tb.itertuples(), 1):
                w.writerow([mname, i, GU[r.sig_cd], r.nm, round(getattr(r, col), 4), r.in_nodelink, round(r.bt_mean, 2), r.n_seg, round(r.deg_mean, 2)])
    out = {"rule_doc": "docs/판정기준.md §24", "rule_commit": RULE, "samples": {"n": int(len(X)), "positives": int(y.sum()),
           "negatives": int(len(y) - y.sum()), "positive_rate_baseline_pr_auc": round(float(y.mean()), 4), "positives_missing_from_features": missing_pos},
           "features_M1": base_feats, "features_M2_extra": ["in_nodelink"], "cv": "Leave-One-Group-Out by 구(5)", "results": res,
           "M2_minus_M1": diffs, "importance": importance,
           "top20_M1_logistic": [{"gu": GU[r.sig_cd], "name": r.nm, "p": round(r.M1_logistic_oof, 4)} for r in top1.itertuples()],
           "top20_M2_logistic": [{"gu": GU[r.sig_cd], "name": r.nm, "p": round(r.M2_logistic_oof, 4)} for r in top2.itertuples()],
           "limits": ["양성 42 — 탐색적", "라벨 = 행정 지정(기준 비공개)", "대전 한정", "구 원핫은 구 단위 교차검증에서 기여 불가", "road_bt·road_lt 단위 미확인", "건물 폴리곤 간격 미포함(사전 결정)"]}
    (DER / "ai_a_classifier.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("samples", "results", "M2_minus_M1")}, ensure_ascii=False))
    print(json.dumps(importance, ensure_ascii=False))
    print([(r["gu"], r["name"], r["p"]) for r in out["top20_M1_logistic"][:10]])


if __name__ == "__main__":
    {"fetch": fetch, "run": run}[sys.argv[1]]()
