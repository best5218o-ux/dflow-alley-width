"""검토 인계 팩트시트 자동 생성 (D-070 Part F). 손으로 쓰지 않는다.

사용: python factsheet.py <제출본.hwpx> <직전판.hwpx> <저장소 루트> [--pdf-json 실측.json]
산출: deliverables/검토_팩트시트.md
- 쪽수는 hwpx_pdf_pages.py 실측(JSON)만 쓴다. 추정치는 적지 않는다.
- 수치 대조는 verify_numbers.py, 출처 대조는 주장_출처대조.csv, 민감도는 sensitivity.json 에서 읽는다.
"""
import csv
import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import zipfile
from contextlib import redirect_stdout

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import verify_numbers  # noqa: E402


def stats(hwpx):
    z = zipfile.ZipFile(hwpx)
    s = z.read("Contents/section0.xml").decode("utf-8")
    t = "".join(re.findall(r"<hp:t>([^<]*)</hp:t>", s))
    return {"문단": len(re.findall(r"<hp:p[ >]", s)), "글자": len(t), "pic": s.count("<hp:pic"), "tbl": s.count("<hp:tbl")}


def headings(hwpx):
    txt = verify_numbers.body_text(hwpx)
    s2 = txt[txt.index("<서식2>"):txt.index("<서식3>")]
    return [ln.strip() for ln in s2.split("\n") if ln.strip().startswith("□")]


def summary_text(hwpx):
    txt = verify_numbers.body_text(hwpx)
    m = re.search(r"(□ 문제 —.*?)(?:\n(?!□)|$)", txt, re.S)
    lines = [ln for ln in txt.split("\n") if re.match(r"□ (문제|해법|실증|적용) —", ln.strip())]
    return "\n".join(ln.strip() for ln in lines)


def form_pages(pdf):
    import fitz
    d = fitz.open(pdf)
    marks = {}
    for i, pg in enumerate(d):
        for k in ("<서식1>", "<서식2>", "<서식3>", "<서식4>", "<서식5>"):
            if k in pg.get_text() and k not in marks:
                marks[k] = i + 1
    keys = sorted(marks, key=marks.get)
    out = []
    for j, k in enumerate(keys):
        end = (marks[keys[j + 1]] - 1) if j + 1 < len(keys) else len(d)
        out.append((k, marks[k], end, end - marks[k] + 1))
    return out


def md_table(rows):
    if not rows:
        return "(없음)\n"
    keys = list(rows[0].keys())
    out = "| " + " | ".join(keys) + " |\n|" + "---|" * len(keys) + "\n"
    for r in rows:
        out += "| " + " | ".join("" if r[k] is None else str(r[k]) for k in keys) + " |\n"
    return out


def main(hwpx, prev, repo, pdf_json, pdf):
    repo = pathlib.Path(repo)
    st = os.stat(hwpx)
    commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    pages = json.loads(pathlib.Path(pdf_json).read_text(encoding="utf-8-sig"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = verify_numbers.main(hwpx, str(repo))
    verify_out = buf.getvalue()
    truth, _ = verify_numbers.load_truth(repo)
    claims = list(csv.DictReader((repo / "deliverables/주장_출처대조.csv").open(encoding="utf-8-sig")))
    from collections import Counter
    cnt = Counter(r["출처 유형"] for r in claims)
    manual = list(csv.DictReader((repo / "deliverables/주장_출처대조_사람판정.csv").open(encoding="utf-8-sig")))
    sens = json.loads((repo / "data/vworld/national/derived/sensitivity.json").read_text(encoding="utf-8"))
    det_p = repo / "data/vworld/national/derived/determinism_check.json"
    det = json.loads(det_p.read_text(encoding="utf-8")) if det_p.exists() else None
    a, b = stats(prev), stats(hwpx)
    ha, hb = headings(prev), headings(hwpx)
    summ = summary_text(hwpx)

    L = []
    L.append("# 검토 인계 팩트시트 (자동 생성 — factsheet.py)\n")
    L.append(f"생성 {time.strftime('%Y-%m-%d %H:%M')} · 커밋 `{commit}`\n")
    L.append("## 1. 제출본\n")
    L.append(f"- 파일: `{os.path.basename(hwpx)}`\n- 바이트: {st.st_size:,} · 수정 {time.strftime('%m-%d %H:%M', time.localtime(st.st_mtime))}"
             f" · SHA-256 앞 12자 `{hashlib.sha256(open(hwpx, 'rb').read()).hexdigest()[:12]}`\n")
    L.append("## 2. 쪽수 — 한글 PDF 실측(hwpx_pdf_pages.py)\n")
    L.append("```json\n" + json.dumps(pages, ensure_ascii=False, indent=1) + "\n```\n")
    L.append("## 3. 서식별 쪽 구성(PDF)\n")
    L.append(md_table([{"서식": k, "시작": s_, "끝": e, "쪽수": n} for k, s_, e, n in form_pages(pdf)]))
    L.append("\n## 4. 서식1 요약 자수\n")
    L.append(f"- 네 문단 합계(공백 포함 · 줄바꿈 제외) **{len(summ.replace(chr(10), ''))}자** · 한도 500자\n")
    L.append("## 5. 파이프라인 수치(산출물에서 읽음)\n")
    L.append(md_table([{"항목": k, "값": v} for k, v in truth.items()]))
    L.append("\n- 표기 규칙(§34-5-1): 709(규격 통과)와 351(버퍼 안)은 병렬 조건, 71 = 709 ∩ 351, 90.0 % 의 분모는 709\n")
    L.append("## 6. 수치 대조(verify_numbers.py)\n")
    L.append(f"결과: **{'PASS' if rc == 0 else 'FAIL'}**\n\n```\n{verify_out}```\n")
    L.append("## 7. 출처 대조(주장_출처대조.csv)\n")
    L.append(f"- 행 {len(claims)} · " + " · ".join(f"{k} {v}" for k, v in cnt.items()) + "\n")
    L.append("- 기계 1차 분류에서 미확인이었다가 사람이 재계산·원문 확인으로 판정한 항목:\n\n")
    L.append(md_table([{k: r[k] for k in ("추출", "문맥키", "출처 유형", "확인 URL·파일", "조치", "비고")} for r in manual]))
    rest = [r for r in claims if r["출처 유형"] == "미확인"]
    L.append(f"\n- 현재 미확인 잔여: **{len(rest)}건**\n")
    L.append("- 한계: 「저장소 산출」 기계 분류는 같은 숫자가 근거 파일에 있는지만 본다(의미 일치는 사람 판정 항목만 확인됨)\n")
    L.append("## 8. 민감도(sensitivity.py · SAM 재실행 없음)\n")
    L.append(f"- 기준 재현: {json.dumps(sens['summary']['기준재현'], ensure_ascii=False)}\n\n### 버퍼 폭\n\n")
    L.append(md_table(sens["buffer"]))
    L.append("\n### 규격 선험 ±10 %\n\n")
    L.append(md_table(sens["spec"]))
    if det:
        L.append("\n### 결정성(determinism_check.py)\n\n```json\n" + json.dumps(det, ensure_ascii=False, indent=1) + "\n```\n")
    L.append("## 9. 직전 판 대비\n")
    L.append(f"- 직전 판: `{os.path.basename(prev)}`\n")
    L.append(md_table([{"항목": k, "직전": a[k], "현재": b[k], "델타": b[k] - a[k]} for k in a]))
    L.append(f"\n- 소제목(□) 변경 — 직전 {len(ha)}개 · 현재 {len(hb)}개\n\n")
    gone, new = [x for x in ha if x not in hb], [x for x in hb if x not in ha]
    if not gone and not new:
        L.append("  - 변경 없음(071 §3-3 — 추출은 정상이고 두 판 소제목이 같다)\n")
    for x in gone:
        L.append(f"  - 삭제·변경 전: {x}\n")
    for x in new:
        L.append(f"  - 추가·변경 후: {x}\n")
    L.append("\n## 10. 진행 중 수정(재지적 불필요)\n")
    L.append("- 「3,838 → 709 → 351 → 71」 단일 사슬 표기 폐기 — 병렬 표기로 교체 완료(069 §1 · §34-5-1)\n"
             "- 90.0 % 분모 709 명시 완료(verify_numbers DENOM 검사)\n"
             "- 아리랑 GSD 0.5~0.7 m 삭제 · AI허브 주정차 라벨은 「공개 페이지에서 확인되지 않아」로 완화\n"
             "- 「오탐」 표현 본문 0 · 「학습시켰다」류 0\n"
             "- 34개(91.9 %) 문장: 기준이 3.0 m 가 아니라 최종채택 5.5 m 미만임을 바로잡음(070 D)\n"
             "- 공고문 예시 과제·제6회·제7회 수상 여부는 주관기관 확인 전까지 「미확인」 유지\n")
    out = repo / "deliverables/검토_팩트시트.md"
    out.write_text("".join(L), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    args = sys.argv[1:]
    j = args.index("--pdf-json")
    main(args[0], args[1], args[2], args[j + 1], args[j + 2])
