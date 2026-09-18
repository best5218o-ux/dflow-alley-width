"""004 §6-5 — C 3안: SOP 200 제3장 3.1 을 대기 슬롯(R2) 조건으로 적용.

규칙: docs/판정기준.md §6 (실행 전 커밋 223da5e). 2안(§5-6) 조건 위에 R1·R2·R3 을 더한다.

- 수요·용량은 시나리오 합성 파라미터(SYNTHETIC_EVENT). 운영 실적이 아니다.
- 경로탐색·결정기록·재계산 버전 = 공통엔진 DFlowCore. 칸 용량·해소·장부·2-hop·SOP 조건 판정은 이 스크립트(capability 공백).
- 「회차에 용이한 장소」는 폭이 없어 판정 보류(D) — 필터로 쓰지 않고 모든 대기 레코드에 잠금 사유로 기록.
- R3: 같은 우선순위 차량 간 차량 ID 순서를 쓰지 않는다. 지연은 분포로만 보고.

출력: data/vworld/national/derived/slot_itaewon_arm3.json · slot_itaewon_arm3_gantt.csv · slot_itaewon_arm3_candidates.csv
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "DFLOW_008R9R4_CORE"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dflow_core.core import DFlowCore  # noqa: E402
from dflow_core.schema import stable_hash  # noqa: E402
from slot_itaewon_demo import build_area, angle  # noqa: E402

DER = ROOT / "data/vworld/national/derived"
HYD = ROOT / "data/vworld/national/raw/서울시 소방재난본부_소방용수시설_20251231.csv"
SLOTS, SLOT_MIN, THETA_LOCK = 6, 10, 90.0
SOP_REF = "소방청, 재난현장 표준작전절차, 2026.5, SOP 200 제3장 3.1"
LOCK_TURNAROUND = "SOP 3.1.2.1 회차에 용이한 장소: 판정 보류(D) — 가용 폭 부재, 지휘관 확인 필요"

# [B] 관측 입력 (회전기하_판정기준.md §7, 실행 전 커밋 b1555ca)
EVENT_DIR = ROOT / "data/vworld/its/event"
TRAFFIC_ZIP = ROOT / "data/vworld/its/traffic/20260914_5Min.zip"
POP_ZIP = ROOT / "data/vworld/seoul_pop/LOCAL_PEOPLE_DONG_202607.zip"
DONG_CODE_ZIP = ROOT / "data/vworld/seoul_pop/store_dong_2025.zip"
ITAEWON_DONGS = ("11170650", "11170660")
SCENARIO_HOUR = 20


def load_b2_events(area_ids):
    import csv, io, zipfile
    rows, n_all, files = [], 0, []
    for f in sorted(EVENT_DIR.glob("*.zip")):
        z = zipfile.ZipFile(f)
        files.append(f.name)
        for r in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode("utf-8-sig"))):
            n_all += 1
            if r["링크아이디"] in area_ids:
                rows.append({k: r[k] for k in ("돌발일시", "관리기관", "도로명", "돌발구분", "링크아이디", "돌발종료일시")})
    return {"files": files, "records_all": n_all, "selected": rows}


def load_b3_profile():
    import csv, io, zipfile
    z = zipfile.ZipFile(DONG_CODE_ZIP)
    t = z.read(z.namelist()[0])
    t = t.decode("utf-8-sig") if t[:3] == b"\xef\xbb\xbf" else t.decode("cp949")
    names = {r["행정동_코드"]: r["행정동_코드_명"] for r in csv.DictReader(io.StringIO(t))}
    code_check = {c: names.get(c) for c in ITAEWON_DONGS}
    if code_check != {"11170650": "이태원1동", "11170660": "이태원2동"}:
        raise SystemExit(f"B3 행정동 코드 대조 실패 — 미확인: {code_check}")
    z = zipfile.ZipFile(POP_ZIP)
    acc, days = {}, set()
    with z.open(z.namelist()[0]) as fh:
        for r in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig")):
            if r["행정동코드"] in ITAEWON_DONGS:
                h = int(r["시간대구분"])
                acc[h] = acc.get(h, 0.0) + float(r["총생활인구수"])
                days.add(r["기준일ID"])
    P = {h: acc[h] / len(days) for h in sorted(acc)}
    med = float(np.median(list(P.values())))
    r = {h: P[h] / med for h in P}
    return {"code_check": code_check, "days": len(days), "hours": len(P), "r": {h: round(v, 3) for h, v in r.items()},
            "peak_hour": max(r, key=r.get)}


def load_b1_speeds(area_ids):
    import zipfile
    z = zipfile.ZipFile(TRAFFIC_ZIP)
    name = z.namelist()[0]
    parts = []
    with z.open(name) as fh:
        for ch in pd.read_csv(fh, header=None, dtype=str, chunksize=2_000_000, encoding="utf-8", encoding_errors="replace"):
            parts.append(ch[ch[2].isin(area_ids)])
    df = pd.concat(parts)
    return name, df


def b1_capacity(sp, by_id):
    """§7-3: 칸 s = 20:00+10s 분, v_obs = 10분 안 5분 속도 평균, v_ref = 당일 95분위, 일반차량 용량 = round(LANES × min(1, v_obs/v_ref))."""
    sp = sp.rename(columns={0: "date", 1: "hhmm", 2: "link_id", 3: "agency", 4: "speed", 5: "ttime"})
    sp["speed"] = pd.to_numeric(sp["speed"], errors="coerce")
    sp["minute"] = pd.to_numeric(sp["hhmm"].str[:2], errors="coerce") * 60 + pd.to_numeric(sp["hhmm"].str[2:4], errors="coerce")
    ref = sp.groupby("link_id")["speed"].quantile(0.95)
    cap, rows = {}, []
    for s in range(SLOTS):
        m0 = SCENARIO_HOUR * 60 + SLOT_MIN * s
        win = sp[(sp.minute >= m0) & (sp.minute < m0 + SLOT_MIN)]
        vobs = win.groupby("link_id")["speed"].mean()
        for lid, v in vobs.items():
            if lid in by_id and ref.get(lid, 0) > 0:
                k = min(1.0, float(v) / float(ref[lid]))
                cap[(lid, s)] = int(round(by_id[lid]["lanes"] * k))
                rows.append((lid, s, round(float(v), 1), round(float(ref[lid]), 1), round(k, 3), cap[(lid, s)]))
    covered = sorted({r[0] for r in rows})
    reduced = [r for r in rows if r[5] < by_id[r[0]]["lanes"]]
    return cap, {"date": sorted(sp["date"].unique().tolist())[:3], "area_links": len(by_id), "links_with_speed": len(covered),
                 "links_without_speed": len(by_id) - len(covered), "cells_corrected": len(rows), "cells_capacity_reduced": len(reduced),
                 "reduced_examples": reduced[:10]}


def main():
    use_b2, use_b3, use_b1 = "--b2" in sys.argv, "--b3" in sys.argv, "--b1" in sys.argv
    b3_hour_arg = "20"
    if use_b3:
        k = sys.argv.index("--b3") + 1
        if k < len(sys.argv) and not sys.argv[k].startswith("--"):
            b3_hour_arg = sys.argv[k]
    stage = "arm3" + ("_b2" if use_b2 else "") + (f"_b3h{b3_hour_arg}" if use_b3 else "") + ("_b1" if use_b1 else "")
    sx, sy, N, A, TOUCH, boundary = build_area()

    core = DFlowCore(now="2026-09-15T20:00:00+09:00")
    nodes = {n: {"x": float(N.loc[n, "x"]), "y": float(N.loc[n, "y"])} for n in set(A.F_NODE) | set(A.T_NODE)}
    links = [{"link_id": r.LINK_ID, "f_node": r.F_NODE, "t_node": r.T_NODE, "length_m": r.LENGTH,
              "lanes": int(float(r.LANES)), "road_rank": r.ROAD_RANK} for r in A.itertuples()]
    by_id = {l["link_id"]: l for l in links}
    geom = dict(zip(A.LINK_ID, A.geometry))
    snap = core.network_snapshot(nodes, links, graph_source="MOCT_NODELINK_20260914", source_type="PROVIDER_SNAPSHOT",
                                 observed_at="2026-09-14", coverage_note="이태원동 동 대표점 반경 700 m")

    # 급회전 잠금 + 2안 해제(긴급차량 baseline 경로 위만)
    first, last = {}, {}
    for lid, g in geom.items():
        d = np.diff(shapely.get_coordinates(g), axis=0)
        d = d[(d != 0).any(axis=1)]
        first[lid], last[lid] = d[0], d[-1]
    out_by_node = {}
    for l in links:
        out_by_node.setdefault(l["f_node"], []).append(l)
    bans = []
    for a in links:
        for b in out_by_node.get(a["t_node"], []):
            if b["link_id"] != a["link_id"] and angle(last[a["link_id"]], first[b["link_id"]]) >= THETA_LOCK:
                bans.append((a["t_node"], a["link_id"], b["link_id"]))
    tree = shapely.STRtree(A.geometry.values)
    inc_idx = int(tree.nearest(shapely.Point(sx, sy)))
    inc_link, inc_node = A.LINK_ID[inc_idx], A.T_NODE[inc_idx]
    cands = sorted((r.ROAD_RANK, (r.F_NODE if r.F_NODE in nodes else r.T_NODE)) for r in TOUCH.itertuples()
                   if (r.F_NODE in nodes) or (r.T_NODE in nodes))
    em_origin = cands[0][1]
    base = core.route_candidates(nodes, links, em_origin, inc_node)[0]["edges"]
    on_path = {(by_id[base[i]]["t_node"], base[i], base[i + 1]) for i in range(len(base) - 1)}
    released = sorted(b for b in bans if b in on_path)
    bans = [b for b in bans if b not in on_path]
    ban_set = set(bans)
    turn_bans = [{"node_id": n, "st_link": s, "ed_link": e} for n, s, e in bans]
    bnodes = [b for b in boundary if b in nodes]

    def route(o, d, *, lock=False, blocked=frozenset()):
        r = core.route_candidates(nodes, links, o, d, turn_bans=turn_bans if lock else (),
                                  edge_blocked=(lambda ln: ln["link_id"] in blocked) if blocked else None)
        return r[0]["edges"] if r else None

    far = sorted(((sum(float(by_id[e]["length_m"]) for e in r), b) for b in bnodes if (r := route(inc_node, b))),
                 key=lambda t: (-t[0], t[1]))
    evac_dest = far[0][1]

    # 소방용수시설
    hyd = pd.read_csv(HYD, encoding="cp949", encoding_errors="replace", dtype=str)
    la, lo = pd.to_numeric(hyd["위도"], errors="coerce"), pd.to_numeric(hyd["경도"], errors="coerce")
    ok = la.between(33, 39) & lo.between(124, 132)
    tr = Transformer.from_crs(4326, 5186, always_xy=True)
    hx, hy = tr.transform(lo[ok].values, la[ok].values)
    hyd_ok = hyd[ok].assign(x=hx, y=hy)
    near = hyd_ok[np.hypot(hyd_ok.x - sx, hyd_ok.y - sy) <= 1500]
    htree = shapely.STRtree(shapely.points(near.x.values, near.y.values))

    # 후보 대기 링크: 사건 링크에서 무방향 1~3 hop
    adj = {}
    for l in links:
        for n in (l["f_node"], l["t_node"]):
            adj.setdefault(n, set()).add(l["link_id"])
    hop = {inc_link: 0}
    frontier = {inc_link}
    for h in (1, 2, 3):
        nxt = set()
        for e in frontier:
            for n in (by_id[e]["f_node"], by_id[e]["t_node"]):
                for f in adj[n]:
                    if f not in hop:
                        hop[f] = h
                        nxt.add(f)
        frontier = nxt
    cand_links = sorted(e for e, h in hop.items() if 1 <= h <= 3)
    cand_info = {}
    for e in cand_links:
        mid = geom[e].interpolate(0.5, normalized=True)
        j = htree.nearest(mid)
        cand_info[e] = {"hop": hop[e], "lanes": by_id[e]["lanes"], "hydrant_dist_m": round(float(mid.distance(shapely.points(near.x.values[j], near.y.values[j]))), 1),
                        "hydrant_id": near["시설번호"].values[j]}

    # ---------- 점유 모델 ----------
    occ = Counter()  # (link, slot) -> 차로 점유 대수
    evac_zero = set()

    def cap(e, s):
        return 0 if (e, s) in evac_zero or (e, s) in closed else by_id[e]["lanes"]

    def free(e, s):
        return cap(e, s) - occ[(e, s)]

    def fits_route(r, s):
        return all(free(e, s) >= 1 for e in r)

    def fits_hold(e, s, need_left=0):
        return all(free(e, t) - 1 >= need_left for t in range(s, SLOTS))

    closed = set()
    ledger, cards = [], []
    obs = {"stage": stage}
    # B3: 대피 점유 칸 수 n(h) = clamp(round(2 × r(h)), 1, 5)  (§7-2, 가정 · 증거등급 C)
    n_evac = 2
    if use_b3:
        prof = load_b3_profile()
        h = prof["peak_hour"] if b3_hour_arg == "peak" else int(b3_hour_arg)
        n_evac = int(min(5, max(1, round(2 * prof["r"][h]))))
        obs["b3"] = {**prof, "hour_used": h, "r_used": prof["r"][h], "n_evac_slots": n_evac, "evidence_grade": "C(점유 칸 환산 가정)",
                     "absolute_population_used": False}
    evac_route = route(inc_node, evac_dest)
    for s in range(n_evac):
        for e in evac_route:
            evac_zero.add((e, s))
    # B1: 일반차량 칸 용량 = round(LANES × min(1, v_obs/v_ref))  (§7-3)
    cap_general = {}
    if use_b1:
        fname, sp = load_b1_speeds(set(by_id))
        obs["b1_raw_rows"] = int(len(sp))
        cap_general, b1_info = b1_capacity(sp, by_id)
        obs["b1"] = {"file": fname, **b1_info}
    ledger.append({"actor": "대피 보행 흐름", "kind": "evac", "status": "확정", "slot": 0, "delay_min": 0, "route_links": len(evac_route)})

    # R1 펌프차: 진입 + 전개(사건 링크 1차로, 진입 칸~t5)
    pump_route = route(em_origin, inc_node, lock=True)
    pump = {"actor": "펌프차(선착)", "kind": "emergency", "requested_slot": 1}
    # 버그 수정: 펌프차 경로의 마지막 링크가 사건(전개) 링크이면 진입 통행과 전개를 이중 계수하지 않는다(전개 1대로만 셈)
    pump_pass = [e for e in (pump_route or []) if e != inc_link]
    for s in range(1, SLOTS):
        if pump_route and fits_route(pump_pass, s) and fits_hold(inc_link, s):
            for e in pump_pass:
                occ[(e, s)] += 1
            for t in range(s, SLOTS):
                occ[(inc_link, t)] += 1
            pump.update(status="확정", slot=s, delay_min=(s - 1) * SLOT_MIN, route=pump_route, deploy_link=inc_link)
            break
    else:
        pump.update(status="미해소", reason="진입·전개 칸 없음", delay_min=None)
    ledger.append(pump)
    pump_links = set(pump.get("route") or []) | {inc_link}

    # R2 조건 판정표(후보별)
    rows = []
    for e in cand_links:
        c3 = e not in pump_links
        c5 = e != inc_link
        rows.append({"link_id": e, **cand_info[e], "c1_turnaround": "보류 D", "c2_hydrant_dist_m": cand_info[e]["hydrant_dist_m"],
                     "c3_no_block_pump_retreat": c3, "c5_not_deploy_link": c5})
    cdf = pd.DataFrame(rows)

    # R2+R3: 구급차 3대 — 칸마다 수용 가능한 대수만큼 동시 배정, 차량 ID 순서 없음
    remaining = 3
    placements = []
    for s in range(1, SLOTS):
        progress = True
        while remaining and progress:
            progress = False
            order = sorted(cand_links, key=lambda e: (cand_info[e]["hydrant_dist_m"], cand_info[e]["hop"], e))
            for e in order:
                if e in pump_links or e == inc_link:
                    continue
                if not fits_hold(e, s, need_left=1):  # 조건 4: 대기 후 잔여 차로 ≥ 1 (전 대기 칸)
                    continue
                if hop[e] == 1 and not fits_hold(e, s, need_left=1):  # 조건 5(전개 링크 인접) — 조건 4 와 같은 확인을 한 번 더
                    continue
                r = route(em_origin, by_id[e]["f_node"], lock=True)
                if r is None and em_origin != by_id[e]["f_node"]:
                    continue
                r = (r or [])
                if r and (by_id[r[-1]]["t_node"], r[-1], e) in ban_set:
                    continue
                if not fits_route(r, s):
                    continue
                for x in r:
                    occ[(x, s)] += 1
                for t in range(s, SLOTS):
                    occ[(e, t)] += 1
                placements.append({"slot": s, "delay_min": (s - 1) * SLOT_MIN, "staging_link": e, "route_links": len(r),
                                   "wait_slots": SLOTS - s, "wait_min": (SLOTS - s) * SLOT_MIN,
                                   "hydrant_dist_m": cand_info[e]["hydrant_dist_m"], "hop": hop[e],
                                   "sop_locks": [LOCK_TURNAROUND], "status": "조건부 권고(지휘관 확인)", "_route": r})
                remaining -= 1
                progress = True
                break
    unplaced = remaining
    amb_delays = sorted(p["delay_min"] for p in placements)
    ledger.append({"actor": "구급차 3대(후착, R3 — 차량 구분 없음)", "kind": "emergency", "placed": len(placements), "unplaced": unplaced,
                   "delay_distribution_min": amb_delays,
                   "staging": [{k: p[k] for k in ("slot", "staging_link", "wait_min", "hydrant_dist_m", "hop", "status")} for p in placements]})

    # 일반차량(뒤 칸 ≤ 2)
    general = []
    for gid, (o, d) in (("일반차량 1", (bnodes[0], bnodes[-1])), ("일반차량 2", (bnodes[1], bnodes[-2]))):
        r = route(o, d, blocked=frozenset({inc_link}))
        rec = {"actor": gid, "kind": "general", "route_links": len(r) if r else None}
        if not r:
            rec.update(status="미해소", reason="경로 없음", delay_min=None)
        else:
            for s in (0, 1, 2):
                if fits_route(r, s) and all(occ[(x, s)] < cap_general.get((x, s), by_id[x]["lanes"]) for x in r):
                    for x in r:
                        occ[(x, s)] += 1
                    rec.update(status="확정", slot=s, delay_min=s * SLOT_MIN,
                               crosses_staging=sorted(set(r) & {p["staging_link"] for p in placements}))
                    break
            else:
                staging_ids = {p["staging_link"] for p in placements}
                why = {}
                for s_ in (0, 1, 2):
                    why[f"t{s_}"] = [{"link_id": x, "cause": ("대피 점유" if (x, s_) in evac_zero else
                                                              "대기 점유" if x in staging_ids and occ[(x, s_)] >= by_id[x]["lanes"] else
                                                              "전개 점유" if x == inc_link else "긴급차량 진입 통행"),
                                      "lanes": by_id[x]["lanes"], "occupied": occ[(x, s_)]}
                                     for x in r if free(x, s_) < 1]
                rec.update(status="미해소", reason="뒤 칸 2칸 이내 불가 — 조건부 카드", delay_min=None, blocked_cells=why,
                           crosses_staging=sorted(set(r) & staging_ids))
                cards.append({"actor": gid, "card": "역방향 차로 일시 전용 또는 대피 경로 분산 검토", "auto_execute": False})
            rec["route"] = r
        general.append(rec)
        ledger.append(rec)

    # 결정기록(공통엔진 계약)
    inc = core.create_incident(incident_id="SYN-ITAEWON-003", occurred_at="2026-09-15T20:00:00+09:00",
                               source_type="SYNTHETIC_EVENT", evidence_grade="SYNTHETIC_PROTOTYPE", region="서울 용산구 이태원동")
    ev0 = core.update_event(event_id="EV0", incident_id=inc.incident_id, kind="화재+다중운집", occurred_at=inc.occurred_at,
                            source_type="SYNTHETIC_EVENT")
    decisions = 0
    for rt in [pump.get("route")] + [p["_route"] for p in placements]:
        if rt:
            core.record_decision(incident_id=inc.incident_id, event_id=ev0.event_id, decision_version=1,
                                 network_snapshot_id=snap.network_snapshot_id, input_hash=stable_hash({"r": rt}),
                                 source_type="SYNTHETIC_EVENT", evidence_grade="SYNTHETIC_PROTOTYPE", module_id="CONTEST_DEMO_SLOT_SOP3",
                                 baseline_route={"edges": base}, emergency_route={"edges": rt},
                                 eligibility_status="UNKNOWN_FAIL_CLOSED",
                                 block_or_recommend_reason=f"{SOP_REF} 적용 권고 · 폭 축 D · RECOMMEND_ONLY")
            decisions += 1

    # 재계산 트리거(2안과 같은 규칙): t2, 긴급차량 확정 진입 경로 링크 중 LINK_ID 최소
    em_route_links = sorted(set(pump.get("route") or []) | {x for p in placements for x in p["_route"]})
    recompute = {}

    def scope(X, event_id, detail, source_type):
        hop1 = adj[by_id[X]["f_node"]] | adj[by_id[X]["t_node"]]
        hop2 = set(hop1)
        for e in hop1:
            hop2 |= adj[by_id[e]["f_node"]] | adj[by_id[e]["t_node"]]
        in_scope = []
        if pump.get("status") == "확정" and (set(pump["route"]) | {inc_link}) & hop2:
            in_scope.append("펌프차")
        for p in placements:
            if (set(p["_route"]) | {p["staging_link"]}) & hop2:
                in_scope.append(f"대기 {p['staging_link']}")
        for g in general:
            if g.get("status") == "확정" and g["slot"] >= 2 and set(g["route"]) & hop2:
                in_scope.append(g["actor"])
        using = []
        if pump.get("status") == "확정" and X in (pump["route"] + [inc_link]) and (X == inc_link or pump["slot"] >= 2):
            using.append("펌프차 전개" if X == inc_link else "펌프차 진입")
        for p in placements:
            if (X == p["staging_link"]) or (X in p["_route"] and p["slot"] >= 2):
                using.append(f"대기 {p['staging_link']}")
        for g in general:
            if g.get("status") == "확정" and g["slot"] >= 2 and X in g["route"]:
                using.append(g["actor"])
        ev = core.update_event(event_id=event_id, incident_id=inc.incident_id, kind="돌발(단일 링크 이벤트)", occurred_at="2026-09-15T20:20:00+09:00",
                               parent_event_id="EV0", source_type=source_type, detail=detail)
        return {"link_id": X, "slot": 2, "two_hop_links": len(hop2), "records_in_scope": in_scope,
                "records_out_of_scope_locked": (1 + len(placements) + sum(1 for g in general if g.get("status") == "확정")) - len(in_scope),
                "records_using_event_link_after_t2": using, "next_decision_version": core.recompute_on_change(inc.incident_id, ev, lambda v, e: v)}

    if use_b2:
        b2 = load_b2_events(set(by_id))
        obs["b2"] = {"files": b2["files"], "records_all": b2["records_all"], "selected": b2["selected"],
                     "interpretation": "단일 링크 이벤트 — 통제 구간 아님, 차단·용량 차감 없음, 칸 대응 t2(시나리오 가정)"}
        recompute = {"trigger_source": "ITS 돌발상황 실제 기록(링크 단위)", "synthetic_trigger_removed": True,
                     "events": [scope(r["링크아이디"], f"EV{i + 1}", f"{r['돌발일시']} {r['도로명']} {r['돌발구분']}", "PROVIDER_SNAPSHOT")
                                for i, r in enumerate(b2["selected"])]}
        if not b2["selected"]:
            recompute = {"trigger_source": "미확인 — 권역 링크 일치 0건", "events": []}
    elif em_route_links:
        X = em_route_links[0]
        hop1 = adj[by_id[X]["f_node"]] | adj[by_id[X]["t_node"]]
        hop2 = set(hop1)
        for e in hop1:
            hop2 |= adj[by_id[e]["f_node"]] | adj[by_id[e]["t_node"]]
        in_scope = []
        if pump.get("status") == "확정" and pump["slot"] + (SLOTS - pump["slot"]) > 2 and (set(pump["route"]) | {inc_link}) & hop2:
            in_scope.append("펌프차")
        for p in placements:
            if (set(p["_route"]) | {p["staging_link"]}) & hop2:
                in_scope.append(f"대기 {p['staging_link']}")
        for g in general:
            if g.get("status") == "확정" and g["slot"] >= 2 and set(g["route"]) & hop2:
                in_scope.append(g["actor"])
        # 범위 안 레코드 중 t2 이후 통제 링크를 쓰는 것
        broken = []
        if pump.get("status") == "확정" and X in (pump["route"] + [inc_link]) and pump["slot"] >= 2:
            broken.append("펌프차 진입")
        for p in placements:
            if (X == p["staging_link"]) or (X in p["_route"] and p["slot"] >= 2):
                broken.append(f"대기 {p['staging_link']}")
        ev1 = core.update_event(event_id="EV1", incident_id=inc.incident_id, kind="돌발 통제", occurred_at="2026-09-15T20:20:00+09:00",
                                parent_event_id="EV0", source_type="SYNTHETIC_EVENT", detail=X)
        recompute = {"trigger": {"slot": 2, "link_id": X}, "two_hop_links": len(hop2),
                     "records_in_scope": in_scope, "records_out_of_scope_locked": (1 + len(placements) + sum(1 for g in general if g.get("status") == "확정")) - len(in_scope),
                     "records_using_closed_link_after_t2": broken,
                     "next_decision_version": core.recompute_on_change(inc.incident_id, ev1, lambda v, e: v)}

    a2 = json.loads((DER / "slot_itaewon_arm2.json").read_text(encoding="utf-8"))
    a2_delay = a2["delay_min"]
    delays_all = [0] + ([pump["delay_min"]] if pump.get("delay_min") is not None else []) + amb_delays + \
                 [g["delay_min"] for g in general if g.get("delay_min") is not None]
    by_kind = {"대피": 0, "긴급(펌프+구급)": (pump.get("delay_min") or 0) + sum(amb_delays),
               "일반": sum(g["delay_min"] for g in general if g.get("delay_min") is not None)}
    g1_a2 = next(r for r in a2["ledger"] if r["id"] == "G1_car")
    out = {
        "rule_commit": "223da5e", "sop_ref": SOP_REF, "source_type": "SYNTHETIC_EVENT", "scenario_params_are_not_measurements": True,
        "base_conditions": "2안과 같음(사람 확인 해제 2건)", "released_turns": [f"{n}:{s}->{e}" for n, s, e in released],
        "hydrant": {"file": HYD.name, "rows": int(len(hyd)), "coord_excluded": int((~ok).sum()), "within_1500m": int(len(near)),
                    "type_code_counts_within_1500m": near["시설유형코드"].value_counts().to_dict(), "usable_flag_all_blank": bool(hyd["사용가능여부"].isna().all())},
        "candidates": {"count": len(cand_links), "hop_counts": Counter(hop[e] for e in cand_links)},
        "sop_conditions": [
            {"no": 1, "clause": "회차에 용이한 장소(3.1.2.1)", "status": "보류 D", "used_as": "잠금 사유 기록(필터 아님)", "data": "노드링크·폭 없음"},
            {"no": 2, "clause": "소화전 인근(3.1.2.1)", "status": "판정", "used_as": "순위 1", "data": "서울 소방용수시설 2025-12-31"},
            {"no": 3, "clause": "선착대 퇴각에 장애 없음(3.1.2.1)", "status": "판정", "used_as": "필터", "data": "펌프차 경로·전개 링크"},
            {"no": 4, "clause": "특수 소방차량 진입에 장애 없음(3.1.2.1)", "status": "부분 C", "used_as": "필터(잔여 차로 ≥ 1)", "data": "LANES·폭 없음"},
            {"no": 5, "clause": "후착대 배치 공간 고려(3.1.1.1)", "status": "부분 C", "used_as": "필터", "data": "경로·차로수"},
        ],
        "pump": {k: pump.get(k) for k in ("status", "slot", "delay_min", "deploy_link", "reason")},
        "pump_entry_change": {"arm2_slot": 5, "arm2_delay_min": a2_delay["by_actor"].get("F1_pump"), "arm3_slot": pump.get("slot"), "arm3_delay_min": pump.get("delay_min")},
        "ambulances": {"placed": len(placements), "unplaced": unplaced, "delay_distribution_min": amb_delays,
                       "staging": [{k: p[k] for k in ("slot", "staging_link", "wait_slots", "wait_min", "hydrant_dist_m", "hop", "route_links", "sop_locks", "status")} for p in placements]},
        "general": [{k: g.get(k) for k in ("actor", "status", "slot", "delay_min", "crosses_staging", "reason", "blocked_cells")} for g in general],
        "general_effect_vs_arm2": {"일반차량 1": {"arm2_slot": g1_a2.get("slot"), "arm2_delay_min": a2_delay["by_actor"].get("G1_car"),
                                              "arm3_slot": general[0].get("slot"), "arm3_delay_min": general[0].get("delay_min"),
                                              "route_crosses_staging": general[0].get("crosses_staging")}},
        "delay_min": {"total": sum(delays_all), "by_kind": by_kind, "max_individual": max(delays_all)},
        "arm2_delay_min": {"total": a2_delay["total"], "by_kind": a2_delay["by_kind"], "max_individual": a2_delay["max_individual"]},
        "unresolved": [g["actor"] for g in general if g.get("status") == "미해소"] + (["펌프차"] if pump.get("status") == "미해소" else []) + (["구급차"] * unplaced),
        "cards": cards, "decision_records": decisions, "recompute": recompute, "observed_inputs": obs,
        "evac_slots": n_evac, "general_demand_is_scenario_parameter": True,
    }
    cdf.to_csv(DER / f"slot_itaewon_{stage}_candidates.csv", index=False, encoding="utf-8-sig")
    cells = set(occ) | set(evac_zero)
    staging_ids = {p["staging_link"] for p in placements}
    g_rows = [{"link_id": e, "slot": s, "occupied": occ[(e, s)], "lanes": by_id[e]["lanes"], "evac_zero": (e, s) in evac_zero,
               "role": ("전개" if e == inc_link else "대기" if e in staging_ids else "진입")} for (e, s) in sorted(cells)]
    pd.DataFrame(g_rows).to_csv(DER / f"slot_itaewon_{stage}_gantt.csv", index=False, encoding="utf-8-sig")
    (DER / f"slot_itaewon_{stage}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("hydrant", "candidates", "pump", "pump_entry_change", "ambulances", "general", "general_effect_vs_arm2",
                                          "delay_min", "arm2_delay_min", "unresolved", "decision_records", "recompute", "evac_slots")}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
