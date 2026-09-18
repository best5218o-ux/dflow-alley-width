"""hwpx -> PDF 변환 + 서식2 쪽 범위 실측 (D-070 Part B). 추정 금지, 실측만.

사용: python hwpx_pdf_pages.py <입력.hwpx> <출력.pdf>
- 한글 2024 COM(HWPFrame.HwpObject)으로 PDF 를 저장하고, PyMuPDF 로 쪽마다 글자를 읽는다.
- 서식2 시작 = 「<서식2>」가 처음 나오는 쪽, 끝 = 「<서식3>」이 처음 나오는 쪽 - 1.
- 잔여 여백 = 본문 하단 경계(용지 높이 - 아래 여백 - 꼬리말, section0.xml pagePr 에서 읽음) - 끝 쪽 마지막 글자 yMax.
- 입력 파일을 한글이 열고 있으면 실행하지 않는다(열린 판이 나중에 저장되면 되돌아간다).
"""
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile

HWPUNIT_PER_PT = 100          # 1 pt = 100 HWPUNIT
PT_PER_MM = 72 / 25.4


def is_locked(path):
    try:
        with open(path, "r+b"):
            return False
    except OSError:
        return True


def hwp_running():
    """한글이 이미 떠 있으면 COM 이 그 프로세스에 붙는다 — 사용자가 열어 둔 문서의 미저장 편집을 Clear·Quit 가 날린다."""
    import subprocess
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Hwp.exe", "/NH"], capture_output=True).stdout
    return b"Hwp.exe" in out


def to_pdf(hwpx_path, pdf_path):
    if hwp_running():
        raise SystemExit("[중단] 한글(Hwp.exe)이 실행 중이다 — 열린 문서를 저장하고 한글을 모두 닫은 뒤 다시 실행한다")
    import pythoncom
    import win32com.client as win32
    pythoncom.CoInitialize()
    hwp = win32.Dispatch("HWPFrame.HwpObject")
    try:
        try:
            hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        except Exception as e:  # 미등록이어도 진행 — 승인 창이 뜨면 보고한다
            print("[warn] FilePathCheckerModule 미등록:", e, file=sys.stderr)
        try:
            hwp.XHwpWindows.Item(0).Visible = False
        except Exception:
            pass
        ok = hwp.Open(os.path.abspath(hwpx_path), "HWPX", "forceopen:true;versionwarning:false")
        if not ok:
            raise RuntimeError("한글 Open 실패")
        pages = hwp.PageCount
        if not hwp.SaveAs(os.path.abspath(pdf_path), "PDF", ""):
            raise RuntimeError("한글 SaveAs PDF 실패")
        hwp.Clear(1)     # 문서 닫기(변경 버림) — 원본에 쓰지 않는다
        return pages
    finally:
        try:
            hwp.Quit()
        except Exception:
            pass


def copy_one_page_per_sheet(hwpx_path, dst):
    """임시 사본의 settings.xml 인쇄 방식만 「한 쪽씩」(PrintMethod 0)으로 바꾼다.

    양식 원본의 PrintMethod 가 4(모아찍기)라 그대로 PDF 로 저장하면 가로 2쪽 모아찍기가 된다.
    조판(쪽 나눔)은 인쇄 방식과 무관하며, 원본 파일은 바꾸지 않는다.
    """
    zin = zipfile.ZipFile(hwpx_path)
    with zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "settings.xml":
                data = re.sub(rb'(name="PrintMethod" type="short">)\d+', rb"\g<1>0", data)
            zout.writestr(info, data)


def body_box_pt(hwpx_path):
    """(본문 상단, 본문 하단) pt — section0.xml pagePr 의 용지 높이·여백·머리말·꼬리말에서 읽는다."""
    sec = zipfile.ZipFile(hwpx_path).read("Contents/section0.xml").decode("utf-8")
    pp = re.search(r'<hp:pagePr[^>]*height="(\d+)"[^>]*>\s*<hp:margin([^>]*)/>', sec)
    height = int(pp.group(1))
    mg = dict(re.findall(r'(\w+)="(\d+)"', pp.group(2)))
    top = (int(mg["top"]) + int(mg["header"])) / HWPUNIT_PER_PT
    bottom = (height - int(mg["bottom"]) - int(mg["footer"])) / HWPUNIT_PER_PT
    return top, bottom


def page_texts(pdf_path):
    import fitz
    doc = fitz.open(pdf_path)
    return doc, [pg.get_text("text") for pg in doc]


def last_glyph_ymax(doc, page_no):
    """page_no(1-base) 쪽 본문 글자 중 가장 아래 글자의 yMax(pt)."""
    words = doc[page_no - 1].get_text("words")
    return max(w[3] for w in words) if words else None


def measure(hwpx_path, pdf_path):
    if is_locked(hwpx_path):
        raise SystemExit(f"[중단] 한글이 파일을 잡고 있다: {hwpx_path}")
    # 원본을 한글에 직접 열지 않는다 — 임시 사본으로 변환
    tmpdir = tempfile.mkdtemp(prefix="hwpxpdf_")
    src = os.path.join(tmpdir, "src.hwpx")
    copy_one_page_per_sheet(hwpx_path, src)
    hwp_pages = to_pdf(src, pdf_path)
    doc, texts = page_texts(pdf_path)
    n = len(texts)
    s2 = [i + 1 for i, t in enumerate(texts) if "<서식2>" in t]
    s3 = [i + 1 for i, t in enumerate(texts) if "<서식3>" in t]
    start = s2[0] if s2 else None
    end = (s3[0] - 1) if s3 else n
    y = last_glyph_ymax(doc, end) if start else None
    top, bottom = body_box_pt(hwpx_path)
    out = {
        "hwpx": os.path.basename(hwpx_path),
        "hwp_pagecount": hwp_pages, "pdf_pages": n,
        "seosik2_start": start, "seosik2_end": end,
        "seosik2_pages": (end - start + 1) if start else None,
        "last_glyph_yMax": round(y, 2) if y else None,
        "body_bottom_pt": round(bottom, 1),
        "slack_mm": round((bottom - y) / PT_PER_MM, 1) if y else None,
        "last_page_used_mm": round((y - top) / PT_PER_MM, 1) if y else None,   # 끝 쪽에서 쓴 본문 높이
        "limit_ok": ((end - start + 1) <= 15) if start else None,
    }
    doc.close()
    shutil.rmtree(tmpdir, ignore_errors=True)
    return out


if __name__ == "__main__":
    print(json.dumps(measure(sys.argv[1], sys.argv[2]), ensure_ascii=False, indent=2))
