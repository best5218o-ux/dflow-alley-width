"""한글 환경 차이로 생기는 조판 편차 실측 (D-072 §2). 추정 금지, 실측만.

사용: python layout_variance.py <제출본.hwpx> <작업 폴더>
- 형식 편차(§2-1): hwpx 그대로 · hwp(바이너리)로 저장해 다시 연 것 · 이전 버전 호환 저장(한글에 옵션이 있을 때)
- 글꼴 편차(§2-2): 임시 사본 header.xml 의 「휴먼명조」를 「함초롬바탕」으로 일괄 치환
- 각 경우 PDF 를 뽑아 서식2 쪽수·slack_mm 을 잰다. 제출본은 읽기만 한다(임시 사본에서만 작업)
산출: data/vworld/national/derived/layout_variance.json
"""
import json
import os
import pathlib
import re
import shutil
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import hwpx_pdf_pages as hp  # noqa: E402

PT_PER_MM = hp.PT_PER_MM


def measure_pdf(pdf, box_src_hwpx):
    doc, texts = hp.page_texts(pdf)
    s2 = [i + 1 for i, t in enumerate(texts) if "<서식2>" in t]
    s3 = [i + 1 for i, t in enumerate(texts) if "<서식3>" in t]
    start, end = (s2[0] if s2 else None), ((s3[0] - 1) if s3 else len(texts))
    y = hp.last_glyph_ymax(doc, end) if start else None
    top, bottom = hp.body_box_pt(box_src_hwpx)
    doc.close()
    return {"pdf_pages": len(texts), "seosik2_start": start, "seosik2_end": end,
            "seosik2_pages": (end - start + 1) if start else None,
            "slack_mm": round((bottom - y) / PT_PER_MM, 1) if y else None,
            "last_page_used_mm": round((y - top) / PT_PER_MM, 1) if y else None}


def com_session():
    import time
    for _ in range(30):              # 직전 세션의 Quit 뒤 프로세스가 내려갈 때까지 최대 30초 기다린다
        if not hp.hwp_running():
            break
        time.sleep(1)
    if hp.hwp_running():
        raise SystemExit("[중단] 한글(Hwp.exe)이 실행 중이다 — 한글을 모두 닫은 뒤 다시 실행한다")
    import pythoncom
    import win32com.client as win32
    pythoncom.CoInitialize()
    hwp = win32.Dispatch("HWPFrame.HwpObject")
    try:
        hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
    except Exception:
        pass
    try:
        hwp.XHwpWindows.Item(0).Visible = False
    except Exception:
        pass
    return hwp


def main(src, work):
    work = pathlib.Path(work)
    work.mkdir(parents=True, exist_ok=True)
    base = work / "base.hwpx"
    hp.copy_one_page_per_sheet(src, str(base))       # 인쇄 방식만 한 쪽씩(조판 무관)
    font = work / "font_hamchorom.hwpx"
    with zipfile.ZipFile(base) as zin, zipfile.ZipFile(font, "w") as zout:
        n_sub = 0
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "Contents/header.xml":
                txt = data.decode("utf-8")
                n_sub = txt.count('face="휴먼명조"')
                data = txt.replace('face="휴먼명조"', 'face="함초롬바탕"').encode("utf-8")
            zout.writestr(info, data)

    out = {"src": os.path.basename(src)}
    hwp = com_session()
    try:
        def run(label, path, fmt, save_as=None, save_fmt=None, save_arg=""):
            if not hwp.Open(str(path), fmt, "forceopen:true;versionwarning:false"):
                return {"오류": f"{fmt} 열기 실패"}
            rec = {}
            if save_as:
                ok = hwp.SaveAs(str(save_as), save_fmt, save_arg)
                rec["저장"] = f"SaveAs({save_fmt}, '{save_arg}') = {bool(ok)}"
                hwp.Clear(1)
                if not ok or not hwp.Open(str(save_as), save_fmt, "forceopen:true;versionwarning:false"):
                    rec["오류"] = "저장본 다시 열기 실패"
                    return rec
            pdf = work / f"{label}.pdf"
            rec["hwp_pagecount"] = hwp.PageCount
            if not hwp.SaveAs(str(pdf), "PDF", ""):
                rec["오류"] = "PDF 저장 실패"
            hwp.Clear(1)
            if "오류" not in rec:
                rec.update(measure_pdf(str(pdf), str(base)))
            return rec

        out["hwpx(기준)"] = run("hwpx", base, "HWPX")
        out["hwp(바이너리)"] = run("hwp", base, "HWPX", work / "as_binary.hwp", "HWP")
        # 한글 SaveAs 의 이전 버전 호환: 형식 이름 「HWP」 외에 공개된 구버전 형식 이름이 없어 인자 방식으로만 시도한다
        compat = run("hwp_compat", base, "HWPX", work / "as_compat.hwp", "HWP", "compatibility:true")
        out["hwp(이전 버전 호환 인자 시도)"] = compat
        out["휴먼명조→함초롬바탕(치환 %d곳)" % n_sub] = run("font", font, "HWPX")
    finally:
        try:
            hwp.Quit()
        except Exception:
            pass

    fmt_keys = [k for k in out if k.startswith("hwp")]
    fmt_slacks = [out[k]["slack_mm"] for k in fmt_keys if out[k].get("seosik2_pages") == out["hwpx(기준)"].get("seosik2_pages")
                  and out[k].get("slack_mm") is not None]
    fmt_pages = {out[k].get("seosik2_pages") for k in fmt_keys}
    font_key = next(k for k in out if k.startswith("휴먼명조"))
    base_rec = out["hwpx(기준)"]

    def dev(rec):
        """기준 대비 조판 편차(mm). 쪽수가 늘면 넘친 높이(끝 쪽 사용분)까지 더한다."""
        if rec.get("seosik2_pages") is None:
            return None
        if rec["seosik2_pages"] == base_rec["seosik2_pages"]:
            return round(max(0.0, base_rec["slack_mm"] - rec["slack_mm"]), 1)
        return round(base_rec["slack_mm"] + rec["last_page_used_mm"], 1)   # 한 쪽 넘친 경우

    out["편차"] = {
        "형식 편차_mm": max([dev(out[k]) or 0.0 for k in fmt_keys] + [0.0]),
        "형식별 서식2 쪽수": sorted(p for p in fmt_pages if p is not None),
        "글꼴 편차_mm": dev(out[font_key]),
        "글꼴 치환 서식2 쪽수": out[font_key].get("seosik2_pages"),
    }
    need = max(out["편차"]["형식 편차_mm"], out["편차"]["글꼴 편차_mm"] or 0.0) + 2.0
    out["필요 마진_mm(max+2)"] = round(need, 1)
    out["현재 slack_mm"] = base_rec.get("slack_mm")
    out["발송 가능"] = base_rec.get("slack_mm") is not None and base_rec["slack_mm"] >= need
    dst = pathlib.Path(__file__).resolve().parents[1] / "data/vworld/national/derived/layout_variance.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
