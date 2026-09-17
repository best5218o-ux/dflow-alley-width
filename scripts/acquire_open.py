"""D-001 A조 — 로그인 없이 받을 수 있는 원천만 내려받고 절차를 기록한다.

- 인증키·세션값은 받지도 기록하지도 않는다.
- 소요시간은 「포털 페이지 요청 시작 → 파일 디스크 기록 완료」(스크립트 실측)이다.
  사람이 브라우저로 받는 시간과 같지 않다.
- 원본은 data/vworld/national/raw/ 에 무수정 보관한다(.gitignore deny).

실행: python scripts/acquire_open.py [source_id ...]
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # 저장소 루트(scripts/ 한 단계 위)
RAW = ROOT / "data" / "vworld" / "national" / "raw"
LOG = ROOT / "data" / "vworld" / "national" / "acquire_log.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
DGK = "https://www.data.go.kr"

SOURCES = {
    # 연번 2 — 전국 1파일. 목록 페이지의 최신 항목 링크를 그대로 따른다.
    "nodelink": {"kind": "its", "page": "https://www.its.go.kr/nodelink/nodelinkRef",
                 "href": "https://www.its.go.kr/opendata/nodelinkFileSDownload/DF_220/0",
                 "label": "[2026-09-14]NODELINKDATA.zip (목록 표기 258.69MB)"},
    # 연번 5 — 원고의 「전국 도로교량 및 터널 표준데이터」는 현재 포털에 그 이름으로 없다.
    #          교량·터널이 별도 파일데이터로 나뉘어 있다.
    "bridge": {"kind": "datagokr", "page": f"{DGK}/data/15081953/fileData.do"},
    "tunnel": {"kind": "datagokr", "page": f"{DGK}/data/15081955/fileData.do"},
    # 001 §10 — 연번 16 대전광역시 소방차 진입곤란(불가)지역
    "daejeon_access": {"kind": "datagokr", "page": f"{DGK}/data/15080770/fileData.do"},
    # 001 §10 — 연번 16b 같은 대상의 공간정보판(포털 검색에서 발견)
    "daejeon_access_geo": {"kind": "datagokr", "page": f"{DGK}/data/15097262/fileData.do"},
    # 004 §6-5 — 연번 15 소방용수시설(서울, 이태원 권역 C 3안 「소화전 인근」 입력)
    # data.go.kr 15146212 는 「기관자체에서 다운로드」 → 서울열린데이터광장 OA-21306 으로 이동. 그쪽 파일 폼(POST)을 따른다.
    "seoul_hydrant": {"kind": "seoul", "page": "https://data.seoul.go.kr/dataList/OA-21306/S/1/datasetView.do",
                      "form": {"infId": "OA-21306", "seqNo": "", "seq": "6", "infSeq": "1"},
                      "label": "서울시 소방재난본부_소방용수시설_20251231.csv"},
}


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _req(url, data=None, referer=None, xhr=False):
    h = {"User-Agent": UA}
    if referer:
        h["Referer"] = referer
    if xhr:
        h["X-Requested-With"] = "XMLHttpRequest"
        h["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    body = urllib.parse.urlencode(data).encode() if data else None
    return urllib.request.urlopen(urllib.request.Request(url, data=body, headers=h), timeout=600)


def _filename(headers) -> str | None:
    cd = headers.get("Content-Disposition") or ""
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd, re.I) or re.search(r'filename="?([^";]+)"?', cd, re.I)
    if not m:
        return None
    raw = m.group(1)
    if "%" in raw:
        return urllib.parse.unquote(raw)
    for enc in ("utf-8", "cp949"):
        try:
            return raw.encode("latin-1").decode(enc)
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return raw


def _stream(resp, path: Path) -> tuple[int, str]:
    h = hashlib.sha256()
    n = 0
    with path.open("wb") as f:
        while chunk := resp.read(1 << 20):
            f.write(chunk)
            h.update(chunk)
            n += len(chunk)
    return n, h.hexdigest()


def acquire(sid: str) -> dict:
    spec = SOURCES[sid]
    e = {"source_id": sid, "page": spec["page"], "started_at": _now(), "login_required": None}
    t0 = time.perf_counter()
    html = _req(spec["page"]).read().decode("utf-8", "ignore")
    if spec["kind"] == "its":
        url, ref = spec["href"], spec["page"]
        e["portal_label"] = spec["label"]
    elif spec["kind"] == "seoul":
        e["portal_label"] = spec["label"]
        resp = _req("https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false", spec["form"], referer=spec["page"])
        ctype = resp.headers.get("Content-Type", "")
        if "text/html" in ctype.lower():
            e.update(status="BLOCKED", reason="파일 대신 HTML 응답", elapsed_s=round(time.perf_counter() - t0, 1))
            return e
        name = re.sub(r'[\/:*?"<>|]+', "_", _filename(resp.headers) or spec["label"])
        RAW.mkdir(parents=True, exist_ok=True)
        size, sha = _stream(resp, RAW / name)
        e.update(status="DOWNLOADED", login_required=False, file_name=name, content_type=ctype, size_bytes=size, sha256=sha,
                 finished_at=_now(), elapsed_s=round(time.perf_counter() - t0, 1))
        return e
    else:
        title = re.search(r"<title>([^<|]+)", html)
        e["portal_title"] = title.group(1).strip() if title else None
        m = re.search(r"fn_fileDataDown\('(\d+)',\s*'(uddi:[0-9a-f-]+)',\s*'([^']*)',\s*'(\d+)',\s*'(\d+)'\)", html)
        if not m:
            e.update(status="BLOCKED", reason="페이지에 다운로드 수단 없음", elapsed_s=round(time.perf_counter() - t0, 1))
            return e
        j = json.loads(_req(f"{DGK}/tcs/dss/selectFileDataDownload.do", {
            "publicDataDetailPk": m.group(2), "publicDataPk": m.group(1), "atchFileId": m.group(3),
            "fileDetailSn": m.group(4), "publicDataTyCode": "PR0051"}, referer=spec["page"], xhr=True).read())
        if not j.get("status") or not j.get("atchFileId"):
            e.update(status="BLOCKED", reason=f"첨부 ID 조회 거부: {str(j.get('error'))[:80]}")
            return e
        url = f"{DGK}/cmm/cmm/fileDownload.do?atchFileId={j['atchFileId']}&fileDetailSn={j.get('fileDetailSn') or m.group(4)}&insertDataPrcus=N"
        ref = spec["page"]
    resp = _req(url, referer=ref)
    ctype = resp.headers.get("Content-Type", "")
    if "text/html" in ctype.lower():
        e.update(status="BLOCKED", reason="파일 대신 HTML 응답(로그인 요구 가능)", elapsed_s=round(time.perf_counter() - t0, 1))
        return e
    name = re.sub(r'[\\/:*?"<>|]+', "_", _filename(resp.headers) or f"{sid}.bin")
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / name
    size, sha = _stream(resp, path)
    e.update(status="DOWNLOADED", login_required=False, file_name=name, content_type=ctype,
             size_bytes=size, sha256=sha, finished_at=_now(), elapsed_s=round(time.perf_counter() - t0, 1))
    return e


def main(argv):
    ids = argv or list(SOURCES)
    log = json.loads(LOG.read_text(encoding="utf-8")) if LOG.exists() else []
    for sid in ids:
        for attempt in range(1, 4):  # 재시도 3회
            try:
                e = acquire(sid)
            except Exception as exc:  # noqa: BLE001 — 실패 사유를 그대로 남긴다
                e = {"source_id": sid, "status": "ERROR", "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
            e["attempt"] = attempt
            log.append(e)
            print(json.dumps({k: e.get(k) for k in ("source_id", "status", "file_name", "size_bytes", "elapsed_s", "reason", "error")}, ensure_ascii=False))
            if e["status"] in ("DOWNLOADED", "BLOCKED"):
                break
        LOG.parent.mkdir(parents=True, exist_ok=True)
        LOG.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
