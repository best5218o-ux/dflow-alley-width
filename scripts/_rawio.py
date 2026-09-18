"""원천 캐시(jsonl) 읽기 — 평문이 없으면 같은 이름의 .gz 를 연다.

2026-09-18 추가. 공개 저장소에는 브이월드 WFS 응답 캐시를 gzip 으로만 둔다
(road_bt_national_cells.jsonl.gz · sprd_national_lt_cells.jsonl.gz · daejeon_sprd_geom.jsonl.gz).
스크립트는 평문 .jsonl 을 먼저 찾고, 없으면 .jsonl.gz 를 읽는다. 쓰기(재수급)는 평문에만 한다.
"""
from __future__ import annotations

import gzip
from pathlib import Path


def raw_path(p: Path) -> Path:
    """실제로 존재하는 경로(평문 우선, 없으면 .gz)를 돌려준다. 둘 다 없으면 평문 경로."""
    p = Path(p)
    if p.exists():
        return p
    g = p.with_name(p.name + ".gz")
    return g if g.exists() else p


def open_raw(p: Path, encoding: str = "utf-8"):
    q = raw_path(p)
    if q.suffix == ".gz":
        return gzip.open(q, "rt", encoding=encoding)
    return q.open(encoding=encoding)


def raw_exists(p: Path) -> bool:
    return raw_path(p).exists()
