"""003 §3 A · §4 B — 회전 기하 전국 전수 + 진입곤란 37개소 역검증.

규칙: docs/판정기준.md (산출 전 커밋 d93d3d6 · 좌표화 v2 c1740bf). 규칙 밖 판단을 넣지 않는다.
폭이 없으므로 모든 판정은 증거등급 D · 판정 보류. 「통과 불가」를 산출하지 않는다.

출력(data/vworld/national/derived/)
- turn_census.json          A 전국·대상지 4곳 요약, 설계기준자동차 요구 폭, 구간표
- access37_reverse.json     B 매칭·분위수·기준·결과 요약
- access37_links.csv        B 37개소 매칭 링크 특징
- daejeon_indistinct.csv    B 구별되지 않는 링크 목록(도표용)
- sharp_moves_targets.csv   A 대상지 4곳 급회전 이동(도표용)
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]   # 저장소 루트(scripts/ 한 단계 위)
NL = ROOT / "data/vworld/national/raw/NODELINKDATA_20260914"
DER = ROOT / "data/vworld/national/derived"
STEP = 10.0
THETA_SHARP = 90.0
R_SHARP = 12.0
R_WIN = 500.0
THETA_BINS = [0, 30, 60, 90, 120, 150, 180.0001]
R_BINS = [0, 7, 12, 15, 30, 60, np.inf]
DAEJEON = [str(i) for i in range(183, 188)]
import re  # noqa: E402
ROADRE = re.compile(r"^([가-힣0-9]+?(?:대로|로|길))(\d+번안?길)?")
TARGETS = [("서울 이태원동", "서울 용산구 이태원동"), ("부산 초량동", "부산 동구 초량동"),
           ("대전 변동", "대전 서구 변동"), ("청주 내덕동", "청주 청원구 내덕동")]
DESIGN = {  # 규칙 제5조② — 폭 B, 축간거리 L, 앞내민 F, 최소회전반지름 R
    "대형자동차": (2.5, 6.5, 2.5, 12.0), "소형자동차": (2.0, 3.7, 1.0, 7.0), "승용자동차": (1.7, 2.7, 0.8, 6.0)}
WIDEN_LARGE = [(110, 200, 0.25), (65, 110, 0.50), (45, 65, 0.75), (35, 45, 1.00), (25, 35, 1.25), (20, 25, 1.50),
               (18, 20, 1.75), (15, 18, 2.00)]  # 규칙 제22조① 대형자동차 (R 이상, 미만, 확폭 m)


def swept_width(B, L, F, R):
    r_or = math.sqrt(R * R - L * L)
    r_ir = r_or - B
    r_oc = math.sqrt(r_or * r_or + (L + F) ** 2)
    return round(r_oc - r_ir, 3), {"R_or": round(r_or, 3), "R_ir": round(r_ir, 3), "R_oc": round(r_oc, 3)}


def end_vectors(geoms):
    """마지막 선분·첫 선분 방향벡터(길이 0 선분은 건너뜀)."""
    coords, idx = shapely.get_coordinates(geoms, return_index=True)
    df = pd.DataFrame({"i": idx, "x": coords[:, 0], "y": coords[:, 1]})
    df["dx"] = df.groupby("i").x.diff()
    df["dy"] = df.groupby("i").y.diff()
    seg = df[(df.dx.notna()) & ((df.dx != 0) | (df.dy != 0))]
    first = seg.groupby("i").first()[["dx", "dy"]]
    last = seg.groupby("i").last()[["dx", "dy"]]
    return first, last


def min_radius(geoms, lengths):
    n = len(geoms)
    out = np.full(n, np.nan)
    ok = lengths >= 20.0
    ids = np.nonzero(ok)[0]
    counts = (np.floor(lengths[ids] / STEP).astype(int) + 1)
    # arange(0, len, STEP) + 끝점
    reps = counts + 1
    gi = np.repeat(ids, reps)
    offs = np.concatenate([np.append(np.arange(c) * STEP, lengths[i]) for c, i in zip(counts, ids)])
    # 끝점이 마지막 격자점과 겹치면(길이가 10의 배수) 중복 제거
    pts = shapely.line_interpolate_point(geoms[gi], offs)
    xy = shapely.get_coordinates(pts)
    d = pd.DataFrame({"i": gi, "o": offs, "x": xy[:, 0], "y": xy[:, 1]}).drop_duplicates(["i", "o"])
    g = d.groupby("i")
    x0, y0 = d.x.values, d.y.values
    x1, y1 = g.x.shift(-1).values, g.y.shift(-1).values
    x2, y2 = g.x.shift(-2).values, g.y.shift(-2).values
    a = np.hypot(x1 - x0, y1 - y0)
    b = np.hypot(x2 - x1, y2 - y1)
    c = np.hypot(x2 - x0, y2 - y0)
    area2 = np.abs((x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0))
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(area2 > 1e-9, a * b * c / (2 * area2), np.inf)
    rr = pd.Series(r, index=d.i.values)[~np.isnan(x2)]
    mins = rr.groupby(level=0).min()
    out[mins.index.values] = mins.values
    return out


def bins_count(values, edges):
    v = values[~np.isnan(values)]
    h = np.histogram(v, bins=edges)[0]
    return {f"{edges[k]}–{edges[k+1] if np.isfinite(edges[k+1]) else '∞'}": int(h[k]) for k in range(len(h))}


def main():
    tr = Transformer.from_crs(4326, 5186, always_xy=True)
    L = pyogrio.read_dataframe(NL / "MOCT_LINK.shp", columns=["LINK_ID", "F_NODE", "T_NODE", "LANES", "ROAD_RANK", "ROAD_NAME"])
    L["p3"] = L.LINK_ID.str[:3]
    L["lanes"] = pd.to_numeric(L.LANES, errors="coerce")
    geoms = L.geometry.values
    L["len"] = shapely.length(geoms)
    first, last = end_vectors(geoms)
    L["fx"], L["fy"] = first.dx.reindex(L.index).values, first.dy.reindex(L.index).values
    L["lx"], L["ly"] = last.dx.reindex(L.index).values, last.dy.reindex(L.index).values
    print("vectors done", flush=True)

    # 이동(진입 a → 진출 b) — 노드에서 조인
    a = L[["LINK_ID", "F_NODE", "T_NODE", "ROAD_NAME", "lx", "ly"]].rename(columns=lambda c: "a_" + c)
    b = L[["LINK_ID", "F_NODE", "T_NODE", "ROAD_NAME", "fx", "fy"]].rename(columns=lambda c: "b_" + c)
    M = a.merge(b, left_on="a_T_NODE", right_on="b_F_NODE")
    M = M[M.a_LINK_ID != M.b_LINK_ID]
    dot = M.a_lx * M.b_fx + M.a_ly * M.b_fy
    nrm = np.hypot(M.a_lx, M.a_ly) * np.hypot(M.b_fx, M.b_fy)
    M["theta"] = np.degrees(np.arccos(np.clip(dot / nrm, -1, 1)))
    ex1 = M.b_T_NODE == M.a_F_NODE
    ex2 = (M.a_ROAD_NAME.notna()) & (M.a_ROAD_NAME == M.b_ROAD_NAME) & (M.theta >= 150)
    moves_total = len(M)
    excl = {"reverse_same_nodes": int(ex1.sum()), "same_name_theta_ge150": int((ex2 & ~ex1).sum())}
    M = M[~(ex1 | ex2)].copy()
    ti = pyogrio.read_dataframe(NL / "TURNINFO.dbf", read_geometry=False)
    tik = set(zip(ti.ST_LINK, ti.ED_LINK))
    M["has_turninfo"] = [(x, y) in tik for x, y in zip(M.a_LINK_ID, M.b_LINK_ID)]
    M["sharp"] = M.theta >= THETA_SHARP
    print("moves", moves_total, len(M), flush=True)

    L["R_link"] = min_radius(geoms, L["len"].values)
    print("radius done", flush=True)

    nodes = pyogrio.read_dataframe(NL / "MOCT_NODE.shp", columns=["NODE_ID"])
    nxy = shapely.get_coordinates(nodes.geometry.values)
    node_xy = pd.DataFrame({"x": nxy[:, 0], "y": nxy[:, 1]}, index=nodes.NODE_ID.values)
    M["nx"] = node_xy.x.reindex(M.a_T_NODE.values).values
    M["ny"] = node_xy.y.reindex(M.a_T_NODE.values).values
    bnd = shapely.bounds(geoms)
    L["mx"], L["my"] = (bnd[:, 0] + bnd[:, 2]) / 2, (bnd[:, 1] + bnd[:, 3]) / 2

    design = {k: {"B": v[0], "L": v[1], "F": v[2], "R": v[3], "W_req_turn_m": swept_width(*v)[0], "detail": swept_width(*v)[1]}
              for k, v in DESIGN.items()}

    def summarize(mv, lk):
        sharp = mv[mv.sharp]
        rl = lk.R_link.values
        return {
            "moves_after_exclusion": int(len(mv)), "sharp_moves": int(len(sharp)),
            "nodes_with_sharp_move": int(sharp.a_T_NODE.nunique()),
            "sharp_moves_with_turninfo_record": int(sharp.has_turninfo.sum()),
            "theta_bins": bins_count(mv.theta.values, THETA_BINS),
            "links": int(len(lk)), "links_R_not_computed(<20m)": int(np.isnan(rl).sum()),
            "links_R_lt_12": int(np.nansum(rl < R_SHARP)),
            "R_link_bins": bins_count(rl, R_BINS),
            "judgeable_sharp": 0, "evidence_grade": "D", "reason": "폭 속성 부재(표준노드링크) — 판정 보류",
        }

    res = {"rule_commit": "d93d3d6", "design_vehicles_rule_5_2": design,
           "vehicle_specific_W_req": {"P50": None, "L50": None, "A1": None, "reason": "R·L·F 공란(선보고 §0-1)"},
           "national": summarize(M, L), "moves_total_before_exclusion": moves_total, "excluded": excl, "targets": {}}
    probe = json.loads((DER / "vworld_probe.json").read_text(encoding="utf-8"))["items"]["4_geocoder"]["search_district"]
    tgt_rows = []
    for label, key in TARGETS:
        x, y = tr.transform(*probe[key]["candidates"][0]["point"])
        mv = M[np.hypot(M.nx - x, M.ny - y) <= R_WIN]
        lk = L[np.hypot(L.mx - x, L.my - y) <= R_WIN]
        s = summarize(mv, lk)
        s["note"] = "반경 500 m 탐색창 값이며 도시 대표값이 아니다"
        sh = lk[lk.R_link < R_SHARP]
        s["sharp_curve_links_widening_ref_large"] = "규칙 제22조 대형자동차 표 범위(R≥15 m) 밖" if len(sh) else None
        res["targets"][label] = s
        t = mv[mv.sharp][["a_LINK_ID", "b_LINK_ID", "a_T_NODE", "theta", "nx", "ny"]].copy()
        t["target"] = label
        tgt_rows.append(t)
    pd.concat(tgt_rows).to_csv(DER / "sharp_moves_targets.csv", index=False, encoding="utf-8-sig")
    (DER / "turn_census.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"national": res["national"], "targets": {k: {x: v[x] for x in ("sharp_moves", "nodes_with_sharp_move", "links_R_lt_12", "moves_after_exclusion", "links")} for k, v in res["targets"].items()}, "excluded": excl}, ensure_ascii=False), flush=True)

    # ---------------- B ----------------
    geo = json.loads((DER / "access37_geocode_v2.json").read_text(encoding="utf-8"))
    D = L[L.p3.isin(DAEJEON)].copy()
    Md = M[M.a_LINK_ID.str[:3].isin(DAEJEON) | M.b_LINK_ID.str[:3].isin(DAEJEON)]
    f1 = pd.concat([Md[["a_LINK_ID", "theta"]].rename(columns={"a_LINK_ID": "LINK_ID"}),
                    Md[["b_LINK_ID", "theta"]].rename(columns={"b_LINK_ID": "LINK_ID"})]).groupby("LINK_ID").theta.max()
    D["f1"] = f1.reindex(D.LINK_ID).values
    tree = shapely.STRtree(D.geometry.values)
    DNAMES = set(D.ROAD_NAME.dropna().str.replace(" ", ""))
    recs = []
    for row in geo["rows"]:
        for g in row["pieces"]:
            if not g.get("v2_accepted"):
                continue
            px, py = tr.transform(*g["point"])
            pt = shapely.Point(px, py)
            j = tree.nearest(pt)
            lk = D.iloc[j]
            m = ROADRE.match(g["piece"].replace(" ", ""))
            road = (m.group(1) + (m.group(2) or "")) if m else None
            # 버그 수정(2026-09-15): 이전 판은 「ROAD_NAME ⊂ 조각」 부분문자열 비교라 「계족로」가 「계족로330번길」과 일치로 셈 → 완전 일치로 교정
            recs.append({"연번": row["연번"], "piece": g["piece"], "road": road, "LINK_ID": lk.LINK_ID, "dist_m": round(float(lk.geometry.distance(pt)), 1),
                         "ROAD_NAME": lk.ROAD_NAME, "name_match": road is not None and str(lk.ROAD_NAME).replace(" ", "") == road,
                         "road_in_daejeon_nodelink": road is not None and road in DNAMES,
                         "f1": lk.f1, "f2": lk.R_link, "f3": lk.lanes, "f4": lk.ROAD_RANK})
    R = pd.DataFrame(recs)
    R.to_csv(DER / "access37_links.csv", index=False, encoding="utf-8-sig")
    S = D[D.LINK_ID.isin(set(R.LINK_ID))]
    nc_rate = float(np.isnan(S.R_link.values).mean())
    q_f1 = float(np.nanpercentile(S.f1.values, 25))
    max_f3 = float(np.nanmax(S.lanes.values))
    set_f4 = sorted(set(S.ROAD_RANK))
    use_c4 = nc_rate <= 0.5
    cond = (D.f1 >= q_f1) & (D.lanes <= max_f3) & (D.ROAD_RANK.isin(set_f4))
    q_f2 = None
    if use_c4:
        q_f2 = float(np.nanpercentile(S.R_link.values, 75))
        cond &= (D.R_link <= q_f2)
    cand = D[cond & ~D.LINK_ID.isin(set(S.LINK_ID))]
    # 같은 이름·반대방향 짝 제거 근사(30 m 이내, 방향벡터 내적 음수)
    kept, seen = [], set()
    ct = shapely.STRtree(cand.geometry.values)
    cvec = np.stack([cand.fx.values + cand.lx.values, cand.fy.values + cand.ly.values], 1)
    for i in range(len(cand)):
        if i in seen:
            continue
        kept.append(i)
        for j in ct.query(cand.geometry.values[i].buffer(30)):
            if j != i and j not in seen and cand.ROAD_NAME.values[j] == cand.ROAD_NAME.values[i] and cand.ROAD_NAME.values[i] \
                    and float(np.dot(cvec[i], cvec[j])) < 0:
                seen.add(j)
    cand.drop(columns=["geometry"]).assign(x=cand.mx, y=cand.my).to_csv(DER / "daejeon_indistinct.csv", index=False, encoding="utf-8-sig")
    out = {
        "rule_commit": {"criteria": "d93d3d6", "geocode_v2": "c1740bf"},
        "geocode": {"v1": json.loads((DER / "access37_geocode.json").read_text(encoding="utf-8"))["summary"],
                    "v2": geo["summary"]},
        "matched_pieces": int(len(R)), "matched_sites": int(R["연번"].nunique()), "matched_links_unique": int(S.LINK_ID.nunique()),
        "match_dist_m": {"min": float(R.dist_m.min()), "median": float(R.dist_m.median()), "p90": float(R.dist_m.quantile(0.9)), "max": float(R.dist_m.max())},
        "match_name_equal": int(R.name_match.sum()),
        "pieces_road_in_daejeon_nodelink": int(R.road_in_daejeon_nodelink.sum()),
        "sites_any_road_in_daejeon_nodelink": int(R.groupby("연번").road_in_daejeon_nodelink.any().sum()),
        "site_link_features": {"f1_theta_max": {"P25": q_f1, "median": float(np.nanmedian(S.f1.values)), "n_nan": int(np.isnan(S.f1.values).sum())},
                               "f2_R_link_not_computed_rate": round(nc_rate, 3), "f3_lanes_max": max_f3, "f4_rank_set": set_f4,
                               "sharp_move_links(f1>=90)": int((S.f1 >= THETA_SHARP).sum())},
        "criteria_applied": {"C1": f"f1 >= {q_f1:.2f}", "C2": f"LANES <= {max_f3:.0f}", "C3": f"ROAD_RANK in {set_f4}",
                             "C4": (f"R_link <= {q_f2:.2f}" if use_c4 else f"미적용 — NOT_COMPUTED 비율 {nc_rate:.1%} > 50%")},
        "daejeon_links": int(len(D)),
        "indistinct_links_outside_37": int(len(cand)),
        "indistinct_links_pair_dedup_approx": int(len(kept)),
        "judgeable": 0, "evidence_grade": "D",
        "statement": "37개소와 기하적으로 구별되지 않는 링크가 대전에 N개 더 있고, 그 N개를 판정할 폭 데이터가 없다.",
    }
    (DER / "access37_reverse.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, default=str), flush=True)


if __name__ == "__main__":
    main()
