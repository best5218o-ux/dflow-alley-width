"""D-001 §8-3 1단 — 골목 판정 가능성 결측 전수 집계.

입력(전량, 손에 있는 것만)
- 표준노드링크 MOCT_LINK 1,562,356 (2026-09-14)
- 교량 표준데이터 35,593 / 터널 표준데이터 3,840 (기준일 2025-12-31)
- 대상지 시드: 브이월드 검색 API(type=district) 동 대표점 — vworld_probe.json 에서 읽는다(키 불요)

정의(전부 표준노드링크 속성만으로 판정 — 추정으로 채우지 않는다)
- LANES == 1: 「편도 1차로 링크」. 표준노드링크는 양방향 도로를 방향별 링크 2개로 담는다(lanes_direction_check.py —
  대상 구 4곳 LANES=1 의 98.5~99.7% 가 같은 이름·반대 방향 짝 보유, 짝 간격 중앙값 12 m).
  → 왕복 2차로 일반도로도 포함하므로 「골목」 프록시가 아니다. 개수·연장은 방향별로 이중 계수된다.
- 폭 재료: 표준노드링크에 도로 폭 속성이 **없다**(REST_W 는 통행제한 폭). → 폭 판정 재료는 구조적으로 0.
  REST_W > 0 는 「통행제한 폭이 명시된 링크」로만 센다.
- 높이 재료: REST_H > 0 (명시) / REST_H == 0 (제한 없음·미조사 구분 불가) / 빈칸.
- 교량 결부: 교량 시점–종점 선분 15 m 버퍼와 교차하는 링크. 다리 **위** 링크와 **아래** 링크를 구분하지 못한다
  (높이값 없음) → 「교량 선형 근접」으로만 부르고, 그 교량의 `하부통과제한높이` 값 유무를 센다.
- 터널 결부: 터널 선분 15 m 버퍼 교차. 터널에는 통과제한높이 컬럼이 없다(터널높이만).
- 좌표 이상: 위도 33–39, 경도 124–132 밖 교량·터널은 결부에서 제외하고 건수를 적는다.

출력: data/vworld/national/derived/alley_census.json · figures/*.png
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
SHP = ROOT / "data/vworld/national/raw/NODELINKDATA_20260914/MOCT_LINK.shp"
RAW = ROOT / "data/vworld/national/raw"
PROBE = ROOT / "data/vworld/national/derived/vworld_probe.json"
OUT = ROOT / "data/vworld/national/derived/alley_census.json"
FIG = ROOT / "figures"
BUF = 15.0
R_WIN = 500.0

rng = lambda a, b: [str(i) for i in range(a, b + 1)]  # noqa: E731
SCOPES = [  # (라벨, 수준, 권역코드 목록 | None)
    ("전국", "national", None),
    ("서울특별시", "city", rng(100, 124)),
    ("부산광역시", "city", rng(130, 145)),
    ("대전광역시", "city", rng(183, 187)),
    ("청주시", "city", ["270", "271", "283", "284"]),
    ("서울 용산구", "district", ["102"]),
    ("부산 동구", "district", ["132"]),
    ("대전 서구", "district", ["185"]),
    ("청주 청원구", "district", ["284"]),
]
TARGETS = [  # (라벨, vworld_probe search_district 키) — PM 확정 대상지 (§8-2)
    ("서울 이태원동", "서울 용산구 이태원동"),
    ("부산 초량동", "부산 동구 초량동"),
    ("대전 변동", "대전 서구 변동"),
    ("청주 내덕동", "청주 청원구 내덕동"),
]


def load_structures(tr) -> tuple[gpd.GeoDataFrame, dict]:
    notes = {}
    frames = []
    for kind, fname, la, lo, la2, lo2, hcol in [
        ("bridge", "국토교통부_전국교량표준데이터_20251231.csv", "교량시작점위도", "교량시작점경도", "교량종료점위도", "교량종료점경도", "하부통과제한높이"),
        ("tunnel", "국토교통부_전국도로터널정보표준데이터_20251231.csv", "터널시작점위도", "터널시작점경도", "터널종료점위도", "터널종료점경도", None),
    ]:
        df = pd.read_csv(RAW / fname, encoding="utf-8-sig", dtype=str)
        c = df[[la, lo, la2, lo2]].apply(pd.to_numeric, errors="coerce")
        ok = c[la].between(33, 39) & c[lo].between(124, 132) & c[la2].between(33, 39) & c[lo2].between(124, 132)
        notes[kind] = {"rows": len(df), "bad_coords_excluded": int((~ok).sum())}
        df, c = df[ok], c[ok]
        x1, y1 = tr.transform(c[lo].values, c[la].values)
        x2, y2 = tr.transform(c[lo2].values, c[la2].values)
        geom = shapely.linestrings(np.stack([np.stack([x1, y1], 1), np.stack([x2, y2], 1)], 1))
        hv = pd.to_numeric(df[hcol], errors="coerce") if hcol else pd.Series(np.nan, index=df.index)
        frames.append(gpd.GeoDataFrame({"kind": kind, "clear_h_value": (hv > 0).values},
                                       geometry=shapely.buffer(geom, BUF), crs=5186))
    return pd.concat(frames, ignore_index=True), notes


def metrics(sub: pd.DataFrame) -> dict:
    n = len(sub)
    l1 = sub[sub.lanes == 1]
    m = len(l1)
    pct = lambda k, d: round(100 * k / d, 2) if d else None  # noqa: E731
    return {
        "links": n, "l1_links": m, "l1_share_pct": pct(m, n),
        "l1_length_km": round(float(l1.length_m.sum()) / 1000, 1),
        "l1_width_attr_pct": 0.0,  # 속성 부재 — 계산값이 아니라 스키마 사실
        "l1_rest_w_pos_pct": pct(int((l1.rest_w > 0).sum()), m),
        "l1_rest_h_pos_pct": pct(int((l1.rest_h > 0).sum()), m),
        "l1_rest_h_zero_pct": pct(int((l1.rest_h == 0).sum()), m),
        "l1_rest_h_null_pct": pct(int(l1.rest_h.isna().sum()), m),
        "l1_near_bridge": int(l1.near_bridge.sum()),
        "l1_near_bridge_with_clear_h": int(l1.bridge_h.sum()),
        "l1_near_tunnel": int(l1.near_tunnel.sum()),
        "l1_height_evidence_pct": pct(int(((l1.rest_h > 0) | l1.bridge_h).sum()), m),
        "l2plus_rest_h_pos_pct": pct(int((sub[sub.lanes >= 2].rest_h > 0).sum()), int((sub.lanes >= 2).sum())),
    }


def main():
    tr = Transformer.from_crs(4326, 5186, always_xy=True)
    g = pyogrio.read_dataframe(SHP, columns=["LINK_ID", "LANES", "REST_W", "REST_H", "LENGTH"])
    g = g.set_crs(5186, allow_override=True)
    g["p3"] = g.LINK_ID.str[:3]
    g["lanes"] = pd.to_numeric(g.LANES, errors="coerce")
    g["rest_w"] = pd.to_numeric(g.REST_W, errors="coerce")
    g["rest_h"] = pd.to_numeric(g.REST_H, errors="coerce")
    g["length_m"] = pd.to_numeric(g.LENGTH, errors="coerce")

    st, st_notes = load_structures(tr)
    j = gpd.sjoin(g[["geometry"]], st, predicate="intersects", how="inner")
    agg = j.groupby(level=0).agg(near_bridge=("kind", lambda s: (s == "bridge").any()),
                                 near_tunnel=("kind", lambda s: (s == "tunnel").any()),
                                 bridge_h=("clear_h_value", "any"))
    g = g.join(agg)
    for c in ("near_bridge", "near_tunnel", "bridge_h"):
        g[c] = g[c].fillna(False).astype(bool)

    res = {"inputs": {"nodelink": SHP.name, "structures": st_notes, "buffer_m": BUF, "window_radius_m": R_WIN},
           "scopes": {}, "targets": {}}
    for label, level, pre in SCOPES:
        sub = g if pre is None else g[g.p3.isin(pre)]
        res["scopes"][label] = {"level": level, "prefixes": pre, **metrics(sub)}

    probe = json.loads(PROBE.read_text(encoding="utf-8"))["items"]["4_geocoder"]["search_district"]
    b = shapely.bounds(g.geometry.values)
    mx, my = (b[:, 0] + b[:, 2]) / 2, (b[:, 1] + b[:, 3]) / 2
    for label, key in TARGETS:
        cand = probe[key]["candidates"][0]
        x, y = tr.transform(*cand["point"])
        win = g[np.hypot(mx - x, my - y) <= R_WIN]
        res["targets"][label] = {"seed_source": "브이월드 검색 API type=district 동 대표점", "seed_title": cand["title"],
                                 "seed_lonlat": cand["point"], "seed_5186": [round(x, 1), round(y, 1)], **metrics(win)}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in {**res["scopes"], **res["targets"]}.items():
        print(k, {x: v[x] for x in ("links", "l1_links", "l1_share_pct", "l1_length_km", "l1_rest_h_pos_pct",
                                    "l1_rest_h_zero_pct", "l1_near_bridge", "l1_near_bridge_with_clear_h",
                                    "l1_height_evidence_pct", "l2plus_rest_h_pos_pct")})
    print(st_notes)
    figures(g, res, tr)


def figures(g, res, tr):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False, "font.size": 9})
    INK, INK2, GRID = "#0b0b0b", "#52514e", "#c9c9c7"
    BLUE, ORANGE = "#1864AB", "#D9480F"
    FIG.mkdir(parents=True, exist_ok=True)

    # 도표 A — 대상지 4곳 결측 지도(같은 축척)
    half = 700
    fig, axes = plt.subplots(2, 2, figsize=(8.2, 8.6), dpi=200)
    for ax, (label, t) in zip(axes.flat, res["targets"].items()):
        x, y = t["seed_5186"]
        box = shapely.box(x - half, y - half, x + half, y + half)
        w = g[g.intersects(box)]
        other = w[w.lanes != 1]
        l1 = w[w.lanes == 1]
        has_h = l1[(l1.rest_h > 0) | l1.bridge_h]
        no_h = l1[~((l1.rest_h > 0) | l1.bridge_h)]
        other.plot(ax=ax, color=GRID, linewidth=0.8)
        no_h.plot(ax=ax, color=ORANGE, linewidth=1.6)
        if len(has_h):
            has_h.plot(ax=ax, color=BLUE, linewidth=2.4, linestyle=(0, (1, 1)))
        circ = shapely.Point(x, y).buffer(R_WIN)
        ax.plot(*circ.exterior.xy, color=INK2, linewidth=0.7, linestyle="--")
        ax.set_xlim(x - half, x + half); ax.set_ylim(y - half, y + half)
        ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color(GRID)
        ax.set_title(f"{label}  —  편도1차로 링크 {t['l1_links']}/{t['links']} · 높이 재료 {t['l1_height_evidence_pct']}%",
                     color=INK, fontsize=9.5, loc="left")
        # 축척바 500 m + 방위표
        x0, y0 = x - half + 60, y - half + 70
        ax.plot([x0, x0 + 500], [y0, y0], color=INK, linewidth=2)
        ax.text(x0 + 250, y0 + 25, "500 m", ha="center", va="bottom", color=INK, fontsize=8)
        ax.annotate("N", xy=(x + half - 70, y + half - 60), xytext=(x + half - 70, y + half - 200),
                    ha="center", color=INK, fontsize=9, arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.2))
    handles = [Line2D([], [], color=ORANGE, lw=1.6, label="편도 1차로 링크(LANES=1) — 폭·높이 판정 재료 없음"),
               Line2D([], [], color=BLUE, lw=2.4, ls=(0, (1, 1)), label="편도 1차로 링크 — 높이 제한값 있음(REST_H>0 또는 근접 교량 하부통과제한높이)"),
               Line2D([], [], color=GRID, lw=0.8, label="2차로 이상 링크"),
               Line2D([], [], color=INK2, lw=0.7, ls="--", label="집계 반경 500 m (브이월드 검색 API 동 대표점 중심)")]
    fig.legend(handles=handles, loc="lower center", ncol=2, frameon=False, fontsize=8, bbox_to_anchor=(0.5, 0.035))
    fig.text(0.5, 0.006, "표준노드링크에는 폭 속성이 없다 — 폭 판정 재료는 네 곳 모두 0%. 높이 재료는 교량 위 링크를 포함한 상한. 링크는 방향별(짝 간격 12 m)로 그려진다.\n"
             "자료: 국토교통부 표준노드링크(2026-09-14), 교량·터널 표준데이터(2025-12-31). 좌표계 EPSG:5186.",
             ha="center", color=INK2, fontsize=7.2)
    fig.tight_layout(rect=(0, 0.09, 1, 1))
    fig.savefig(FIG / "도표A_골목결측지도_4개도시.png")
    plt.close(fig)

    # 도표 B — 도시 비교(두 지표를 두 패널로 — 이중축 금지)
    labels = ["서울 용산구", "부산 동구", "대전 서구", "청주 청원구"]
    s = res["scopes"]
    fig, axes = plt.subplots(1, 2, figsize=(8.2, 2.9), dpi=200)
    for ax, key, title in [(axes[0], "l1_share_pct", "전체 링크 중 편도 1차로 링크 비율(%)"),
                           (axes[1], "l1_height_evidence_pct", "편도 1차로 링크 중 높이 판정 재료 보유율(%, 상한)")]:
        vals = [s[l][key] for l in labels]
        nat = s["전국"][key]
        ax.barh(labels[::-1], vals[::-1], color=ORANGE if key == "l1_share_pct" else BLUE, height=0.55)
        ax.axvline(nat, color=INK2, linewidth=1, linestyle="--")
        ax.text(nat, -0.62, f" 전국 {nat}", color=INK2, fontsize=7.5, va="bottom", ha="left")
        for i, v in enumerate(vals[::-1]):
            ax.text(v, i + 0.36, f"{v}", va="center", ha="right" if v > nat * 0.6 and abs(v - nat) < max(vals) * 0.12 else "left", color=INK, fontsize=8)
        ax.set_title(title, loc="left", color=INK, fontsize=9)
        ax.set_xlim(0, max(max(vals), nat) * 1.2 or 1)
        ax.set_ylim(-0.75, len(labels) - 0.35)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.tick_params(colors=INK2)
    fig.text(0.5, 0.01, "구 단위(표준노드링크 권역코드 102·132·185·284). 폭 판정 재료 보유율은 전 범위 0%(속성 부재).",
             ha="center", color=INK2, fontsize=7.2)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(FIG / "도표B_골목재료_도시비교.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
