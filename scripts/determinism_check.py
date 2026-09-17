"""SAM 결정성 검사 (D-070 Part E-3) — 변정7길 1조각만 같은 입력·같은 시드로 재실행해 캐시와 대조한다.

캐시(sam_vehicle_cache/work_XX.json)는 덮어쓰지 않는다. 타일은 로컬 캐시에서 읽는다(없을 때만 키 사용).
산출: data/vworld/national/derived/determinism_check.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import shapely.wkt
import torch
from PIL import Image
from shapely.geometry import LineString, MultiLineString, Point

sys.path.insert(0, str(Path(__file__).parent))
import sam_vehicle_width as sv  # noqa: E402

TARGET = "변정7길"


def main():
    torch.manual_seed(0)
    np.random.seed(0)
    roads = sv.load_roads()
    for i, pc in enumerate(sv.pieces()):
        if pc["조각"] != TARGET:
            continue
        lon, lat = pc["point"]
        mpp = sv.gsd(lat) / sv.UP
        px, py = sv.T45.transform(lon, lat)
        row = min(roads[pc["road_name"]], key=lambda r: shapely.wkt.loads(r["wkt"]).distance(Point(px, py)))
        geom = shapely.wkt.loads(row["wkt"])
        rbt = float(row["road_bt"])
        near = min(sv.lines_of(geom), key=lambda l: l.distance(Point(px, py)))
        npt = near.interpolate(near.project(Point(px, py)))
        gx, gy = sv.gpx(*sv.T54.transform(npt.x, npt.y))
        arr, ox, oy = sv.mosaic(gx, gy, 260)
        cx, cy = gx - ox, gy - oy
        x0, y0 = int(round(cx - sv.WIN / 2)), int(round(cy - sv.WIN / 2))
        img = np.array(Image.fromarray(arr[y0:y0 + sv.WIN, x0:x0 + sv.WIN]).resize((sv.WIN * sv.UP, sv.WIN * sv.UP), Image.BICUBIC))

        def to_px(x, y):
            qx, qy = sv.gpx(*sv.T54.transform(x, y))
            return ((qx - ox) - x0) * sv.UP, ((qy - oy) - y0) * sv.UP
        lines_px = [LineString([to_px(x, y) for x, y in l.coords]) for l in sv.lines_of(geom)]
        corridor = MultiLineString(lines_px).buffer((rbt / 2) / mpp)
        from segment_anything import SamAutomaticMaskGenerator, sam_model_registry
        sam = sam_model_registry["vit_b"](checkpoint=str(sv.CKPT))
        sam.to("cpu")
        gen = SamAutomaticMaskGenerator(sam, points_per_side=32, pred_iou_thresh=0.86, stability_score_thresh=0.90, min_mask_region_area=300)
        t0 = time.time()
        masks = sv.run_sam(gen, img)
        rows = sv.classify(masks, lines_px, corridor, mpp)
        n_new = len(rows)
        cache = json.loads((sv.WORK / f"work_{i:02d}.json").read_text(encoding="utf-8"))
        def summ(n_masks, rws):
            spec = [r for r in rws if r["spec"]]
            conf = [r for r in spec if r["corridor"]]
            return {"n_masks": n_masks, "n_spec": len(spec), "n_corr": sum(r["corridor"] for r in rws), "n_conf": len(conf),
                    "lat_max": max((r["lateral_m"] for r in conf), default=None)}
        new = summ(len(masks), rows)   # 071 §3-2 — 재실행 원 마스크 수를 채운다
        old = summ(cache["n_masks"], cache["rows"])
        # classify 는 윤곽 없는 마스크를 건너뛰므로 원 마스크 수(n_masks)와 행 수(rows)를 둘 다 비교한다
        new["rows"], old["rows"] = n_new, len(cache["rows"])
        same_rows = [{k: r[k] for k in ("A", "L", "S", "R", "spec", "corridor", "lateral_m")} for r in rows] == \
                    [{k: r[k] for k in ("A", "L", "S", "R", "spec", "corridor", "lateral_m")} for r in cache["rows"]]
        out = {"조각": TARGET, "캐시": old, "재실행": new, "행 단위 완전 일치": same_rows,
               "차량후보·규격·버퍼 집계 일치": all(new[k] == old[k] for k in ("n_masks", "n_spec", "n_corr", "n_conf", "lat_max", "rows")),
               "소요초": round(time.time() - t0), "torch": torch.__version__}
        (sv.DER / "determinism_check.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False))
        return


if __name__ == "__main__":
    main()
