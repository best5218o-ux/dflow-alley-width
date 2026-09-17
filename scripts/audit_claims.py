"""서식2 본문 주장 전수 추출·출처 대조 (D-070 Part D).

사용: python audit_claims.py <제출본.hwpx> <저장소 루트> [사람판정.csv]
산출: deliverables/주장_출처대조.csv

분류 규칙(기계 1차 분류 → 사람 판정은 manual.csv 로 덮어쓴다)
- [문헌X]              → 출처 일람의 확인 수준으로 분류(본문 확인 = 1차 원문, 초록·일부만 확인 = 2차 인용)
- 법령·KFS·ISO·SOP     → 1차 원문(출처 일람 「기준 문서」 행)
- 숫자+단위             → 원고 외 저장소 파일(산출물·판정기준·실사 기록)에서 같은 숫자가 발견되면 저장소 산출
- 그 밖                 → 미확인(사람이 판정해 manual.csv 에 적는다)
원고 자체(신청서_*.md)와 이 스크립트 산출물은 근거 파일로 치지 않는다(순환 방지).
"""
import csv
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from verify_numbers import body_text  # noqa: E402

UNIT = r"(?:m/px|㎡|km|mm|pt|%p|%|m|건|개소|개|조각|구간|명|시간|만 장|종|대|자|쪽|년|초|분)"
PAT = re.compile(
    r"(?P<num>\d[\d,]*(?:\.\d+)?(?:\s*[~–·/]\s*\d[\d,]*(?:\.\d+)?)?)\s*(?P<unit>" + UNIT + r")(?![A-Za-z가-힣])"
    r"|(?P<law>제\d+조(?:의\d+)?|별표\s*\d+|KFS[\s-]?[\d-]+|ISO\s*[\d-]+(?::\d{4})?|SOP\s*[\d.]+)"
    r"|(?P<ref>\[문헌[A-Z·]+\])"
)
EVIDENCE_GLOBS = [
    "deliverables/*.csv", "deliverables/*.md",
    "docs/판정기준.md", "docs/vworld/데이터수급_실사.md", "docs/vworld/학술문헌_조사.md",
    "docs/vworld/기술조사_임무배정.md", "data/vworld/national/derived/*.json", "data/vworld/national/derived/*.csv",
]
EXCLUDE = {"주장_출처대조.csv", "주장_출처대조_사람판정.csv", "검토_팩트시트.md"}


def evidence_files(repo):
    out = []
    for g in EVIDENCE_GLOBS:
        for p in sorted(repo.glob(g)):
            if p.name in EXCLUDE or p.stat().st_size > 30_000_000:
                continue
            try:
                out.append((p, p.read_text(encoding="utf-8-sig", errors="ignore")))
            except OSError:
                pass
    return out


def ref_levels(txt):
    """출처 일람 표에서 문헌 기호별 확인 수준."""
    lv = {}
    for label, typ in (("문헌 — 본문 확인", "1차 원문"), ("문헌 — 초록까지 확인", "2차 인용"), ("문헌 — 일부만 확인", "2차 인용")):
        i = txt.find(label)
        if i < 0:
            continue
        seg = txt[i + len(label): i + len(label) + 1200].split("\n문헌 —")[0]
        for m in re.finditer(r"(?:^|[\n·—]\s*)([A-Z])\s", seg):
            lv.setdefault(m.group(1), typ)
    return lv


def main(hwpx, repo, manual=None):
    repo = pathlib.Path(repo)
    t = body_text(hwpx)
    s2 = t[t.index("<서식2>"):t.index("<서식3>")]
    paras = s2.split("\n")
    ev = evidence_files(repo)
    lv = ref_levels(s2)
    man = []   # 사람 판정: (추출, 문맥키) 가 맞는 행을 덮어쓴다 — 문단 번호는 판마다 바뀌므로 쓰지 않는다
    if manual and pathlib.Path(manual).exists():
        man = list(csv.DictReader(open(manual, encoding="utf-8-sig")))
    rows = []
    for i, p in enumerate(paras):
        for m in PAT.finditer(p):
            phrase = p[max(0, m.start() - 25): m.end() + 10].strip()
            key = m.group(0)
            if m.group("ref"):
                syms = re.findall(r"[A-Z]", m.group("ref"))
                typ = "1차 원문" if all(lv.get(s) == "1차 원문" for s in syms) else ("2차 인용" if all(s in lv for s in syms) else "미확인")
                src, act = "출처 일람 " + "·".join(f"{s}={lv.get(s, '없음')}" for s in syms), "유지" if typ != "미확인" else "문장 수정"
            elif m.group("law"):
                typ, src, act = "1차 원문", "출처 일람 「기준 문서」 행", "유지"
            else:
                nums = [x.replace(",", "") for x in re.findall(r"\d[\d,]*(?:\.\d+)?", m.group("num"))]
                found = []
                for path, body in ev:
                    flat = body.replace(",", "")
                    if all(re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", flat) for n in nums):
                        found.append(str(path.relative_to(repo)).replace("\\", "/"))
                if found:
                    typ, src, act = "저장소 산출", " | ".join(found[:3]), "유지"
                else:
                    typ, src, act = "미확인", "", "사람 판정"
            r = {"본문 구절": phrase, "위치": f"서식2 문단 {i}", "추출": key, "출처 유형": typ, "확인 URL·파일": src, "조치": act, "비고": ""}
            for mm in man:
                if mm["추출"] == key and mm["문맥키"] in p:
                    r.update({k: mm[k] for k in ("출처 유형", "확인 URL·파일", "조치", "비고") if mm.get(k)})
                    break
            rows.append(r)
    out = repo / "deliverables/주장_출처대조.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print("행", len(rows), dict(Counter(r["출처 유형"] for r in rows)))
    return rows


if __name__ == "__main__":
    main(*sys.argv[1:4])
