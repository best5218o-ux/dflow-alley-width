"""시공간 슬롯 — 시간 축 1단계 (법정 근거만 사용)

    python scripts/slot_time_stage1.py

제출본 서식2 「미산출」 칸의 **「슬롯은 순서만 냈다(호스 연장 기준·시간 미계산)」** 를 여는 첫 단계다.

설계 원칙 — **절대 시간을 예측하지 않는다.**
  가정한 상수로 「몇 분 걸린다」를 내면 그 상수가 곧 공격 지점이 된다.
  대신 **임계값**을 낸다: 「골목이 몇 m 를 넘으면 보행 선행이 긴급차량 도착을 지연시키는가」.
  이러면 가정이 틀려도 결론이 무너지지 않고, 현장에서 확인해야 할 값을 지목하는 산출물이 된다.

1단계에서 쓰는 값은 **전부 법정·공개 근거(등급 A)** 다.
  v_ped = 1.0 m/s   도로교통법 시행규칙 보행자 신호시간 산정 기준
  E = 2.5 m         소방장비 기본규격 KFS 0008 3.3 펌프차 전폭 상한
  P = 1.2 m         편의증진법 시행규칙 별표1 1.가.(1) 보행 유효폭 원칙값
  G = 2.0 m         도로의 구조·시설 기준에 관한 규칙 제5조 소형자동차 폭
  L                 도로경계 면 안 축선 길이 — deliverables/도로경계내접폭_26개소.csv
  W                 최종채택 통행가능폭 — deliverables/통행가능폭_주차차감_37조각.csv

**진입 속도·전개 시간·호스 연장 속도는 1단계에서 쓰지 않는다.** 공개 근거가 없다(등급 C).
그것들은 2·3단계에서 범위와 민감도로 다룬다. 이 파일은 등급 A 만으로 낼 수 있는 값만 낸다.
"""
from __future__ import annotations
import csv, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
D = ROOT / "deliverables"

V_PED = 1.0   # m/s  도로교통법 시행규칙 보행신호 산정
E, P, G = 2.5, 1.2, 2.0

# 허용 대기 후보(초) — 「이 시간을 넘는 대기는 받아들일 수 없다」는 운영 판단값.
# 값 자체를 주장하지 않는다. 각 후보에 대해 임계 링크길이 L* 를 낸다.
WAIT_BUDGETS = [10, 20, 30, 60]


def rd(name):
    with (D / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def num(x):
    x = (x or "").strip()
    return None if x in ("", "-", "null") else float(x)


def main():
    length = {r["조각"]: num(r["면안축선(m)"]) for r in rd("도로경계내접폭_26개소.csv")}
    rows = []
    for r in rd("통행가능폭_주차차감_37조각.csv"):
        k = r["조각"]
        L = length.get(k)
        W = num(r["최종채택(m)"])
        if L is None or W is None:
            # 2026-09-18: 조용히 건너뛰지 않는다. 입력이 빈 조각도 행으로 남기고 사유를 적는다(fail-closed).
            miss = " · ".join(x for x in (("면안축선(m) 없음" if L is None else ""),
                                          ("최종채택(m) 없음" if W is None else "")) if x)
            rows.append({"조각": k, "도로명": r["도로명"],
                         "링크길이 L(m)": "" if L is None else f"{L:.1f}",
                         "최종채택 W(m)": "" if W is None else f"{W:.2f}",
                         "판정(폭 축)": r["판정(최종채택)"], "분리방식(폭 축)": r["분리방식"],
                         "보행 통과시간 T_ped(s)": "NOT_COMPUTED", "긴급+보행 동시통행": "UNKNOWN_FAIL_CLOSED",
                         "긴급+일반 동시통행": "UNKNOWN_FAIL_CLOSED", "보행 선행 시 긴급차량 대기(s)": "NOT_COMPUTED",
                         "속도근거": "", "폭근거": "", "근거등급": "",
                         "미산출사유": f"입력 결측 — {miss}"})
            continue
        t_ped = L / V_PED                       # 보행자 1인이 조각을 통과하는 시간
        both_ped = W >= E + P                   # 긴급차량 + 보행자 동시 통행
        both_gen = W >= E + G                   # 긴급차량 + 일반차량 동시 통행
        rows.append({
            "조각": k,
            "도로명": r["도로명"],
            "링크길이 L(m)": f"{L:.1f}",
            "최종채택 W(m)": f"{W:.2f}",
            "판정(폭 축)": r["판정(최종채택)"],
            "분리방식(폭 축)": r["분리방식"],
            "보행 통과시간 T_ped(s)": f"{t_ped:.1f}",
            "긴급+보행 동시통행": "가능" if both_ped else "불가",
            "긴급+일반 동시통행": "가능" if both_gen else "불가",
            "보행 선행 시 긴급차량 대기(s)": "0.0" if both_ped else f"{t_ped:.1f}",
            "속도근거": "v_ped=1.0 m/s 도로교통법 시행규칙 보행신호 산정",
            "폭근거": "E=2.5 KFS 0008 3.3 · P=1.2 편의증진법 별표1 · G=2.0 도로구조규칙 제5조",
            "근거등급": "A (전부 법정·공개)",
            "미산출사유": "",
        })

    out = D / "슬롯시간_26개소.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(max(rows, key=lambda x: len(x)).keys()))
        w.writeheader(); w.writerows(rows)

    calc = [r for r in rows if r["미산출사유"] == ""]
    skipped = [r for r in rows if r["미산출사유"]]
    n = len(calc)
    blocked_ped = [r for r in calc if r["긴급+보행 동시통행"] == "불가"]
    blocked_gen = [r for r in calc if r["긴급+일반 동시통행"] == "불가"]
    waits = sorted(float(r["보행 선행 시 긴급차량 대기(s)"]) for r in calc)

    print(f"산출: {out.name}  (전체 {len(rows)}조각 · 산출 {n} · 입력 결측 {len(skipped)})")
    for r in skipped:
        print(f"  결측 — {r['조각']}: {r['미산출사유']}")
    print()
    print("[동시 통행 판정 — 폭만으로 결정된다]")
    print(f"  긴급차량 + 보행자 동시 통행 불가 : {len(blocked_ped)}/{n} 조각  (W < E+P = {E+P} m)")
    print(f"  긴급차량 + 일반차량 동시 통행 불가 : {len(blocked_gen)}/{n} 조각  (W < E+G = {E+G} m)")
    print()
    print("[보행 선행 시 긴급차량이 기다리는 시간]")
    if waits:
        nz = [w for w in waits if w > 0]
        print(f"  대기 발생 조각 {len(nz)}개 · 최소 {min(nz):.1f}s · 중앙 {nz[len(nz)//2]:.1f}s · 최대 {max(nz):.1f}s")
    print()
    print("[임계 링크길이 L* — 허용 대기를 넘기는 경계]")
    print("  허용 대기를 t 초로 두면 L* = t × 1.0 m/s. 그보다 긴 조각은 순서 배정이 필요하다.")
    for t in WAIT_BUDGETS:
        Lstar = t * V_PED
        over = [r for r in blocked_ped if float(r["링크길이 L(m)"]) > Lstar]
        print(f"  허용 대기 {t:>3}s → L* = {Lstar:>5.1f} m → 순서 배정 필요 조각 {len(over):>2}/{len(blocked_ped)}")
    print()
    print("이 산출물이 주장하는 것: 「폭이 좁아 동시 통행이 불가한 조각에서, 보행 선행이")
    print("긴급차량을 몇 초 지연시키는가」 — 속도 가정 없이 법정 값만으로 계산된다.")
    print("주장하지 않는 것: 실제 출동 소요시간, 전개 시간, 호스 연장 시간(2·3단계 과제).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
