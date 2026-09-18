"""003 §7 E — 도표 5 표출용 GeoJSON 레이어(EPSG:4326) 내보내기. 키 불요.

출력: data/vworld/e5/*.geojson (Git 제외)
- daejeon_sites_v2.geojson      진입곤란 37개소 브이월드 좌표화(v2 인정 조각)
- daejeon_official_lines.geojson 진입곤란 공간정보 SHP 공식 선형(2021-11)
- daejeon_sharp_moves.geojson   대전 권역 급회전 이동 노드(θ≥90°, D) — 사이트 1 km 이내만
- itaewon_links.geojson         이태원 권역 링크(700 m)
- itaewon_locked.geojson        긴급차량 잠금 이동 노드(arm1 32, 해제 2 표시)
- itaewon_routes_arm2.geojson   arm2 확정 경로(긴급·대피·일반)
- itaewon_incident.geojson      사건 지점
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"
NL = ROOT / "data/vworld/national/raw/NODELINKDATA_20260914"
OUT = ROOT / "data/vworld/e5"


def save(gdf, name):
    OUT.mkdir(parents=True, exist_ok=True)
    gdf.to_crs(4326).to_file(OUT / name, driver="GeoJSON")
    print(name, len(gdf))


def main():
    tr = Transformer.from_crs(4326, 5186, always_xy=True)
    geo = json.loads((DER / "access37_geocode_v2.json").read_text(encoding="utf-8"))
    pts = [{"연번": r["연번"], "piece": g["piece"], "사유": r["사유"], "geometry": shapely.Point(*g["point"])}
           for r in geo["rows"] for g in r["pieces"] if g.get("v2_accepted")]
    sites = gpd.GeoDataFrame(pts, crs=4326)
    save(sites, "daejeon_sites_v2.geojson")
    shp = pyogrio.read_dataframe(glob.glob(str(ROOT / "data/vworld/national/raw/daejeon_access_geo/*.shp"))[0])
    save(shp[["인덱스", "도로명", "이유", "geometry"]], "daejeon_official_lines.geojson")

    sm = pd.read_csv(DER / "sharp_moves_targets.csv", dtype=str)  # 대상지 4곳만 저장돼 있음 → 대전은 turn_census 재계산 대신 대상지 변동분 사용
    sm = sm[sm.target == "대전 변동"]
    g = gpd.GeoDataFrame(sm, geometry=gpd.points_from_xy(sm.nx.astype(float), sm.ny.astype(float)), crs=5186)
    save(g[["a_T_NODE", "theta", "geometry"]], "daejeon_sharp_moves.geojson")

    a1 = json.loads((DER / "slot_itaewon_arm1.json").read_text(encoding="utf-8"))
    a2 = json.loads((DER / "slot_itaewon_arm2.json").read_text(encoding="utf-8"))
    locked = json.loads((DER / "slot_itaewon_arm1_locked_moves.json").read_text(encoding="utf-8"))
    released = {(x["node_id"], x["st_link"], x["ed_link"]) for x in a2["released_by_human_confirmation"]}
    N = pyogrio.read_dataframe(NL / "MOCT_NODE.shp", columns=["NODE_ID"], where="NODE_ID LIKE '102%'")
    nxy = N.set_index("NODE_ID").geometry
    lk = gpd.GeoDataFrame([{"theta": x["theta"], "released": (x["node_id"], x["st_link"], x["ed_link"]) in released,
                            "geometry": nxy[x["node_id"]]} for x in locked], crs=5186)
    save(lk, "itaewon_locked.geojson")
    L = pyogrio.read_dataframe(NL / "MOCT_LINK.shp", columns=["LINK_ID", "LANES"], where="LINK_ID LIKE '102%'")
    gantt = pd.read_csv(DER / "slot_itaewon_arm2_gantt.csv", dtype={"link_id": str})
    area_ids = set(gantt.link_id)
    # 권역 링크 전체: slot_itaewon 결과에 링크 목록이 없으므로 이태원 대표점 700 m 안 양끝으로 재선정
    probe = json.loads((DER / "vworld_probe.json").read_text(encoding="utf-8"))["items"]["4_geocoder"]["search_district"]
    sx, sy = tr.transform(*probe["서울 용산구 이태원동"]["candidates"][0]["point"])
    b = shapely.bounds(L.geometry.values)
    inside = (np.hypot(b[:, 0] - sx, b[:, 1] - sy) <= 800) | (np.hypot(b[:, 2] - sx, b[:, 3] - sy) <= 800)
    save(L[inside], "itaewon_links.geojson")
    rows = []
    after = gantt[gantt.phase == "after"]
    for actor in ["E0_evac", "G1_car", "A1_amb", "A2_amb", "A3_amb", "F1_pump"]:
        ids = set(after[after.actors.str.contains(actor)].link_id)
        if ids:
            geom = shapely.union_all(L[L.LINK_ID.isin(ids)].geometry.values)
            kind = "evac" if actor.startswith("E") else ("general" if actor.startswith("G") else "emergency")
            rows.append({"actor": actor, "kind": kind, "geometry": geom})
    save(gpd.GeoDataFrame(rows, crs=5186), "itaewon_routes_arm2.geojson")
    inc = L[L.LINK_ID == a1["incident"]["link"]]
    save(inc.assign(label="사건 지점(시나리오)"), "itaewon_incident.geojson")
    _ = area_ids


if __name__ == "__main__":
    main()
