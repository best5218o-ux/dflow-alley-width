"""016 I — 대전 공개 교통 목적 CCTV(불법주정차 단속 고정형 CCTV 단속구간) × 진입곤란 26개소 · 대전 길·번길. 기준 §28 (실행 전 커밋 b543dde).

- 키·회원가입 없이 공공데이터포털 파일데이터(로그인 불요 경로)만 사용
- 방범 목적 데이터셋(유성구 CCTV 설치현황 등)은 받지 않음
- 대조 규칙 §23: 26개소 같은 도로명 선형 30 m 이내 · 골목급 = 최근접 lt_l_sprd 15 m 이내 길·번길이며 로·대로가 더 가깝지 않음
출력: data/vworld/national/derived/daejeon_cctv_check.json (원천 파일은 data/vworld/national/raw/daejeon_cctv/, 미커밋)
"""
from __future__ import annotations

import io
import json
import re
import sys
import urllib.parse
import urllib.request
import zipfile
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/vworld/national/raw/daejeon_cctv"
DER = ROOT / "data/vworld/national/derived"
DGK = "https://www.data.go.kr"
SETS = {"15097265": "불법주정차 단속구간(고정형CCTV)_공간정보", "15076794": "불법주정차 단속구간(고정형 CCTV 단속구간)"}
UA = {"User-Agent": "Mozilla/5.0 (D-FLOW contest)"}


def download(pk):
    cj = CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    page = f"{DGK}/data/{pk}/fileData.do"
    html = op.open(urllib.request.Request(page, headers=UA), timeout=60).read().decode("utf-8", "ignore")
    m = re.search(r"fn_fileDataDown\('(\d+)',\s*'(uddi:[0-9a-f-]+)',\s*'([^']*)',\s*'(\d+)',\s*'(\d+)'\)", html)
    if not m:
        return None, "페이지에 다운로드 수단 없음"
    data = urllib.parse.urlencode({"publicDataDetailPk": m.group(2), "publicDataPk": m.group(1), "atchFileId": m.group(3),
                                   "fileDetailSn": m.group(4), "publicDataTyCode": "PR0051"}).encode()
    j = json.loads(op.open(urllib.request.Request(f"{DGK}/tcs/dss/selectFileDataDownload.do", data=data,
                                                  headers={**UA, "Referer": page, "X-Requested-With": "XMLHttpRequest"}), timeout=60).read())
    if not j.get("atchFileId"):
        return None, "첨부 ID 조회 거부"
    url = f"{DGK}/cmm/cmm/fileDownload.do?atchFileId={j['atchFileId']}&fileDetailSn={j.get('fileDetailSn') or m.group(4)}&insertDataPrcus=N"
    r = op.open(urllib.request.Request(url, headers={**UA, "Referer": page}), timeout=120)
    ct = r.headers.get("Content-Type", "")
    body = r.read()
    if "text/html" in ct.lower():
        return None, "파일 대신 HTML(로그인 요구 가능)"
    cd = r.headers.get("Content-Disposition", "")
    name = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
    fname = urllib.parse.unquote(name.group(1)) if name else f"{pk}.bin"
    RAW.mkdir(parents=True, exist_ok=True)
    p = RAW / re.sub(r'[\\/:*?"<>|]+', "_", fname)
    p.write_bytes(body)
    return p, None


def main():
    got = {}
    for pk, label in SETS.items():
        for attempt in range(3):
            try:
                p, err = download(pk)
                break
            except Exception as e:  # noqa: BLE001
                p, err = None, type(e).__name__
        got[pk] = {"label": label, "file": p.name if p else None, "error": err, "bytes": p.stat().st_size if p else None}
    print(json.dumps(got, ensure_ascii=False))
    (DER / "daejeon_cctv_check.json").write_text(json.dumps({"rule_commit": "b543dde", "downloads": got}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
