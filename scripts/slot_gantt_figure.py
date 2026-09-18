"""003 §5 C · 도표 4 — 슬롯 충돌 해소 전/후 간트 + 지연 장부 (arm 1·2 나란히).

입력: data/vworld/national/derived/slot_itaewon_arm{1,2}.json · _gantt.csv
출력(로컬 전용, .gitignore 이미지 규칙): figures/도표4_슬롯간트_이태원.png
         + C:/Users/<user>/Downloads/브이월드_공모전/ 사본(경로는 홈 기준으로 계산, 저장소에 절대경로를 남기지 않음)
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
OK, OVER, EVAC, LOCK = "#1864AB", "#D9480F", "#8f8f8a", "#52514e"


def panel(ax, g, phase, links, title):
    d = g[g.phase == phase]
    ax.set_xlim(-0.5, 5.5)
    ax.set_ylim(-0.5, len(links) - 0.5)
    for yi, lk in enumerate(links):
        for s in range(6):
            cell = d[(d.link_id == lk) & (d.slot == s)]
            if cell.empty:
                ax.add_patch(plt.Rectangle((s - 0.46, yi - 0.4), 0.92, 0.8, fc=SURF, ec=GRID, lw=0.8))
                continue
            dem, lanes = int(cell.demand.iloc[0]), int(cell.lanes.iloc[0])
            actors = cell.actors.iloc[0]
            evac = "E0_evac" in actors
            over = (dem - (1 if evac else 0)) > (0 if evac else lanes) if phase == "after" else dem > lanes
            fc = OVER if over else (EVAC if evac and dem == 1 else OK)
            ax.add_patch(plt.Rectangle((s - 0.46, yi - 0.4), 0.92, 0.8, fc=fc, ec=SURF, lw=2))
            ax.text(s, yi, f"{dem}/{lanes}", ha="center", va="center", color="white", fontsize=8, fontweight="bold")
    ax.set_yticks(range(len(links)), links, fontsize=7.5, color=INK2)
    ax.set_xticks(range(6), [f"t{s}\n+{s*10}분" for s in range(6)], fontsize=7.5, color=INK2)
    ax.set_title(title, loc="left", fontsize=9.5, color=INK)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0)


def main():
    plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False})
    a1 = json.loads((DER / "slot_itaewon_arm1.json").read_text(encoding="utf-8"))
    a2 = json.loads((DER / "slot_itaewon_arm2.json").read_text(encoding="utf-8"))
    g2 = pd.read_csv(DER / "slot_itaewon_arm2_gantt.csv", dtype={"link_id": str})
    links = a2["gantt_top_links"]
    fig = plt.figure(figsize=(8.4, 9.2), dpi=200)
    gs = fig.add_gridspec(3, 2, height_ratios=[1.05, 1.05, 1.25], hspace=0.55, wspace=0.28)
    ax1 = fig.add_subplot(gs[0, 0]); ax2 = fig.add_subplot(gs[0, 1])
    panel(ax1, g2, "before", links, "② 사람 확인 후 해제 — 해소 전(수요/차로)")
    panel(ax2, g2, "after", links, "② 해소 후 — 5단계 고정 순서")
    ax3 = fig.add_subplot(gs[1, :]); ax3.axis("off")
    ax3.set_title("① 엄격 fail-closed — 급회전 잠금(θ≥90°, 증거등급 D)", loc="left", fontsize=9.5, color=INK)
    rows1 = [[r["id"], r["status"], r.get("reason") or r.get("action") or "", "" if r.get("delay_slots") is None else f"{r['delay_slots']*10}분"] for r in a1["ledger"]]
    t1 = ax3.table(cellText=rows1, colLabels=["주체", "상태", "사유·조치", "지연"], loc="upper left", cellLoc="left", colWidths=[0.14, 0.1, 0.62, 0.1])
    t1.auto_set_font_size(False); t1.set_fontsize(7.5); t1.scale(1, 1.15)
    ax3.text(0, -0.08, f"잠긴 급회전 이동 {a1['locked_sharp_moves']}개 · 긴급차량 4대 경로 없음 → 미해소 · 공통엔진 결정기록 {len(a1['decision_records_refused'])}건 계약 거부",
             transform=ax3.transAxes, fontsize=7.8, color=INK2)
    ax4 = fig.add_subplot(gs[2, :]); ax4.axis("off")
    ax4.set_title("② 지연 장부 + t2 돌발 통제 재계산(2-hop)", loc="left", fontsize=9.5, color=INK)
    rows2 = [[r["id"], r["status"], f"t{r['slot']}", r.get("action") or r.get("reason") or "", "" if r.get("delay_slots") is None else f"{r['delay_slots']*10}분"] for r in a2["ledger"]]
    t2 = ax4.table(cellText=rows2, colLabels=["주체", "상태", "칸", "조치·사유", "지연"], loc="upper left", cellLoc="left", colWidths=[0.14, 0.1, 0.07, 0.55, 0.1])
    t2.auto_set_font_size(False); t2.set_fontsize(7.5); t2.scale(1, 1.15)
    dm = a2["delay_min"]; rc = a2["recompute"]
    ax4.text(0, -0.02, f"총지연 {dm['total']}분 · 긴급 {dm['by_kind'].get('emergency', 0)}분 · 일반 {dm['by_kind'].get('general', 0)}분 · 최대 개인 지연 {dm['max_individual']}분 · 미해소 {', '.join(a2['unresolved']) or '없음'}",
             transform=ax4.transAxes, fontsize=7.8, color=INK)
    ax4.text(0, -0.1, f"재계산: 통제 링크 {rc['trigger']['link_id']} · 2-hop {rc['two_hop_links']}링크 · 범위 안 재배정 {rc['records_reassigned_in_scope']}건 · 범위 밖 잠금 유지 {rc['records_locked_out_of_scope']}건 · "
             f"재배정 후 미해소 {sum(1 for r in rc['ledger_after'] if r['status']=='미해소')}건 · 결정 버전 → {rc['next_decision_version']}",
             transform=ax4.transAxes, fontsize=7.8, color=INK2)
    fig.text(0.5, 0.012, "시나리오 파라미터(SYNTHETIC_EVENT) — 측정값 아님 · 표준노드링크 2026-09-14 이태원동 반경 700 m · 폭 축 전 링크 D · 권고 전용(RECOMMEND_ONLY)",
             ha="center", fontsize=7.2, color=INK2)
    fig.text(0.5, 0.035, "모르는 회전은 열지 않는다 — 잠그면 경로가 사라지고, 사람이 확인한 이동만 열면 배정·지연·미해소가 장부에 남는다",
             ha="center", fontsize=8.6, color=INK, fontweight="bold")
    FIG.mkdir(parents=True, exist_ok=True)
    out = FIG / "도표4_슬롯간트_이태원.png"
    fig.savefig(out, facecolor=SURF)
    plt.close(fig)
    OUTDIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out, OUTDIR / out.name)
    print(out.name, "ok")


if __name__ == "__main__":
    main()
