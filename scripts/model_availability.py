"""014 §3 — 오픈 모델 설치·실행 가능 여부. 기준 docs/판정기준.md §22 (실행 전 커밋 cadef64).

- 모델: Segment Anything ViT-B (코드 PyPI segment-anything, Apache-2.0 / 가중치 Meta 공식 URL) · 실행 틀 PyTorch CPU
- 가능 판정: 정사영상 타일 모자이크에서 512 px 이내 한 장 자동 마스크 추론이 5분 안에 끝남
- 입력: data/vworld/ortho_cache 의 z19 타일(키 없음) — 결과 영상은 저장·커밋하지 않고 수치만 기록
출력: data/vworld/national/derived/model_availability.json
"""
from __future__ import annotations

import hashlib
import importlib.metadata as md
import json
import platform
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CKPT = ROOT / "data/vworld/models/sam_vit_b_01ec64.pth"
CACHE = ROOT / "data/vworld/ortho_cache"
OUT = ROOT / "data/vworld/national/derived/model_availability.json"
URL = "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth"


def main():
    rec = {"rule_commit": "cadef64", "model": "Segment Anything (SAM) ViT-B", "weights_url": URL, "license": "Apache-2.0(코드·가중치, Meta 공개 저장소 표기)",
           "runtime": "PyTorch CPU", "machine": {"cpu": platform.processor(), "python": platform.python_version(), "gpu": "없음(내장 그래픽 — CUDA 미사용)"},
           "commercial_api_calls": 0}
    try:
        import torch
        from segment_anything import SamAutomaticMaskGenerator, sam_model_registry
        rec["versions"] = {"torch": torch.__version__, "segment-anything": md.version("segment-anything")}
        rec["weights_sha256"] = hashlib.sha256(CKPT.read_bytes()).hexdigest()
        rec["weights_bytes"] = CKPT.stat().st_size
        tiles = sorted(CACHE.glob("sat_19_*.jpg"))[:4]
        xs = sorted({int(p.stem.split("_")[2]) for p in tiles})
        img = Image.open(tiles[0]).convert("RGB")
        if len(tiles) >= 4:
            mos = Image.new("RGB", (512, 512))
            for i, p in enumerate(tiles):
                mos.paste(Image.open(p).convert("RGB"), ((i % 2) * 256, (i // 2) * 256))
            img = mos
        arr = np.array(img)
        rec["input"] = {"source": "브이월드 WMTS Satellite z19 캐시 타일", "shape": list(arr.shape), "tiles": [p.name for p in tiles]}
        t0 = time.time()
        sam = sam_model_registry["vit_b"](checkpoint=str(CKPT))
        sam.to("cpu")
        load_s = time.time() - t0
        gen = SamAutomaticMaskGenerator(sam, points_per_side=16)
        t1 = time.time()
        masks = gen.generate(arr)
        infer_s = time.time() - t1
        rec.update(load_seconds=round(load_s, 1), inference_seconds=round(infer_s, 1), masks=len(masks),
                   mask_area_px_p50=int(np.median([m["area"] for m in masks])) if masks else None,
                   verdict="가능" if infer_s <= 300 else "불가(5분 초과)")
    except Exception as e:  # noqa: BLE001
        rec.update(verdict="불가", error=f"{type(e).__name__}: {str(e)[:300]}")
    OUT.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rec, ensure_ascii=False))


if __name__ == "__main__":
    main()
