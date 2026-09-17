"""도로구간 버퍼 폭·차량 규격 선험 민감도 (D-070 Part E-2).

SAM 은 다시 돌리지 않는다. sam_vehicle_cache/work_XX.json 의 마스크 행(A·L·S·R·중심 상자·횡점유)을 그대로 쓰고
필터 조건만 바꿔 재집계한다(§34-13 캐시 사용). 현재 값(버퍼 road_bt/2 · §34-4 선험)은 고정하고 흔들림만 잰다.

산출: deliverables/민감도_버퍼폭.csv · 민감도_규격선험.csv
기준 재현 검사: 배율 1.0 · 선험 무변동에서 캐시의 corridor 플래그와 37조각 최종채택·판정·분리 방식을 원 산출물과 대조한다.
캐시의 A·L·S·R 은 소수 둘째 자리 반올림 값이라, 선험 변동은 「원 플래그 + 반올림 값 판정이 바뀐 마스크만 뒤집기」로 적용한다.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import shapely.wkt
from shapely.geometry import LineString, MultiLineString, Point

sys.path.insert(0, str(Path(__file__).parent))
import sam_vehicle_width as sv  # noqa: E402

BASE_SPEC = {"A": (3.0, 20.0), "L": (3.0, 7.5), "S": (1.4, 2.8), "LS": (1.6, 4.2), "R": (0.62, None)}


def spec_ok(r, sp):
    ls = r["L"] / r["S"] if r["S"] else 0
    val = {"A": r["A"], "L": r["L"], "S": r["S"], "LS": ls, "R": r["R"]}
    for k, (lo, hi) in sp.items():
        if lo is not None and val[k] < lo:
            return False
        if hi is not None and val[k] > hi:
            return False
    return True


def geometry():
    """sam_vehicle_width.main 과 같은 순서·같은 좌표계로 조각별 선형(작업창 화소)을 만든다. 타일은 읽지 않는다."""
    roads = sv.load_roads()
    out = []
    for i, pc in enumerate(sv.pieces()):
        lon, lat = pc["point"]
        g = sv.gsd(lat)
        mpp = g / sv.UP
        cands = roads.get(pc["road_name"], [])
        px, py = sv.T45.transform(lon, lat)
        rec = {"i": i, "조각": pc["조각"], "시군구": pc["시군구"], "mpp": mpp}
        if not cands:
            out.append(rec)
            continue
        row = min(cands, key=lambda r: shapely.wkt.loads(r["wkt"]).distance(Point(px, py)))
        geom = shapely.wkt.loads(row["wkt"])
        rbt = row.get("road_bt")
        if rbt in (None, "", 0):
            out.append(rec)
            continue
        rbt = float(rbt)
        near = min(sv.lines_of(geom), key=lambda l: l.distance(Point(px, py)))
        npt = near.interpolate(near.project(Point(px, py)))
        gx, gy = sv.gpx(*sv.T54.transform(npt.x, npt.y))
        ox, oy = int((gx - 260) // 256) * 256, int((gy - 260) // 256) * 256     # mosaic 원점과 같다
        cx, cy = gx - ox, gy - oy
        x0, y0 = int(round(cx - sv.WIN / 2)), int(round(cy - sv.WIN / 2))

        def to_px(x, y):
            qx, qy = sv.gpx(*sv.T54.transform(x, y))
            return ((qx - ox) - x0) * sv.UP, ((qy - oy) - y0) * sv.UP
        rec.update(rbt=rbt, lines=MultiLineString([LineString([to_px(x, y) for x, y in l.coords]) for l in sv.lines_of(geom)]))
        cache = sv.WORK / f"work_{i:02d}.json"
        rec["rows"] = json.loads(cache.read_text(encoding="utf-8"))["rows"] if cache.exists() else None
        out.append(rec)
    return out


def evaluate(geo, k_buf, sp, readings, old):
    """조각별 (최종채택, 판정, 분리방식) 과 집계."""
    res, n_spec, n_conf = {}, 0, 0
    for g in geo:
        key = (g["시군구"], g["조각"])
        if "rbt" not in g or g.get("rows") is None:
            ww, st = None, "UNKNOWN_FAIL_CLOSED"
        else:
            corr = g["lines"].buffer(k_buf * (g["rbt"] / 2) / g["mpp"])
            # 캐시 플래그(원 실행의 반올림 전 값 판정)를 기준으로 두고, 흔든 선험이 반올림 값 판정을 바꾼 마스크만 뒤집는다
            spec = [r for r in g["rows"] if r["spec"] != (spec_ok(r, sp) != spec_ok(r, BASE_SPEC))]
            conf = [r for r in spec if corr.contains(Point(*np.mean(r["box"], axis=0)))]
            n_spec += len(spec)
            n_conf += len(conf)
            rd = readings.get(g["조각"]) or next((v for kk, v in readings.items() if sv.norm(kk) == sv.norm(g["조각"])), None)
            seen = rd.get("parked_vehicles_seen") if rd else None
            if conf:
                ww = round(g["rbt"] - max(r["lateral_m"] for r in conf), 2)
                st = sv.band(ww)
            elif (isinstance(seen, int) and seen >= 1) or isinstance(seen, str):
                ww, st = None, "UNKNOWN_FAIL_CLOSED_미탐"
            else:
                ww, st = g["rbt"], "차량없음_road_bt적용"
        ded = old.get(key, {}).get("차감폭 최소(m)", "")
        ded = float(ded) if ded not in ("", None) else None
        if st == "UNKNOWN_FAIL_CLOSED_미탐":
            final, fst = None, st
        else:
            vals = [v for v in (ded, ww) if v is not None]
            final = round(min(vals), 2) if vals else None
            fst = sv.band(final) if vals else "UNKNOWN_FAIL_CLOSED"
        mode = sv.separation(final)[0] if final is not None else "보류"
        res[key] = (final, fst, mode)
    return res, n_spec, n_conf


def compare(base, cur):
    ch_w = sum(1 for k in base if base[k][0] != cur[k][0])
    ch_b = sum(1 for k in base if base[k][1] != cur[k][1])
    ch_m = sum(1 for k in base if base[k][2] != cur[k][2])
    return ch_w, ch_b, ch_m


def main():
    readings = {r["piece"]: r for r in json.loads((sv.DER / "ortho_readings.json").read_text(encoding="utf-8"))["readings"]}
    old = {(r["시군구"], r["조각"]): r for r in csv.DictReader((sv.DELIV / "도로경계내접폭_26개소.csv").open(encoding="utf-8-sig"))}
    geo = geometry()

    # 기준 재현 검사 — 캐시 플래그와 원 산출물
    flag_mis = spec_mis = 0
    for g in geo:
        if g.get("rows") is None:
            continue
        corr = g["lines"].buffer((g["rbt"] / 2) / g["mpp"])
        for r in g["rows"]:
            flag_mis += corr.contains(Point(*np.mean(r["box"], axis=0))) != r["corridor"]
            spec_mis += spec_ok(r, BASE_SPEC) != r["spec"]
    base, bs, bc = evaluate(geo, 1.0, BASE_SPEC, readings, old)
    prod = {(r["시군구"], r["조각"]): r for r in csv.DictReader((sv.DELIV / "통행가능폭_주차차감_37조각.csv").open(encoding="utf-8-sig"))}
    prod_mis = sum(1 for k, v in base.items()
                   if (str(v[0]) if v[0] is not None else "") != (str(float(prod[k]["최종채택(m)"])) if prod[k]["최종채택(m)"] else "")
                   or v[1] != prod[k]["판정(최종채택)"] or v[2] != prod[k]["분리방식"])
    check = {"corridor 플래그 불일치": int(flag_mis), "spec 플래그 불일치(반올림 값 재판정)": int(spec_mis),
             "37조각 최종채택·판정·분리 불일치": prod_mis, "기준 규격통과": bs, "기준 차량후보": bc}
    print("기준 재현:", json.dumps(check, ensure_ascii=False))

    n = len(base)
    rows_b = []
    for k in (0.8, 0.9, 1.0, 1.1, 1.2):
        cur, s, c = evaluate(geo, k, BASE_SPEC, readings, old)
        w, b, m = compare(base, cur)
        rows_b.append({"배율(road_bt/2 ×)": k, "차량 후보 수": c, "규격 통과 수": s, "버퍼 밖 제외율(%)": round(100 * (s - c) / s, 1),
                       "최종채택 변동 조각": w, "판정(밴드) 변동 조각": b, "분리 방식 변동 조각": m,
                       "판정 불변율(%)": round(100 * (n - b) / n, 1)})
    rows_s = []
    for var in ("A", "L", "S", "LS", "R"):
        for f in (0.9, 1.1):
            sp = dict(BASE_SPEC)
            lo, hi = sp[var]
            sp[var] = (lo * f if lo is not None else None, hi * f if hi is not None else None)
            cur, s, c = evaluate(geo, 1.0, sp, readings, old)
            w, b, m = compare(base, cur)
            label = {"A": "면적 A 상하한", "L": "장변 L 상하한", "S": "단변 S 상하한", "LS": "L/S 상하한", "R": "직사각도 R 하한"}[var]
            rows_s.append({"변수": label, "배율": f, "하한": None if sp[var][0] is None else round(sp[var][0], 3),
                           "상한": None if sp[var][1] is None else round(sp[var][1], 3),
                           "차량 후보 수": c, "규격 통과 수": s, "버퍼 밖 제외율(%)": round(100 * (s - c) / s, 1) if s else "",
                           "최종채택 변동 조각": w, "판정(밴드) 변동 조각": b, "분리 방식 변동 조각": m,
                           "판정 불변율(%)": round(100 * (n - b) / n, 1)})
    for name, rows in (("민감도_버퍼폭.csv", rows_b), ("민감도_규격선험.csv", rows_s)):
        with (sv.DELIV / name).open("w", encoding="utf-8-sig", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            wr.writeheader()
            wr.writerows(rows)
    summ = {"기준재현": check, "조각": n,
            "버퍼폭_최소불변율": min(r["판정 불변율(%)"] for r in rows_b),
            "규격선험_최소불변율": min(r["판정 불변율(%)"] for r in rows_s),
            "버퍼폭_최대밴드변동": max(r["판정(밴드) 변동 조각"] for r in rows_b),
            "규격선험_최대밴드변동": max(r["판정(밴드) 변동 조각"] for r in rows_s)}
    (sv.DER / "sensitivity.json").write_text(json.dumps({"summary": summ, "buffer": rows_b, "spec": rows_s}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summ, ensure_ascii=False))
    for r in rows_b + rows_s:
        print(r)


if __name__ == "__main__":
    main()
