"""027 §7-3 · 7-4 — 도표 2장 생성.

도표 1 지휘관 화면 — 26개소 중 연번 31(충무로68번길)의 **실제 산출값만** 얹는다.
             초는 계산하지 않았으므로 순서만 적는다(NOT_COMPUTED). RECOMMEND_ONLY 를 화면에 표기한다.
도표 2 대전 26개소 좌표화 지도 — 폭 축 판정별 색 + 모양(흑백 인쇄 대비 이중 부호화).

색은 상태(status) 팔레트다. 명도 차 + 마커 모양 + 직접 라벨로 흑백에서도 구분된다.
출력: figures/도표1_지휘관화면.png · 도표2_대전26개소_좌표화.png
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrow, FancyBboxPatch, Rectangle
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform as shp_transform

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"
FIG = ROOT / "figures"
CACHE = ROOT / "data/vworld/daejeon_gu.geojson"

font_manager.fontManager.addfont("C:/Windows/Fonts/malgun.ttf")
font_manager.fontManager.addfont("C:/Windows/Fonts/malgunbd.ttf")
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

INK, INK2, MUTED = "#1A1C1E", "#44474A", "#8A8F94"
PASS, COND, LOCK, BLOCK = "#1B7F4B", "#E8A400", "#9AA0A6", "#B3261E"
SURFACE, LINE = "#FFFFFF", "#D4D7DA"


def gu_polygons():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    key = os.environ["VWORLD_APIKEY"].strip()
    q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": "lt_c_adsigg",
         "OUTPUT": "application/json", "MAXFEATURES": "1000", "SRSNAME": "EPSG:4326",
         "BBOX": "36.15,127.25,36.50,127.60,EPSG:4326", "key": key, "domain": os.environ.get("VWORLD_DOMAIN", "localhost")}
    url = "https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode(q)
    j = json.loads(urllib.request.urlopen(url, timeout=90).read().decode("utf-8", "replace"))
    feats = [f for f in j["features"] if str(f["properties"].get("sig_cd", "")).startswith("30")]
    out = {"type": "FeatureCollection", "features": feats}
    CACHE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def ortho_patch(lon, lat, half_m=58.0):
    """브이월드 항공정사영상 조각과 그 위에 얹을 실제 선형(도로명주소 도로구간). 영상은 배경이고 판정 근거가 아니다(028 §2-3)."""
    import io, math, urllib.parse, urllib.request
    from PIL import Image
    KEY = os.environ["VWORLD_APIKEY"].strip()
    Z, R = 19, 20037508.342789244
    T43 = Transformer.from_crs(4326, 3857, always_xy=True)
    CACHE_T = ROOT / "data/vworld/ortho_cache"
    CACHE_T.mkdir(parents=True, exist_ok=True)

    def tile(x, y):
        f = CACHE_T / f"sat_{Z}_{x}_{y}.jpg"
        if not f.exists():
            u = f"https://api.vworld.kr/req/wmts/1.0.0/{KEY}/Satellite/{Z}/{y}/{x}.jpeg"
            f.write_bytes(urllib.request.urlopen(urllib.request.Request(
                u, headers={"User-Agent": "D-FLOW contest"}), timeout=40).read())
        return Image.open(f).convert("RGB")

    mx, my = T43.transform(lon, lat)
    k = 1 / math.cos(math.radians(lat))
    half = half_m * k
    s = 256 * 2 ** Z / (2 * R)
    gx, gy = (mx + R) * s, (R - my) * s
    px = half * s
    tx0, ty0 = int((gx - px) // 256), int((gy - px) // 256)
    tx1, ty1 = int((gx + px) // 256), int((gy + px) // 256)
    mos = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            mos.paste(tile(tx, ty), ((tx - tx0) * 256, (ty - ty0) * 256))
    ox, oy = tx0 * 256, ty0 * 256
    img = mos.crop((int(gx - px - ox), int(gy - px - oy), int(gx + px - ox), int(gy + px - oy)))
    extent = (mx - half, mx + half, my - half, my + half)
    q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": "lt_l_sprd",
         "OUTPUT": "application/json", "MAXFEATURES": "1000", "SRSNAME": "EPSG:900913",
         "BBOX": f"{mx-half},{my-half},{mx+half},{my+half},EPSG:900913", "key": KEY, "domain": os.environ.get("VWORLD_DOMAIN", "localhost")}
    j = json.loads(urllib.request.urlopen(
        "https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode(q), timeout=60).read().decode("utf-8", "replace"))
    lines = []
    for f in j["features"]:
        nm = "".join(str(f["properties"].get("rn") or "").split())
        g = shape(f["geometry"])
        for ln in getattr(g, "geoms", [g]):
            lines.append((nm, list(ln.coords)))
    return img, extent, lines


def band_style(band: str):
    return {"BLOCKED": (BLOCK, "o", "BLOCKED"),
            "CONDITIONAL_C": (COND, "^", "CONDITIONAL_C"),
            "폭축_통과후보": (INK2, "s", "폭 축에서 배제되지 않음"),
            "UNKNOWN_FAIL_CLOSED": (LOCK, "D", "UNKNOWN_FAIL_CLOSED")}.get(band, (LOCK, "D", "UNKNOWN_FAIL_CLOSED"))


def fig_commander():
    """028 §2 — 시간 칸 중립 표기(3칸) · 링크 선 패턴 병용 · 정사영상 배경 · 겹친 글자 정리."""
    SITE = (127.42449960092145, 36.31692278758278)   # 연번 31 충무로68번길 조각 지점
    fig = plt.figure(figsize=(9.8, 5.4), dpi=190)
    fig.patch.set_facecolor(SURFACE)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 100); ax.set_ylim(0, 58); ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.6, 0.6), 98.8, 56.8, boxstyle="round,pad=0.4", fc=SURFACE, ec=LINE, lw=1.2))
    ax.text(3, 54.4, "지휘관 화면 (권고안) — 대전 연번 31 · 충무로68번길",
            fontsize=12.4, fontweight="bold", color=INK, va="center")
    ax.add_patch(FancyBboxPatch((64, 52.8), 32.4, 3.1, boxstyle="round,pad=0.22", fc="#EEF1F4", ec=LINE, lw=0.9))
    ax.text(65.4, 54.35, "authority_scope = RECOMMEND_ONLY", fontsize=9, color=INK2, va="center")
    ax.text(3, 49.6, "① 링크 상태 — 브이월드 항공정사영상 위", fontsize=10.4, fontweight="bold", color=INK)

    axm = fig.add_axes([0.055, 0.305, 0.40, 0.475])
    img, extent, lines = ortho_patch(*SITE)
    axm.imshow(img, extent=extent, origin="upper")
    drew = False
    for nm, coords in lines:
        xs = [c[0] for c in coords]; ys = [c[1] for c in coords]
        if nm == "충무로68번길":
            axm.plot(xs, ys, color="#FFFFFF", lw=7.2, ls="-", solid_capstyle="round", zorder=3)
            axm.plot(xs, ys, color=COND, lw=4.4, ls=(0, (5, 2.4)), solid_capstyle="butt", zorder=4)
            drew = True
        elif nm.endswith("대로") or nm.endswith("로"):
            axm.plot(xs, ys, color="#FFFFFF", lw=6.0, ls="-", zorder=2)
            axm.plot(xs, ys, color=INK, lw=3.0, ls="-", zorder=3)
    cx, cy = Transformer.from_crs(4326, 3857, always_xy=True).transform(*SITE)
    axm.plot([cx], [cy], marker="*", ms=15, color="#FFFFFF", markeredgecolor=INK, markeredgewidth=1.0, zorder=6)
    axm.plot([cx + 10, cx + 40], [cy - 26, cy - 50], color="#FFFFFF", lw=5.4, ls="-", zorder=3)
    axm.plot([cx + 10, cx + 40], [cy - 26, cy - 50], color="#3B4045", lw=4.0, ls=(0, (1.5, 1.7)), zorder=4)
    axm.set_xlim(extent[0], extent[1]); axm.set_ylim(extent[2], extent[3]); axm.axis("off")
    axm.text(0.03, 0.965, "충무로68번길 — 조건부 4.56 m", transform=axm.transAxes,
             fontsize=7.8, color="#FFFFFF", va="top", ha="left",
             bbox=dict(fc=COND, ec="none", alpha=0.95, pad=2.0))
    axm.text(0.97, 0.035, "회전·경사·노면·높이 미확인 → 잠금", transform=axm.transAxes,
             fontsize=7.4, color="#FFFFFF", ha="right", va="bottom",
             bbox=dict(fc="#4F5459", ec="none", alpha=0.95, pad=2.0))
    axm.text(0.97, 0.965, "★ 재난지점", transform=axm.transAxes, fontsize=7.8, color="#FFFFFF",
             ha="right", va="top", bbox=dict(fc=INK, ec="none", alpha=0.82, pad=2.0))

    # 029 §2 — 보행자 대피 흐름(권고 방향)과 충돌 칸을 영상 위에 되살린다
    PED = "#2C6BD6"
    ax0, ay0 = cx - 2, cy + 8            # 사건 링크(재난지점 옆)
    ax1, ay1 = cx - 44, cy + 38          # 큰 길(충무로) 방향
    axm.annotate("", xy=(ax1, ay1), xytext=(ax0, ay0),
                 arrowprops=dict(arrowstyle="-|>", color="#FFFFFF", lw=6.0,
                                 shrinkA=0, shrinkB=0), zorder=5)
    axm.annotate("", xy=(ax1, ay1), xytext=(ax0, ay0),
                 arrowprops=dict(arrowstyle="-|>", color=PED, lw=3.0,
                                 shrinkA=0, shrinkB=0), zorder=6)
    axm.text(0.03, 0.12, "보행자 대피 흐름 (권고 방향 · 관측값 아님)", transform=axm.transAxes,
             fontsize=7.4, color=PED, va="bottom", ha="left",
             bbox=dict(fc="#FFFFFF", ec="none", alpha=0.9, pad=1.8), zorder=7)
    # 030 §4 — 산출물에 「충돌 칸」 판정이 없어 박스를 그리지 않는다(없는 판정을 그림으로 만들지 않는다)

    ax.text(3, 16.2, "링크 상태 — 색과 선 모양을 함께 쓴다", fontsize=9.2, fontweight="bold", color=INK)
    for i, (col, sty, txt) in enumerate([(PASS, "-", "통과 근거 확인 (실선)"),
                                         (COND, (0, (5, 2.2)), "조건부 · 현장 확인 필요 (파선)"),
                                         ("#3B4045", (0, (1.5, 1.7)), "데이터 부족 — 자동판정 잠금 (점선)")]):
        y = 13.0 - i * 3.1
        ax.plot([3.6, 9.4], [y, y], color=col, lw=3.4, ls=sty, solid_capstyle="butt")
        ax.text(10.6, y, txt, fontsize=8.6, color=INK2, va="center")
    ax.text(3.6, 3.2, "이 개소에는 녹색(통과 근거 확인) 링크가 없다", fontsize=8.4, color=MUTED)

    ax.text(52, 49.6, "② 진입 순서 (시간 칸)", fontsize=10.4, fontweight="bold", color=INK)
    for i, (veh, k, what) in enumerate([("펌프차", 0, "진입 → 전개"), ("구조차", 1, "큰 길 대기 후 진입"),
                                        ("구급차", 2, "큰 길 대기 후 진입")]):
        y = 44.8 - i * 4.2
        ax.text(52, y + 1.25, veh, fontsize=9.2, color=INK, va="center")
        for c in range(3):
            x = 59.5 + c * 6.6
            ax.add_patch(FancyBboxPatch((x, y), 5.8, 2.5, boxstyle="round,pad=0.1", fc="#FFFFFF",
                                        ec=INK2 if c == k else LINE, lw=1.5 if c == k else 0.8))
            if c == k:
                ax.text(x + 2.9, y + 1.25, str(k + 1), fontsize=9.4, fontweight="bold", color=INK,
                        ha="center", va="center")
        ax.text(80.4, y + 1.25, what, fontsize=8.4, color=INK2, va="center")
    ax.text(52, 31.6, "칸은 순서다. 초는 계산하지 않았다 (seconds: NOT_COMPUTED)", fontsize=8.6, color=BLOCK)

    ax.text(52, 27.4, "③ 배치", fontsize=10.4, fontweight="bold", color=INK)
    for i, s in enumerate(["후착대 대기 위치 : 충무로(큰 길) — 펌프 통행 비간섭",
                           "전개면 : 펌프차 전개 구간(사건 링크 1차로)",
                           "최근접 소방용수 직선거리 37.3 m — 도달성은 기준 미확보"]):
        ax.text(52, 23.8 - i * 3.2, s, fontsize=8.8, color=INK if i < 2 else INK2)

    ax.text(52, 13.2, "④ 지휘관 조작", fontsize=10.4, fontweight="bold", color=INK)
    for i, (label, col) in enumerate([("승인", PASS), ("수정", COND), ("보류", LOCK)]):
        x = 52 + i * 12.2
        ax.add_patch(FancyBboxPatch((x, 6.8), 10.6, 4.0, boxstyle="round,pad=0.18", fc="#FFFFFF", ec=col, lw=1.7))
        ax.text(x + 5.3, 8.8, label, fontsize=10, color=INK, ha="center", va="center", fontweight="bold")
    ax.text(52, 4.2, "결정은 지휘관이 한다. D-FLOW 는 권고와 근거만 제시한다.", fontsize=8.8, color=INK)

    fig.savefig(FIG / "도표1_지휘관화면.png", facecolor="white", bbox_inches="tight", pad_inches=0.10)
    plt.close(fig)
    return drew


def fig_map(marker_s: float = 34.0):
    """030 §1·§2 — 왼쪽: 대전 전역 5개 구와 구별 개소 수 / 오른쪽: 개소 밀집부 확대(마커 겹침 0).

    한 장에 전역을 담으면 1 px 이 약 48 m 라 400 m 오프셋으로는 마커가 겹침을 못 벗어난다.
    그래서 전역은 구별 집계로, 개별 판정은 확대도로 나눈다. 좌표를 크게 옮기지 않기 위한 선택이다.
    """
    import math
    from shapely.geometry import Point as SPoint
    rows = json.loads((DER / "site_table_26.json").read_text(encoding="utf-8"))["rows"]
    cc = json.loads((DER / "missing_alley_crosscheck.json").read_text(encoding="utf-8"))
    pts = {}
    for s in cc["sites"]:
        q = [x for x in s["pieces"] if x["type"] == "road"]
        if q:
            pts[s["연번"]] = q[0]["point"]
    tr = Transformer.from_crs(4326, 5186, always_xy=True)
    gus = []
    for f in gu_polygons()["features"]:
        gus.append((f["properties"].get("sig_kor_nm", ""),
                    shp_transform(lambda x, y: tr.transform(x, y), shape(f["geometry"]))))

    def gu_of(pt):
        for nm, g in gus:
            if g.covers(pt):
                return nm
        return None

    raw = {r["연번"]: tr.transform(*pts[r["연번"]]) for r in rows}
    by_gu = {}
    for r in rows:
        by_gu[gu_of(SPoint(*raw[r["연번"]]))] = by_gu.get(gu_of(SPoint(*raw[r["연번"]])), 0) + 1

    fig = plt.figure(figsize=(10.6, 5.0), dpi=190)
    axA = fig.add_axes([0.015, 0.15, 0.25, 0.78])    # 전역
    axB = fig.add_axes([0.295, 0.15, 0.50, 0.78])    # 확대
    # ── A: 대전 전역, 5개 구 전부
    bx = [g.bounds for _, g in gus]
    minx, miny = min(b[0] for b in bx), min(b[1] for b in bx)
    maxx, maxy = max(b[2] for b in bx), max(b[3] for b in bx)
    axA.set_xlim(minx - 1200, maxx + 1200); axA.set_ylim(miny - 1200, maxy + 1200)
    axA.set_aspect("equal"); axA.axis("off")
    drawn = 0
    gu_label_pos = {}
    for nm, g in gus:
        for poly in getattr(g, "geoms", [g]):
            axA.plot(*poly.exterior.xy, color="#8C9196", lw=1.2, zorder=1)
        drawn += 1
        c = g.representative_point()
        n = by_gu.get(nm, 0)
        lx, ly = c.x, c.y
        gu_label_pos[nm] = (lx, ly)
        axA.text(lx, ly, nm + chr(10) + f"{n}개소", fontsize=9.0, color=INK if n else MUTED,
                 ha="center", va="center", zorder=6,
                 bbox=dict(fc="#FFFFFF", ec="none", alpha=0.85, pad=1.2))
    xs = [v[0] for v in raw.values()]; ys = [v[1] for v in raw.values()]
    zpad = 900
    zx0, zy0, zx1, zy1 = min(xs) - zpad, min(ys) - zpad, max(xs) + zpad, max(ys) + zpad
    axA.add_patch(Rectangle((zx0, zy0), zx1 - zx0, zy1 - zy0, fc="none", ec=INK, lw=1.4,
                            ls=(0, (4, 2)), zorder=5))
    axA.set_title("대전 전역 — 구별 지정 개소 수", fontsize=10.6, fontweight="bold", color=INK, loc="left")
    x0, y0 = axA.get_xlim()[0] + 1200, axA.get_ylim()[0] + 900
    axA.plot([x0, x0 + 5000], [y0, y0], color=INK, lw=2.2, zorder=6)
    for xx in (x0, x0 + 5000):
        axA.plot([xx, xx], [y0 - 350, y0 + 350], color=INK, lw=1.4, zorder=6)
    axA.text(x0 + 2500, y0 + 800, "5 km", fontsize=8.2, color=INK, ha="center", zorder=6)

    # ── B: 밀집부 확대
    axB.set_xlim(zx0, zx1); axB.set_ylim(zy0, zy1)
    axB.set_aspect("equal"); axB.axis("off")
    fig.canvas.draw()
    m_per_px = (zx1 - zx0) / axB.get_window_extent().width
    MARKER_PX = {"o": 27, "^": 27, "D": 37, "s": 27}     # s=80·190dpi 실측
    scale = math.sqrt(marker_s / 80.0)
    max_marker_m = max(MARKER_PX.values()) * scale * m_per_px
    MIN_GAP, MAX_OFF = max_marker_m + 55.0, 400.0
    for nm, g in gus:
        for poly in getattr(g, "geoms", [g]):
            axB.plot(*poly.exterior.xy, color="#8C9196", lw=1.2, zorder=1)
    seen, counts = {}, {}
    placed, moved, max_off, gave_up, crossed = [], 0, 0.0, 0, 0
    for r in rows:
        ox, oy = raw[r["연번"]]
        home = gu_of(SPoint(ox, oy))
        x, y = ox, oy
        conflicts = [(px, py) for px, py in placed if math.hypot(px - x, py - y) < MIN_GAP]
        if conflicts:
            # 가장 가까운 기존 마커의 반대 방향부터 시도한다(최소 이동으로 떼어놓기 위해)
            nx_, ny_ = min(conflicts, key=lambda c: math.hypot(c[0] - ox, c[1] - oy))
            base = math.atan2(oy - ny_, ox - nx_)
            best = None
            for rad in [r_ for r_ in range(120, int(MAX_OFF) + 1, 20)]:
                for dth in (0, 20, -20, 40, -40, 60, -60, 90, -90, 120, -120, 150, -150, 180):
                    ang = base + math.radians(dth)
                    c2 = (ox + rad * math.cos(ang), oy + rad * math.sin(ang))
                    if gu_of(SPoint(*c2)) != home:
                        continue
                    if any(math.hypot(px - c2[0], py - c2[1]) < MIN_GAP for px, py in placed):
                        continue
                    best = c2
                    break
                if best:
                    break
            if best:
                x, y = best
            else:
                gave_up += 1
        d = math.hypot(x - ox, y - oy)
        if d > 1:
            moved += 1
            max_off = max(max_off, d)
        if gu_of(SPoint(x, y)) != home:
            crossed += 1
        placed.append((x, y))
        col, mk, lab = band_style(r["통과판정(폭 축)"])
        axB.scatter([x], [y], s=marker_s, marker=mk, facecolor=col, edgecolor="white", linewidth=1.1, zorder=4)
        seen[lab] = (col, mk); counts[lab] = counts.get(lab, 0) + 1
    axB.set_title("개소 밀집부 확대 — 폭 축 판정", fontsize=10.6, fontweight="bold", color=INK, loc="left")
    bx0, by0 = zx0 + 400, zy0 + 400
    axB.plot([bx0, bx0 + 2000], [by0, by0], color=INK, lw=2.2, zorder=6)
    for xx in (bx0, bx0 + 2000):
        axB.plot([xx, xx], [by0 - 120, by0 + 120], color=INK, lw=1.4, zorder=6)
    axB.text(bx0 + 1000, by0 + 520, "2 km", fontsize=8.2, color=INK, ha="center", zorder=6)
    nx, ny = zx1 - 500, zy1 - 2000
    axB.annotate("", xy=(nx, ny + 900), xytext=(nx, ny),
                 arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.6), zorder=6)
    axB.text(nx, ny + 1150, "N", fontsize=9, color=INK, ha="center", fontweight="bold", zorder=6)

    order = ["BLOCKED", "CONDITIONAL_C", "UNKNOWN_FAIL_CLOSED", "폭 축에서 배제되지 않음"]
    handles = [plt.Line2D([], [], marker=seen[l][1], ls="", markerfacecolor=seen[l][0], markeredgecolor="white",
                          markersize=8.6, label=f"{l} {counts[l]}개소") for l in order if l in seen]
    fig.legend(handles=handles, loc="center left", bbox_to_anchor=(0.80, 0.56), frameon=False,
               fontsize=9.0, labelcolor=INK2)
    empty = [nm for nm, _ in gus if by_gu.get(nm, 0) == 0]
    import textwrap
    cap1 = ("폭 축만의 판정이다. BLOCKED 는 「현재 자료로는 통과를 인정할 수 없다」이고 「못 들어간다」가 아니다. "
            "개소 값은 조각 판정의 최솟값(사후 집계)이다."
            + ("".join(f" {nm}에는 이 26개소 기준으로 지정 개소가 없다." for nm in empty) if empty else "")
            + " 개소 수는 좌표화된 개소 기준이다. 도로명 기준 처리군(길·번길 42개)은 5개 구에 분포하며, 유성구 지정 2개소는"
              " 같은 개소에 표준 도로망 링크가 있는 도로명(신성남로·온천서로)이 포함돼 개소 단위에서 제외됐다.")
    cap2 = (f"오른쪽은 왼쪽 점선 사각형 구간의 확대다. 표시가 겹치는 근접 개소 {moved}곳에 최대 {max_off:,.0f} m 상당 오프셋을 줬다"
            "(구 경계를 넘지 않는 범위). 좌표 원값은 산출물 26개소_산출표.csv 에 있다. "
            "행정경계 : 브이월드 시군구 경계(lt_c_adsigg, 조회 2026-09-16) · 좌표계 EPSG:5186.")
    fig.text(0.03, 0.115, textwrap.fill(cap1 + " " + cap2, 132), fontsize=7.6, color=INK2, va="top", linespacing=1.5)
    fig.savefig(FIG / "도표2_대전26개소_좌표화.png", facecolor="white", bbox_inches="tight", pad_inches=0.10)
    plt.close(fig)
    return {"마커 픽셀 외접지름(s=80)": MARKER_PX, "확대도 m/px": round(m_per_px, 2),
            "최소 간격 m": round(MIN_GAP, 1), "오프셋 개소": moved, "최대 오프셋 m": round(max_off, 1),
            "구 경계 넘음": crossed, "겹침 감수": gave_up, "폴리곤 렌더": drawn,
            "구별 개소 수": by_gu, "합": sum(by_gu.values()), "지정 개소 0인 구": empty,
            "배치 후 최소 간격 m": round(min((math.hypot(a[0]-b[0], a[1]-b[1])
                                        for i, a in enumerate(placed) for b in placed[i+1:]), default=0), 1)}


if __name__ == "__main__":
    FIG.mkdir(parents=True, exist_ok=True)
    print("도표1 골목 선형 그림:", fig_commander())
    print("도표2 오프셋:", fig_map())
    for n in ("도표1_지휘관화면.png", "도표2_대전26개소_좌표화.png"):
        print(n, (FIG / n).stat().st_size, "bytes")
