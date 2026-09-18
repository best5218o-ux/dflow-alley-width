"""007 §11-3 · 006 §3-3 — 대표 6곳 정사영상 판독 화면 생성(선형 실재 · 노면 폭 vs road_bt).

기준: docs/판정기준.md §9 (실행 전 커밋 050decc).
- 브이월드 WMTS Satellite z19 타일 모자이크 + lt_l_sprd(회색/일치 빨강) + lt_c_spbd 외곽 + 조각 점 + 수직 횡단선(±15 m, 1 m 눈금)
- 판독(일치/불일치/판독불가, 폭 범위)은 사람이 화면을 보고 적는다 — 이 스크립트는 화면과 참고값(건물 간격)만 만든다
- 키: os.environ["VWORLD_APIKEY"] 만. 타일 캐시 파일명·이미지·로그에 키 없음
출력: figures/ortho/연번_조각.png(전체) · _zoom.png(횡단선 확대) · data/vworld/national/derived/ortho_crosscheck_panels.json
"""
from __future__ import annotations

import io
import json
import math
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import shapely
import shapely.ops
from PIL import Image, ImageDraw, ImageFont
from pyproj import Transformer
from shapely.geometry import LineString, Point, shape

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"
FIG = ROOT / "figures/ortho"
CACHE = ROOT / "data/vworld/ortho_cache"
KEY = os.environ["VWORLD_APIKEY"].strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
SITES = [1, 5, 10, 15, 28, 27]
Z = 19
R = 20037508.342789244
T43 = Transformer.from_crs(4326, 3857, always_xy=True)
T35 = Transformer.from_crs(3857, 5186, always_xy=True)
FONT = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 15)
FONT_S = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 12)


def mask(s):
    return str(s).replace(KEY, "***")


def tile(x, y):
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"sat_{Z}_{x}_{y}.jpg"
    if not p.exists():
        url = f"https://api.vworld.kr/req/wmts/1.0.0/{KEY}/Satellite/{Z}/{y}/{x}.jpeg"
        for attempt in range(3):
            try:
                b = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"}), timeout=30).read()
                Image.open(io.BytesIO(b)).verify()
                p.write_bytes(b)
                break
            except Exception as e:  # noqa: BLE001
                err = mask(e)
                time.sleep(1.5)
        else:
            raise RuntimeError(f"타일 실패 {Z}/{x}/{y}: {err}")
    return Image.open(p).convert("RGB")


def wfs(typename, x0, y0, x1, y1):
    q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": typename, "OUTPUT": "application/json",
         "MAXFEATURES": "1000", "SRSNAME": "EPSG:900913", "BBOX": f"{x0},{y0},{x1},{y1},EPSG:900913", "key": KEY, "domain": DOMAIN}
    url = "https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode(q)
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"}), timeout=60).read())["features"]


def gpx(mx, my):
    s = 256 * 2 ** Z / (2 * R)
    return (mx + R) * s, (R - my) * s


def norm(s):
    return "".join(str(s or "").split())


def panel(site, piece):
    lon, lat = piece["point"]
    mx, my = T43.transform(lon, lat)
    k = 1 / math.cos(math.radians(lat))  # 지상 1 m = 머케이터 k 단위
    half = 70 * k
    gx, gy = gpx(mx, my)
    tx0, ty0 = int((gx - 320) // 256), int((gy - 320) // 256)
    tx1, ty1 = int((gx + 320) // 256), int((gy + 320) // 256)
    mosaic = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            mosaic.paste(tile(tx, ty), ((tx - tx0) * 256, (ty - ty0) * 256))
    ox, oy = tx0 * 256, ty0 * 256
    to_px = lambda x, y: (gpx(x, y)[0] - ox, gpx(x, y)[1] - oy)
    roads = wfs("lt_l_sprd", mx - half, my - half, mx + half, my + half)
    blds = wfs("lt_c_spbd", mx - half, my - half, mx + half, my + half)
    d = ImageDraw.Draw(mosaic, "RGBA")
    for b in blds:
        g = shape(b["geometry"])
        for poly in getattr(g, "geoms", [g]):
            d.line([to_px(*c) for c in poly.exterior.coords], fill=(255, 255, 0, 150), width=1)
    name = piece["road_name"]
    matched = []
    for f in roads:
        g = shape(f["geometry"])
        same = norm(f["properties"].get("rn")) == name
        for ln in getattr(g, "geoms", [g]):
            d.line([to_px(*c) for c in ln.coords], fill=(255, 40, 40, 230) if same else (200, 200, 200, 160), width=3 if same else 2)
        if same:
            matched.append((g, f["properties"]))
    info = {"연번": site, "piece": piece["piece"], "road_name": name, "point": piece["point"], "roads_in_view": len(roads),
            "buildings_in_view": len(blds), "matched_features_in_view": len(matched)}
    px, py = to_px(mx, my)
    d.ellipse([px - 5, py - 5, px + 5, py + 5], outline=(0, 255, 255, 255), width=2)
    if matched:
        pt = Point(mx, my)
        g, props = min(matched, key=lambda m: m[0].distance(pt))
        near = shapely.ops.nearest_points(g, pt)[0]
        s = g.project(near) if g.geom_type == "LineString" else None
        ln = g if g.geom_type == "LineString" else min(g.geoms, key=lambda q: q.distance(pt))
        s = ln.project(near)
        a, b = ln.interpolate(max(0, s - 2 * k)), ln.interpolate(min(ln.length, s + 2 * k))
        vx, vy = b.x - a.x, b.y - a.y
        L = math.hypot(vx, vy) or 1
        nx, ny = -vy / L, vx / L
        p0 = (near.x - nx * 15 * k, near.y - ny * 15 * k)
        p1 = (near.x + nx * 15 * k, near.y + ny * 15 * k)
        d.line([to_px(*p0), to_px(*p1)], fill=(0, 255, 255, 255), width=2)
        for i in range(-15, 16):
            c = (near.x + nx * i * k, near.y + ny * i * k)
            cx, cy = to_px(*c)
            tl = 6 if i % 5 == 0 else 3
            d.line([cx - ny * tl, cy - nx * tl * -1, cx + ny * tl, cy + nx * tl * -1], fill=(0, 255, 255, 255), width=1)
        # 참고: 횡단선과 건물 외곽 교차 — 좌우 최근접 거리(지상 m)
        tr_line = LineString([T35.transform(*p0), T35.transform(*p1)])
        c5186 = Point(*T35.transform(near.x, near.y))
        left, right = None, None
        for bld in blds:
            gb = shapely.ops.transform(lambda x, y, z=None: T35.transform(x, y), shape(bld["geometry"]))
            inter = tr_line.intersection(gb.boundary)
            for q in getattr(inter, "geoms", [inter]):
                if q.is_empty or q.geom_type != "Point":
                    continue
                side = tr_line.project(q) - tr_line.project(c5186)
                dist = abs(side)
                if side < 0:
                    left = dist if left is None else min(left, dist)
                else:
                    right = dist if right is None else min(right, dist)
        info.update(road_bt=props.get("road_bt"), road_lt=props.get("road_lt"), line_offset_from_point_m=round(pt.distance(g) / k, 1),
                    ref_building_gap_m=(round(left + right, 1) if left is not None and right is not None else None),
                    ref_building_left_m=None if left is None else round(left, 1), ref_building_right_m=None if right is None else round(right, 1))
        # 확대 화면(횡단선 중심 ±20 m, 3배)
        cx, cy = to_px(near.x, near.y)
        r = 22 * k * 256 * 2 ** Z / (2 * R)
        zoom = mosaic.crop((int(cx - r), int(cy - r), int(cx + r), int(cy + r))).resize((int(2 * r * 3), int(2 * r * 3)), Image.LANCZOS)
        zd = ImageDraw.Draw(zoom)
        zd.rectangle([0, 0, zoom.width, 24], fill=(0, 0, 0))
        zd.text((6, 3), f"연번 {site} {piece['piece']} · 횡단선 ±15 m 눈금 1 m(긴 눈금 5 m) · road_bt={props.get('road_bt')}", font=FONT_S, fill="white")
        FIG.mkdir(parents=True, exist_ok=True)
        zoom.save(FIG / f"{site:02d}_{norm(piece['piece'])}_zoom.png")
        # 판독용 정렬 화면: 선형 방향이 가로가 되게 회전, 횡단 방향 ±12 m 에 1 m 격자·숫자(오버레이 없는 원영상)
        raw = Image.new("RGB", mosaic.size)
        for tx in range(tx0, tx1 + 1):
            for ty in range(ty0, ty1 + 1):
                raw.paste(tile(tx, ty), ((tx - tx0) * 256, (ty - ty0) * 256))
        ppm = 256 * 2 ** Z / (2 * R) * k  # 화소/지상 m
        ang = math.degrees(math.atan2(-(vy), vx))  # 화면 좌표(y 아래)에서 선형 각도
        rot = raw.rotate(ang, center=(cx, cy), resample=Image.BICUBIC)
        hw, hh = 16 * ppm, 12 * ppm
        al = rot.crop((int(cx - hw), int(cy - hh), int(cx + hw), int(cy + hh)))
        S = 5
        al = al.resize((al.width * S, al.height * S), Image.LANCZOS)
        ad = ImageDraw.Draw(al, "RGBA")
        mid = al.height / 2
        for m in range(-12, 13):
            yy = mid - m * ppm * S
            ad.line([(40, yy), (al.width, yy)], fill=(0, 255, 255, 200 if m % 5 == 0 else 90), width=2 if m == 0 else 1)
            ad.text((4, yy - 8), f"{m:+d}", font=FONT_S, fill=(0, 255, 255, 255))
        ad.rectangle([0, 0, al.width, 22], fill=(0, 0, 0, 230))
        ad.text((46, 3), f"연번 {site} {piece['piece']} · 선형 방향 가로 정렬 · 가로선 1 m 간격(0 = 선형) · road_bt={props.get('road_bt')}", font=FONT_S, fill="white")
        al.save(FIG / f"{site:02d}_{norm(piece['piece'])}_ruler.png")
    crop = mosaic.crop((int(px - 290), int(py - 290), int(px + 290), int(py + 290)))
    cd = ImageDraw.Draw(crop)
    cd.rectangle([0, 0, 580, 42], fill=(0, 0, 0))
    cd.text((6, 2), f"연번 {site} · {piece['piece']} (도로명 {name})", font=FONT, fill="white")
    cd.text((6, 22), "빨강 = 같은 도로명 도로명주소도로 · 회색 = 다른 도로 · 노랑 = 도로명주소건물 · 하늘 = 조각 점·횡단선", font=FONT_S, fill="white")
    # 축척 20 m
    sb = 20 * k * 256 * 2 ** Z / (2 * R)
    cd.rectangle([10, 560, 10 + sb, 566], fill="white")
    cd.text((14 + sb, 552), "20 m", font=FONT_S, fill="white")
    FIG.mkdir(parents=True, exist_ok=True)
    crop.save(FIG / f"{site:02d}_{norm(piece['piece'])}.png")
    return info


def main():
    cc = json.loads((DER / "missing_alley_crosscheck.json").read_text(encoding="utf-8"))
    out = []
    for s in cc["sites"]:
        if s["연번"] not in SITES:
            continue
        for p in s["pieces"]:
            if p["type"] == "road":
                out.append(panel(s["연번"], p))
    (DER / "ortho_crosscheck_panels.json").write_text(json.dumps({"rule_commit": "050decc", "zoom": Z, "panels": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    for o in out:
        print(json.dumps(o, ensure_ascii=False))


if __name__ == "__main__":
    main()
