"""016 I — 대전 불법주정차 단속 고정형 CCTV(교통 목적, 공공데이터포털 15076794) 위경도 × lt_l_sprd 대조. 기준 §28·§23 (b543dde).

- 26개소: 26개소 도로명 조각과 같은 도로명 선형 30 m 이내 CCTV 수
- 골목급: 최근접 lt_l_sprd 선형 15 m 이내이고 그 선형 위계가 길·번길(= 15 m 안에서 로·대로가 더 가깝지 않음)
- 영상은 받지 않음(파일에 영상 없음). 좌표·집계만
출력: data/vworld/national/derived/daejeon_cctv_match.json · deliverables/대전_단속CCTV_골목급대조.csv
"""
from __future__ import annotations

import csv
import glob
import io
import json
import sys
from pathlib import Path

import pandas as pd
import shapely
from pyproj import Transformer
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hierarchy_compare import tier  # noqa: E402
from inclusion_rate import norm  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"
DELIV = ROOT / "deliverables"


def main():
    f = [p for p in glob.glob(str(ROOT / "data/vworld/national/raw/daejeon_cctv/*.csv"))][0]
    cam = pd.read_csv(io.StringIO(open(f, "rb").read().decode("utf-8-sig")), dtype=str)
    t = Transformer.from_crs(4326, 5186, always_xy=True)
    lat, lon = pd.to_numeric(cam["위도"], errors="coerce"), pd.to_numeric(cam["경도"], errors="coerce")
    ok = lat.between(36.1, 36.6) & lon.between(127.2, 127.6)
    cam = cam[ok].copy()
    xy = [t.transform(a, b) for a, b in zip(lon[ok], lat[ok])]
    segs = []
    for line in open(ROOT / "data/vworld/national/raw/daejeon_sprd_geom.jsonl", encoding="utf-8"):
        r = json.loads(line)
        segs.append((norm(r["rn"]), shapely.from_wkt(r["wkt"])))
    geoms = [g for _, g in segs]
    tree = shapely.STRtree(geoms)
    cc = json.loads((DER / "missing_alley_crosscheck.json").read_text(encoding="utf-8"))
    names26 = {p["road_name"] for s in cc["sites"] for p in s["pieces"] if p["type"] == "road"}
    rows = []
    for (x, y), rec in zip(xy, cam.itertuples()):
        pt = Point(x, y)
        near = tree.query(pt, predicate="dwithin", distance=30.0)
        cand = sorted(((geoms[i].distance(pt), segs[i][0]) for i in near), key=lambda z: z[0])
        nearest = cand[0] if cand else None
        in15 = [c for c in cand if c[0] <= 15]
        alley = bool(in15) and tier(in15[0][1]) in ("길", "번길")
        on26 = sorted({n for d, n in cand if d <= 30 and n in names26})
        rows.append({"관리번호": rec.관리번호, "시군구명": rec.시군구명, "주소": rec.주소, "nearest_road": nearest[1] if nearest else None,
                     "nearest_m": round(nearest[0], 1) if nearest else None, "nearest_tier": tier(nearest[1]) if nearest else None,
                     "alley_level": alley, "within30m_26site_names": on26})
    df = pd.DataFrame(rows)
    out = {"rule_commit": "b543dde", "source": "공공데이터포털 15076794 대전광역시_불법주정차 단속구간(고정형 CCTV 단속구간) — 교통(주정차 단속) 목적, 영상 없음, 좌표만",
           "cameras_total": int(len(cam)), "coord_excluded": int((~ok).sum()),
           "alley_level_cameras": int(df.alley_level.sum()), "alley_level_by_tier": df[df.alley_level].nearest_tier.value_counts().to_dict(),
           "nearest_tier_distribution(≤30m)": df.nearest_tier.value_counts().to_dict(), "no_road_within_30m": int(df.nearest_road.isna().sum()),
           "cameras_within30m_of_26site_same_name_road": int((df.within30m_26site_names.str.len() > 0).sum()),
           "26site_names_hit": sorted({n for v in df.within30m_26site_names for n in v}),
           "alley_level_list": df[df.alley_level][["관리번호", "시군구명", "주소", "nearest_road", "nearest_m"]].to_dict("records"),
           "note": "주정차는 주제가 아니라 관측 원천 유무 확인용 · 설치 좌표가 골목급이어도 영상은 공개되지 않음(이 파일은 좌표·대표이미지 번호만)"}
    (DER / "daejeon_cctv_match.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    DELIV.mkdir(parents=True, exist_ok=True)
    df.to_csv(DELIV / "대전_단속CCTV_골목급대조.csv", index=False, encoding="utf-8-sig", columns=["관리번호", "시군구명", "주소", "nearest_road", "nearest_m", "nearest_tier", "alley_level", "within30m_26site_names"])
    print(json.dumps({k: v for k, v in out.items() if k != "alley_level_list"}, ensure_ascii=False))
    print(out["alley_level_list"][:15])


if __name__ == "__main__":
    main()
