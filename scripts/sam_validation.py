"""016 F·G — AI-B SAM 검증(판정 구간) + AI 보완 전후 판정 커버리지. 기준 §25·§26 (실행 전 커밋 34c4dd1).

- 모델(M): Segment Anything ViT-B, 로컬 CPU, 가중치 sha256 ec2df627…c912, 사전학습 그대로(조정 없음)
- 검증셋 11조각은 비교에만 쓴다(학습 없음). 적용셋 = 26개소 도로명 조각 37
- 기하(G) = lt_c_spbd 건물 외곽 간격 — AI 아님, 보완 수치에 합산하지 않음
- 원본 영상·마스크 영상은 저장·커밋하지 않고 수치만 기록
키: os.environ["VWORLD_APIKEY"] 만. 출력: data/vworld/national/derived/sam_validation.json · deliverables/AI-B_SAM검증_4자대조.csv · AI보완_커버리지표.csv
"""
from __future__ import annotations

import csv
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
from PIL import Image
from pyproj import Transformer
from shapely.geometry import LineString, Point, shape
from shapely.ops import transform as shp_transform

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"
DELIV = ROOT / "deliverables"
CACHE = ROOT / "data/vworld/ortho_cache"
CKPT = ROOT / "data/vworld/models/sam_vit_b_01ec64.pth"
KEY = os.environ["VWORLD_APIKEY"].strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
Z, R = 19, 20037508.342789244
UP = 4
W_REQ, UNC = 3.5, 0.48
T43 = Transformer.from_crs(4326, 3857, always_xy=True)
T35 = Transformer.from_crs(3857, 5186, always_xy=True)
RULE = "34c4dd1"


def norm(s):
    return "".join(str(s or "").split())


def tile(x, y):
    p = CACHE / f"sat_{Z}_{x}_{y}.jpg"
    if not p.exists() or p.stat().st_size == 0:
        url = f"https://api.vworld.kr/req/wmts/1.0.0/{KEY}/Satellite/{Z}/{y}/{x}.jpeg"
        for attempt in range(3):
            try:
                b = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"}), timeout=30).read()
                Image.open(io.BytesIO(b)).verify()
                CACHE.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b)
                break
            except Exception:  # noqa: BLE001
                time.sleep(1.5)
        else:
            raise RuntimeError("tile fetch failed")
    return Image.open(p).convert("RGB")


def wfs(typename, x0, y0, x1, y1):
    q = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0", "TYPENAME": typename, "OUTPUT": "application/json",
         "MAXFEATURES": "1000", "SRSNAME": "EPSG:900913", "BBOX": f"{x0},{y0},{x1},{y1},EPSG:900913", "key": KEY, "domain": DOMAIN}
    url = "https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode(q)
    for attempt in range(3):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"}), timeout=60).read())["features"]
        except Exception:  # noqa: BLE001
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("wfs failed")


def gpx(mx, my):
    s = 256 * 2 ** Z / (2 * R)
    return (mx + R) * s, (R - my) * s


def band(w):
    if w is None:
        return "UNKNOWN_FAIL_CLOSED"
    return "BLOCKED_C" if w + UNC < W_REQ else "CONDITIONAL_C"


def prepare(piece):
    lon, lat = piece["point"]
    mx, my = T43.transform(lon, lat)
    k = 1 / math.cos(math.radians(lat))
    half = 70 * k
    roads = wfs("lt_l_sprd", mx - half, my - half, mx + half, my + half)
    blds = wfs("lt_c_spbd", mx - half, my - half, mx + half, my + half)
    same = [shape(f["geometry"]) for f in roads if norm(f["properties"].get("rn")) == piece["road_name"]]
    props = [f["properties"] for f in roads if norm(f["properties"].get("rn")) == piece["road_name"]]
    if not same:
        return None
    pt = Point(mx, my)
    j = int(np.argmin([g.distance(pt) for g in same]))
    g = same[j]
    ln = g if g.geom_type == "LineString" else min(g.geoms, key=lambda q: q.distance(pt))
    near = shapely.ops.nearest_points(ln, pt)[0]
    s = ln.project(near)
    a, b = ln.interpolate(max(0, s - 2 * k)), ln.interpolate(min(ln.length, s + 2 * k))
    vx, vy = b.x - a.x, b.y - a.y
    L = math.hypot(vx, vy) or 1
    nx, ny = -vy / L, vx / L
    # 기하(G): 건물 외곽 간격(§9 참고값과 같은 방식)
    p0 = (near.x - nx * 15 * k, near.y - ny * 15 * k)
    p1 = (near.x + nx * 15 * k, near.y + ny * 15 * k)
    tr_line = LineString([T35.transform(*p0), T35.transform(*p1)])
    c5 = Point(*T35.transform(near.x, near.y))
    left = right = None
    for f in blds:
        gb = shp_transform(lambda x, y, z=None: T35.transform(x, y), shape(f["geometry"]))
        inter = tr_line.intersection(gb.boundary)
        for q in getattr(inter, "geoms", [inter]):
            if q.is_empty or q.geom_type != "Point":
                continue
            side = tr_line.project(q) - tr_line.project(c5)
            if side < 0:
                left = abs(side) if left is None else min(left, abs(side))
            else:
                right = side if right is None else min(right, side)
    g_gap = round(left + right, 2) if left is not None and right is not None else None
    # 정렬 원영상
    gx, gy = gpx(near.x, near.y)
    tx0, ty0, tx1, ty1 = int((gx - 300) // 256), int((gy - 300) // 256), int((gx + 300) // 256), int((gy + 300) // 256)
    mos = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            mos.paste(tile(tx, ty), ((tx - tx0) * 256, (ty - ty0) * 256))
    cx, cy = gx - tx0 * 256, gy - ty0 * 256
    ang = math.degrees(math.atan2(-vy, vx))
    rot = mos.rotate(ang, center=(cx, cy), resample=Image.BICUBIC)
    ppm = 256 * 2 ** Z / (2 * R) * k
    hw, hh = 16 * ppm, 12 * ppm
    crop = rot.crop((int(cx - hw), int(cy - hh), int(cx + hw), int(cy + hh)))
    crop = crop.resize((crop.width * UP, crop.height * UP), Image.BICUBIC)
    return {"img": np.array(crop), "ppm": ppm, "g_gap": g_gap, "road_bt": props[j].get("road_bt")}


def sam_width(predictor, img, ppm):
    H, W = img.shape[:2]
    mid = H // 2
    pts = np.array([[int(W * f), mid] for f in (0.25, 0.5, 0.75)])
    predictor.set_image(img)
    masks, scores, _ = predictor.predict(point_coords=pts, point_labels=np.ones(3), multimask_output=True)
    m = masks[int(np.argmax(scores))]
    area = m.mean()
    info = {"mask_area_frac": round(float(area), 3), "pred_iou": round(float(scores.max()), 3)}
    if area > 0.8 or area < 0.01:
        return None, {**info, "fail": "마스크 면적 조건"}
    c0, c1 = int(W * 0.2), int(W * 0.8)
    widths = []
    for c in range(c0, c1):
        col = m[:, c]
        if not col[mid]:
            continue
        up = mid
        while up > 0 and col[up - 1]:
            up -= 1
        dn = mid
        while dn < H - 1 and col[dn + 1]:
            dn += 1
        widths.append(dn - up + 1)
    cover = len(widths) / (c1 - c0)
    info["center_cover"] = round(cover, 3)
    if cover < 0.5:
        return None, {**info, "fail": "가운데 줄 포함 열 50 % 미만"}
    cv = float(np.std(widths) / np.mean(widths))
    info["width_cv"] = round(cv, 3)
    if cv > 0.5:
        return None, {**info, "fail": "열별 폭 변동계수 > 0.5"}
    w_m = float(np.median(widths)) / UP / ppm
    return round(w_m, 2), info


def main():
    import torch
    from segment_anything import SamPredictor, sam_model_registry
    torch.set_num_threads(os.cpu_count() or 4)
    sam = sam_model_registry["vit_b"](checkpoint=str(CKPT))
    predictor = SamPredictor(sam)
    cc = json.loads((DER / "missing_alley_crosscheck.json").read_text(encoding="utf-8"))
    readings = {(r["연번"], norm(r["piece"]).split("22-14")[0]): r for r in json.loads((DER / "ortho_readings.json").read_text(encoding="utf-8"))["readings"]}
    rows = []
    t_start = time.time()
    for s in cc["sites"]:
        for p in s["pieces"]:
            if p["type"] != "road":
                continue
            key = (s["연번"], p["road_name"])
            rd = readings.get(key)
            rec = {"연번": s["연번"], "piece": p["piece"], "road_name": p["road_name"], "validation": rd is not None}
            t0 = time.time()
            try:
                prep = prepare(p)
                if prep is None:
                    rec.update(sam_width_m=None, sam_band="UNKNOWN_FAIL_CLOSED", fail="같은 도로명 선형 없음")
                else:
                    w, info = sam_width(predictor, prep["img"], prep["ppm"])
                    rec.update(sam_width_m=w, sam_band=band(w), **info, g_gap_m=prep["g_gap"], g_band=band(prep["g_gap"]) if prep["g_gap"] else "UNKNOWN_FAIL_CLOSED",
                               road_bt_unit_unconfirmed=prep["road_bt"])
            except Exception as e:  # noqa: BLE001
                rec.update(sam_width_m=None, sam_band="UNKNOWN_FAIL_CLOSED", fail=f"오류 {type(e).__name__}")
            rec["seconds"] = round(time.time() - t0, 1)
            if rd is not None:
                wr = rd.get("width_read_m")
                rec["human_read_m"] = wr
                rec["human_band"] = "UNKNOWN_FAIL_CLOSED" if not wr else ("BLOCKED_C" if wr[1] < W_REQ else "CONDITIONAL_C")
                def cmp(v):
                    if v is None or not wr:
                        return "대조 불가"
                    return "모순되지 않음" if wr[0] - 1 <= v <= wr[1] + 1 else "차이"
                rec["M_vs_human"] = cmp(rec.get("sam_width_m"))
                rec["G_vs_human"] = cmp(rec.get("g_gap_m"))
                try:
                    rb = float(rec.get("road_bt_unit_unconfirmed"))
                except (TypeError, ValueError):
                    rb = None
                rec["road_bt_vs_human"] = cmp(rb)
                rec["band_match_M_human"] = rec["sam_band"] == rec["human_band"]
            rows.append(rec)
            print(json.dumps({k: rec.get(k) for k in ("연번", "road_name", "validation", "sam_width_m", "sam_band", "fail", "human_read_m", "M_vs_human", "seconds")}, ensure_ascii=False), flush=True)
    val = [r for r in rows if r["validation"]]
    cnt = lambda rs, k, v: sum(1 for r in rs if r.get(k) == v)
    def coverage(rs):
        n = len(rs)
        after = sum(1 for r in rs if r["sam_band"] != "UNKNOWN_FAIL_CLOSED")
        return {"n": n, "before_judgeable": 0, "after_judgeable": after, "after_pct": round(after / n * 100, 1) if n else None,
                "increase": after, "after_still_fail_closed": n - after,
                "G_reference_judgeable(기하, 합산 안 함)": sum(1 for r in rs if r.get("g_band") and r["g_band"] != "UNKNOWN_FAIL_CLOSED")}
    sites = {}
    for r in rows:
        sites.setdefault(r["연번"], []).append(r)
    site_after = sum(1 for v in sites.values() if any(x["sam_band"] != "UNKNOWN_FAIL_CLOSED" for x in v))
    out = {"rule_doc": "docs/판정기준.md §25·§26", "rule_commit": RULE, "model": "SAM ViT-B (Apache-2.0, 로컬 CPU, 조정 없음)",
           "threshold": {"B_m": 2.5, "side_clearance_m_each": 0.5, "W_req_m": W_REQ, "uncertainty_m": UNC,
                         "gsd_note": "z19 0.2405 m/px 가 촬영 원본임은 증명 못 함 — z18 수준(0.48 m/px)이면 불확실 2배"},
           "pieces_processed": len(rows), "seconds_total": round(time.time() - t_start, 1),
           "validation": {"n": len(val), "band_distribution": {b: cnt(val, "sam_band", b) for b in ("BLOCKED_C", "CONDITIONAL_C", "UNKNOWN_FAIL_CLOSED")},
                          "human_band_distribution": {b: cnt(val, "human_band", b) for b in ("BLOCKED_C", "CONDITIONAL_C", "UNKNOWN_FAIL_CLOSED")},
                          "band_match_M_human": sum(1 for r in val if r.get("band_match_M_human")),
                          "M_vs_human": {v: cnt(val, "M_vs_human", v) for v in ("모순되지 않음", "차이", "대조 불가")},
                          "G_vs_human": {v: cnt(val, "G_vs_human", v) for v in ("모순되지 않음", "차이", "대조 불가")},
                          "road_bt_vs_human": {v: cnt(val, "road_bt_vs_human", v) for v in ("모순되지 않음", "차이", "대조 불가")},
                          "fail_reasons": [r.get("fail") for r in val if r.get("fail")]},
           "application": {"band_distribution": {b: cnt(rows, "sam_band", b) for b in ("BLOCKED_C", "CONDITIONAL_C", "UNKNOWN_FAIL_CLOSED")}},
           "coverage": {"검증셋 11조각": coverage(val), "대전 진입곤란 26개소 조각": coverage(rows),
                        "대전 진입곤란 26개소 개소": {"n": len(sites), "before_judgeable": 0, "after_judgeable": site_after, "increase": site_after,
                                              "after_still_fail_closed": len(sites) - site_after}},
           "rows": rows}
    (DER / "sam_validation.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    DELIV.mkdir(parents=True, exist_ok=True)
    with (DELIV / "AI-B_SAM검증_4자대조.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["연번", "도로명", "M_SAM폭m", "M판정구간", "M실패사유", "G_건물간격m(기하·AI아님)", "G판정구간", "road_bt(단위미확인)", "사람판독m(C)", "사람판정구간",
                    "M대사람", "G대사람", "road_bt대사람", "판정구간일치(M=사람)"])
        for r in val:
            w.writerow([r["연번"], r["road_name"], r.get("sam_width_m"), r["sam_band"], r.get("fail"), r.get("g_gap_m"), r.get("g_band"), r.get("road_bt_unit_unconfirmed"),
                        r.get("human_read_m"), r.get("human_band"), r.get("M_vs_human"), r.get("G_vs_human"), r.get("road_bt_vs_human"), r.get("band_match_M_human")])
    with (DELIV / "AI보완_커버리지표.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["구간", "n", "보완 전 판정 가능", "보완 후 판정 가능(SAM)", "보완 후 %", "증가", "보완 후에도 FAIL_CLOSED", "참고: 기하(G) 판정 가능(합산 안 함)"])
        for k, v in out["coverage"].items():
            w.writerow([k, v["n"], v["before_judgeable"], v["after_judgeable"], v.get("after_pct", ""), v["increase"], v["after_still_fail_closed"], v.get("G_reference_judgeable(기하, 합산 안 함)", "")])
    print(json.dumps({k: out[k] for k in ("pieces_processed", "seconds_total", "validation", "application", "coverage")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
