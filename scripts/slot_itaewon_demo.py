"""003 §5 C — 이태원 권역 시공간 슬롯 배정 시연.

규칙: docs/판정기준.md §5 (실행 전 커밋 84d7943 · 보완 9dc3be5). 그대로 구현한다.

- 수요·용량은 시나리오 파라미터. 사건은 SYNTHETIC_EVENT. 인구 격자 미수급.
- 경로탐색·결정기록·재계산 버전은 공통엔진 DFlowCore 를 import 해서 쓴다.
- 공통엔진에 없는 것(칸 용량 · 충돌해소 5단계 · 지연 장부 · 2-hop 범위)만 여기 둔다 — capability 공백으로 보고.
- 긴급차량은 θ ≥ 90° 이동을 잠금(D · 판정 보류)하고 제외, 잠금은 전부 장부에 남긴다. 폭 축은 전 링크 D.

출력: data/vworld/national/derived/slot_itaewon_arm{1,2}.json · slot_itaewon_arm{1,2}_gantt.csv
--arm2: §5-6 사람 확인 후 해제(긴급차량 baseline 경로 위 잠긴 이동만 해제, 커밋 1311cd9)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "DFLOW_008R9R4_CORE"))
from dflow_core.core import DFlowCore  # noqa: E402
from dflow_core.schema import stable_hash  # noqa: E402

NL = ROOT / "data/vworld/national/raw/NODELINKDATA_20260914"
DER = ROOT / "data/vworld/national/derived"
R_AREA = 700.0
SLOTS = 6
SLOT_MIN = 10
THETA_LOCK = 90.0
ARM = 2 if "--arm2" in sys.argv else 1


def angle(a_last, b_first):
    dot = a_last[0] * b_first[0] + a_last[1] * b_first[1]
    n = np.hypot(*a_last) * np.hypot(*b_first)
    return float(np.degrees(np.arccos(np.clip(dot / n, -1, 1)))) if n else 0.0


def build_area():
    tr = Transformer.from_crs(4326, 5186, always_xy=True)
    probe = json.loads((DER / "vworld_probe.json").read_text(encoding="utf-8"))["items"]["4_geocoder"]["search_district"]
    sx, sy = tr.transform(*probe["서울 용산구 이태원동"]["candidates"][0]["point"])
    bbox = (sx - R_AREA - 50, sy - R_AREA - 50, sx + R_AREA + 50, sy + R_AREA + 50)
    N = pyogrio.read_dataframe(NL / "MOCT_NODE.shp", bbox=bbox, columns=["NODE_ID"])
    xy = shapely.get_coordinates(N.geometry.values)
    N["x"], N["y"] = xy[:, 0], xy[:, 1]
    N["inside"] = np.hypot(N.x - sx, N.y - sy) <= R_AREA
    inside = set(N.NODE_ID[N.inside])
    L = pyogrio.read_dataframe(NL / "MOCT_LINK.shp", bbox=bbox,
                               columns=["LINK_ID", "F_NODE", "T_NODE", "LANES", "ROAD_RANK", "ROAD_NAME", "LENGTH"])
    in_both = L.F_NODE.isin(inside) & L.T_NODE.isin(inside)
    touch = (L.F_NODE.isin(inside) ^ L.T_NODE.isin(inside))
    boundary = sorted(set(L.F_NODE[touch & L.F_NODE.isin(inside)]) | set(L.T_NODE[touch & L.T_NODE.isin(inside)]))
    A = L[in_both].reset_index(drop=True)
    return sx, sy, N.set_index("NODE_ID"), A, L[touch], boundary


def main():
    sx, sy, N, A, TOUCH, boundary = build_area()
    core = DFlowCore(now="2026-09-15T20:00:00+09:00")
    nodes = {n: {"x": float(N.loc[n, "x"]), "y": float(N.loc[n, "y"])} for n in set(A.F_NODE) | set(A.T_NODE)}
    links = [{"link_id": r.LINK_ID, "f_node": r.F_NODE, "t_node": r.T_NODE, "length_m": r.LENGTH,
              "lanes": int(float(r.LANES)), "road_rank": r.ROAD_RANK, "road_name": r.ROAD_NAME} for r in A.itertuples()]
    by_id = {l["link_id"]: l for l in links}
    snap = core.network_snapshot(nodes, links, graph_source="MOCT_NODELINK_20260914", source_type="PROVIDER_SNAPSHOT",
                                 observed_at="2026-09-14", coverage_note="이태원동 동 대표점 반경 700 m, 양끝 노드 권역 안")

    # 급회전 이동 잠금 목록(θ ≥ 90°) — 공통엔진 turn_bans 형식
    first, last = {}, {}
    for r in A.itertuples():
        c = shapely.get_coordinates(r.geometry)
        d = np.diff(c, axis=0)
        d = d[(d != 0).any(axis=1)]
        first[r.LINK_ID], last[r.LINK_ID] = d[0], d[-1]
    bans, locked = [], []
    out_by_node = {}
    for l in links:
        out_by_node.setdefault(l["f_node"], []).append(l)
    for a in links:
        for b in out_by_node.get(a["t_node"], []):
            if b["link_id"] == a["link_id"]:
                continue
            th = angle(last[a["link_id"]], first[b["link_id"]])
            if th >= THETA_LOCK:
                bans.append({"node_id": a["t_node"], "st_link": a["link_id"], "ed_link": b["link_id"]})
                locked.append({"node_id": a["t_node"], "st_link": a["link_id"], "ed_link": b["link_id"], "theta": round(th, 1),
                               "evidence_grade": "D", "status": "판정 보류 — 가용 폭 부재", "applies_to": "긴급차량"})

    # 사건 지점: 동 대표점 최근접 링크의 종점 노드
    tree = shapely.STRtree(A.geometry.values)
    inc_idx = int(tree.nearest(shapely.Point(sx, sy)))
    inc_link = A.LINK_ID[inc_idx]
    inc_node = A.T_NODE[inc_idx]
    # 긴급차량 출발: 경계 링크 중 ROAD_RANK 최소 → 권역 안 끝점, 동률 NODE_ID 오름차순
    cands = []
    for r in TOUCH.itertuples():
        inner = r.F_NODE if r.F_NODE in nodes else r.T_NODE
        if inner in nodes:
            cands.append((r.ROAD_RANK, inner))
    em_origin = sorted(cands)[0][1]
    bnodes = [b for b in boundary if b in nodes]
    released = []
    if ARM == 2:  # §5-6: 긴급차량 baseline 경로 위 잠긴 이동만 해제
        base = core.route_candidates(nodes, links, em_origin, inc_node)
        e = base[0]["edges"] if base else []
        on_path = {(by_id[e[i]]["t_node"], e[i], e[i + 1]) for i in range(len(e) - 1)}
        keep = []
        for bn, lk in zip(bans, locked):
            if (bn["node_id"], bn["st_link"], bn["ed_link"]) in on_path:
                lk.update(status="해제 — 지휘관 현장 확인(가정), 폭 값 없음, D 유지, RECOMMEND_ONLY")
                released.append(dict(lk))
            else:
                keep.append(bn)
        bans[:] = keep

    def route(o, d, *, lock=False, blocked=frozenset()):
        res = core.route_candidates(nodes, links, o, d, turn_bans=bans if lock else (),
                                    edge_blocked=(lambda ln: ln["link_id"] in blocked) if blocked else None)
        return res[0] if res else None

    # 대피 목적지: 사건 지점에서 그래프 거리 최대인 경계 노드
    far = []
    for b in bnodes:
        rt = route(inc_node, b)
        if rt:
            far.append((rt["distance_m"], b))
    evac_dest = sorted(far, key=lambda t: (-t[0], t[1]))[0][1]

    actors = [
        {"id": "E0_evac", "kind": "evac", "o": inc_node, "d": evac_dest, "t": 0, "hold": 2},
        {"id": "G1_car", "kind": "general", "o": bnodes[0], "d": bnodes[-1], "t": 0, "hold": 1},
        {"id": "G2_car", "kind": "general", "o": bnodes[1], "d": bnodes[-2], "t": 0, "hold": 1},
        {"id": "F1_pump", "kind": "emergency", "o": em_origin, "d": inc_node, "t": 1, "hold": 1},
        {"id": "A1_amb", "kind": "emergency", "o": em_origin, "d": inc_node, "t": 1, "hold": 1},
        {"id": "A2_amb", "kind": "emergency", "o": em_origin, "d": inc_node, "t": 1, "hold": 1},
        {"id": "A3_amb", "kind": "emergency", "o": em_origin, "d": inc_node, "t": 1, "hold": 1},
    ]
    log = []
    for ac in actors:
        if ac["kind"] == "general":
            rt = route(ac["o"], ac["d"], blocked=frozenset({inc_link}))
        elif ac["kind"] == "emergency":
            ac["baseline"] = route(ac["o"], ac["d"])
            rt = route(ac["o"], ac["d"], lock=True)
            used_locks = []
            if ac["baseline"]:
                e = ac["baseline"]["edges"]
                bl = {(x["node_id"], x["st_link"], x["ed_link"]) for x in bans}
                used_locks = [f"{by_id[e[i]]['t_node']}:{e[i]}->{e[i+1]}" for i in range(len(e) - 1)
                              if (by_id[e[i]]["t_node"], e[i], e[i + 1]) in bl]
            ac["baseline_locked_moves"] = used_locks
        else:
            rt = route(ac["o"], ac["d"])
        ac["route"] = rt["edges"] if rt else None
        log.append({"actor": ac["id"], "route_links": len(ac["route"]) if ac["route"] else None})

    def demand_table(recs):
        occ = {}
        for r in recs:
            if not r.get("route"):
                continue
            for s_ in range(r["slot"], min(SLOTS, r["slot"] + r["hold"])):
                for e in r["route"]:
                    occ.setdefault((e, s_), []).append(r["id"])
        return occ

    def capacity(e, s_, confirmed, closed):
        if (e, s_) in closed:
            return 0
        for r in confirmed:
            if r["kind"] == "evac" and r.get("route") and e in r["route"] and r["slot"] <= s_ < r["slot"] + r["hold"]:
                return 0  # 군중 점유 = 차량 유효차로 0
        return by_id[e]["lanes"]

    def used(e, s_, confirmed):
        return sum(1 for r in confirmed if r["kind"] != "evac" and r.get("route") and e in r["route"]
                   and r["slot"] <= s_ < r["slot"] + r["hold"])

    def fits(route_, slot, confirmed, closed):
        return all(used(e, slot, confirmed) < capacity(e, slot, confirmed, closed) for e in route_)

    def resolve(requests, closed=frozenset(), locked_confirmed=()):
        confirmed = list(locked_confirmed)
        ledger, cards = [], []
        order = sorted(requests, key=lambda r: ({"evac": 0, "emergency": 1, "general": 2}[r["kind"]], r["id"]))
        for r in order:
            rec = dict(r)
            if not r.get("route"):
                rec.update(status="미해소", reason="판정 보류로 경로 없음(급회전 잠금)" if r["kind"] == "emergency" else "경로 없음",
                           delay_slots=None)
                ledger.append(rec)
                continue
            if r["kind"] == "evac":  # ① 인명안전 확정
                rec.update(status="확정", delay_slots=0)
                confirmed.append(rec)
                ledger.append(rec)
                continue
            if fits(r["route"], r["slot"], confirmed, closed):
                rec.update(status="확정", delay_slots=0)
                confirmed.append(rec)
                ledger.append(rec)
                continue
            if r["kind"] == "emergency":  # ② 대체 경로(잠금 유지) → 칸 뒤로
                sat = frozenset(e for e in by_id if used(e, r["slot"], confirmed) >= capacity(e, r["slot"], confirmed, closed))
                alt = route(r["o"], r["d"], lock=True, blocked=sat)
                if alt and fits(alt["edges"], r["slot"], confirmed, closed):
                    rec.update(route=alt["edges"], status="확정", delay_slots=0, action="대체 경로(잠금 유지)")
                    confirmed.append(rec)
                    ledger.append(rec)
                    continue
                for dslot in range(1, SLOTS - r["slot"]):
                    if fits(r["route"], r["slot"] + dslot, confirmed, closed):
                        rec.update(slot=r["slot"] + dslot, status="확정", delay_slots=dslot, action=f"칸 +{dslot}")
                        confirmed.append(rec)
                        break
                else:
                    rec.update(status="미해소", reason="대체 경로·칸 이동 모두 불가", delay_slots=None)
                ledger.append(rec)
                continue
            for dslot in (1, 2):  # ③ 일반차량 뒤 칸
                if r["slot"] + dslot < SLOTS and fits(r["route"], r["slot"] + dslot, confirmed, closed):
                    rec.update(slot=r["slot"] + dslot, status="확정", delay_slots=dslot, action=f"칸 +{dslot}")
                    confirmed.append(rec)
                    break
            else:  # ④ 조건부 카드(자동 실행 안 함) → ⑤ 미해소
                cards.append({"actor": r["id"], "card": "역방향 차로 일시 전용 또는 대피 경로 분산 검토", "auto_execute": False})
                rec.update(status="미해소", reason="뒤 칸 2칸 이내 불가 — 조건부 카드 제시", delay_slots=None)
            ledger.append(rec)
        return confirmed, ledger, cards

    requests = [{"id": a["id"], "kind": a["kind"], "o": a["o"], "d": a["d"], "slot": a["t"], "hold": a["hold"],
                 "route": a["route"]} for a in actors]
    before = demand_table(requests)
    confirmed, ledger, cards = resolve(requests)

    # 결정기록(공통엔진 계약) — 긴급차량
    inc = core.create_incident(incident_id="SYN-ITAEWON-001", occurred_at="2026-09-15T20:00:00+09:00",
                               source_type="SYNTHETIC_EVENT", evidence_grade="SYNTHETIC_PROTOTYPE", region="서울 용산구 이태원동")
    ev0 = core.update_event(event_id="EV0", incident_id=inc.incident_id, kind="화재+다중운집", occurred_at=inc.occurred_at,
                            source_type="SYNTHETIC_EVENT")
    decisions, refused = [], []
    for a in actors:
        if a["kind"] != "emergency":
            continue
        payload = {"a": a["id"], "o": a["o"], "d": a["d"], "snap": snap.network_snapshot_id}
        try:
            d = core.record_decision(incident_id=inc.incident_id, event_id=ev0.event_id, decision_version=1,
                                     network_snapshot_id=snap.network_snapshot_id, input_hash=stable_hash(payload),
                                     source_type="SYNTHETIC_EVENT", evidence_grade="SYNTHETIC_PROTOTYPE",
                                     module_id="CONTEST_DEMO_SLOT",
                                     baseline_route={"edges": (a["baseline"] or {}).get("edges", [])},
                                     emergency_route={"edges": a["route"] or []},
                                     eligibility_status="UNKNOWN_FAIL_CLOSED",
                                     block_or_recommend_reason="폭 축 D(속성 부재) · 급회전 잠금 · RECOMMEND_ONLY")
            decisions.append({"actor": a["id"], "decision_version": d.decision_version})
        except Exception as e:  # noqa: BLE001 — 계약 거부를 그대로 기록
            refused.append({"actor": a["id"], "refused": str(e)[:160]})

    # 재계산 트리거: t2 돌발 통제 — 긴급차량 확정 경로 링크 중 LINK_ID 최소
    em_links = sorted({e for r in confirmed if r["kind"] == "emergency" for e in r["route"]})
    trigger = None
    recompute = {}
    if em_links:
        X = em_links[0]
        trigger = {"slot": 2, "link_id": X, "event": "돌발 통제(용량 0)"}
        adj = {}
        for l in links:
            for n in (l["f_node"], l["t_node"]):
                adj.setdefault(n, set()).add(l["link_id"])
        hop1 = set().union(*(adj[n] for n in (by_id[X]["f_node"], by_id[X]["t_node"])))
        hop2 = set(hop1)
        for e in hop1:
            hop2 |= adj[by_id[e]["f_node"]] | adj[by_id[e]["t_node"]]
        closed = frozenset((X, s_) for s_ in range(2, SLOTS))
        affected = [r for r in confirmed if r["slot"] + r["hold"] > 2 and set(r["route"]) & hop2]
        kept = [r for r in confirmed if r not in affected]
        reqs2 = [{k: r[k] for k in ("id", "kind", "o", "d", "slot", "hold", "route")} for r in affected]
        conf2, ledger2, cards2 = resolve(reqs2, closed=closed, locked_confirmed=kept)
        ev1 = core.update_event(event_id="EV1", incident_id=inc.incident_id, kind="돌발 통제", occurred_at="2026-09-15T20:20:00+09:00",
                                parent_event_id="EV0", source_type="SYNTHETIC_EVENT", detail=X)
        ver = core.recompute_on_change(inc.incident_id, ev1, lambda v, e: v)
        recompute = {"trigger": trigger, "two_hop_links": len(hop2), "records_total": len(confirmed),
                     "records_reassigned_in_scope": len(affected), "records_locked_out_of_scope": len(kept),
                     "ledger_after": [{k: r.get(k) for k in ("id", "status", "slot", "delay_slots", "action", "reason")} for r in ledger2],
                     "cards": cards2, "next_decision_version": ver, "parent_event": "EV0"}

    def gantt(occ, recs_confirmed=None):
        rows = []
        for (e, s_), who in occ.items():
            rows.append({"link_id": e, "slot": s_, "demand": len(who), "actors": ",".join(who), "lanes": by_id[e]["lanes"]})
        return pd.DataFrame(rows)

    gb = gantt(before)
    after = demand_table([r for r in ledger if r["status"] == "확정"])
    ga = gantt(after)
    gb["overload"] = gb.demand > gb.lanes
    top = gb.groupby("link_id").overload.sum().sort_values(ascending=False)
    top_links = list(top[top > 0].index[:4]) or list(gb.groupby("link_id").demand.sum().sort_values(ascending=False).index[:4])
    gb.assign(phase="before").pipe(lambda d: pd.concat([d, ga.assign(phase="after")])).to_csv(
        DER / f"slot_itaewon_arm{ARM}_gantt.csv", index=False, encoding="utf-8-sig")

    delays = {r["id"]: (r["delay_slots"] * SLOT_MIN if r.get("delay_slots") is not None else None) for r in ledger}
    kinds = {}
    for r in ledger:
        if r.get("delay_slots") is not None:
            kinds.setdefault(r["kind"], 0)
            kinds[r["kind"]] += r["delay_slots"] * SLOT_MIN
    out = {
        "rule_commit": ["84d7943", "9dc3be5"], "source_type": "SYNTHETIC_EVENT", "scenario_params_are_not_measurements": True,
        "area": {"radius_m": R_AREA, "links": len(links), "nodes": len(nodes), "boundary_nodes": len(bnodes),
                 "network_snapshot_id": snap.network_snapshot_id},
        "incident": {"link": inc_link, "node": inc_node}, "emergency_origin": em_origin, "evac_dest": evac_dest,
        "arm": ARM, "locked_sharp_moves": len(locked), "released_by_human_confirmation": released, "width_axis": "전 링크 D(속성 부재)",
        "emergency_baseline_would_use_locked_moves": {a["id"]: a.get("baseline_locked_moves") for a in actors if a["kind"] == "emergency"},
        "routes": log,
        "overloads_before": int(gb.overload.sum()), "overload_cells_before": gb[gb.overload][["link_id", "slot", "demand", "lanes", "actors"]].to_dict("records"),
        "ledger": [{k: r.get(k) for k in ("id", "kind", "status", "slot", "delay_slots", "action", "reason")} for r in ledger],
        "delay_min": {"total": sum(v for v in delays.values() if v is not None), "by_kind": kinds,
                      "max_individual": max([v for v in delays.values() if v is not None], default=0), "by_actor": delays},
        "unresolved": [r["id"] for r in ledger if r["status"] == "미해소"],
        "cards": cards, "decision_records": decisions, "decision_records_refused": refused,
        "gantt_top_links": top_links, "recompute": recompute,
        "capability_gap": ["시간 칸 용량", "충돌해소 고정 5단계", "지연 장부", "재계산 2-hop 범위 한정"],
    }
    (DER / f"slot_itaewon_arm{ARM}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (DER / f"slot_itaewon_arm{ARM}_locked_moves.json").write_text(json.dumps(locked, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("arm", "released_by_human_confirmation", "area", "incident", "locked_sharp_moves", "emergency_baseline_would_use_locked_moves", "routes",
                                          "overloads_before", "ledger", "delay_min", "unresolved", "decision_records",
                                          "decision_records_refused", "gantt_top_links")}, ensure_ascii=False, default=str))
    print(json.dumps(recompute, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
