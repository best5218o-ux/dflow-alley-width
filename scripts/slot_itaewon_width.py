"""087 §5 D — 이태원 권역 폭 실증. 대전 26개소와 **같은 밴드·같은 임계값**으로 두 번째 현장을 판정한다.

권역 정의: 도로명주소 도로구간(lt_l_sprd) 중 서울 용산구(sig_cd=11170) · 도로명에 「이태원」이 들어가는 구간 전부.
  - 좌표 반경이 아니라 도로명 집합이다. 표준노드링크 shp 가 이 실행 환경에서 열리지 않아(심볼릭 링크 미해석)
    slot_itaewon_demo 의 700 m 반경 권역을 쓰지 못했다 — 권역 구성이 그 시연과 다르다는 뜻이고, 감추지 않는다.
  - 중복 제거 키는 (rds_man_no, rn). 용산구 전체 3,170 구간을 같은 규칙으로 함께 판정해 대조군으로 둔다.
폭 출처: road_bt(도로폭 m) — 오프라인 수집분(data/.../road_bt_national_cells.jsonl[.gz]). API 호출 없음.
  대전에서 쓴 도로경계 내접폭·SAM 차량 차감폭과 **다른 출처**다. 이 권역에 SAM 은 **미적용**이다.
판정: docs/판정기준.md §29-5 그대로 — ≤ 2.5 BLOCKED(문헌) · ≤ 3.5 CONDITIONAL_C(우리 설정) · 그 외 폭축_통과후보.
긴급차량 전폭 E: KFS 전폭 상한(경형 1.9 · 소형 2.2 · 중형/대형 2.5) 중 W 이하 최대. 일반차량 G = 2.0.
4단 슬롯(§34-14): 2.5(E) · 3.7(E+P) · 5.7(E+P+G).
폭 값이 없는 구간은 값을 만들지 않는다 → WIDTH_UNKNOWN(판정 보류, fail-closed).
출력: deliverables/이태원_도로구간폭_판정.csv · data/vworld/national/derived/slot_itaewon_width.json
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _rawio import open_raw  # noqa: E402

RAW_BT = ROOT / "data/vworld/national/raw/road_bt_national_cells.jsonl"
DER = ROOT / "data/vworld/national/derived"
DELIV = ROOT / "deliverables"
SIG, KEYWORD = "11170", "이태원"
E_MAX = [1.9, 2.2, 2.5]
G = 2.0


def load():
    seg = {}
    with open_raw(RAW_BT) as f:
        for line in f:
            for r in json.loads(line).get("rows", []):
                if r.get("sig_cd") != SIG:
                    continue
                rn = (r.get("rn") or "").strip()
                seg[(r.get("rds_man_no"), rn)] = r.get("road_bt")
    return seg


def band(W):
    if W is None:
        return "WIDTH_UNKNOWN", "판정 보류 — 폭 값 없음"
    if W <= 2.5:
        return "BLOCKED", "문헌 — 소방차 표준 폭 2.2~2.5 m"
    if W <= 3.5:
        return "CONDITIONAL_C", "우리 설정 — 측방 여유·회전(근거 문헌 미확보)"
    return "폭축_통과후보", "밴드 상한 초과"


def judge(W):
    b, why = band(W)
    e = max([x for x in E_MAX if x <= W], default=None) if W is not None else None
    s = (None, None, None) if W is None else (W > 2.5, W > 3.7, W > 5.7)
    return b, why, e, s


def rows_for(seg, only_kw):
    out = []
    for (no, rn), bt in sorted(seg.items(), key=lambda x: (x[0][1], x[0][0])):
        if only_kw and KEYWORD not in rn:
            continue
        W = float(bt) if isinstance(bt, (int, float)) and bt > 0 else None
        b, why, e, s = judge(W)
        out.append({
            "도로명": rn, "도로관리번호": no,
            "폭m_road_bt": "" if W is None else W,
            "판정": b, "판정근거": why,
            "긴급차량_전폭상한E": "" if e is None else e,
            "슬롯_E": "" if s[0] is None else ("Y" if s[0] else "N"),
            "슬롯_E+P": "" if s[1] is None else ("Y" if s[1] else "N"),
            "슬롯_E+P+G": "" if s[2] is None else ("Y" if s[2] else "N"),
            "폭출처": "도로명주소 도로구간 road_bt(오프라인 수집분)" if W is not None else "속성 없음 — 값 만들지 않음",
        })
    return out


def stats(rows):
    w = [r["폭m_road_bt"] for r in rows if r["폭m_road_bt"] != ""]
    c = Counter(r["판정"] for r in rows)
    return {
        "구간수": len(rows), "폭_부여": len(w), "폭_미상": len(rows) - len(w),
        "폭_최소m": min(w) if w else None, "폭_최대m": max(w) if w else None,
        "폭_중앙값m": statistics.median(w) if w else None,
        "판정분포": dict(c),
        "BLOCKED_비율%": round(100 * c["BLOCKED"] / len(rows), 1) if rows else None,
        "긴급차량_통과후보_비율%": round(100 * c["폭축_통과후보"] / len(rows), 1) if rows else None,
    }


def main():
    seg = load()
    it, ys = rows_for(seg, True), rows_for(seg, False)
    DELIV.mkdir(exist_ok=True)
    out = DELIV / "이태원_도로구간폭_판정.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(it[0].keys()))
        w.writeheader()
        w.writerows(it)
    summary = {
        "권역": "서울 용산구 도로명주소 도로구간 중 도로명에 「이태원」 포함",
        "권역_정의_한계": "좌표 반경 권역이 아니다(표준노드링크 shp 미열림). slot_itaewon_demo 의 700 m 권역과 구성이 다르다.",
        "이태원": stats(it), "용산구_전체_대조군": stats(ys),
        "폭출처": "도로명주소 도로구간 lt_l_sprd road_bt · sig_cd=11170 · 오프라인 수집분 · API 호출 없음",
        "SAM_차량탐지": "미적용 — 이 권역은 공간정보 폭만으로 판정",
        "밴드": "docs/판정기준.md §29-5 · 임계값 2.5/3.5 · E 1.9/2.2/2.5 · G 2.0 · 슬롯 2.5/3.7/5.7",
        "대전과의 차이": "대전은 도로경계 내접폭 + SAM 차감폭, 이태원은 도로명주소 속성폭. 밴드와 임계값만 같다.",
    }
    (DER / "slot_itaewon_width.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("→", out)


if __name__ == "__main__":
    main()
