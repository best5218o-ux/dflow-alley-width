"""민감도 기준 재현의 spec 플래그 불일치 규명 (D-071 §3-1).

캐시의 A·L·S·R 은 반올림 값이다. 원 실행은 반올림 전 값으로 §34-4 선험을 판정했다.
반올림 값으로 다시 판정했을 때 원 플래그와 다른 마스크를 전부 뽑아, 어느 변수의 어느 경계에서 뒤집혔는지와
그 마스크가 버퍼 안인지·최종 결과에 들어갔는지를 적는다.
산출: deliverables/민감도_경계값10건.csv
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).parent))
import sam_vehicle_width as sv  # noqa: E402
from sensitivity import BASE_SPEC, geometry  # noqa: E402

LABEL = {"A": "면적 A(㎡)", "L": "장변 L(m)", "S": "단변 S(m)", "LS": "L/S", "R": "직사각도 R"}


def impact(g, r, re_ok):
    """산출물은 원 플래그(반올림 전 값 판정)로 만들어졌으므로 산출 영향은 0 이다. 버퍼 안 마스크는 가상 영향을 함께 적는다."""
    if not r["corridor"]:
        return "산출 영향 없음 — 버퍼 밖이라 어느 판정으로도 차량 후보가 아니다"
    conf = [x for x in g["rows"] if x["spec"] and x["corridor"]]
    now = round(g["rbt"] - max([x["lateral_m"] for x in conf]), 2) if conf else g["rbt"]
    lat = [x["lateral_m"] for x in conf] + ([r["lateral_m"]] if re_ok else [])
    hyp = round(g["rbt"] - max(lat), 2) if lat else g["rbt"]
    return (f"산출 영향 없음 — 원 실행은 반올림 전 값으로 판정해 제외했다. 반올림 값으로 판정했다면 차량 후보가 되어 "
            f"W_worst {now} → {hyp} m(밴드 {sv.band(now)} → {sv.band(hyp)}) — 경계 1 cm 미만 차이에 판정이 걸린 사례")


def main():
    rows = []
    for g in geometry():
        if g.get("rows") is None:
            continue
        corr = g["lines"].buffer((g["rbt"] / 2) / g["mpp"])
        for j, r in enumerate(g["rows"]):
            ls = r["L"] / r["S"] if r["S"] else 0
            val = {"A": r["A"], "L": r["L"], "S": r["S"], "LS": ls, "R": r["R"]}
            fails = [k for k, (lo, hi) in BASE_SPEC.items() if (lo is not None and val[k] < lo) or (hi is not None and val[k] > hi)]
            re_ok = not fails
            if re_ok == r["spec"]:
                continue
            # 경계 판정: 반올림 값이 경계와 같거나(≤ 반올림 오차) 가장 가까운 경계
            near = []
            for k, (lo, hi) in BASE_SPEC.items():
                tol = 0.005 if k != "LS" else 0.005 * (1 / r["S"] + r["L"] / r["S"] ** 2)
                for side, b in (("하한", lo), ("상한", hi)):
                    if b is not None and abs(val[k] - b) <= tol + 1e-9:
                        near.append(f"{LABEL[k]} {side} {b} (값 {round(val[k], 4)})")
            inside = bool(corr.contains(Point(*np.mean(r["box"], axis=0))))
            rows.append({"조각": g["조각"], "마스크 행": j, "A": r["A"], "L": r["L"], "S": r["S"], "L/S": round(ls, 4), "R": r["R"],
                         "원 플래그(spec)": r["spec"], "반올림 값 재판정": re_ok,
                         "뒤집힌 경계": " · ".join(near) if near else "반올림 오차 범위 밖 — " + ",".join(fails or ["통과"]),
                         "버퍼 안(corridor)": r["corridor"], "차량 후보(원 판정)": bool(r["spec"] and r["corridor"]),
                         "최종 영향": impact(g, r, re_ok)})
    out = sv.DELIV / "민감도_경계값10건.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(len(rows))
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
