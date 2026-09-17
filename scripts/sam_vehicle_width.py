"""057 §34 · 실행 전 커밋 4783bcb — 주차차량 차감 통행가능폭(SAM 차량탐지 + 도로구간 회랑) · 분리 방식 판정.

- §25(노면 분할 측정, 실패)와 별개. sam_validation.py 는 수정하지 않는다
- 모델: Segment Anything ViT-B 사전학습 가중치 그대로 · 로컬 CPU · SamAutomaticMaskGenerator 파라미터 §34-3 고정
- 폭의 출처는 공공데이터 road_bt, AI 는 차량 횡점유(차감량)만 낸다. 증거등급 C · 촬영 시점 미표기(실시간 아님)
- 키: os.environ["VWORLD_APIKEY"] (캐시에 없는 타일만)
출력: data/vworld/national/derived/sam_vehicle_width.json · deliverables/통행가능폭_주차차감_37조각.csv ·
      회랑필터_전후_오탐.csv · 차량탐지_사람대조_11조각.csv · figures/도표9a_필터전_오탐.png · 도표9b_회랑필터_확정.png
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import shapely.wkt
from PIL import Image, ImageDraw, ImageFont
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import transform as shp_transform

ROOT = Path(__file__).resolve().parents[1]   # 저장소 루트(scripts/ 한 단계 위)
DER = ROOT / "data/vworld/national/derived"
DELIV = ROOT / "deliverables"
FIG = ROOT / "figures"
CACHE = ROOT / "data/vworld/ortho_cache"
WORK = DER / "sam_vehicle_cache"
CKPT = ROOT / "data/vworld/models/sam_vit_b_01ec64.pth"
RULE = "4783bcb"
Z, UP, WIN = 19, 3, 256
T54 = Transformer.from_crs(5186, 4326, always_xy=True)
T45 = Transformer.from_crs(4326, 5186, always_xy=True)

# §34-10 임계 — 원문에서 읽은 값(원천 문서 위치를 함께 둔다)
KFS_WIDTH = [(1.9, "소방펌프차 경형(KFS 0008 3.3)"), (2.2, "소방펌프차 소형(KFS 0008 3.3)"),
             (2.5, "소방펌프차 중·대형(KFS 0008 3.3)·물탱크차 0009·화학차 0010·사다리차 0011·굴절차 0012")]
P_WALK = 1.2   # 장애인등편의법 시행규칙 [별표 1] 1.가.(1) — 원칙값(접근로에 완화값 없음)
G_CAR = 2.0    # 도로의 구조·시설 기준에 관한 규칙 제5조 소형자동차 폭
SRC_NOTE = "E=KFS 3.3 전폭 상한(차종 연동) · P=1.2 m 별표1 1.가.(1) 원칙값 · G=2.0 m 도로구조규칙 제5조 소형자동차"


def norm(s):
    return "".join(str(s or "").split())


def gsd(lat):
    return 156543.03392 * math.cos(math.radians(lat)) / 2 ** Z


def gpx(lon, lat):
    n = 256 * 2 ** Z
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def tile(x, y):
    p = CACHE / f"sat_{Z}_{x}_{y}.jpg"
    if not p.exists() or p.stat().st_size == 0:
        key = os.environ["VWORLD_APIKEY"]
        url = f"https://api.vworld.kr/req/wmts/1.0.0/{key}/Satellite/{Z}/{y}/{x}.jpeg"
        for _ in range(3):
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


def mosaic(gx, gy, half):
    tx0, ty0 = int((gx - half) // 256), int((gy - half) // 256)
    tx1, ty1 = int((gx + half) // 256), int((gy + half) // 256)
    mos = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            mos.paste(tile(tx, ty), ((tx - tx0) * 256, (ty - ty0) * 256))
    return np.array(mos), tx0 * 256, ty0 * 256


def load_roads():
    idx = {}
    with (ROOT / "data/vworld/national/raw/daejeon_sprd_geom.jsonl").open(encoding="utf-8") as f:
        for ln in f:
            r = json.loads(ln)
            idx.setdefault(norm(r.get("rn")), []).append(r)
    return idx


def lines_of(geom):
    return list(geom.geoms) if isinstance(geom, MultiLineString) else [geom]


def pieces():
    cc = json.loads((DER / "missing_alley_crosscheck.json").read_text(encoding="utf-8"))
    out = []
    for s in cc["sites"]:
        for p in s["pieces"]:
            if p["type"] == "road":
                out.append({"연번": s["연번"], "시군구": s["시군구"], "조각": p["piece"], "road_name": p.get("road_name") or norm(p["piece"]), "point": p["point"]})
    return out


def lateral_span(pts, line):
    c = np.array(line.interpolate(line.project(Point(*pts.mean(0)))).coords[0])
    t = np.array(line.interpolate(min(line.length, line.project(Point(*pts.mean(0))) + 5)).coords[0])
    d = t - c
    if np.hypot(*d) < 1e-6:
        t = np.array(line.interpolate(max(0, line.project(Point(*pts.mean(0))) - 5)).coords[0])
        d = c - t
    d = d / (np.hypot(*d) or 1)
    nrm = np.array([-d[1], d[0]])
    off = (pts - c) @ nrm
    return float(off.max() - off.min())


def classify(masks, line_px, corridor, mpp):
    rows = []
    for m in masks:
        seg = m["segmentation"].astype(np.uint8)
        a = float(seg.sum()) * mpp * mpp
        cnts = cv2.findContours(seg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
        if not cnts:
            continue
        cnt = max(cnts, key=cv2.contourArea)
        (rx, ry), (rw, rh), _ = cv2.minAreaRect(cnt)
        L, S = max(rw, rh) * mpp, min(rw, rh) * mpp
        if S <= 0:
            continue
        R = a / (L * S)
        spec = (3.0 <= a <= 20.0) and (3.0 <= L <= 7.5) and (1.4 <= S <= 2.8) and (1.6 <= L / S <= 4.2) and R >= 0.62
        inr = corridor.contains(Point(rx, ry)) if corridor is not None else False
        pts = cnt.reshape(-1, 2).astype(float)
        line = min(line_px, key=lambda g: g.distance(Point(rx, ry)))
        rows.append({"A": round(a, 2), "L": round(L, 2), "S": round(S, 2), "R": round(R, 2), "spec": bool(spec), "corridor": bool(inr),
                     "lateral_m": round(lateral_span(pts, line) * mpp, 2), "box": cv2.boxPoints(cv2.minAreaRect(cnt)).tolist()})
    return rows


def band(w):
    return "BLOCKED" if w <= 2.5 else ("CONDITIONAL_C" if w <= 3.5 else "폭축_통과후보")


RANK = {"폭축_통과후보": 3, "CONDITIONAL_C": 2, "BLOCKED": 1, "UNKNOWN_FAIL_CLOSED": 1, "UNKNOWN_FAIL_CLOSED_미탐": 1}


def separation(w):
    if w < KFS_WIDTH[0][0]:
        return "통과불가", None, "Y"
    E, _ = max((x for x in KFS_WIDTH if x[0] <= w), key=lambda x: x[0])
    mode = "공간" if w >= E + P_WALK else "시간"
    return mode, E, ("Y" if w < E + G_CAR else "N")


def run_sam(gen, img):
    return gen.generate(img)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    roads = load_roads()
    readings = {r["piece"]: r for r in json.loads((DER / "ortho_readings.json").read_text(encoding="utf-8"))["readings"]}
    old = {(r["시군구"], r["조각"]): r for r in csv.DictReader((DELIV / "도로경계내접폭_26개소.csv").open(encoding="utf-8-sig"))}
    from segment_anything import SamAutomaticMaskGenerator, sam_model_registry
    sam = sam_model_registry["vit_b"](checkpoint=str(CKPT))
    sam.to("cpu")
    gen = SamAutomaticMaskGenerator(sam, points_per_side=32, pred_iou_thresh=0.86, stability_score_thresh=0.90, min_mask_region_area=300)

    results, val = [], []
    for i, pc in enumerate(pieces()):
        lon, lat = pc["point"]
        g = gsd(lat)
        mpp = g / UP
        rec = {**{k: pc[k] for k in ("연번", "시군구", "조각", "road_name")}, "gsd": round(g, 4)}
        cands = roads.get(pc["road_name"], [])
        px, py = T45.transform(lon, lat)
        if not cands:
            rec.update(status="UNKNOWN_FAIL_CLOSED", reason="같은 도로명 도로구간 없음")
            results.append(rec)
            print(i, pc["조각"], rec["status"], flush=True)
            continue
        row = min(cands, key=lambda r: shapely.wkt.loads(r["wkt"]).distance(Point(px, py)))
        geom = shapely.wkt.loads(row["wkt"])
        rbt = row.get("road_bt")
        rec.update(rds_man_no=row.get("rds_man_no"), road_bt=rbt)
        if rbt in (None, "", 0):
            rec.update(status="UNKNOWN_FAIL_CLOSED", reason="road_bt 없음")
            results.append(rec)
            continue
        rbt = float(rbt)
        near = min(lines_of(geom), key=lambda l: l.distance(Point(px, py)))
        npt = near.interpolate(near.project(Point(px, py)))
        clon, clat = T54.transform(npt.x, npt.y)
        gx, gy = gpx(clon, clat)
        arr, ox, oy = mosaic(gx, gy, 260)
        cx, cy = gx - ox, gy - oy
        x0, y0 = int(round(cx - WIN / 2)), int(round(cy - WIN / 2))
        crop = Image.fromarray(arr[y0:y0 + WIN, x0:x0 + WIN]).resize((WIN * UP, WIN * UP), Image.BICUBIC)
        img = np.array(crop)
        to_px = lambda x, y: (((gpx(*T54.transform(x, y))[0] - ox) - x0) * UP, ((gpx(*T54.transform(x, y))[1] - oy) - y0) * UP)
        lines_px = [LineString([to_px(x, y) for x, y in l.coords]) for l in lines_of(geom)]
        corridor = MultiLineString(lines_px).buffer((rbt / 2) / mpp)
        cache = WORK / f"work_{i:02d}.json"
        if cache.exists():
            rows = json.loads(cache.read_text(encoding="utf-8"))
        else:
            t0 = time.time()
            masks = run_sam(gen, img)
            rows = classify(masks, lines_px, corridor, mpp)
            cache.write_text(json.dumps({"n_masks": len(masks), "rows": rows}, ensure_ascii=False), encoding="utf-8")
            rows = {"n_masks": len(masks), "rows": rows}
            print(i, pc["조각"], "masks", len(masks), f"{time.time() - t0:.0f}s", flush=True)
        n_masks, rws = rows["n_masks"], rows["rows"]
        spec = [r for r in rws if r["spec"]]
        conf = [r for r in spec if r["corridor"]]
        rec.update(n_masks=n_masks, n_spec=len(spec), n_corr=sum(r["corridor"] for r in rws), n_conf=len(conf),
                   fp_removed=len(spec) - len(conf))
        if pc["조각"] == "변정7길":
            rec["_fig"] = {"img": img, "rows": rws, "corridor": corridor}
        rd = readings.get(pc["조각"]) or next((v for k, v in readings.items() if norm(k) == pc["road_name"]), None)
        seen = rd.get("parked_vehicles_seen") if rd else None
        if conf:
            lats = [r["lateral_m"] for r in conf]
            med, mx = float(np.median(lats)), max(lats)
            rec.update(lat_med=round(med, 2), lat_max=round(mx, 2), W_pass=round(rbt - med, 2), W_worst=round(rbt - mx, 2))
            rec["status"] = band(rec["W_worst"])
        elif (isinstance(seen, int) and seen >= 1) or isinstance(seen, str):
            rec.update(status="UNKNOWN_FAIL_CLOSED_미탐")
        else:
            rec.update(W_pass=rbt, W_worst=rbt, status="차량없음_road_bt적용")
        results.append(rec)

        # 검증셋 대조창(§25-2 창, 선형 가로 정렬)
        if rd is not None:
            v = WORK / f"val_{i:02d}.json"
            p0 = np.array(to_px(*near.interpolate(max(0, near.project(npt) - 5)).coords[0]))
            p1 = np.array(to_px(*near.interpolate(min(near.length, near.project(npt) + 5)).coords[0]))
            d = (p1 - p0) / UP
            ang = math.degrees(math.atan2(d[1], d[0]))
            M = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)
            rot = cv2.warpAffine(arr, M, (arr.shape[1], arr.shape[0]), flags=cv2.INTER_CUBIC)
            dv = M[:, :2] @ d
            assert abs(dv[1]) < 1e-6 * max(1, abs(dv[0])) + 1e-3, dv
            hw, hh = int(round(16 / g)), int(round(12 / g))
            vx0, vy0 = int(round(cx - hw)), int(round(cy - hh))
            vimg = np.array(Image.fromarray(rot[vy0:vy0 + 2 * hh, vx0:vx0 + 2 * hw]).resize((2 * hw * UP, 2 * hh * UP), Image.BICUBIC))

            def vpx(x, y):
                qx, qy = gpx(*T54.transform(x, y))
                q = M @ np.array([qx - ox, qy - oy, 1.0])
                return ((q[0] - vx0) * UP, (q[1] - vy0) * UP)
            vlines = [LineString([vpx(x, y) for x, y in l.coords]) for l in lines_of(geom)]
            vcorr = MultiLineString(vlines).buffer((rbt / 2) / mpp)
            if v.exists():
                vv = json.loads(v.read_text(encoding="utf-8"))
            else:
                t0 = time.time()
                vm = run_sam(gen, vimg)
                vv = {"n_masks": len(vm), "rows": classify(vm, vlines, vcorr, mpp)}
                v.write_text(json.dumps(vv, ensure_ascii=False), encoding="utf-8")
                print(i, pc["조각"], "val masks", len(vm), f"{time.time() - t0:.0f}s", flush=True)
            vconf = [r for r in vv["rows"] if r["spec"] and r["corridor"]]
            vrec = {"연번": pc["연번"], "조각": pc["조각"], "사람_대수": seen, "AI_확정_대수": len(vconf),
                    "사람_판독폭": rd.get("width_read_m"), "note": rd.get("note")}
            if vconf:
                vrec["W_worst_창"] = round(rbt - max(r["lateral_m"] for r in vconf), 2)
            val.append(vrec)

    write_outputs(results, val, old)


def write_outputs(results, val, old):
    DELIV.mkdir(parents=True, exist_ok=True)
    rows1 = []
    for r in results:
        st = r["status"]
        orow = old.get((r["시군구"], r["조각"]), {})
        o = orow.get("판정(차감폭)", "")
        ded = orow.get("차감폭 최소(m)", "")
        ded = float(ded) if ded not in ("", None) else None
        ww = r.get("W_worst")
        # §34-13 최종채택 = min(차감폭, W_worst)
        if st == "UNKNOWN_FAIL_CLOSED_미탐":
            final, basis, fst = None, "판정 보류(미탐) — min 미적용", st
        else:
            vals = [(v, k) for v, k in ((ded, "차감폭"), (ww, "W_worst")) if v is not None]
            if not vals:
                final, basis, fst = None, "두 값 모두 없음", "UNKNOWN_FAIL_CLOSED"
            else:
                final, which = min(vals, key=lambda t: t[0])
                basis = which if len(vals) == 2 else f"{which}(다른 값 없음)"
                fst = band(final)
        if final is None:
            mode, E, block = "보류", None, ""
        else:
            mode, E, block = separation(final)
        if not o:
            change = "비교 불가"
        else:
            dr = RANK[fst] - RANK[o]
            change = "상향" if dr > 0 else ("강등" if dr < 0 else "동일")
        note = []
        if st == "차량없음_road_bt적용":
            note.append("W_worst 는 road_bt 그대로(확정 차량 0 · 미탐 가능)")
        if change == "상향":
            note.append(f"상향 잔존: 차감폭 {ded} · W_worst {ww}")
        if r.get("reason"):
            note.append(r["reason"])
        rows1.append({"시군구": r["시군구"], "조각": r["조각"], "도로명": r["road_name"], "road_bt": r.get("road_bt", ""),
                      "확정차량수": r.get("n_conf", ""), "횡점유중앙(m)": r.get("lat_med", ""), "횡점유최대(m)": r.get("lat_max", ""),
                      "W_pass(m)": r.get("W_pass", ""), "SAM판정(W_worst)": st,
                      "내접폭차감(m)": "" if ded is None else ded, "W_worst(m)": "" if ww is None else ww,
                      "최종채택(m)": "" if final is None else round(final, 2), "채택근거(둘중작은값)": basis,
                      "판정(최종채택)": fst, "기존판정(내접폭)": o, "판정변화": change, "비고": " / ".join(note),
                      "분리방식": mode, "일반차량_진입차단_필요": block, "임계근거": (f"E={E} m · " if E else "") + SRC_NOTE})
    with (DELIV / "통행가능폭_주차차감_37조각.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows1[0].keys()))
        w.writeheader()
        w.writerows(rows1)

    rows2, tot = [], dict(a=0, b=0, c=0, d=0, e=0)
    for r in results:
        if "n_masks" not in r:
            continue
        rate = round(100 * r["fp_removed"] / r["n_spec"], 1) if r["n_spec"] else ""
        rows2.append({"조각": r["조각"], "SAM원마스크": r["n_masks"], "규격선험통과": r["n_spec"], "회랑안": r["n_corr"],
                      "확정(둘다)": r["n_conf"], "규격선험만통과했으나_회랑밖(=오탐제거수)": r["fp_removed"], "오탐제거율(%)": rate})
        tot["a"] += r["n_masks"]; tot["b"] += r["n_spec"]; tot["c"] += r["n_corr"]; tot["d"] += r["n_conf"]; tot["e"] += r["fp_removed"]
    rows2.append({"조각": "합계", "SAM원마스크": tot["a"], "규격선험통과": tot["b"], "회랑안": tot["c"], "확정(둘다)": tot["d"],
                  "규격선험만통과했으나_회랑밖(=오탐제거수)": tot["e"], "오탐제거율(%)": round(100 * tot["e"] / tot["b"], 1) if tot["b"] else ""})
    with (DELIV / "회랑필터_전후_오탐.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows2[0].keys()))
        w.writeheader()
        w.writerows(rows2)

    rows3, match, diff = [], 0, 0
    for v in val:
        h = v["사람_대수"]
        if not isinstance(h, int):
            d = "대조 불가"
        else:
            d = v["AI_확정_대수"] - h
            match += d == 0
            diff += d != 0
        width = "잔여노면 판독 없음"
        if v.get("note") and "3.5~4" in v["note"]:
            ww = v.get("W_worst_창")
            width = "대조 불가(확정 차량 0)" if ww is None else ("부합" if 3.5 - 1 <= ww <= 4 + 1 else "차이") + f" (판독 3.5~4 m · W_worst {ww} m)"
        rows3.append({"연번": v["연번"], "조각": v["조각"], "사람_대수": h if h is not None else "null", "AI_확정_대수": v["AI_확정_대수"],
                      "차이": d, "사람_판독폭(m)": v["사람_판독폭"], "W_worst(m)": v.get("W_worst_창", ""), "폭_대조": width})
    with (DELIV / "차량탐지_사람대조_11조각.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows3[0].keys()))
        w.writeheader()
        w.writerows(rows3)

    summary = {"rule_commit": RULE, "n_pieces": len(results),
               "판정": dict(__import__("collections").Counter(r["판정(최종채택)"] for r in rows1)),
               "판정변화": dict(__import__("collections").Counter(r["판정변화"] for r in rows1)),
               "분리방식": dict(__import__("collections").Counter(r["분리방식"] for r in rows1)),
               "일반차량_진입차단": dict(__import__("collections").Counter(r["일반차량_진입차단_필요"] for r in rows1)),
               "회랑필터_합계": rows2[-1], "사람대조": {"대조가능": match + diff, "대수일치": match, "차이": diff}}
    (DER / "sam_vehicle_width.json").write_text(json.dumps({"summary": summary, "pieces": [{k: v for k, v in r.items() if k != "_fig"} for r in results], "validation": val}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    fig = next((r["_fig"] for r in results if "_fig" in r), None)
    if fig:
        figures(fig)


def figures(fig):
    FIG.mkdir(parents=True, exist_ok=True)
    img, rows, corr = fig["img"], fig["rows"], fig["corridor"]
    a = img.copy()
    for r in rows:
        if r["spec"]:
            cv2.polylines(a, [np.int32(r["box"])], True, (255, 60, 60), 3)
    b = img.copy()
    for poly in getattr(corr, "geoms", [corr]):
        cv2.polylines(b, [np.int32(np.array(poly.exterior.coords))], True, (255, 210, 0), 3)
    for r in rows:
        if r["spec"] and r["corridor"]:
            cv2.polylines(b, [np.int32(r["box"])], True, (40, 230, 40), 4)
    Image.fromarray(a).save(FIG / "도표9a_필터전_오탐.png")
    Image.fromarray(b).save(FIG / "도표9b_회랑필터_확정.png")
    font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 26)
    W, H = a.shape[1], a.shape[0]
    can = Image.new("RGB", (2 * W + 24, H + 64), (255, 255, 255))
    can.paste(Image.fromarray(a), (0, 0))
    can.paste(Image.fromarray(b), (W + 24, 0))
    ImageDraw.Draw(can).text((8, H + 16), "SAM 단독(좌) → 도로구간 버퍼 적용(우). 변정7길, 브이월드 Satellite z19(촬영 시점 미표기).", font=font, fill=(20, 20, 20))
    can.save(FIG / "도표9_버퍼필터_전후.png")   # 062 §3-4 용어


if __name__ == "__main__":
    sys.exit(main())
