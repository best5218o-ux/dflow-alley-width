"""021 §4 — 시각 앵커 1장: 「영상에는 골목이 있는데 표준 도로망에는 선이 없다」.

대상: 대전 진입곤란 지정 연번 31·32(문화119안전센터 관할)
화면: 브이월드 위성 정사영상(z19) + 도로명주소 도로구간 `lt_l_sprd`(파랑, 지정 도로명은 굵게) + 표준노드링크 MOCT_LINK(빨강)
규율(021 §4): **경로선을 그리지 않는다**(도로망 존재 비교) · 판독 수치를 그림에 쓰지 않는다(선의 유무만) ·
      촬영 시점 미확인을 캡션에 적는다 · 키가 이미지·파일명·로그에 드러나지 않게 한다
출력: figures/도표8_영상과도로망_연번31_32.png
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

import geopandas as gpd
from PIL import Image, ImageDraw, ImageFont
from pyproj import Transformer
from shapely.geometry import box, shape

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"
FIG = ROOT / "figures"
CACHE = ROOT / "data/vworld/ortho_cache"
LINK_SHP = ROOT / "data/vworld/national/raw/NODELINKDATA_20260914"
KEY = os.environ["VWORLD_APIKEY"].strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
Z = 19
R = 20037508.342789244
T43 = Transformer.from_crs(4326, 3857, always_xy=True)
FONT = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 19)
FONT_S = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 15)
HALF_M = 90


def mask(s):
    return str(s).replace(KEY, "***")


def tile(x, y):
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"sat_{Z}_{x}_{y}.jpg"
    if not p.exists():
        url = f"https://api.vworld.kr/req/wmts/1.0.0/{KEY}/Satellite/{Z}/{y}/{x}.jpeg"
        err = None
        for _ in range(3):
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


def links_gdf():
    shp = next(LINK_SHP.rglob("*LINK*.shp"))
    g = gpd.read_file(shp)
    return g.to_crs(3857), shp.name


def panel(site_no, piece, links):
    lon, lat = piece["point"]
    mx, my = T43.transform(lon, lat)
    k = 1 / math.cos(math.radians(lat))
    half = HALF_M * k
    gx, gy = gpx(mx, my)
    tx0, ty0 = int((gx - 360) // 256), int((gy - 360) // 256)
    tx1, ty1 = int((gx + 360) // 256), int((gy + 360) // 256)
    mosaic = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            mosaic.paste(tile(tx, ty), ((tx - tx0) * 256, (ty - ty0) * 256))
    ox, oy = tx0 * 256, ty0 * 256

    def to_px(x, y):
        a, b = gpx(x, y)
        return a - ox, b - oy

    d = ImageDraw.Draw(mosaic, "RGBA")
    roads = wfs("lt_l_sprd", mx - half, my - half, mx + half, my + half)
    tgt = norm(piece["road_name"])
    n_same = 0
    for f in roads:
        g = shape(f["geometry"])
        same = norm(f["properties"].get("rn")) == tgt
        n_same += int(same)
        for ln in getattr(g, "geoms", [g]):
            d.line([to_px(*c) for c in ln.coords], fill=(60, 140, 255, 235) if same else (140, 190, 255, 150),
                   width=6 if same else 3)
    win = box(mx - half, my - half, mx + half, my + half)
    sel = links[links.intersects(win)]
    link_names = sorted({str(v) for v in sel["ROAD_NAME"].fillna("-")})
    same_name_links = int((sel["ROAD_NAME"].map(norm) == tgt).sum())
    n_link = 0
    for geom in sel.geometry:
        for ln in getattr(geom, "geoms", [geom]):
            d.line([to_px(*c[:2]) for c in ln.coords], fill=(255, 60, 60, 235), width=4)
            n_link += 1
    px, py = to_px(mx, my)
    d.ellipse([px - 7, py - 7, px + 7, py + 7], outline=(0, 255, 255, 255), width=3)
    # 창을 지정 폭으로 자른다
    x0p, y0p = to_px(mx - half, my + half)
    x1p, y1p = to_px(mx + half, my - half)
    img = mosaic.crop((int(x0p), int(y0p), int(x1p), int(y1p)))
    return img, {"연번": site_no, "조각": piece["piece"], "도로명": piece["road_name"],
                 "같은 도로명 도로구간 선형(화면 안)": n_same, "표준노드링크 링크 구간(화면 안)": n_link,
                 "화면 안 링크 도로명": link_names, "지정 도로명 링크": same_name_links}


def main():
    cc = json.loads((DER / "missing_alley_crosscheck.json").read_text(encoding="utf-8"))
    links, shp_name = links_gdf()
    picks = []
    for s in cc["sites"]:
        if s.get("연번") in (31, 32):
            pcs = [p for p in s["pieces"] if p["type"] == "road"]
            picks.append((s["연번"], pcs[0]))
    imgs, infos = [], []
    for no, pc in picks:
        im, info = panel(no, pc, links)
        imgs.append(im)
        infos.append(info)
        print(json.dumps(info, ensure_ascii=False), flush=True)
    w = sum(i.width for i in imgs) + 24
    h = max(i.height for i in imgs)
    canvas = Image.new("RGB", (w, h + 140), (255, 255, 255))   # 048 A안 — 캡션을 사진 밖 흰 여백으로
    x = 0
    for im, info in zip(imgs, infos):
        canvas.paste(im, (x, 40))
        d = ImageDraw.Draw(canvas)
        d.text((x + 6, 12), f"연번 {info['연번']} · {info['도로명']}", font=FONT, fill=(20, 20, 20))
        cap = "표준 도로망 링크 " + "·".join(info["화면 안 링크 도로명"]) + f" · 지정 도로명 링크 {info['지정 도로명 링크']}"
        d.text((x + 6, h + 46), cap, font=FONT_S, fill=(20, 20, 20))
        x += im.width + 24
    d = ImageDraw.Draw(canvas)
    y = h + 78
    d.rectangle([6, y + 3, 30, y + 9], fill=(60, 140, 255))
    d.text((36, y - 4), "도로명주소 도로구간 — 지정 도로명", font=FONT_S, fill=(20, 20, 20))
    d.rectangle([330, y + 4, 354, y + 8], fill=(140, 190, 255))
    d.text((360, y - 4), "도로명주소 도로구간 — 그 밖의 도로명", font=FONT_S, fill=(20, 20, 20))
    d.rectangle([700, y + 3, 724, y + 9], fill=(255, 60, 60))
    d.text((730, y - 4), "표준 도로망 링크(표준노드링크 2026-09-14)", font=FONT_S, fill=(20, 20, 20))
    d.ellipse([1110, y - 3, 1126, y + 13], outline=(0, 190, 190), width=3)
    d.text((1134, y - 4), "지정 개소 위치", font=FONT_S, fill=(20, 20, 20))
    d.text((6, y + 24), "브이월드 위성영상 z19 · 촬영 시점 미확인 · 화면 반경 약 90 m · 경로선 아님(도로망 존재 비교) · 판독 수치 없음",
           font=FONT_S, fill=(70, 70, 70))
    FIG.mkdir(parents=True, exist_ok=True)
    out = FIG / "도표8_영상과도로망_연번31_32.png"
    canvas.save(out, "PNG")
    (DER / "anchor_figure.json").write_text(json.dumps(
        {"rule": "021 §4", "shapefile": shp_name, "panels": infos,
         "caption": "대전 연번 31·32 — 영상에 골목이 보이고 도로명주소 도로구간 선형도 있는데, 표준 도로망 링크는 큰 길(충무로·보문산공원로)에만 있고 지정 도로명 링크는 0이다.",
         "note": "촬영 시점 미확인 · 경로선 없음 · 판독 수치 없음 · 범례 4종(지정 도로명 선형 · 그 밖의 도로명 선형 · 표준 도로망 링크 · 지정 개소 위치)"}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(out.name, canvas.size)


if __name__ == "__main__":
    main()
