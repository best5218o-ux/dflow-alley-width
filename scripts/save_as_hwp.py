"""제출용 .hwp 저장·검증 (D-075 §5). 확장자만 바꾸지 않고 한글에서 「한글 문서(.hwp)」로 저장한다.

사용: python save_as_hwp.py <제출본.hwpx> <출력.hwp> <작업 폴더>
1) 한글로 hwpx 를 열어 HWP 형식으로 저장한다(원본 hwpx 는 임시 사본으로 연다)
2) 저장된 .hwp 를 다시 열어 쪽수를 읽고, 검증용으로 HWPX 로 되저장해 표·그림(서명·날인) 수와 서식2 쪽수를 잰다
   (PDF 는 인쇄 설정을 한 쪽씩으로 바꾼 임시 사본에서 뽑는다 — hwpx_pdf_pages 와 같은 방식)
"""
import json
import os
import shutil
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hwpx_pdf_pages as hp  # noqa: E402
from layout_variance import com_session, measure_pdf  # noqa: E402


def counts(hwpx):
    s = zipfile.ZipFile(hwpx).read("Contents/section0.xml").decode("utf-8")
    i3 = s.index("&lt;서식3&gt;")
    return {"tbl": s.count("<hp:tbl"), "pic": s.count("<hp:pic"), "서식3~5 pic": s[i3:].count("<hp:pic")}


def main(src, dst, work):
    os.makedirs(work, exist_ok=True)
    tmp_src = os.path.join(work, "src.hwpx")
    shutil.copyfile(src, tmp_src)
    tmp_hwp = os.path.join(work, "out.hwp")
    back = os.path.join(work, "roundtrip.hwpx")
    hwp = com_session()
    out = {}
    try:
        assert hwp.Open(tmp_src, "HWPX", "forceopen:true;versionwarning:false")
        out["hwpx 쪽수"] = hwp.PageCount
        assert hwp.SaveAs(tmp_hwp, "HWP", "")
        hwp.Clear(1)
        assert hwp.Open(tmp_hwp, "HWP", "forceopen:true;versionwarning:false")
        out["hwp 다시 열기 쪽수"] = hwp.PageCount
        assert hwp.SaveAs(back, "HWPX", "")
        hwp.Clear(1)
    finally:
        try:
            hwp.Quit()
        except Exception:
            pass
    one = os.path.join(work, "roundtrip_1up.hwpx")
    hp.copy_one_page_per_sheet(back, one)
    pdf = os.path.join(work, "roundtrip.pdf")
    hwp = com_session()
    try:
        assert hwp.Open(one, "HWPX", "forceopen:true;versionwarning:false")
        assert hwp.SaveAs(pdf, "PDF", "")
        hwp.Clear(1)
    finally:
        try:
            hwp.Quit()
        except Exception:
            pass
    out["hwp 경유 PDF"] = measure_pdf(pdf, src)
    out["원본 hwpx 구성"] = counts(src)
    out["hwp 되저장 구성"] = counts(back)
    out["구성 일치"] = out["원본 hwpx 구성"] == out["hwp 되저장 구성"]
    shutil.copyfile(tmp_hwp, dst)
    out["hwp"] = {"파일": os.path.basename(dst), "바이트": os.path.getsize(dst)}
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:4])
