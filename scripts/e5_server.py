"""003 §7 E — 도표 5 브이월드 실제 화면용 로컬 서버.

- 브이월드 2D 타일(WMTS)을 **서버에서** 키를 붙여 받아 /vw/<layer>/<z>/<y>/<x> 로 넘긴다.
  브라우저·페이지·캡처·로그에 키가 나타나지 않는다. 키는 os.environ["VWORLD_APIKEY"] 만 읽는다.
- data/vworld/e5/ 의 GeoJSON 과 docs/vworld/e5/ 의 페이지(HTML)를 정적으로 제공한다.
- 로그는 요청 경로만 찍는다(경로에 키 없음). 상류 URL 은 찍지 않는다.

실행(키가 보이는 프로세스에서): data/vworld/.venv/Scripts/python.exe scripts/e5_server.py 8765
"""
from __future__ import annotations

import http.server
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = os.environ["VWORLD_APIKEY"].strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
STATIC = {"/data/": ROOT / "data/vworld/e5", "/page/": ROOT / "docs/vworld/e5"}
TILE = re.compile(r"^/vw/(Base|Satellite|Hybrid|white|midnight)/(\d+)/(\d+)/(\d+)$")
EXT = {"Base": "png", "Hybrid": "png", "white": "png", "midnight": "png", "Satellite": "jpeg"}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 경로만
        sys.stderr.write(f"{self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}\n")

    def do_GET(self):
        m = TILE.match(self.path)
        if m:
            layer, z, y, x = m.groups()
            up = f"https://api.vworld.kr/req/wmts/1.0.0/{KEY}/{layer}/{z}/{y}/{x}.{EXT[layer]}"
            try:
                with urllib.request.urlopen(urllib.request.Request(up, headers={"User-Agent": "dflow-contest-e5"}), timeout=20) as r:
                    body, ctype = r.read(), r.headers.get("Content-Type", "")
            except Exception:  # noqa: BLE001
                self.send_error(502)
                return
            if not ctype.startswith("image/"):
                self.send_error(502, "tile error")
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()
            self.wfile.write(body)
            return
        for prefix, base in STATIC.items():
            if self.path.startswith(prefix):
                p = (base / self.path[len(prefix):].split("?")[0]).resolve()
                if base.resolve() in p.parents and p.is_file():
                    ctype = {"html": "text/html; charset=utf-8", "geojson": "application/geo+json", "json": "application/json",
                             "js": "text/javascript"}.get(p.suffix[1:], "application/octet-stream")
                    body = p.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.end_headers()
                    self.wfile.write(body)
                    return
        self.send_error(404)


    def do_POST(self):  # 캡처 저장 — 이름은 안전 문자만, 저장 위치는 로컬 전용 두 곳
        m = re.match(r"^/save/([\w가-힣%.\-]+\.png)$", self.path)
        if not m:
            self.send_error(404)
            return
        name = urllib.parse.unquote(m.group(1))
        if "/" in name or "\\" in name or ".." in name:
            self.send_error(400)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        for d in (ROOT / "figures", Path.home() / "Downloads" / "브이월드_공모전"):
            d.mkdir(parents=True, exist_ok=True)
            (d / name).write_bytes(body)
        self.send_response(201)
        self.end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
