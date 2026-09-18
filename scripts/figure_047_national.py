"""047 §2 — 전국 16개 시도 포함 범위 밖 비율 가로 막대(새 계산 없음 · 산출물 CSV 그대로 그린다).

입력: deliverables/전국대조군_길번길포함률.csv (미포함률 · 포함률95CI)
출력: figures/도표0_전국16시도_포함범위밖.png
"""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "deliverables/전국대조군_길번길포함률.csv"
OUT = ROOT / "figures/도표0_전국16시도_포함범위밖.png"
font_manager.fontManager.addfont("C:/Windows/Fonts/malgun.ttf")
font_manager.fontManager.addfont("C:/Windows/Fonts/malgunbd.ttf")
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False
INK, INK2, MUTED, BAR = "#1A1C1E", "#44474A", "#8A8F94", "#3B5B7A"
SHORT = {"부산광역시": "부산", "서울특별시": "서울", "충청남도": "충남", "인천광역시": "인천", "경상북도": "경북",
         "대전광역시": "대전", "세종특별자치시": "세종", "경상남도": "경남", "충청북도": "충북", "제주특별자치도": "제주",
         "전북특별자치도": "전북", "강원특별자치도": "강원", "전남광주통합특별시": "전남광주", "경기도": "경기",
         "대구광역시": "대구", "울산광역시": "울산"}


def main():
    rows = list(csv.DictReader(SRC.open(encoding="utf-8-sig")))
    total = next(r for r in rows if r["시도"] == "전국(합산)")
    sido = [r for r in rows if r["시도"] in SHORT]
    sido.sort(key=lambda r: -float(r["미포함률"]))           # 내림차순(CSV 순서와 같다)
    names = [SHORT[r["시도"]] for r in sido]
    # 비율은 CSV 의 개수(이름수·포함)에서 낸다 — 4자리 반올림값을 다시 반올림하지 않기 위해(새 계산 아님)
    vals = [(int(r["이름수"]) - int(r["포함"])) / int(r["이름수"]) * 100 for r in sido]
    lo, hi = [], []
    for r, v in zip(sido, vals):
        a, b = (float(x) for x in r["포함률95CI"].strip("[]").split(","))
        lo.append(v - (1 - b) * 100)          # 미포함률 CI = 1 − 포함률 CI
        hi.append((1 - a) * 100 - v)
    tot = (int(total["이름수"]) - int(total["포함"])) / int(total["이름수"]) * 100

    fig, ax = plt.subplots(figsize=(165 / 25.4, 72 / 25.4), dpi=300)
    y = list(range(len(names)))[::-1]
    ax.barh(y, vals, height=0.62, color=BAR, edgecolor="none", zorder=2)
    ax.errorbar(vals, y, xerr=[lo, hi], fmt="none", ecolor=INK, elinewidth=0.6, capsize=1.6, zorder=3)
    for yy, v in zip(y, vals):                   # 값은 막대 오른쪽 고정 열 — 기준선과 겹치지 않게
        ax.text(101.5, yy, f"{v:.1f}", va="center", ha="left", fontsize=6.6, color=INK, clip_on=False)
    ax.axvline(tot, color=INK, lw=0.9, ls=(0, (4, 2.5)), zorder=4)
    ax.text(tot - 1.2, len(names) - 0.25, f"전국 합산 {tot:.1f} %", ha="right", va="bottom", fontsize=7.0, color=INK,
            fontweight="bold")
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=7.0, color=INK)
    ax.set_xlim(0, 100)
    ax.set_ylim(-0.7, len(names) + 0.6)
    ax.text(101.5, len(names) - 0.25, "%", ha="left", va="bottom", fontsize=6.6, color=INK2, clip_on=False)
    ax.set_xticks(range(0, 101, 20))
    ax.set_xticklabels([f"{t}" for t in range(0, 101, 20)], fontsize=6.6, color=INK2)
    ax.set_xlabel("골목 도로명(길·번길) 중 국가 표준 도로망 포함 범위 밖 비율 (%) · 오차막대 95 % CI", fontsize=6.8, color=INK2)
    ax.grid(axis="x", color="#D9DCDF", lw=0.5, zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
        ax.spines[side].set_linewidth(0.6)
    ax.tick_params(length=2, width=0.5, color=MUTED)
    fig.tight_layout(pad=0.3)
    fig.savefig(OUT, facecolor="white")
    plt.close(fig)
    print(OUT, {n: round(v, 2) for n, v in zip(names, vals)}, "합산", round(tot, 2))


if __name__ == "__main__":
    main()
