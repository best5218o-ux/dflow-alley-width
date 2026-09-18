"""006 §3-2(a) — 브이월드 2D 데이터 레이어 전수 목록(WFS·WMS GetCapabilities) + 출입구·도로명주소 계열 확인.

키: os.environ["VWORLD_APIKEY"] 만 참조. 저장하는 응답·URL·로그에서 키 문자열은 *** 로 치환한다(응답 XML 의 OnlineResource 포함).
규칙(실행 전 고정)
- 「총 종수」 = GetCapabilities 응답의 FeatureType(WFS) / Layer Name(WMS) 고유 개수. 두 값이 다르면 둘 다 적는다
- 출입구 관련 = 레이어 이름·제목·요약에 「출입구」「entrance」「ENTRC」 포함
- 도로명주소 도로구간 후보 = 제목에 「도로」가 들어가는 레이어 전부를 나열(코드 추정으로 확정하지 않음) — 확정은 DescribeFeatureType 의 속성(도로명 필드 유무)으로
출력: data/vworld/national/derived/vworld_layer_catalog.json · raw/vworld_caps_{wfs,wms}.xml(키 마스킹)
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"
RAW = ROOT / "data/vworld/national/raw"
KEY = os.environ["VWORLD_APIKEY"].strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
API = "https://api.vworld.kr"


def mask(s: str) -> str:
    return s.replace(KEY, "***").replace(urllib.parse.quote(KEY), "***")


def get(path, params):
    q = urllib.parse.urlencode({**params, "key": KEY, "domain": DOMAIN})
    url = f"{API}{path}?{q}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "D-FLOW contest"}), timeout=60) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read(), mask(url)
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read(), mask(url)


def local(tag):
    return tag.rsplit("}", 1)[-1]


def main():
    out = {"requests": {}}
    RAW.mkdir(parents=True, exist_ok=True)
    wfs_layers, wms_layers = [], []
    for svc, path, params in (("wfs", "/req/wfs", {"SERVICE": "WFS", "REQUEST": "GetCapabilities", "VERSION": "1.1.0"}),
                              ("wms", "/req/wms", {"SERVICE": "WMS", "REQUEST": "GetCapabilities", "VERSION": "1.3.0"})):
        st, ct, body, url = get(path, params)
        text = mask(body.decode("utf-8", "replace"))
        (RAW / f"vworld_caps_{svc}.xml").write_text(text, encoding="utf-8")
        out["requests"][svc] = {"url": url, "status": st, "content_type": ct, "bytes": len(body)}
        try:
            root = ET.fromstring(text.encode("utf-8"))
        except ET.ParseError as e:
            out["requests"][svc]["parse_error"] = str(e)[:200]
            out["requests"][svc]["head"] = text[:300]
            continue
        if svc == "wfs":
            for ft in root.iter():
                if local(ft.tag) == "FeatureType":
                    d = {local(c.tag): (c.text or "").strip() for c in ft}
                    wfs_layers.append({"name": d.get("Name"), "title": d.get("Title"), "abstract": d.get("Abstract", "")[:200]})
        else:
            for ly in root.iter():
                if local(ly.tag) == "Layer":
                    d = {local(c.tag): (c.text or "").strip() for c in ly if local(c.tag) in ("Name", "Title", "Abstract")}
                    if d.get("Name"):
                        wms_layers.append({"name": d.get("Name"), "title": d.get("Title"), "abstract": d.get("Abstract", "")[:200]})
    uniq = lambda ls: sorted({(l["name"] or "").lower(): l for l in ls if l["name"]}.values(), key=lambda l: l["name"].lower())
    wfs_u, wms_u = uniq(wfs_layers), uniq(wms_layers)
    allnames = {l["name"].lower() for l in wfs_u} | {l["name"].lower() for l in wms_u}
    hit = lambda l, pat: re.search(pat, " ".join(str(l.get(k) or "") for k in ("name", "title", "abstract")), re.I)
    out.update({
        "wfs_layer_count": len(wfs_u), "wms_layer_count": len(wms_u), "union_count": len(allnames),
        "entrance_layers": [l for l in wfs_u + wms_u if hit(l, r"출입구|entrance|entrc")],
        "road_title_layers": [l for l in wfs_u + wms_u if hit(l, r"도로")],
        "lt_l_sprd": {"in_wfs": any(l["name"].lower() == "lt_l_sprd" for l in wfs_u), "in_wms": any(l["name"].lower() == "lt_l_sprd" for l in wms_u),
                      "titles": [l["title"] for l in wfs_u + wms_u if l["name"].lower() == "lt_l_sprd"]},
        "wfs_layers": wfs_u, "wms_layers": wms_u,
    })
    # 도로 계열 후보의 속성 확인(DescribeFeatureType)
    desc = {}
    for l in [l for l in wfs_u if hit(l, r"도로")][:12]:
        st, ct, body, url = get("/req/wfs", {"SERVICE": "WFS", "REQUEST": "DescribeFeatureType", "VERSION": "1.1.0", "TYPENAME": l["name"]})
        t = mask(body.decode("utf-8", "replace"))
        desc[l["name"]] = {"status": st, "attributes": re.findall(r'name="([^"]+)"\s+[^>]*type=', t)[:40]}
    out["road_layer_attributes"] = desc
    DER.mkdir(parents=True, exist_ok=True)
    (DER / "vworld_layer_catalog.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("requests", "wfs_layer_count", "wms_layer_count", "union_count", "entrance_layers", "lt_l_sprd")}, ensure_ascii=False))
    print(json.dumps([(l["name"], l["title"]) for l in out["road_title_layers"]], ensure_ascii=False))
    print(json.dumps(desc, ensure_ascii=False)[:3000])


if __name__ == "__main__":
    main()
