"""088 §5 E — 이태원 arm3(폭 축): 폭 값이 붙으면 fail-closed 시연이 어떻게 달라지는가.

배경 — arm1/arm2(slot_itaewon_demo.py)는 폭 값이 없어 폭 축이 전 링크 D(판정 보류)였고,
긴급차량 4대가 전부 「판정 보류로 경로 없음」이 되는 fail-closed 판이었다.
이 스크립트는 그 시연에 **실제 폭 값**(deliverables/이태원_도로구간폭_판정.csv, 도로명주소 도로구간 road_bt)을
넣었을 때 폭 축 판정이 어떻게 바뀌는지를 **공통엔진 DFlowCore.evaluate_constraints 로 직접** 산출한다.

방법
  - 판정 주체는 이 스크립트가 아니라 공통엔진이다. 각 도로구간을 단일 링크(rest_w = road_bt 폭)로 만들어
    DFlowCore.evaluate_constraints(edges=[구간], links_by_id, spec=차량제원) 을 호출하고 그 반환값을 그대로 쓴다.
  - 차량 제원 spec.status="VERIFIED" 일 때만 승격된다. 폭이 없는 구간은 rest_w 를 비워 두어
    엔진이 위반으로 세지 않게 하고, 이 스크립트가 WIDTH_UNKNOWN(판정 보류)으로 따로 센다 — 0건과 구분한다.
  - 차급 전폭: 경형 1.9 · 소형 2.2 · 중형/대형 2.5 (KFS 전폭 상한). 일반차량 G = 2.0.
  - §34-14 4단 슬롯 경계: E 2.5 · E+P 3.7 · E+P+G 5.7 — 폭 W 가 경계 이상이면 그 조합이 성립.
  - arm1/arm2 의 긴급차량 4대(F1_pump 대형 2.5 · A1~A3_amb 소형 2.2)를 같은 엔진에 그대로 물린다.

가정·한계 (감추지 않는다)
  1) **원래 시연의 경로탐색은 재현하지 못했다.** slot_itaewon_demo 의 700 m 반경 권역은 표준노드링크 shp
     (data/vworld/national/raw/NODELINKDATA_20260914)에서 나오는데, 이 심볼릭 링크가 이 실행 환경에서
     열리지 않는다(Input/output error, readlink 실패). 오프라인 수집분(sprd/road_bt jsonl)에는 기하가 없어
     링크 망을 대신 만들 수도 없다. 따라서 arm3 은 **폭 축 판정만**이고 칸 배정·지연·경로는 산출하지 않는다.
  2) 권역이 arm1/arm2 와 다르다: 좌표 반경 700 m 가 아니라 「도로명에 이태원이 들어가는 용산구 도로구간 164개」다.
  3) 폭 출처는 도로명주소 도로구간 속성폭(road_bt)이다. 대전에서 쓴 도로경계 내접폭·SAM 차감폭과 다른 출처이고,
     이 권역에 SAM 은 미적용이다. 구간 대표값 1개이므로 구간 내 최협부는 반영되지 않는다.
  4) 시나리오 값은 없다. 이 산출물의 모든 수는 관측된 폭 값으로부터 계산된 값이다(차량 전폭 상한은 제원 상수).

출력: deliverables/이태원_긴급차량_차급별_진입판정.csv · data/vworld/national/derived/slot_itaewon_arm3_width.json
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = Path.home() / "mnt/dflow-disaster-orchestration/DFLOW_008R9R4_CORE"
sys.path.insert(0, str(CORE))
from dflow_core.core import DFlowCore  # noqa: E402

SRC = ROOT / "deliverables/이태원_도로구간폭_판정.csv"
OUT_CSV = ROOT / "deliverables/이태원_긴급차량_차급별_진입판정.csv"
OUT_JSON = ROOT / "data/vworld/national/derived/slot_itaewon_arm3_width.json"

CLASSES = [("경형", 1.9), ("소형", 2.2), ("중형·대형", 2.5)]
G_WIDTH = 2.0
SLOT_BOUNDS = [("E", 2.5), ("E+P", 3.7), ("E+P+G", 5.7)]
ACTORS = [("F1_pump", "중형·대형", 2.5), ("A1_amb", "소형", 2.2),
          ("A2_amb", "소형", 2.2), ("A3_amb", "소형", 2.2)]


def load():
    rows = []
    with SRC.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            w = r.get("폭m_road_bt", "").strip()
            try:
                wv = float(w)
            except ValueError:
                wv = None
            rows.append({"도로명": r["도로명"], "도로관리번호": r["도로관리번호"],
                         "폭m": wv, "밴드판정": r.get("판정", "")})
    return rows


def main():
    core = DFlowCore(now="2026-09-15T20:00:00+09:00")
    segs = load()
    have = [s for s in segs if s["폭m"] is not None]
    unknown = [s for s in segs if s["폭m"] is None]

    # 공통엔진 호출: 구간 1개 = 링크 1개
    links_by_id = {s["도로관리번호"]: ({"rest_w": s["폭m"]} if s["폭m"] is not None else {}) for s in segs}

    def engine_pass(seg_id, width_m):
        spec = {"status": "VERIFIED", "width_m": width_m}
        res = core.evaluate_constraints([seg_id], links_by_id, spec)
        return res["can_reach"], res

    # 1) 차급별 진입 가능 구간
    per_class = {}
    for name, w in CLASSES:
        ok = blocked = unk = 0
        for s in segs:
            if s["폭m"] is None:
                unk += 1
                continue
            r, _ = engine_pass(s["도로관리번호"], w)
            ok += bool(r is True)
            blocked += bool(r is False)
        per_class[name] = {"전폭m": w, "진입가능_구간": ok, "진입불가_구간": blocked,
                           "폭미상_판정보류": unk, "판정주체": "DFlowCore.evaluate_constraints"}

    # 2) §34-14 슬롯 경계 — 일반차량 G=2.0 이 함께 있을 때
    slots = {}
    for label, bound in SLOT_BOUNDS:
        n = sum(1 for s in have if s["폭m"] >= bound)
        slots[label] = {"경계m": bound, "성립_구간": n,
                        "미성립_구간": len(have) - n, "폭미상_판정보류": len(unknown)}

    # 3) arm1/arm2 의 긴급차량 4대 — 폭 축이 D 에서 무엇으로 바뀌는가
    actors = {}
    for aid, cls, w in ACTORS:
        ok = sum(1 for s in have if engine_pass(s["도로관리번호"], w)[0] is True)
        actors[aid] = {"차급": cls, "전폭m": w,
                       "arm1_arm2_폭축": "D(판정 보류) — 폭 값 부재, eligibility UNKNOWN_FAIL_CLOSED",
                       "arm3_폭축": "VERIFIED — road_bt 폭으로 구간별 판정",
                       "진입가능_구간": ok, "진입불가_구간": len(have) - ok,
                       "폭미상_판정보류": len(unknown)}

    # CSV: 구간별 차급 판정
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        wri = csv.writer(f)
        wri.writerow(["도로명", "도로관리번호", "폭m_road_bt", "밴드판정",
                      "경형1.9", "소형2.2", "중형대형2.5", "일반차량G2.0",
                      "슬롯_E_2.5", "슬롯_EP_3.7", "슬롯_EPG_5.7",
                      "arm1_arm2_폭축", "arm3_폭축_판정주체"])
        for s in segs:
            if s["폭m"] is None:
                wri.writerow([s["도로명"], s["도로관리번호"], "", s["밴드판정"]]
                             + ["판정보류"] * 7 + ["D(판정 보류)", "WIDTH_UNKNOWN — 값 없음(0건 아님)"])
                continue
            cells = []
            for _, w in CLASSES:
                cells.append("가능" if engine_pass(s["도로관리번호"], w)[0] is True else "불가")
            cells.append("가능" if engine_pass(s["도로관리번호"], G_WIDTH)[0] is True else "불가")
            for _, b in SLOT_BOUNDS:
                cells.append("성립" if s["폭m"] >= b else "미성립")
            wri.writerow([s["도로명"], s["도로관리번호"], s["폭m"], s["밴드판정"]] + cells
                         + ["D(판정 보류)", "DFlowCore.evaluate_constraints"])

    out = {
        "권역": "서울 용산구 도로명주소 도로구간 중 도로명에 「이태원」 포함",
        "구간수": len(segs), "폭_부여": len(have), "폭_미상_판정보류": len(unknown),
        "폭출처": "도로명주소 도로구간 road_bt(오프라인 수집분) · API 호출 없음",
        "판정_주체": "공통엔진 DFlowCore.evaluate_constraints (읽기 전용 저장소에서 import)",
        "engine_capabilities": list(DFlowCore.CAPABILITIES),
        "arm1_arm2_대비": {
            "arm1_arm2": "폭 축 전 링크 D(판정 보류) → 긴급차량 4대 전부 「판정 보류로 경로 없음」(fail-closed)",
            "arm3": "폭 값 부여 → 폭 축이 구간별 VERIFIED 판정으로 전환. 긴급차량 4대 전부 폭 축 확정 판정을 받음",
        },
        "차급별": per_class,
        "슬롯_34_14": slots,
        "긴급차량_4대": actors,
        "재현하지_못한_것": {
            "경로탐색·칸배정·지연": "미산출",
            "이유": "표준노드링크 shp 심볼릭 링크가 이 실행 환경에서 열리지 않음(Input/output error) · "
                    "오프라인 수집분(sprd/road_bt jsonl)에 기하 없음 → 700 m 권역 링크 망 재구성 불가",
            "실패와_0건_구분": "위 항목은 '0건'이 아니라 '조회·재현 실패'다",
        },
        "시나리오_값": "없음 — 이 산출물의 모든 수는 관측 폭 값에서 계산된 값이다(차량 전폭은 KFS 제원 상수)",
        "밴드분포_참고": dict(Counter(s["밴드판정"] for s in segs)),
        "폭_해상도_발견": {
            "폭값_분포_m": dict(sorted(Counter(s["폭m"] for s in have).items())),
            "관찰": "이 권역 road_bt 는 전부 1 m 단위 정수다(최소 1.0 · 최대 19.0). "
                    "2.2 m 이상 2.5 m 미만 구간이 0개여서 소형(2.2)과 중형·대형(2.5)의 진입 가능 구간 수가 "
                    "134 로 같게 나온다 — 차급이 같아서가 아니라 속성폭 해상도가 차급 차이를 담지 못해서다.",
            "함의": "속성폭만으로는 0.3 m 단위 차급 분리가 불가능하다. 대전에서 쓴 내접폭·차감폭이 필요한 이유.",
        },
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"차급별": per_class, "슬롯": slots,
                      "긴급차량_4대": {k: v["진입가능_구간"] for k, v in actors.items()},
                      "구간수": len(segs), "폭미상": len(unknown)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
