"""D-001 §9 — 브이월드 API 5종 실증 + 대상지 시드 좌표 재확인.

키 취급
- 키는 os.environ["VWORLD_APIKEY"] 로만 읽는다. 코드·출력·로그 어디에도 값을 남기지 않는다.
- 로그에 남기는 URL·오류문은 키를 *** 로 치환한 뒤 기록한다(_mask).

도메인·Referer 제한 확인
- 같은 요청을 (a) Referer·DOMAIN 없이 (b) DOMAIN 파라미터만 (c) Referer 헤더만 붙여 보내 결과를 비교한다.

출력: data/vworld/national/derived/vworld_probe.json (키 없음) + 콘솔 요약
실행: VWORLD_APIKEY 가 보이는 프로세스에서
      python scripts/vworld_api_probe.py
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # 저장소 루트(scripts/ 한 단계 위)
OUT = ROOT / "data/vworld/national/derived/vworld_probe.json"
KEY = os.environ.get("VWORLD_APIKEY", "").strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
if not KEY:
    # 2026-09-18: 네트워크 단계(브이월드 WFS/WMS 조회)라 키 없이는 재수급할 수 없다. 원 실행(2026-09-15~16) 산출은
    # data/vworld/national/derived/vworld_probe.json 에 있고, 검증은 scripts/verify_deliverables.py 로 한다.
    sys.exit("VWORLD_APIKEY 없음 — 이 스크립트는 브이월드 API 조회 단계다. 원 실행 산출: data/vworld/national/derived/vworld_probe.json")
UA = "Mozilla/5.0 (D-FLOW contest probe)"
API = "https://api.vworld.kr"


def _mask(s: str) -> str:
    return s.replace(KEY, "***").replace(urllib.parse.quote(KEY), "***")


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def fetch(url: str, referer: str | None = None, keep_body: bool = False) -> dict:
    h = {"User-Agent": UA}
    if referer:
        h["Referer"] = referer
    rec = {"url": _mask(url), "referer": referer, "at": _now()}
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
            body = r.read()
            rec.update(status=r.status, content_type=r.headers.get("Content-Type"), bytes=len(body))
    except urllib.error.HTTPError as e:
        body = e.read()
        rec.update(status=e.code, content_type=e.headers.get("Content-Type"), bytes=len(body))
    except Exception as e:  # noqa: BLE001 — 네트워크 실패도 그대로 기록
        rec.update(status=None, error=_mask(f"{type(e).__name__}: {e}"))
        body = b""
    rec["elapsed_ms"] = round((time.perf_counter() - t0) * 1000)
    ct = (rec.get("content_type") or "").lower()
    if body and ("json" in ct or "xml" in ct or "text" in ct or "javascript" in ct):
        rec["head"] = _mask(body[:300].decode("utf-8", "replace"))
    if body[:8] == b"\x89PNG\r\n\x1a\n":
        rec["magic"] = "PNG"
    elif body[:3] == b"\xff\xd8\xff":
        rec["magic"] = "JPEG"
    if keep_body:
        rec["_body"] = body
    return rec


def tile_xy(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def variants(url_no_domain: str, domain_param: str) -> dict:
    """(a) 없음 (b) DOMAIN 파라미터 (c) Referer 헤더."""
    return {
        "a_none": fetch(url_no_domain),
        "b_domain_param": fetch(url_no_domain + ("&" if "?" in url_no_domain else "?") + domain_param),
        "c_referer_header": fetch(url_no_domain, referer="http://localhost/"),
    }


# 이태원역 부근 — 요청 위치만 정한다(결과 수치에 쓰지 않음)
LON, LAT = 126.9946, 37.5345
BBOX_4326 = (126.9930, 37.5335, 126.9960, 37.5355)  # 약 260 m × 220 m


def main():
    res = {"run_at": _now(), "key_len": len(KEY), "items": {}}
    z = 17
    x, y = tile_xy(LON, LAT, z)

    # 1 2D 배경지도 TMS(WMTS 타일 경로)
    base = f"{API}/req/wmts/1.0.0/{KEY}/Base/{z}/{y}/{x}.png"
    res["items"]["1_base_tms"] = {"tile": [z, x, y], **variants(base, "domain=localhost")}

    # 5 항공사진 정사영상 TMS
    sat = f"{API}/req/wmts/1.0.0/{KEY}/Satellite/{z}/{y}/{x}.jpeg"
    res["items"]["5_satellite_tms"] = {"tile": [z, x, y], **variants(sat, "domain=localhost")}

    # 3a WMS GetMap — 도로명주소건물 레이어
    b = BBOX_4326
    wms = (f"{API}/req/wms?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&LAYERS=lt_c_spbd&STYLES=lt_c_spbd"
           f"&CRS=EPSG:4326&BBOX={b[1]},{b[0]},{b[3]},{b[2]}&WIDTH=512&HEIGHT=512&FORMAT=image/png"
           f"&TRANSPARENT=true&KEY={KEY}")
    res["items"]["3a_wms_getmap"] = variants(wms, "DOMAIN=localhost")

    # 3b WFS GetFeature — 같은 레이어, 피처 건수
    wfs = (f"{API}/req/wfs?SERVICE=WFS&REQUEST=GetFeature&VERSION=1.1.0&TYPENAME=lt_c_spbd"
           f"&BBOX={b[1]},{b[0]},{b[3]},{b[2]},EPSG:4326&SRSNAME=EPSG:4326&MAXFEATURES=1000"
           f"&OUTPUT=application/json&KEY={KEY}")
    v = variants(wfs, "DOMAIN=localhost")
    for k, r in v.items():
        rr = fetch(r["url"].replace("***", KEY), referer=r.get("referer"), keep_body=True)
        body = rr.pop("_body", b"")
        try:
            j = json.loads(body.decode("utf-8"))
            r["feature_count"] = len(j.get("features", []))
            r["response_crs"] = (j.get("crs") or {}).get("properties", {}).get("name")
        except Exception:  # noqa: BLE001
            r["feature_count"] = None
    res["items"]["3b_wfs_getfeature"] = v

    # 3c 2D 데이터 API(REST) GetFeature — 원고 연번 6 경로
    data = (f"{API}/req/data?service=data&request=GetFeature&version=2.0&data=LT_C_SPBD&format=json"
            f"&size=1000&page=1&geometry=false&attribute=true&crs=EPSG:4326"
            f"&geomFilter=BOX({b[0]},{b[1]},{b[2]},{b[3]})&key={KEY}")
    v = variants(data, "domain=localhost")
    for k, r in v.items():
        rr = fetch(r["url"].replace("***", KEY), referer=r.get("referer"), keep_body=True)
        body = rr.pop("_body", b"")
        try:
            j = json.loads(body.decode("utf-8"))["response"]
            r["api_status"] = j.get("status")
            r["record_total"] = (j.get("record") or {}).get("total")
            r["error_text"] = _mask(str((j.get("error") or {}).get("text"))) if j.get("error") else None
        except Exception:  # noqa: BLE001
            r["api_status"] = None
    res["items"]["3c_data_api"] = v

    # 2 WebGL 3D — 스크립트로 가능한 범위: JS 로더가 키로 응답하는지까지만
    webgl = f"https://map.vworld.kr/js/webglMapInit.js.do?version=3.0&apiKey={KEY}"
    res["items"]["2_webgl_3d_loader"] = variants(webgl, "domain=localhost")
    res["items"]["2_webgl_3d_loader"]["note"] = "JS 로더 응답까지만 확인. 3D 타일 렌더링은 스크립트로 미검증."

    # 4 지오코더 + 시드 재확인
    res["items"]["4_geocoder"] = geocode_block()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    raw = OUT.read_text(encoding="utf-8")
    assert KEY not in raw, "키가 출력 파일에 남음"
    summarize(res)


SEEDS = [  # (라벨, 행정구역 질의, 비교용 기존 시드 lon, lat, 기존 출처)
    ("서울 용산구 이태원동", "서울특별시 용산구 이태원동", 126.9946, 37.5345, "수기 근사"),
    ("부산 동구 초량동", "부산광역시 동구 초량동", 129.0370, 35.1190, "수기 근사"),
    ("부산 부산진구 전포동", "부산광역시 부산진구 전포동", 129.0650, 35.1540, "수기 근사"),
    ("청주 상당구 수동", "충청북도 청주시 상당구 수동", 127.4960, 36.6405, "수기 근사"),
    ("청주 서원구 모충동", "충청북도 청주시 서원구 모충동", 127.4800, 36.6250, "수기 근사"),
    ("청주 청원구 내덕동", "충청북도 청주시 청원구 내덕동", 127.47426, 36.6591, "교량 소재지 주소 평균"),
    ("대전 서구 변동", "대전광역시 서구 변동", 127.38577, 36.32333, "교량 소재지(태평교)"),
    ("부산 동래구 온천동", "부산광역시 동래구 온천동", 129.06769, 35.21157, "교량 소재지 주소 평균"),
]


def _meters(lon1, lat1, lon2, lat2):
    kx = 111320 * math.cos(math.radians((lat1 + lat2) / 2))
    return round(math.hypot((lon1 - lon2) * kx, (lat1 - lat2) * 110540))


def geocode_block() -> dict:
    out = {"address_api": {}, "search_district": {}}
    # (i) 지오코더 API — 주소→좌표. 동 이름만으로는 번지가 없어 실패할 수 있다 → 그대로 기록
    probe_addr = "서울특별시 용산구 이태원동 34-149"  # 시험용 지번 1건 — 성공/실패 형식 확인용
    for label, q in [("probe_parcel", probe_addr)] + [(s[0], s[1]) for s in SEEDS]:
        url = (f"{API}/req/address?service=address&request=getcoord&version=2.0&crs=epsg:4326"
               f"&address={urllib.parse.quote(q)}&refine=true&simple=false&format=json&type=parcel&key={KEY}")
        r = fetch(url, keep_body=True)
        body = r.pop("_body", b"")
        try:
            j = json.loads(body.decode("utf-8"))["response"]
            r["api_status"] = j.get("status")
            r["crs"] = (j.get("input") or {}).get("crs") or "epsg:4326(요청값)"
            pt = (j.get("result") or {}).get("point")
            r["point"] = [float(pt["x"]), float(pt["y"])] if pt else None
            r["refined"] = ((j.get("refined") or {}).get("text"))
            r["error_text"] = _mask(str((j.get("error") or {}).get("text"))) if j.get("error") else None
        except Exception as e:  # noqa: BLE001
            r["parse_error"] = type(e).__name__
        r.pop("head", None)
        out["address_api"][label] = r
    # (ii) 검색 API type=district — 행정동/법정동 대표점
    for label, q, lon0, lat0, src in SEEDS:
        url = (f"{API}/req/search?service=search&request=search&version=2.0&crs=EPSG:4326&size=5&page=1"
               f"&query={urllib.parse.quote(q)}&type=district&category=L4&format=json&errorformat=json&key={KEY}")
        r = fetch(url, keep_body=True)
        body = r.pop("_body", b"")
        try:
            j = json.loads(body.decode("utf-8"))["response"]
            r["api_status"] = j.get("status")
            items = ((j.get("result") or {}).get("items")) or []
            r["candidates"] = [{"title": it.get("title"), "id": it.get("id"),
                                "point": [float(it["point"]["x"]), float(it["point"]["y"])]} for it in items]
            if r["candidates"]:
                p = r["candidates"][0]["point"]
                r["shift_from_old_seed_m"] = _meters(p[0], p[1], lon0, lat0)
            r["old_seed"] = {"lon": lon0, "lat": lat0, "source": src}
            r["error_text"] = _mask(str((j.get("error") or {}).get("text"))) if j.get("error") else None
        except Exception as e:  # noqa: BLE001
            r["parse_error"] = type(e).__name__
        r.pop("head", None)
        out["search_district"][label] = r
    return out


def summarize(res):
    it = res["items"]
    for name in ("1_base_tms", "5_satellite_tms", "3a_wms_getmap", "3b_wfs_getfeature", "3c_data_api", "2_webgl_3d_loader"):
        for k in ("a_none", "b_domain_param", "c_referer_header"):
            r = it[name][k]
            extra = {x: r.get(x) for x in ("feature_count", "api_status", "record_total", "magic", "error_text", "error") if r.get(x) is not None}
            print(f"{name:20s} {k:18s} {r.get('status')} {r.get('content_type')} {r.get('bytes')} {extra}")
            if r.get("head") and not r.get("magic") and name != "2_webgl_3d_loader":
                print("   head:", r["head"][:160].replace("\n", " "))
    g = it["4_geocoder"]
    for k, r in g["address_api"].items():
        print("addr", k, r.get("status"), r.get("api_status"), r.get("point"), r.get("error_text"))
    for k, r in g["search_district"].items():
        c = (r.get("candidates") or [{}])[0]
        print("dist", k, r.get("status"), r.get("api_status"), c.get("title"), c.get("point"), r.get("shift_from_old_seed_m"), r.get("error_text"))


if __name__ == "__main__":
    main()
