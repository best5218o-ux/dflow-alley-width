"""014 P1-8 — 정사영상 지상해상도 실측. 기준 docs/판정기준.md §21 (실행 전 커밋 cadef64).

- 26개소 도로명 첫 조각 좌표마다 z18·z19·z20 Satellite 타일 존재 확인
- 화소 간격 = 156543.03392·cos(위도)/2^z
- 원본 판별 R = var(Laplacian(z n)) / var(Laplacian(z n−1 을 2배 업샘플해 같은 영역으로 자른 영상)), R < 1.2 → z n 은 업샘플
- 골목 폭 화소 수 = 사람 판독 폭(ortho_readings.json, 등급 C 참고) ÷ 원본 화소 간격
키: os.environ["VWORLD_APIKEY"] 만(타일 요청). 영상은 캐시만, 커밋 없음. 출력: data/vworld/national/derived/ortho_resolution.json
"""
from __future__ import annotations

import io
import json
import math
import os
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"
CACHE = ROOT / "data/vworld/ortho_cache"
KEY = os.environ["VWORLD_APIKEY"].strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")


def tile_xy(lon, lat, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def get_tile(z, x, y):
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"sat_{z}_{x}_{y}.jpg"
    if p.exists() and p.stat().st_size > 0:
        return Image.open(p).convert("L"), "cache"
    url = f"https://api.vworld.kr/req/wmts/1.0.0/{KEY}/Satellite/{z}/{y}/{x}.jpeg"
    for attempt in range(3):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"}), timeout=30).read()
            im = Image.open(io.BytesIO(b))
            im.load()
            p.write_bytes(b)
            return im.convert("L"), "fetched"
        except urllib.error.HTTPError as e:
            return None, f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__
            time.sleep(1.5)
    return None, err


def lap_var(im):
    a = np.asarray(im.filter(ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1)), dtype=float)
    return float(a.var())


def ratio(lon, lat, z):
    x, y = tile_xy(lon, lat, z)
    tx, ty = int(x), int(y)
    hi, s_hi = get_tile(z, tx, ty)
    lo, s_lo = get_tile(z - 1, tx // 2, ty // 2)
    if hi is None or lo is None:
        return None, {"z": z, "hi": s_hi, "lo": s_lo}
    ox, oy = (tx % 2) * 128, (ty % 2) * 128
    up = lo.crop((ox, oy, ox + 128, oy + 128)).resize((256, 256), Image.BICUBIC)
    return lap_var(hi) / max(lap_var(up), 1e-9), {"z": z, "hi": s_hi, "lo": s_lo}


def main():
    cc = json.loads((DER / "missing_alley_crosscheck.json").read_text(encoding="utf-8"))
    rows = []
    for s in cc["sites"]:
        p = next(q for q in s["pieces"] if q["type"] == "road")
        lon, lat = p["point"]
        rec = {"연번": s["연번"], "piece": p["piece"], "lat": round(lat, 5)}
        for z in (19, 20):
            r, meta = ratio(lon, lat, z)
            rec[f"R_z{z}"] = None if r is None else round(r, 3)
            rec[f"z{z}_status"] = meta
        rows.append(rec)
        time.sleep(0.1)
    lat_mean = statistics.mean(r["lat"] for r in rows)
    gsd = {z: round(156543.03392 * math.cos(math.radians(lat_mean)) / 2 ** z, 4) for z in (18, 19, 20)}
    r19 = [r["R_z19"] for r in rows if r["R_z19"] is not None]
    r20 = [r["R_z20"] for r in rows if r["R_z20"] is not None]
    z20_avail = sum(1 for r in rows if r["R_z20"] is not None)
    med19 = statistics.median(r19) if r19 else None
    med20 = statistics.median(r20) if r20 else None
    native = 20 if (med20 is not None and med20 >= 1.2 and med19 is not None and med19 >= 1.2) else (19 if (med19 is not None and med19 >= 1.2) else 18)
    readings = json.loads((DER / "ortho_readings.json").read_text(encoding="utf-8"))["readings"]
    lows = [r["width_read_m"][0] for r in readings if r.get("width_read_m")]
    highs = [r["width_read_m"][1] for r in readings if r.get("width_read_m")]
    px = gsd[native]
    low_px = [round(w / px, 1) for w in lows]
    med_low_px = statistics.median(low_px) if low_px else None
    gate = ("해상도상 가능" if med_low_px is not None and med_low_px >= 10 else "경계" if med_low_px is not None and med_low_px >= 6 else "부족")
    rb = [b for s in cc["sites"] for q in s["pieces"] for b in (q.get("ref_road_bt") or [])]
    out = {"rule_commit": "cadef64", "sites": len(rows), "mean_lat": round(lat_mean, 4), "tile_pixel_spacing_m": gsd,
           "z20_tiles_available": z20_avail, "R_z19_median": med19, "R_z20_median": med20, "native_zoom_by_rule": native,
           "native_pixel_spacing_m": px,
           "reading_width_low_m": lows, "reading_width_high_m": highs, "reading_width_low_px": low_px, "reading_width_low_px_median": med_low_px,
           "M_gate": gate, "road_bt_ref_px_median_unit_unconfirmed": round(statistics.median(rb) / px, 1) if rb else None,
           "note": "판독 폭은 사람 판독(C) 10조각 — 검증셋, 학습에 쓰지 않음 · 수목·그림자 가림은 가부 판정과 별도",
           "rows": rows}
    (DER / "ortho_resolution.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, ensure_ascii=False))
    print([(r["연번"], r["R_z19"], r["R_z20"], r["z20_status"]["hi"]) for r in rows])


if __name__ == "__main__":
    main()
