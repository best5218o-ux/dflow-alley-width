"""021 §1-1 — 26개소 산출표(3장 3-2의 중심). 기준 §29·§30·§31·§32 (사전 커밋 d182518 · 35281c0).

열: 연번 · 개소(시군구·조각 수) · 통과판정(폭 축, 조각 최솟값 — 사후 집계) · 전개 후보지점 ·
    최근접 용수 직선거리 · 용수 도달성 · 슬롯 순서 · 접한 건물 · 미결 항목
출력: deliverables/26개소_산출표.md · .csv · data/vworld/national/derived/site_table_26.json
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DER = ROOT / "data/vworld/national/derived"
DELIV = ROOT / "deliverables"
BAND_ORDER = {"BLOCKED": 0, "CONDITIONAL_C": 1, "폭축_통과후보": 2}


def main():
    cc = json.loads((DER / "missing_alley_crosscheck.json").read_text(encoding="utf-8"))
    mw = {r["piece"]: r for r in json.loads((DER / "ngii_medial_width.json").read_text(encoding="utf-8"))["pieces"]}
    water = {r["연번"]: r for r in json.loads((DER / "water_reach_26.json").read_text(encoding="utf-8"))["rows"]}
    slot = {r["연번"]: r for r in json.loads((DER / "slot_order_26.json").read_text(encoding="utf-8"))["rows"]}
    bld = json.loads((DER / "adjacent_buildings_26.json").read_text(encoding="utf-8"))["by_site"]
    rows = []
    for i, s in enumerate(cc["sites"], 1):
        pieces = [p for p in s["pieces"] if p["type"] == "road"]
        bands = [mw.get(p["piece"], {}).get("band") for p in pieces]
        known = [b for b in bands if b in BAND_ORDER]
        site_band = min(known, key=lambda b: BAND_ORDER[b]) if known else "UNKNOWN_FAIL_CLOSED"
        w, sl = water.get(i, {}), slot.get(i, {})
        b = bld.get(str(i), bld.get(i, {}))
        rows.append({
            "연번": s.get("연번"),
            "시군구": s.get("시군구"),
            "조각": len(pieces),
            "통과판정(폭 축)": site_band,
            "내접폭 최소(m)": min([mw[p["piece"]]["inscribed_min_m"] for p in pieces
                              if mw.get(p["piece"], {}).get("inscribed_min_m") is not None], default=None),
            "전개 후보지점": w.get("전개 후보지점"),
            "전개지점 상태": "1차" if str(w.get("전개지점 상태", "")).startswith("전개") else "UNKNOWN_FAIL_CLOSED",
            "최근접 용수 직선거리(m)": w.get("최근접 용수 직선거리(m)"),
            "용수 도달성": "UNKNOWN_FAIL_CLOSED(기준 미확보)",
            "슬롯 순서": ("펌프→구조→구급(순서만, seconds NOT_COMPUTED)"
                       if str(sl.get("순서", "")).startswith("1 ") else "배정하지 않음(fail-closed)"),
            "대기 큰 길": sl.get("큰 길(대기)") or "미확인",
            "접한 건물(동)": b.get("개소 접한 건물(중복 제거)"),
            "BLOCKED 조각 접한 건물(동)": b.get("BLOCKED 조각 접한 건물"),
            "미결 항목": "높이 ? · 회전 × · 경사 ? · 노면 ?",
        })
    cols = list(rows[0].keys())
    DELIV.mkdir(parents=True, exist_ok=True)
    with (DELIV / "26개소_산출표.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    md = ["# 대전 진입곤란 지정 26개소 산출표 (021 §1-1)", "",
          "기준: `docs/판정기준.md` §29(내접폭)·§30(용수)·§31(슬롯 순서)·§32(접한 건물) — 실행 전 커밋 `d182518`·`35281c0`", "",
          "- **통과판정은 폭 축만이다.** 개소 값은 조각 판정의 최솟값으로 모은 **사후 집계**다(§29 에 사전 고정하지 않았다)",
          "- **`BLOCKED` 는 「소방차가 못 들어간다」가 아니라 「현재 확보된 자료로는 통과를 인정할 수 없다」**이다. 「폭축_통과후보」도 통과 판정이 아니라 **폭 축에서 배제되지 않았다**는 뜻이다",
          "- **용수 거리는 직선거리다.** 경로거리가 아니다. 호스 연장 한계 수치를 확보하지 못해 **도달성은 판정하지 않았다**",
          "- **순서가 배정됐다. 시간은 계산하지 않았다**(`seconds: NOT_COMPUTED`)",
          "- **「접한 건물」**이다. 세대·주민으로 바꾸지 않는다. 인구는 원천을 확보하지 못해 추정하지 않았다", "",
          "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        md.append("| " + " | ".join("" if r[c] is None else str(r[c]) for c in cols) + " |")
    (DELIV / "26개소_산출표.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (DER / "site_table_26.json").write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    agg = {}
    for r in rows:
        agg[r["통과판정(폭 축)"]] = agg.get(r["통과판정(폭 축)"], 0) + 1
    print(json.dumps({"사후 집계 개소 판정": agg,
                      "슬롯 순서 배정": sum(1 for r in rows if r["슬롯 순서"].startswith("펌프")),
                      "접한 건물 합계(개소별 합, 개소 간 중복 가능)": sum(r["접한 건물(동)"] or 0 for r in rows)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
