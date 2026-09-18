"""004 §8 — 도표 4(2안 대 3안 간트 + 지연 장부) · 도표 6(SOP 200 3.1 5개 조건 판정/보류).

입력: data/vworld/national/derived/slot_itaewon_arm{2,3}.json · _gantt.csv · arm3_candidates.csv
출력(로컬 전용): figures/도표4_2안대3안_간트장부.png · 도표6_SOP조건_판정보류.png + Downloads/브이월드_공모전 사본
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"
FIG = ROOT / "figures"
OUTDIR = Path.home() / "Downloads" / "브이월드_공모전"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#d9d9d6", "#fcfcfb"
BLUE, ORANGE, GREEN, GRAY, PURPLE = "#1864AB", "#D9480F", "#2b8a3e", "#8f8f8a", "#6741d9"


def save(fig, name):
    FIG.mkdir(parents=True, exist_ok=True)
    out = FIG / name
    fig.savefig(out, facecolor=SURF, dpi=170)
    plt.close(fig)
    OUTDIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out, OUTDIR / name)
    print(name)


def cell(ax, x, y, fc, text, tc="white"):
    ax.add_patch(plt.Rectangle((x - 0.46, y - 0.4), 0.92, 0.8, fc=fc, ec=SURF, lw=2))
    if text:
        ax.text(x, y, text, ha="center", va="center", color=tc, fontsize=9.2, fontweight="bold")


def gantt_arm2(ax, links, g2):
    d = g2[g2.phase == "after"]
    for yi, lk in enumerate(links):
        for s in range(6):
            c = d[(d.link_id == lk) & (d.slot == s)]
            if c.empty:
                cell(ax, s, yi, SURF, "")
                ax.add_patch(plt.Rectangle((s - 0.46, yi - 0.4), 0.92, 0.8, fc="none", ec=GRID, lw=0.8))
                continue
            evac = "E0_evac" in c.actors.iloc[0]
            cell(ax, s, yi, GREEN if evac else BLUE, f"{int(c.demand.iloc[0])}/{int(c.lanes.iloc[0])}")


def gantt_arm3(ax, links, g3):
    for yi, lk in enumerate(links):
        for s in range(6):
            c = g3[(g3.link_id == lk) & (g3.slot == s)]
            if c.empty or (int(c.occupied.iloc[0]) == 0 and not bool(c.evac_zero.iloc[0])):
                ax.add_patch(plt.Rectangle((s - 0.46, yi - 0.4), 0.92, 0.8, fc="none", ec=GRID, lw=0.8))
                continue
            if bool(c.evac_zero.iloc[0]) and int(c.occupied.iloc[0]) == 0:
                cell(ax, s, yi, GREEN, "대피")
                continue
            role = c.role.iloc[0]
            fc = {"전개": ORANGE, "대기": PURPLE}.get(role, BLUE)
            cell(ax, s, yi, fc, f"{int(c.occupied.iloc[0])}/{int(c.lanes.iloc[0])}")


def style(ax, links, labels, title):
    ax.set_xlim(-0.5, 5.5)
    ax.set_ylim(-0.5, len(links) - 0.5)
    ax.invert_yaxis()
    ax.set_yticks(range(len(links)), labels, fontsize=8.8, color=INK2)
    ax.set_xticks(range(6), [f"t{s}" for s in range(6)], fontsize=9.2, color=INK2)
    ax.set_title(title, loc="left", fontsize=11.3, color=INK)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0)


def fig4():
    """2안 대 3안 간트 + 지연 장부(2안 · 3안 합성 · 3안+관측 입력 B2·B3·B1). 인쇄 폭 150~160 mm 에 맞춰 가로:세로 ≈ 1:1."""
    a2 = json.loads((DER / "slot_itaewon_arm2.json").read_text(encoding="utf-8"))
    a3 = json.loads((DER / "slot_itaewon_arm3.json").read_text(encoding="utf-8"))
    ao = json.loads((DER / "slot_itaewon_arm3_b2_b3h20_b1.json").read_text(encoding="utf-8"))
    g2 = pd.read_csv(DER / "slot_itaewon_arm2_gantt.csv", dtype={"link_id": str})
    g3 = pd.read_csv(DER / "slot_itaewon_arm3_gantt.csv", dtype={"link_id": str})
    deploy = a3["pump"]["deploy_link"]
    staging = [s_["staging_link"] for s_ in a3["ambulances"]["staging"]]
    bottleneck = a2["gantt_top_links"]
    links = bottleneck + [deploy] + staging
    labels = [f"진입{i+1}" for i in range(len(bottleneck))] + ["사건"] + [f"대기{i+1}" for i in range(len(staging))]
    fig = plt.figure(figsize=(6.7, 6.8))
    gs = fig.add_gridspec(3, 2, height_ratios=[0.78, 0.86, 0.36], hspace=0.16, wspace=0.16)
    ax1, ax2 = fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1])
    gantt_arm2(ax1, links, g2)
    gantt_arm3(ax2, links, g3)
    style(ax1, links, labels, "2안 — 지휘관 확인 2건")
    style(ax2, links, labels, "3안 — SOP 200 3.1 적용")
    ax2.set_yticklabels([])
    d2, d3, do = a2["delay_min"], a3["delay_min"], ao["delay_min"]
    amb2 = sorted(v for k, v in d2["by_actor"].items() if k.startswith("A") and v is not None)
    ev = ao["recompute"]["events"][0]
    b2 = ao["observed_inputs"]["b2"]["selected"][0]
    b1 = ao["observed_inputs"]["b1"]
    b3 = ao["observed_inputs"]["b3"]
    rows = [
        ["총지연 · 최대 개인", f"{d2['total']} · {d2['max_individual']}분 ※1", f"{d3['total']} · {d3['max_individual']}분", f"{do['total']} · {do['max_individual']}분"],
        ["미해소", f"{len(a2['unresolved'])}대", f"{len(a3['unresolved'])}대 ※2", f"{len(ao['unresolved'])}대 ※2"],
        ["펌프차 진입", f"+{a3['pump_entry_change']['arm2_delay_min']}분", f"+{a3['pump_entry_change']['arm3_delay_min']}분(R1)", f"+{ao['pump']['delay_min']}분(R1)"],
        ["구급차 · 대기", " · ".join(map(str, amb2)) + "분 · 없음", " · ".join(map(str, a3["ambulances"]["delay_distribution_min"])) + "분 · 대기 3",
         " · ".join(map(str, ao["ambulances"]["delay_distribution_min"])) + "분 · 대기 3"],
        ["재계산 트리거", "합성", f"합성 → 범위 안 {len(a3['recompute']['records_in_scope'])}건", f"돌발 기록 → 범위 안 {len(ev['records_in_scope'])}건 ※3"],
        ["대피 점유 칸", "2칸(가정)", "2칸(가정)", f"{ao['evac_slots']}칸 ※4"],
        ["일반차량 칸 용량", "차로수", "차로수", f"속도 보정 ※5"],
    ]
    ax = fig.add_subplot(gs[1, :]); ax.axis("off")
    t = ax.table(cellText=rows, colLabels=["지연 장부", "2안", "3안(합성)", "3안+관측 입력"], loc="upper center", cellLoc="left",
                 colWidths=[0.22, 0.22, 0.25, 0.31])
    t.auto_set_font_size(False); t.set_fontsize(8.9); t.scale(1, 1.62)
    for (r, c), k in t.get_celld().items():
        k.set_edgecolor(GRID)
        if r == 0:
            k.set_facecolor("#eeeeec"); k.set_text_props(fontweight="bold")
    axn = fig.add_subplot(gs[2, :]); axn.axis("off")
    note = ("※1 차량 ID 동점 처리 결과(현장 우선순위 규칙 아님)  ※2 일반차량 — 대피 점유·긴급차량 동시 진입, 대기 점유가 원인 아님\n"
            f"※3 국가교통정보센터 돌발 {b2['돌발일시'][:10]} {b2['도로명']} 링크 {b2['링크아이디']} — 단일 링크 이벤트(통제 구간 아님), 칸 대응 t2\n"
            f"※4 서울 생활인구 이태원1·2동 {b3['hour_used']}시 상대값 {b3['r_used']:.2f}(시간 분포만, 등급 C)  "
            f"※5 교통소통 5분 속도 {b1['links_with_speed']}/{b1['area_links']} 링크\n"
            f"진입1~4 = {', '.join(bottleneck)} · 사건 = {deploy}\n"
            f"대기1~3 = {', '.join(staging)} · 칸 숫자 = 점유 대수/편도 차로수\n"
            "칸 색(3주체) = 소방차량: 파랑 진입 · 주황 전개 · 보라 대기 / 보행자: 초록 대피 / 일반차량: 통행(표시 구간에 칸 없음)\n"
            "일반차량 수요 규모는 시나리오 파라미터(운영 실적 아님) · 관측 입력 연결 후에도 지연·미해소 값은 같음")
    axn.text(0, 1.0, note, fontsize=7.6, color=INK2, va="top", linespacing=1.5)
    fig.subplots_adjust(left=0.1, right=0.98, top=0.965, bottom=0.03)
    save(fig, "도표4_2안대3안_간트장부.png")


def fig6():
    a3 = json.loads((DER / "slot_itaewon_arm3.json").read_text(encoding="utf-8"))
    st = a3["ambulances"]["staging"]
    dist = " · ".join(f"{s_['hydrant_dist_m']} m" for s_ in st)
    rows = [
        ("보류 D", "회차에 용이한 장소 (3.1.2.1)", "회전 기하 + 가용 폭 · 표준노드링크에 폭 속성 없음", f"대기 {len(st)}건 전부 잠금 기록 — 지휘관 확인 필요"),
        ("판정", "소화전 인근 (3.1.2.1)", "최근접 소방용수까지 거리 최소 · 서울 소방용수시설(2025-12-31)", f"선정 대기 링크 {dist}"),
        ("판정", "선착대 퇴각에 장애 없음 (3.1.2.1)", "펌프차 진입·전개 링크와 겹치지 않음 · 진입 링크", "필터 적용"),
        ("부분 C", "특수 소방차량 진입에 장애 없음 (3.1.2.1)", "대기 후 잔여 차로 1 이상 · 편도 차로수(폭 없음)", "차로 수로만 판정 — 차로 폭 미확인"),
        ("부분 C", "후착대 배치 공간 고려 (3.1.1.1)", "선착 전개가 후착 공간 미잠식 · 진입 링크 + 차로수", "차로 수로만 판정 — 공간 폭 미확인"),
    ]
    color = {"판정": BLUE, "부분 C": "#b08900", "보류 D": INK}
    fig, ax = plt.subplots(figsize=(6.7, 6.4))
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0, 0.99, "SOP 200 제3장 3.1 배치 조건 — 되는 것과 안 되는 것", fontsize=12, fontweight="bold", color=INK, va="top")
    ax.text(0, 0.935, "소방청, 재난현장 표준작전절차, 2026.5 · 3.1 단서 「특별한 사정이 있는 경우에는\n현장 상황에 맞게 배치할 수 있다」 → 엔진은 지휘관 판단의 입력", fontsize=8.6, color=INK2, va="top", linespacing=1.4)
    for i, (status, name, rule, res) in enumerate(rows):
        y = 0.79 - i * 0.155
        ax.add_patch(plt.Rectangle((0, y - 0.03), 0.13, 0.06, fc=color[status], ec="none"))
        ax.text(0.065, y, status, fontsize=9.5, color="white", ha="center", va="center", fontweight="bold")
        ax.text(0.16, y + 0.012, name, fontsize=10, color=INK, va="center", fontweight="bold")
        ax.text(0.16, y - 0.035, rule, fontsize=8.6, color=INK2, va="center")
        ax.text(0.16, y - 0.075, "→ " + res, fontsize=8.8, color=INK, va="center")
        ax.plot([0, 1], [y - 0.105, y - 0.105], color=GRID, lw=0.7)
    ax.text(0.5, 0.005, "판정 2 · 부분(C) 2 · 보류(D) 1 — 「회차에 용이한 장소」를 판정할 폭이 없다",
            ha="center", fontsize=10, fontweight="bold", color=INK)
    fig.subplots_adjust(left=0.04, right=0.98, top=0.97, bottom=0.03)
    save(fig, "도표6_SOP조건_판정보류.png")


def fig3():
    """도표 3 — 판정 재료 결측(§4-1 수치만)."""
    items = [("도로 폭 속성", 0.0, "필드 자체 없음 · 0%"),
             ("높이 제한값 명시", 1.81, "1.81%"),
             ("높이 재료 합산 상한", 2.64, "최대 2.64%"),
             ("교량 하부통과제한높이", 100 - 83.9, "빈칸 83.9%")]
    fig, ax = plt.subplots(figsize=(6.7, 4.2))
    ys = list(range(len(items)))[::-1]
    for y, (lab, v, txt) in zip(ys, items):
        ax.barh(y, 100, color="#ecebe8", height=0.55)
        ax.barh(y, v, color=BLUE, height=0.55)
        ax.text(max(v, 0) + 1.5, y, txt, va="center", fontsize=10.5, color=INK, fontweight="bold")
    ax.set_yticks(ys, [i[0] for i in items], fontsize=10, color=INK)
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 50, 100], ["0%", "50%", "100%"], fontsize=9, color=INK2)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.set_title("통과 판정 재료가 국가 표준 데이터에 얼마나 있는가", loc="left", fontsize=11.5, fontweight="bold", color=INK)
    fig.text(0.02, 0.115, "폭·높이 명시: 표준노드링크 1,562,356 링크(높이는 편도 1차로 1,133,588 기준) · 2026-09-14\n"
             "교량: 표준데이터 35,593건 · 터널 3,840건에는 통과높이 항목 자체 없음 · 20251231판\n"
             "REST_H 값 0 이 97.43% — 제한 없음·미조사 구분 불가 · 합산 상한은 교량 위 링크 포함",
             fontsize=8.2, color=INK2, linespacing=1.45)
    fig.text(0.5, 0.02, "차가 어디로 가는가는 담지만, 지나갈 수 있는가는 담지 않는다", ha="center", fontsize=10.2, fontweight="bold", color=INK)
    fig.subplots_adjust(left=0.3, right=0.96, top=0.9, bottom=0.34)
    save(fig, "도표3_판정재료_결측.png")


if __name__ == "__main__":
    plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False})
    fig3()
    fig4()
    fig6()
