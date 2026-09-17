"""제출본 hwpx 의 수치를 저장소 산출물과 대조한다 (D-070 Part C). 불일치는 즉시 실패.

사용: python verify_numbers.py <제출본.hwpx> <저장소 루트>
진실값은 파일에서만 읽는다(하드코딩 금지).
- data/vworld/national/derived/sam_vehicle_width.json 의 pieces(37조각) 합 — 1차
- 같은 파일 summary.회랑필터_합계, deliverables/회랑필터_전후_오탐.csv 합계 행 — 교차 확인
"""
import csv
import json
import pathlib
import re
import sys


def body_text(hwpx):
    import zipfile
    x = zipfile.ZipFile(hwpx).read("Contents/section0.xml").decode("utf-8")
    ps = re.findall(r"<hp:p\b.*?</hp:p>", x, re.S)
    txt = "\n".join(re.sub(r"<[^>]+>", "", "".join(re.findall(r"<hp:t[^>]*>(.*?)</hp:t>", p, re.S))) for p in ps)
    return txt.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def load_truth(repo):
    repo = pathlib.Path(repo)
    t, cross = {}, []
    j = repo / "data/vworld/national/derived/sam_vehicle_width.json"
    d = json.loads(j.read_text(encoding="utf-8"))
    ps = [p for p in d["pieces"] if "n_masks" in p]
    t["sam_raw_masks"] = sum(p["n_masks"] for p in ps)
    t["spec_pass"] = sum(p["n_spec"] for p in ps)
    t["corridor_in"] = sum(p["n_corr"] for p in ps)
    t["confirmed"] = sum(p["n_conf"] for p in ps)
    t["outside_removed"] = sum(p["fp_removed"] for p in ps)
    t["outside_rate"] = round(100 * t["outside_removed"] / t["spec_pass"], 1)
    t["n_pieces"] = len(d["pieces"])
    s = d["summary"]["회랑필터_합계"]
    cross.append(("json summary", {"sam_raw_masks": s["SAM원마스크"], "spec_pass": s["규격선험통과"], "corridor_in": s["회랑안"],
                                   "confirmed": s["확정(둘다)"], "outside_removed": s["규격선험만통과했으나_회랑밖(=오탐제거수)"],
                                   "outside_rate": s["오탐제거율(%)"]}))
    c = repo / "deliverables/회랑필터_전후_오탐.csv"
    rows = list(csv.DictReader(c.open(encoding="utf-8-sig")))
    tot = [r for r in rows if r["조각"] == "합계"][-1]
    cross.append(("csv 합계", {"sam_raw_masks": int(tot["SAM원마스크"]), "spec_pass": int(tot["규격선험통과"]), "corridor_in": int(tot["회랑안"]),
                              "confirmed": int(tot["확정(둘다)"]), "outside_removed": int(tot["규격선험만통과했으나_회랑밖(=오탐제거수)"]),
                              "outside_rate": float(tot["오탐제거율(%)"])}))
    return t, cross


def fmt(v):
    return f"{v:,.1f}" if isinstance(v, float) else f"{v:,}"


CHECKS = [
    # (진실값 키, 설명) — 본문 표기는 진실값을 천 단위 쉼표로 쓴 문자열이다
    ("sam_raw_masks", "원 마스크"),
    ("spec_pass", "차량 규격 통과"),
    ("corridor_in", "도로구간 버퍼 안"),
    ("confirmed", "차량 후보"),
    ("outside_removed", "규격 통과했으나 버퍼 밖"),
    ("outside_rate", "버퍼 밖 제외율(분모 규격 통과)"),
    ("n_pieces", "조각 수"),
]

BANNED_PATTERNS = [
    r"3,838\s*→\s*709",      # 순차 사슬 표기 금지(§34-5-1)
    r"709\s*→\s*351",
    r"351\s*→\s*71",
    r"→\s*[^→\n]{0,20}709\s*→",
    r"오탐",
    r"SAM\s*차량\s*탐지",   # 075 §6 — SAM 은 객체 분할이다
    r"학습시켰다",
    r"정확도가\s*올랐다",
]


# 073 §1-3 — 본문의 「소수 + m」 값을 산출물 수치 열 값 집합과 대조한다
VALUE_CSVS = [
    "deliverables/통행가능폭_주차차감_37조각.csv",
    "deliverables/26개소_산출표.csv",
    "deliverables/차량탐지_사람대조_11조각.csv",   # 사람 판독 검증창 W_worst(변정7길 3.92 등) — §34-5-2
]
# CSV 밖 수치 — 그냥 넘기지 않고 근거 파일에서 값을 다시 계산해 맞을 때만 통과시킨다(항목마다 근거)


def _json(repo, rel):
    return json.loads((pathlib.Path(repo) / rel).read_text(encoding="utf-8"))


def _kfs_sum(repo):
    """4단 슬롯 표 경계 5.7 = E 2.5 + P 1.2 + G 2.0 — 37조각 CSV 「임계근거」 열에서 세 값을 읽어 더한다(§34-14)."""
    row = next(csv.DictReader((pathlib.Path(repo) / VALUE_CSVS[0]).open(encoding="utf-8-sig")))
    note = row["임계근거"]
    p = float(re.search(r"P=([\d.]+)", note).group(1))
    g = float(re.search(r"G=([\d.]+)", note).group(1))
    e = max(float(x) for x in re.findall(r"E=([\d.]+)", "".join(r["임계근거"] for r in csv.DictReader(
        (pathlib.Path(repo) / VALUE_CSVS[0]).open(encoding="utf-8-sig")))))
    return round(e + p + g, 2)


def _median_line_d(repo):
    """세 원천 연결 거리 중앙값 — ngii_bound_cover.json 37조각 line_d_to_point_m 중앙값."""
    import statistics
    v = [x["line_d_to_point_m"] for x in _json(repo, "data/vworld/national/derived/ngii_bound_cover.json")
         if x.get("line_d_to_point_m") is not None]
    return round(statistics.median(v), 1)


def _rvwd_soro(repo):
    """RVWD 소로(RDD009) 107건이 전부 같은 값 — ngii_width_probe.json fill.by_rddv_scls 의 min=max."""
    f = _json(repo, "data/vworld/national/derived/ngii_width_probe.json")["fill"]["by_rddv_scls"]
    r = next(v for k, v in f.items() if k.startswith("RDD009"))
    return r["min"] if r["min"] == r["max"] and r["n"] == 107 else None


FILE_CHECKED_M = {
    5.7: _kfs_sum,
    9.9: _median_line_d,
    1.5: _rvwd_soro,
}


def value_set(repo):
    vals = set()
    for rel in VALUE_CSVS:
        for row in csv.DictReader((pathlib.Path(repo) / rel).open(encoding="utf-8-sig")):
            for v in row.values():
                for x in re.findall(r"-?\d+(?:\.\d+)?", v or ""):
                    vals.add(round(float(x), 2))
    return vals


def orphan_m(txt, repo):
    vals = value_set(repo)
    checked = {k for k, fn in FILE_CHECKED_M.items() if fn(repo) is not None and abs(fn(repo) - k) <= 0.005}
    out = []
    for m in re.finditer(r"(?<![\d.])(\d+\.\d+)(?:\s*[~·]\s*(\d+(?:\.\d+)?))?\s*m(?![A-Za-z/²])", txt):
        for g in (m.group(1), m.group(2)):
            if not g or "." not in g:
                continue
            v = round(float(g), 2)
            if v in checked or any(abs(v - x) <= 0.005 for x in vals):
                continue
            out.append((g, ctx(txt, m.start(), m.end())))
    return out


def ctx(txt, a, b, w=60):
    return txt[max(0, a - w):b + w].replace("\n", " ⏎ ")


def main(hwpx, repo):
    txt = body_text(hwpx)
    truth, cross = load_truth(repo)
    fail, info = [], []
    for name, vals in cross:
        for k, v in vals.items():
            if truth[k] != v:
                fail.append(f"[SOURCE] {name} {k}={v} vs pieces 합 {truth[k]}")
    for key, desc in CHECKS:
        lit = fmt(truth[key])
        hits = [m.start() for m in re.finditer(rf"(?<![\d,.]){re.escape(lit)}(?![\d,])", txt)]
        if not hits:
            fail.append(f"[MISSING] {desc} {lit} (산출물 값) 본문에 없음")
        for h in hits:
            info.append(f"[{desc} {lit}] …{ctx(txt, h, h + len(lit))}…")
    for pat in BANNED_PATTERNS:
        for m in re.finditer(pat, txt):
            fail.append(f"[BANNED] '{m.group(0)}' @ …{ctx(txt, m.start(), m.end(), 40)}…")
    for val, c in orphan_m(txt, repo):
        fail.append(f"[ORPHAN] {val} m — 산출물 CSV 수치 열·허용 목록에 없음: …{c}…")
    rate = fmt(truth["outside_rate"])
    spec = fmt(truth["spec_pass"])
    for m in re.finditer(re.escape(rate), txt):
        sent = txt[max(0, m.start() - 160):m.end() + 160]
        if spec not in sent:
            fail.append(f"[DENOM] {rate} % 인근 160자 안에 분모 {spec} 없음: …{ctx(txt, m.start(), m.end())}…")
    print("FAIL" if fail else "PASS")
    print("진실값(pieces 합):", json.dumps(truth, ensure_ascii=False))
    for f in fail:
        print(" -", f)
    print("문맥(사람 확인용):")
    for i in info:
        print(" ·", i)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
