"""저장소만 내려받아 곧바로 돌릴 수 있는 검증기 — 외부 데이터·원고·인터넷이 필요 없다.

    python scripts/verify_deliverables.py

`deliverables/` 의 CSV 만 읽어 제출본이 주장하는 수치를 전부 다시 계산한다.
표준 라이브러리(csv)만 쓴다. 설치가 필요 없다.
불일치가 하나라도 있으면 종료 코드 1.

이 스크립트가 검증하지 못하는 것(= 이 저장소로 확인할 수 없는 것)은
docs/재현_범위.md 에 층별로 적어 두었다.
"""
from __future__ import annotations
import csv, pathlib, statistics, sys, collections

ROOT = pathlib.Path(__file__).resolve().parents[1]
D = ROOT / "deliverables"
OK, FAIL = [], []


def rd(name):
    with (D / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def chk(label, got, want, tol=0.0):
    if isinstance(want, float) or isinstance(got, float):
        good = abs(float(got) - float(want)) <= tol
    else:
        good = got == want
    (OK if good else FAIL).append((label, got, want))
    print(("  PASS  " if good else "  FAIL  ") + f"{label}: 계산 {got} / 주장 {want}")


def num(x):
    x = (x or "").strip()
    return None if x in ("", "-", "null") else float(x)


def main():
    p37 = rd("통행가능폭_주차차감_37조각.csv")
    corr = rd("회랑필터_전후_오탐.csv")
    inner = rd("도로경계내접폭_26개소.csv")
    human = rd("차량탐지_사람대조_11조각.csv")
    buf = rd("민감도_버퍼폭.csv")
    spec = rd("민감도_규격선험.csv")
    nat = rd("전국대조군_길번길포함률.csv")
    s26 = rd("26개소_산출표.csv")

    print("\n[1] SAM → 버퍼 사슬 (회랑필터_전후_오탐.csv 합계 행)")
    tot = [r for r in corr if r["조각"].strip() == "합계"][0]
    chk("원 마스크", int(tot["SAM원마스크"]), 3838)
    chk("규격 선험 통과", int(tot["규격선험통과"]), 709)
    chk("도로구간 버퍼 안", int(tot["회랑안"]), 351)
    chk("차량 후보(둘 다 통과)", int(tot["확정(둘다)"]), 71)
    chk("버퍼 밖 제외 수 = 규격통과 − 확정", int(tot["규격선험만통과했으나_회랑밖(=오탐제거수)"]),
        int(tot["규격선험통과"]) - int(tot["확정(둘다)"]))
    chk("버퍼 밖 제외율(%)", round(int(tot["규격선험만통과했으나_회랑밖(=오탐제거수)"]) / int(tot["규격선험통과"]) * 100, 1), 90.0)
    chk("행 합계 = 합계 행 (원 마스크)", sum(int(r["SAM원마스크"]) for r in corr if r["조각"].strip() != "합계"), 3838)

    print("\n[2] 조각 수와 차량 수 교차")
    chk("조각 수", len(p37), 37)
    chk("확정차량수 합 = 차량 후보", sum(int(r["확정차량수"] or 0) for r in p37), 71)
    chk("조각 키 중복 없음", len(set(r["조각"] for r in p37)), 37)

    print("\n[3] 폭 산식 전수 재계산")
    e1 = e2 = e3 = 0
    for r in p37:
        bt, occ_m, occ_x = num(r["road_bt"]), num(r["횡점유중앙(m)"]), num(r["횡점유최대(m)"])
        wp, ww, inn, fin = num(r["W_pass(m)"]), num(r["W_worst(m)"]), num(r["내접폭차감(m)"]), num(r["최종채택(m)"])
        if occ_m is not None and wp is not None and abs((bt - occ_m) - wp) > 0.011: e1 += 1
        if occ_x is not None and ww is not None and abs((bt - occ_x) - ww) > 0.011: e2 += 1
        cand = [v for v in (ww, inn) if v is not None]
        if cand and fin is not None and abs(min(cand) - fin) > 0.011: e3 += 1
    chk("W_pass = road_bt − 횡점유중앙 (불일치 행)", e1, 0)
    chk("W_worst = road_bt − 횡점유최대 (불일치 행)", e2, 0)
    chk("최종채택 = min(W_worst, 내접폭차감) (불일치 행)", e3, 0)

    print("\n[4] 밴드 판정 임계 (BLOCKED ≤ 2.5 < CONDITIONAL_C ≤ 3.5)")
    b1 = sum(1 for r in p37 if (num(r["최종채택(m)"]) or 9) >= 2.5 and r["판정(최종채택)"] == "BLOCKED")
    b2 = sum(1 for r in p37 if (num(r["최종채택(m)"]) or 9) < 2.5 and "통과후보" in r["판정(최종채택)"])
    chk("최종채택 ≥ 2.5 인데 BLOCKED", b1, 0)
    chk("최종채택 < 2.5 인데 통과후보", b2, 0)

    print("\n[5] AI 차감의 기여 — 본문 「37조각 중 7조각」·「21조각」")
    dn = [r for r in p37 if r["판정변화"].strip() == "강등"]
    zero = [r for r in dn if not int(r["확정차량수"] or 0)]
    veh = [r for r in dn if int(r["확정차량수"] or 0)]
    chk("판정변화=강등 전체", len(dn), 10)
    chk("  그중 확정차량 0 (road_bt 대입 강등)", len(zero), 3)
    chk("  그중 확정차량>0 = 본문 값", len(veh), 7)
    tr = collections.Counter(f'{r["기존판정(내접폭)"]}→{r["판정(최종채택)"]}' for r in veh)
    chk("  전이 통과후보→BLOCKED", tr["폭축_통과후보→BLOCKED"], 4)
    chk("  전이 통과후보→CONDITIONAL_C", tr["폭축_통과후보→CONDITIONAL_C"], 2)
    chk("  전이 CONDITIONAL_C→BLOCKED", tr["CONDITIONAL_C→BLOCKED"], 1)
    dec = [r for r in p37 if r["채택근거(둘중작은값)"].startswith("W_worst") and int(r["확정차량수"] or 0)]
    chk("AI 차감값이 최종값을 결정한 조각", len(dec), 21)

    print("\n[6] 내접폭 산출 / 미산출")
    have = sum(1 for r in inner if num(r["내접폭 최소(m)"]) is not None)
    chk("내접폭 산출", have, 33)
    chk("내접폭 미산출", len(inner) - have, 4)

    print("\n[7] 사람 판독 예비 대조")
    cmpable = [r for r in human if r["차이"].strip() != "대조 불가"]
    chk("대조 가능 조각", len(cmpable), 9)
    chk("대수 일치", sum(1 for r in cmpable if r["차이"].strip() == "0"), 5)

    print("\n[8] 민감도")
    inv = [float(r["판정 불변율(%)"]) for r in buf]
    chk("버퍼 폭 0.8~1.2배 판정 불변율 최솟값", min(inv), 86.5)
    chk("버퍼 폭 판정 불변율 최댓값", max(inv), 100.0)
    chk("규격 선험 ±10 % 판정 불변율 최솟값", min(float(r["판정 불변율(%)"]) for r in spec), 89.2)

    print("\n[9] 전국 도로명 포함률")
    tot_n = [r for r in nat if "전국" in (r.get("시도") or "")][0]
    names, inc = int(tot_n["이름수"]), int(tot_n["포함"])
    chk("전국 이름 수", names, 152944)
    chk("전국 포함", inc, 33336)
    chk("미포함률(%) = 1 − 포함/이름수", round((1 - inc / names) * 100, 1), 78.2)

    print("\n[10] 26개소 ↔ 37조각 구조")
    chk("대표표 개소 수", len(s26), 26)
    chk("대표표 조각 수 합", sum(int(r["조각"]) for r in s26), 37)

    print("\n[11] 파일 간 조각 키 일치")
    base = set(r["조각"] for r in p37)
    for f, col in [("경사_26개소.csv", "조각"), ("도로경계내접폭_26개소.csv", "조각"),
                   ("보행약자축_26개소.csv", "조각"), ("차종투입판정_26개소.csv", "조각")]:
        ks = set(r[col] for r in rd(f))
        chk(f"{f} 키 차집합", len(ks ^ base), 0)

    print("\n" + "=" * 62)
    print(f"통과 {len(OK)} · 실패 {len(FAIL)}")
    if FAIL:
        print("\n실패 항목:")
        for l, g, w in FAIL:
            print(f"  - {l}: 계산 {g} / 주장 {w}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
