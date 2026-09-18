"""019 §3-3 — 5자 대조표(사람 판독 11조각) + 26개소 판정 표. 기준 §29-6·29-7 (실행 전 커밋 d182518)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"
DELIV = ROOT / "deliverables"


def cmp_read(v, rng):
    if v is None or not rng:
        return "대조 불가"
    lo, hi = rng
    return "모순되지 않음" if lo - 1 <= float(v) <= hi + 1 else "차이"


def main():
    mw = json.loads((DER / "ngii_medial_width.json").read_text(encoding="utf-8"))
    rows = {r["piece"]: r for r in mw["pieces"]}
    rd = {r["piece"]: r for r in json.loads((DER / "ortho_readings.json").read_text(encoding="utf-8"))["readings"]}
    sam = {}
    sv = json.loads((DER / "sam_validation.json").read_text(encoding="utf-8"))
    for key in ("rows",):
        if isinstance(sv.get(key), list):
            for r in sv[key]:
                if isinstance(r, dict) and r.get("piece"):
                    sam[r["piece"]] = r
    five, agg = [], {}
    for piece, r in rd.items():
        m = rows.get(piece, {})
        s = sam.get(piece, {})
        rng = r.get("width_read_m")
        rec = {
            "조각": piece, "사람 판독(m)": "~".join(map(str, rng)) if rng else "판독불가",
            "도로경계 내접폭(m)": m.get("inscribed_min_m"), "장애물 차감폭(m)": m.get("deducted_min_m"),
            "RVWD(m)": m.get("rvwd_nearest"), "road_bt": (r.get("road_bt")),
            "SAM(m)": s.get("sam_width_m"),
            "건물간격 기하(m)": s.get("g_gap_m"),
            "판정(내접폭)": m.get("band"), "판정(차감폭)": m.get("band_deducted"),
        }
        for label, key in (("내접폭", "도로경계 내접폭(m)"), ("차감폭", "장애물 차감폭(m)"), ("RVWD", "RVWD(m)"),
                           ("road_bt", "road_bt"), ("SAM", "SAM(m)"), ("건물간격", "건물간격 기하(m)")):
            v = cmp_read(rec[key], rng)
            rec[f"대조:{label}"] = v
            a = agg.setdefault(label, {"모순되지 않음": 0, "차이": 0, "대조 불가": 0})
            a[v] += 1
        five.append(rec)
    grades = {}
    for label, a in agg.items():
        n = a["모순되지 않음"] + a["차이"]
        p = a["모순되지 않음"] / n if n else None
        grades[label] = {"모순되지 않음": a["모순되지 않음"], "차이": a["차이"], "대조 불가": a["대조 불가"],
                         "p": round(p, 3) if p is not None else None,
                         "등급": (None if p is None else "C(참고 가능)" if p >= 0.8 else "D(사용 보류)" if p >= 0.5 else "E(쓰지 않음)")}
    DELIV.mkdir(parents=True, exist_ok=True)
    with (DELIV / "AI-C_도로경계내접폭_5자대조.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(five[0].keys()))
        w.writeheader()
        w.writerows(five)
    with (DELIV / "도로경계내접폭_26개소.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["시군구", "조각", "도로명", "축선거리(m)", "면안축선(m)", "표본점", "내접폭 최소(m)", "내접폭 중앙(m)",
                    "차감폭 최소(m)", "판정(내접폭)", "판정(차감폭)", "담장", "옹벽", "계단", "RVWD(m)", "미산출 사유"])
        for r in mw["pieces"]:
            oc = r.get("obstacle_counts", {})
            w.writerow([r.get("sigg"), r["piece"], r.get("road_name"), (r.get("axis") or {}).get("d_to_piece_m"),
                        r.get("inside_len_m"), r.get("samples"), r.get("inscribed_min_m"), r.get("inscribed_median_m"),
                        r.get("deducted_min_m"), r.get("band"), r.get("band_deducted"), oc.get("wall"), oc.get("retaining"),
                        oc.get("stair"), r.get("rvwd_nearest"), r.get("reason") or r.get("error") or ""])
    bands = {}
    for r in mw["pieces"]:
        bands.setdefault(r.get("band") or "UNKNOWN_FAIL_CLOSED", 0)
        bands[r.get("band") or "UNKNOWN_FAIL_CLOSED"] += 1
    bandsd = {}
    for r in mw["pieces"]:
        k = r.get("band_deducted") or r.get("band") or "UNKNOWN_FAIL_CLOSED"
        bandsd[k] = bandsd.get(k, 0) + 1
    out = {"rule_commit": "d182518", "five_way": five, "대조_집계": agg, "증거등급": grades,
           "판정분포_내접폭_37조각": bands, "판정분포_차감폭_37조각": bandsd,
           "주의": ["산출값은 「도로경계 면 내접폭」이며 「통과가능폭」이 아니다",
                  "도로경계 면이 무엇을 경계로 삼는지 미확인(속성 id·dycd 뿐, SCLS 미제공)",
                  "축선 귀속은 거리 기반 — 「차이」가 값 오차인지 귀속 오차인지 구분되지 않는다",
                  "2.5 m 는 문헌 인용, 3.5 m 는 우리 설정",
                  "판독은 측정이 아니다(등급 C) — 대조는 정확도 측정이 아니다"]}
    (DER / "ngii_five_way.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"집계": agg, "등급": grades, "내접폭": bands, "차감폭": bandsd}, ensure_ascii=False, indent=1))
    for r in five:
        print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
