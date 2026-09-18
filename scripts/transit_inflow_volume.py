"""2026-09-18 · 대중교통 유입 규모 — 조각 반경 100 m 안 정류장·역사의 승하차 인원을 잇는다.

원천(모두 data/vworld/원천/, 사본):
- 대전교통공사_시간대별 승하차인원_20260731.csv — 공공데이터포털 15060591 (역×일자×1시간, 2026-01-01~07-31, cp949)
- tportal_정류장승하차_일별_2026-07.tsv — 대전교통 빅데이터 플랫폼(tportal.daejeon.go.kr) 정류장승하차이용정보 API
  (/web-service/api/v1/bus/getInOutCountByStopDetail · dunit=perD · 2026-07-01~31) 응답을 그대로 적은 것. 정류장×일자. 시간대 없음
- tportal_정류장목록_2026-09-18.tsv — 같은 플랫폼 정류장 목록(getInOutBusStopList): 정류장ID·이름·모바일단축번호(ARS)
키: 공공데이터포털 정류장번호 'DJB8001250' 의 숫자부 == tportal getonBusSttnId '8001250'. 안 맞으면 모바일단축번호로 잇는다.
출력: deliverables/대중교통유입규모_26개소.csv
해상도 한계: 버스는 일 단위 합계뿐이라 시간대 분포를 알 수 없다(도시철도 시간대 비율을 버스에 옮기지 않는다 — 가정이라서).
"""
from __future__ import annotations

import csv
import datetime as dt
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/vworld/원천"
DELIV = ROOT / "deliverables"
PERIOD = "2026-07-01~07-31"


def weekday(ymd):  # 'YYYYMMDD' or 'YYYY-MM-DD'
    return dt.date.fromisoformat(ymd if "-" in ymd else f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}").weekday() < 5


def load_rail():
    raw = (SRC / "대전교통공사_시간대별 승하차인원_20260731.csv").read_bytes().decode("cp949")
    rows = list(csv.DictReader(raw.splitlines()))
    hours = [k for k in rows[0] if k.endswith("시")]
    by = defaultdict(list)  # (역번호4자리, 구분) -> [(날짜, [24])]
    for r in rows:
        if not r["날짜"].startswith("2026-07"):
            continue
        by[(r["역번호"], r["구분"])].append((r["날짜"], [int(r[h] or 0) for h in hours]))
    return hours, by


def load_bus():
    daily = defaultdict(list)  # id -> [(ymd, on, off)]
    p = SRC / "tportal_정류장승하차_일별_2026-07.tsv"
    for r in csv.DictReader(p.open(encoding="utf-8"), delimiter="\t"):
        daily[r["getonBusSttnId"]].append((r["ymdId"], int(r["getonCnt"]), int(r["getoffCnt"])))
    ars = {}
    for r in csv.DictReader((SRC / "tportal_정류장목록_2026-09-18.tsv").open(encoding="utf-8"), delimiter="\t"):
        ars.setdefault(r["ars"], r["getonBusSttnId"])
    return daily, ars


def main():
    hours, rail = load_rail()
    bus, ars = load_bus()
    lst = list(csv.DictReader((DELIV / "대중교통유입_정류장목록_26개소.csv").open(encoding="utf-8-sig")))
    out = []
    piece_sum = defaultdict(lambda: [0.0, 0, 0])  # (시군구,조각) -> [반경안 일평균 승하차 합, 지점수, 미결합]
    for r in lst:
        key = (r["시군구"], r["조각"])
        base = {"시군구": r["시군구"], "조각": r["조각"], "유형": r["유형"], "번호": r["번호"], "이름": r["이름"], "거리(m)": r["거리(m)"], "반경안": r["반경안"],
                "집계기간": PERIOD, "일수": "", "일평균 승차": "", "일평균 하차": "", "일평균 승하차": "", "평일 일평균 승하차": "",
                "시간대 해상도": "", "평일 최대시간대": "", "평일 최대시간대 승하차": "", "결합키": "", "출처": "", "비고": ""}
        if r["유형"] == "도시철도역사":
            no = r["번호"] if len(r["번호"]) == 4 else "1" + r["번호"].zfill(3)  # 15013205 역번호 '104' ↔ 15060591 '1104'
            on, off = rail.get((no, "승차")), rail.get((no, "하차"))
            if not on or not off:
                base["비고"] = f"역번호 {no} 가 시간대별 파일에 없음"
                piece_sum[key][2] += 1
            else:
                days = len(on)
                won = [v for d, v in on if weekday(d)]
                woff = [v for d, v in off if weekday(d)]
                tot = lambda L: sum(sum(v) for v in L) / len(L)
                prof = [sum(v[i] for v in won) / len(won) + sum(v[i] for v in woff) / len(woff) for i in range(len(hours))]
                pk = max(range(len(hours)), key=lambda i: prof[i])
                base.update({"일수": days, "일평균 승차": round(tot([v for _, v in on]), 1), "일평균 하차": round(tot([v for _, v in off]), 1),
                             "일평균 승하차": round(tot([v for _, v in on]) + tot([v for _, v in off]), 1),
                             "평일 일평균 승하차": round(tot(won) + tot(woff), 1), "시간대 해상도": "1시간",
                             "평일 최대시간대": hours[pk], "평일 최대시간대 승하차": round(prof[pk], 1),
                             "결합키": f"역번호 {r['번호']}→{no}", "출처": "공공데이터포털 15060591 (2026-07-31 갱신)"})
                if r["반경안"] == "Y":
                    piece_sum[key][0] += base["일평균 승하차"]
                    piece_sum[key][1] += 1
        else:
            sid = re.sub(r"\D", "", r["번호"])
            how = "정류장번호 숫자부"
            if sid not in bus and r["모바일단축번호"] in ars:
                sid, how = ars[r["모바일단축번호"]], "모바일단축번호(ARS)"
            d = bus.get(sid)
            if not d:
                base["비고"] = f"tportal 에 정류장 {r['번호']} 없음(승하차 집계 대상 아님 또는 ID 불일치)"
                piece_sum[key][2] += 1
            else:
                days = len(d)
                on = sum(x[1] for x in d) / days
                off = sum(x[2] for x in d) / days
                wd = [x for x in d if weekday(x[0])]
                base.update({"일수": days, "일평균 승차": round(on, 1), "일평균 하차": round(off, 1), "일평균 승하차": round(on + off, 1),
                             "평일 일평균 승하차": round(sum(x[1] + x[2] for x in wd) / len(wd), 1) if wd else "",
                             "시간대 해상도": "일(시간대 없음)", "결합키": f"{how} {sid}",
                             "출처": "tportal.daejeon.go.kr 정류장승하차이용정보 API (2026-09-18 조회)"})
                if r["반경안"] == "Y":
                    piece_sum[key][0] += base["일평균 승하차"]
                    piece_sum[key][1] += 1
        out.append(base)
    # 조각 합계 행
    for (sgg, pc), (s, n, miss) in piece_sum.items():
        out.append({"시군구": sgg, "조각": pc, "유형": "조각 합계(반경 100 m 안)", "번호": "", "이름": f"지점 {n} · 미결합 {miss}", "거리(m)": "", "반경안": "Y",
                    "집계기간": PERIOD, "일수": "", "일평균 승차": "", "일평균 하차": "", "일평균 승하차": round(s, 1) if n else "", "평일 일평균 승하차": "",
                    "시간대 해상도": "혼합(역사 1시간 · 버스 일)", "평일 최대시간대": "", "평일 최대시간대 승하차": "", "결합키": "", "출처": "",
                    "비고": "" if n else "반경 안 지점 없음(최근접 지점은 반경안 N 행 참고)"})
    with (DELIV / "대중교통유입규모_26개소.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    joined = sum(1 for o in out if o["일수"] != "" and o["유형"] != "조각 합계(반경 100 m 안)")
    total = sum(1 for o in out if o["유형"] != "조각 합계(반경 100 m 안)")
    inY = [o for o in out if o["반경안"] == "Y" and o["유형"] != "조각 합계(반경 100 m 안)"]
    print(f"지점 {total} (반경안 {len(inY)}) · 결합 {joined} · 조각 합계 행 {len(piece_sum)}")
    vals = [o["일평균 승하차"] for o in inY if o["일수"] != ""]
    if vals:
        vals.sort()
        print(f"반경안 지점 일평균 승하차: 최소 {vals[0]} · 중앙 {vals[len(vals)//2]} · 최대 {vals[-1]}")


if __name__ == "__main__":
    main()
