"""004 §16 — 원고(docs/vworld/신청서_최종.md)를 HWPX(ZIP+XML)로 직접 생성한다. 한글 COM 자동화를 쓰지 않는다.

- 한글을 조종하지 않으므로 보안 프롬프트가 생기지 않는다(보안 설정·레지스트리는 건드리지 않음).
- 서식(공고 서식2 작성요령)을 XML 에 박는다: A4 · 좌우 20mm · 위아래 10mm · 머리말·꼬리말 10mm ·
  본문 휴먼명조 15pt 줄간격 140% · 표·캡션 맑은 고딕 12pt · 개조식.
- 뼈대는 hwpx-mois-format 스킬의 template.hwpx(행안부 예시 기반). header.xml 은 문자열 치환으로만 고친다
  (ElementTree 재직렬화 금지 — 네임스페이스 접두사가 바뀌면 한글이 무시).
- 그림은 BinData/imageN.jpg 로 넣고 content.hpf manifest 에 등록한다(도표 3·4·5a~5c·6, 긴 변 1600px JPEG).
- 표 열 너비는 cellSz 로 직접 지정(합 = 본문폭 48189 HWPUNIT). 5열 데이터표 판 사용.
- 쪽수는 한글로 열어 사람이 확인한다(§16-2). 이 스크립트의 est_pages 는 목표 설정용 거친 추정이며 실측이 아니다.
- 출력은 로컬 전용 ~/Downloads/브이월드_공모전/ . 저장소에는 이 스크립트만 커밋.

실행: python scripts/build_hwpx.py --template PATH [--submission]
  --submission: 서식1 연락처 환경변수 DFLOW_EMAIL · DFLOW_PHONE · DFLOW_AFFILIATION 없으면 중단(값은 저장소에 두지 않음)
- 한글 줄나눔: 1차 PDF 에서 breakNonLatinWord="KEEP_WORD" 가 글자 단위로 끊겨 BREAK_WORD 로 바꿈(실측 근거, 2차 PDF 로 재확인).
- 들여쓰기: 음수 intent 는 둘째 줄부터 내어쓰기로 적용됨(1차 PDF 실측) → 글머리표 left 0 · intent -7mm.
"""
from __future__ import annotations

import html
import json
import math
import os
import re
import sys
import time
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "docs/vworld/신청서_v2.md"  # 024 §2 제목 확정 이후 제출 원고는 v2. v1.0(신청서_최종.md)은 기록으로 보존
FIG = ROOT / "figures"
OUTDIR = Path.home() / "Downloads" / "브이월드_공모전"
WORK = OUTDIR / "_조판_작업"
NAME = f"[GeoAI 혁신 아이디어-{os.environ.get('DFLOW_APPLICANT', '신청자')}] D-FLOW 공간정보 도달률 현장 앞 마지막 골목까지"  # 024 §2 파일명(콜론·엠대시 없이 공백만)  # 신청자명은 저장소에 두지 않음
DEFAULT_TEMPLATE = Path(os.environ.get("HWPX_TEMPLATE", "")) if os.environ.get("HWPX_TEMPLATE") else None

MM = 7200 / 25.4  # HWPUNIT per mm
TEXT_W = round(170 * MM)  # 48189

# 도표: (파일, 인쇄 폭 mm). 14쪽 목표(§16-2)로 170mm 원도를 135~150mm 로 축소 삽입.
FIG_MAP = {
    "[도표 6]": [("도표8_영상과도로망_연번31_32.png", 132)],
}

# ---------------------------------------------------------------- header.xml 스타일
BODY_FONT, TABLE_FONT = "휴먼명조", "맑은 고딕"
LANGS = ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")


def char_pr(cid, font_id, pt, bold=False):
    attrs = lambda v: " ".join(f'{l}="{v}"' for l in LANGS)
    return (f'<hh:charPr id="{cid}" height="{int(pt * 100)}" textColor="#000000" shadeColor="none" useFontSpace="0" '
            f'useKerning="0" symMark="NONE" borderFillIDRef="2"><hh:fontRef {attrs(font_id)}/><hh:ratio {attrs(100)}/>'
            f'<hh:spacing {attrs(0)}/><hh:relSz {attrs(100)}/><hh:offset {attrs(0)}/>{"<hh:bold/>" if bold else ""}'
            '<hh:underline type="NONE" shape="SOLID" color="#000000"/><hh:strikeout shape="NONE" color="#000000"/>'
            '<hh:outline type="NONE"/><hh:shadow type="NONE" color="#C0C0C0" offsetX="10" offsetY="10"/></hh:charPr>')


def para_pr(pid, align="JUSTIFY", left_mm=0.0, indent_mm=0.0, spacing=140, prev_pt=0.0, keep_next=False):
    def margin(k):
        v = lambda x: int(round(x * k))
        return (f'<hh:margin><hc:intent value="{v(indent_mm * MM)}" unit="HWPUNIT"/><hc:left value="{v(left_mm * MM)}" unit="HWPUNIT"/>'
                f'<hc:right value="0" unit="HWPUNIT"/><hc:prev value="{v(prev_pt * 100)}" unit="HWPUNIT"/><hc:next value="0" unit="HWPUNIT"/></hh:margin>'
                f'<hh:lineSpacing type="PERCENT" value="{spacing}" unit="HWPUNIT"/>')
    return (f'<hh:paraPr id="{pid}" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" suppressLineNumbers="0" checked="0">'
            f'<hh:align horizontal="{align}" vertical="BASELINE"/><hh:heading type="NONE" idRef="0" level="0"/>'
            f'<hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="BREAK_WORD" widowOrphan="0" keepWithNext="{int(keep_next)}" '
            'keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/><hh:autoSpacing eAsianEng="0" eAsianNum="0"/>'
            '<hp:switch><hp:case hp:required-namespace="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar">'
            f'{margin(1)}</hp:case><hp:default>{margin(2)}</hp:default></hp:switch>'
            '<hh:border borderFillIDRef="2" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/></hh:paraPr>')


def border_fill(bid, width="0.12 mm", face=None):
    side = "".join(f'<hh:{s}Border type="SOLID" width="{width}" color="#000000"/>' for s in ("left", "right", "top", "bottom"))
    fill = (f'<hc:fillBrush><hc:winBrush faceColor="{face}" hatchColor="#999999" alpha="0"/></hc:fillBrush>' if face else "")
    return (f'<hh:borderFill id="{bid}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">'
            '<hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
            f'{side}<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>{fill}</hh:borderFill>')


def bump_count(xml, tag, add):
    return re.sub(rf'(<hh:{tag} itemCnt=")(\d+)(")', lambda m: f"{m.group(1)}{int(m.group(2)) + add}{m.group(3)}", xml, count=1)


def build_header(tpl_header: str):
    h = tpl_header
    # 폰트: 각 언어 fontface 끝에 휴먼명조·맑은 고딕 추가(기존 id 는 스타일이 참조하므로 유지)
    ids = {}

    def add_fonts(m):
        body = m.group(0)
        n = int(re.search(r'fontCnt="(\d+)"', body).group(1))
        extra = ""
        for k, face in enumerate((BODY_FONT, TABLE_FONT)):
            ids[face] = n + k
            extra += (f'<hh:font id="{n + k}" face="{face}" type="TTF" isEmbedded="0"><hh:typeInfo familyType="FCAT_GOTHIC" '
                      'weight="5" proportion="0" contrast="0" strokeVariation="0" armStyle="0" letterform="0" midline="0" xHeight="0"/></hh:font>')
        body = body.replace(f'fontCnt="{n}"', f'fontCnt="{n + 2}"', 1)
        return body.replace("</hh:fontface>", extra + "</hh:fontface>")

    h = re.sub(r"<hh:fontface [^>]*>.*?</hh:fontface>", add_fonts, h, flags=re.S)
    bf_ids = [int(x) for x in re.findall(r'<hh:borderFill id="(\d+)"', h)]
    b0 = max(bf_ids) + 1
    BF = {"cell": b0, "head": b0 + 1, "table": b0 + 2}
    bfs = border_fill(BF["cell"]) + border_fill(BF["head"], face="#E8E8E8") + border_fill(BF["table"], "0.4 mm")
    i = h.rfind("</hh:borderFill>") + len("</hh:borderFill>")
    h = bump_count(h[:i] + bfs + h[i:], "borderFills", 3)

    c0 = max(int(x) for x in re.findall(r'<hh:charPr id="(\d+)"', h)) + 1
    fb, ft = ids[BODY_FONT], ids[TABLE_FONT]
    CP = {"body": c0, "body_b": c0 + 1, "h1": c0 + 2, "h2": c0 + 3, "h3": c0 + 4, "tbl": c0 + 5, "tbl_b": c0 + 6}
    cps = (char_pr(CP["body"], fb, 15) + char_pr(CP["body_b"], fb, 15, True) + char_pr(CP["h1"], fb, 17, True)
           + char_pr(CP["h2"], fb, 16, True) + char_pr(CP["h3"], fb, 15, True) + char_pr(CP["tbl"], ft, 12)
           + char_pr(CP["tbl_b"], ft, 12, True))
    i = h.rfind("</hh:charPr>") + len("</hh:charPr>")
    h = bump_count(h[:i] + cps + h[i:], "charProperties", 7)

    p0 = max(int(x) for x in re.findall(r'<hh:paraPr id="(\d+)"', h)) + 1
    PP = {"body": p0, "bul": p0 + 1, "sub": p0 + 2, "center": p0 + 3, "cell": p0 + 4, "head": p0 + 5, "cap": p0 + 6,
          "quote": p0 + 7, "pic": p0 + 8}
    pps = (para_pr(PP["body"]) + para_pr(PP["bul"], left_mm=0, indent_mm=-7)
           + para_pr(PP["sub"], left_mm=5, indent_mm=-4.5) + para_pr(PP["center"], "CENTER")
           + para_pr(PP["cell"], "LEFT", spacing=120) + para_pr(PP["head"], "LEFT", prev_pt=6, keep_next=True)
           + para_pr(PP["cap"], "LEFT", spacing=130, prev_pt=3, keep_next=True) + para_pr(PP["quote"], left_mm=3)
           + para_pr(PP["pic"], "CENTER", spacing=100))
    i = h.rfind("</hh:paraPr>") + len("</hh:paraPr>")
    h = bump_count(h[:i] + pps + h[i:], "paraProperties", 9)
    return h, BF, CP, PP


# ---------------------------------------------------------------- section0.xml
def esc(t):
    return html.escape(t, quote=False)


def runs(text, cp, cp_b, force_bold=False):
    out = []
    for k, seg in enumerate(re.split(r"\*\*", text)):
        seg = seg.replace("\\*", "*").replace("`", "")
        if seg:
            out.append(f'<hp:run charPrIDRef="{cp_b if (force_bold or k % 2) else cp}"><hp:t>{esc(seg)}</hp:t></hp:run>')
    return "".join(out) or f'<hp:run charPrIDRef="{cp}"/>'


def para(inner, pp, page_break=False):
    return f'<hp:p id="0" paraPrIDRef="{pp}" styleIDRef="0" pageBreak="{int(page_break)}" columnBreak="0" merged="0">{inner}</hp:p>'


def disp_len(s):
    s = re.sub(r"\*\*|`", "", s)
    return sum(1.0 if ord(c) > 0x2E7F or c in "○□「」·—→×" else 0.55 for c in s)


def col_widths(rows, nc):
    lens = [max(disp_len(r[ci]) if ci < len(r) else 0 for r in rows) for ci in range(nc)]
    wts = [max(l, 2) ** 0.6 for l in lens]
    w = [max(12 * MM, TEXT_W * x / sum(wts)) for x in wts]
    k = TEXT_W / sum(w)
    w = [int(x * k) for x in w]
    w[-1] += TEXT_W - sum(w)
    return w


def table_xml(rows, BF, CP, PP, tid):
    nr, nc = len(rows), max(len(r) for r in rows)
    ws = col_widths(rows, nc)
    row_h = 2000
    trs = []
    for ri, r in enumerate(rows):
        tcs = []
        for ci in range(nc):
            cell = (r[ci] if ci < len(r) else "").strip()
            tcs.append(
                f'<hp:tc name="" header="{int(ri == 0)}" hasMargin="0" protect="0" editable="0" dirty="0" '
                f'borderFillIDRef="{BF["head"] if ri == 0 else BF["cell"]}">'
                '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" '
                'linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
                f'{para(runs(cell, CP["tbl"], CP["tbl_b"], ri == 0), PP["cell"])}</hp:subList>'
                f'<hp:cellAddr colAddr="{ci}" rowAddr="{ri}"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
                f'<hp:cellSz width="{ws[ci]}" height="{row_h}"/>'
                '<hp:cellMargin left="510" right="510" top="141" bottom="141"/></hp:tc>')
        trs.append("<hp:tr>" + "".join(tcs) + "</hp:tr>")
    tbl = (f'<hp:tbl id="{tid}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" '
           f'dropcapstyle="None" pageBreak="CELL" repeatHeader="1" rowCnt="{nr}" colCnt="{nc}" cellSpacing="0" '
           f'borderFillIDRef="{BF["table"]}" noAdjust="0">'
           f'<hp:sz width="{TEXT_W}" widthRelTo="ABSOLUTE" height="{row_h * nr}" heightRelTo="ABSOLUTE" protect="0"/>'
           '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" '
           'horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
           '<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:inMargin left="510" right="510" top="141" bottom="141"/>'
           + "".join(trs) + "</hp:tbl>")
    return para(f'<hp:run charPrIDRef="{CP["tbl"]}">{tbl}<hp:t/></hp:run>', PP["cell"]), ws


def pic_xml(bin_id, px, py, width_mm, pid, CP, PP):
    w = int(width_mm * MM)
    hgt = int(w * py / px)
    dw, dh = px * 75, py * 75
    pic = (f'<hp:pic id="{pid}" zOrder="{pid}" numberingType="PICTURE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" '
           f'dropcapstyle="None" href="" groupLevel="0" instid="{pid + 5000}" reverse="0">'
           f'<hp:offset x="0" y="0"/><hp:orgSz width="{w}" height="{hgt}"/><hp:curSz width="{w}" height="{hgt}"/>'
           f'<hp:flip horizontal="0" vertical="0"/><hp:rotationInfo angle="0" centerX="{w // 2}" centerY="{hgt // 2}" rotateimage="1"/>'
           '<hp:renderingInfo><hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
           '<hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/><hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/></hp:renderingInfo>'
           f'<hc:img binaryItemIDRef="{bin_id}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
           f'<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="{w}" y="0"/><hc:pt2 x="{w}" y="{hgt}"/><hc:pt3 x="0" y="{hgt}"/></hp:imgRect>'
           f'<hp:imgClip left="0" right="{dw}" top="0" bottom="{dh}"/><hp:inMargin left="0" right="0" top="0" bottom="0"/>'
           f'<hp:imgDim dimwidth="{dw}" dimheight="{dh}"/><hp:effects/>'
           f'<hp:sz width="{w}" widthRelTo="ABSOLUTE" height="{hgt}" heightRelTo="ABSOLUTE" protect="0"/>'
           '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" '
           'horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
           '<hp:outMargin left="0" right="0" top="0" bottom="0"/></hp:pic>')
    return para(f'<hp:run charPrIDRef="{CP["body"]}">{pic}<hp:t/></hp:run>', PP["pic"]), hgt / MM


def sec_pr(tpl_section: str):
    s = tpl_section
    i, j = s.find("<hp:secPr"), s.find("</hp:secPr>") + len("</hp:secPr>")
    sp = s[i:j]
    m10, m20 = round(10 * MM), round(20 * MM)
    sp = re.sub(r'<hp:margin [^>]*/>', f'<hp:margin header="{m10}" footer="{m10}" gutter="0" left="{m20}" right="{m20}" top="{m10}" bottom="{m10}"/>', sp)
    sp = re.sub(r'(<hp:pagePr [^>]*width=")\d+(" height=")\d+', r"\g<1>59528\g<2>84186", sp)
    return sp


def parse(md: str):
    lines, out, i, skipped = md.split("\n"), [], 0, False
    while i < len(lines):
        l = lines[i]
        if not skipped and l.startswith("> 원고 v"):
            while i < len(lines) and lines[i].startswith(">"):
                i += 1
            skipped = True
            continue
        if l.startswith("|"):
            block = []
            while i < len(lines) and lines[i].startswith("|"):
                if not re.match(r"^\|\s*-", lines[i]):
                    block.append(lines[i].strip().strip("|").split("|"))
                i += 1
            out.append(("table", block))
            continue
        out.append(("line", l))
        i += 1
    return out


# ---------------------------------------------------------------- 쪽 배치 모의(실측 아님)
# 한글 PDF(2026-09-15 23:31, 13쪽)에서 잰 값: 본문 영역 y 20.0~277.0 mm, 15pt 줄 간격 7.4 mm, 한글 1자 5.26 mm.
BODY_TOP, BODY_BOTTOM = 20.0, 277.0
CHAR_MM_PER_PT = 5.26 / 15
CONTACT_KEYS = ("DFLOW_EMAIL", "DFLOW_PHONE", "DFLOW_AFFILIATION")


def wrap_lines(text, pt, avail_mm, by_word=True):
    """줄 수 추정. by_word=True 는 어절 단위, False 는 글자 단위."""
    text = re.sub(r"\*\*|`", "", text)
    cap = avail_mm / (pt * CHAR_MM_PER_PT)
    if not by_word:
        return max(1, math.ceil(disp_len(text) / cap))
    n, cur = 1, 0.0
    for w in text.split(" "):
        lw = disp_len(w)
        add = lw if cur == 0 else lw + 0.5
        if cur + add > cap and cur > 0:
            n += 1
            cur = lw
            while cur > cap:  # 한 어절이 줄보다 길면 글자로 끊김
                n += 1
                cur -= cap
        else:
            cur += add
    return n


def simulate(blocks):
    """blocks: dict(kind=text|rows|img, h=[줄·행 높이] 또는 그림 높이, prev, keep(다음과 같은 쪽), pb(쪽 나눔), label)."""
    pages, y, free = [[]], BODY_TOP, []
    for k, b in enumerate(blocks):
        if b.get("pb") and pages[-1]:
            free.append(BODY_BOTTOM - y); pages.append([]); y = BODY_TOP
        units = b["h"] if isinstance(b["h"], list) else [b["h"]]
        prev = b.get("prev", 0) if y > BODY_TOP else 0
        need = prev + (sum(units) if b["kind"] == "img" else units[0])
        if b.get("keep") and k + 1 < len(blocks):
            nb = blocks[k + 1]
            nu = nb["h"] if isinstance(nb["h"], list) else [nb["h"]]
            need = prev + sum(units) + nb.get("prev", 0) + (nu[0] if nb["kind"] != "img" else nb["h"])
        if y + need > BODY_BOTTOM and y > BODY_TOP:
            free.append(BODY_BOTTOM - y); pages.append([]); y = BODY_TOP; prev = 0
        y += prev
        pages[-1].append((b["label"], round(y, 1)))
        for u in units:
            if y + u > BODY_BOTTOM and y > BODY_TOP:
                free.append(BODY_BOTTOM - y); pages.append([(b["label"] + "(이어짐)", BODY_TOP)]); y = BODY_TOP
            y += u
    free.append(BODY_BOTTOM - y)
    return pages, free


# ---------------------------------------------------------------- 005 §9 금지어 검사(1건이라도 걸리면 빌드 중단 — 사람이 판정)
BANNED = ("네이버", "카카오", "구글", "파파고", "HyperCLOVA", "T맵", "naver", "kakao", "google",
          "네비게이션", "내비게이션", "길안내", "최단경로", "경로추천", "이중경로",
          "역방향 통행", "순편익", "ETA 단축", "FAST_ROUTE", "FIELD_FLOW",
          "우선신호", "광역 표준화", "광역표준화", "부산 침수", "관광 동선",
          "확장판", "고도화", "후속",
          # 009 §8 폐기 목록 · §3 서술 금지(되살리지 않는다). 「43%」 단독은 인용 가능 수치 97.43% 와 겹쳐 폐기 수치(3.0 m 43% · 1,306)로 좁힘
          "157종", "새주소도로", "3,038", "1,306", "3.0 m 43", "43%(", "43% (", "대로 22", "폭이 어디에도 없다", "길이 없다", "모순", "오류", "부실", "틀렸다", "품질이 나쁘다",
          # 011 §11 폐기 — 번길 가설·코드 12 분절 서술
          "번길 위계 부재", "골목 위계 자체", "코드 체계 불일치", "누락", "빠졌다")
# 화이트리스트 2곳(005 §6-2): ① 1장 「어떤 경로탐색·내비게이션·배정 엔진도 그 골목을 계산 대상으로 삼지 못함」 문장 ② 1-3 자진기재 절 전체
WHITELIST_SENTENCE = "어떤 경로탐색·내비게이션·배정 엔진도 그 골목을 계산 대상으로 삼지 못함"
FIGURE_TEXT_SOURCES = ("scripts/figures_final_004.py", "docs/vworld/e5/figure5.html")


def banned_scan(md: str):
    lines = md.split("\n")
    hits, in_13, wl = [], False, {"sentence": 0, "section_1_3_lines": 0}
    for no, line in enumerate(lines, 1):
        if line.startswith("### □ 1-3.") or line.strip() == "**자진기재**":
            in_13 = True   # 005 §6-2 ② 자진기재 절 — 절 번호가 바뀌어도 같은 범위를 가리킨다
        elif in_13 and (line.startswith("## ") or line.startswith("### ") or line.strip() == "---"):
            in_13 = False
        if in_13:
            wl["section_1_3_lines"] += 1
            continue
        if WHITELIST_SENTENCE in line:
            wl["sentence"] += 1
            line = line.replace(WHITELIST_SENTENCE, "")
        low = line.lower()
        hits += [("원고", no, w) for w in BANNED if w.lower() in low]
    for src in FIGURE_TEXT_SOURCES:
        for no, line in enumerate((ROOT / src).read_text(encoding="utf-8").split("\n"), 1):
            low = line.lower()
            hits += [(src, no, w) for w in BANNED if w.lower() in low]
    return hits, wl


def main():
    tpl = Path(sys.argv[sys.argv.index("--template") + 1]) if "--template" in sys.argv else DEFAULT_TEMPLATE
    if not tpl or not tpl.exists():
        sys.exit("template.hwpx 경로가 필요하다: --template PATH 또는 HWPX_TEMPLATE 환경변수")
    submission = "--submission" in sys.argv
    by_word = "--char-wrap" not in sys.argv
    md = MD.read_text(encoding="utf-8")
    hits, wl = banned_scan(md)
    print(json.dumps({"banned_hits": len(hits), "whitelist": wl}, ensure_ascii=False))
    if wl["sentence"] != 1 or wl["section_1_3_lines"] == 0:
        sys.exit(f"화이트리스트 보존 확인 실패: {wl}")
    if hits:
        for h in hits:
            print("금지어", h)
        sys.exit(f"빌드 중단: 금지어 {len(hits)}건 — 사람이 판정")
    missing = [k for k in CONTACT_KEYS if not os.environ.get(k, "").strip()]
    if submission and missing:
        sys.exit(f"제출본 빌드 중단: 서식1 필수 연락처 환경변수 없음 — {', '.join(missing)} (값은 저장소에 두지 않는다)")
    for key in CONTACT_KEYS:
        md = md.replace("{{" + key + "}}", os.environ.get(key, "").strip() or "〔미기입 — 제출본 아님〕")
    with zipfile.ZipFile(tpl) as z:
        files = {n: z.read(n) for n in z.namelist()}
    header, BF, CP, PP = build_header(files["Contents/header.xml"].decode("utf-8"))
    tsec = files["Contents/section0.xml"].decode("utf-8")
    sec_open = tsec[: tsec.find("<hp:p ")]
    secpr = sec_pr(tsec)

    body, bins, figs_used, tables, blocks = [], [], [], [], []
    first = True
    started_form2 = False
    tid = 1
    L15 = 15 * 0.3528 * 1.4
    L12c = 12 * 0.3528 * 1.3
    wl = lambda t, pt, w: wrap_lines(t, pt, w, by_word)
    for kind, v in parse(md):
        if kind == "table":
            x, ws = table_xml(v, BF, CP, PP, 9000 + tid)
            tables.append({"cols": len(ws), "rows": len(v), "col_mm": [round(w / MM, 1) for w in ws]})
            tid += 1
            body.append(x)
            # 행 높이(1차 PDF 실측): max(최소 7.06, 여백 1.0 + 첫 줄 4.23 + 추가 줄당 5.08) mm
            rows_h = [max(7.06, 1.0 + 4.23 + 5.08 * (max(wl(c.strip(), 12, w / MM - 3.6) for c, w in zip(r, ws)) - 1)) for r in v]
            blocks.append({"kind": "rows", "h": rows_h, "label": "표:" + re.sub(r"\*\*", "", v[0][0]).strip()[:8]})
            continue
        l = v
        if not l.strip() or l.strip() == "---":
            continue
        pb = False
        if l.startswith("## 〈서식2〉") and not started_form2:
            pb, started_form2 = True, True
        m = next((k for k in FIG_MAP if k in l), None)
        bold_line = l.startswith("**") and l.rstrip().endswith("**") and l.count("**") == 2
        if l.startswith("# "):
            x = para(runs(l[2:], CP["h1"], CP["h1"]), PP["center"])
            blocks.append({"kind": "text", "h": [17 * 0.3528 * 1.4] * wl(l[2:], 17, 170), "label": l[2:16]})
        elif l.startswith("## "):
            x = para(runs(l[3:], CP["h2"], CP["h2"]), PP["head"], pb)
            blocks.append({"kind": "text", "h": [16 * 0.3528 * 1.4] * wl(l[3:], 16, 170), "prev": 2.1, "keep": True, "pb": pb, "label": l[3:20]})
        elif l.startswith("### "):
            x = para(runs(l[4:], CP["h3"], CP["h3"]), PP["head"])
            blocks.append({"kind": "text", "h": [L15] * wl(l[4:], 15, 170), "prev": 2.1, "keep": True, "label": l[4:20]})
        elif m and l.startswith("**"):
            x = para(runs(l, CP["tbl_b"], CP["tbl_b"]), PP["cap"])
            blocks.append({"kind": "text", "h": [L12c] * wl(l, 12, 170), "prev": 1.1, "keep": True, "label": l[2:12]})
            for f, wmm in FIG_MAP[m]:
                WORK.mkdir(parents=True, exist_ok=True)
                im = Image.open(FIG / f).convert("RGB")
                k = 1600 / max(im.size)
                if k < 1:
                    im = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
                bid = f"image{len(bins) + 1}"
                jp = WORK / (Path(f).stem + ".jpg")
                im.save(jp, "JPEG", quality=85, optimize=True)
                bins.append((bid, jp))
                px, hmm = pic_xml(bid, im.width, im.height, wmm, len(bins), CP, PP)
                x += px
                blocks.append({"kind": "img", "h": hmm, "label": "그림:" + f[:6]})
                figs_used.append({"file": f, "width_mm": wmm, "height_mm": round(hmm, 1)})
        elif bold_line:
            # 표 제목 등 단독 굵은 줄 — 다음 표와 같은 쪽(keepWithNext)
            x = para(runs(l, CP["tbl_b"], CP["tbl_b"]), PP["cap"])
            blocks.append({"kind": "text", "h": [L12c] * wl(l, 12, 170), "prev": 1.1, "keep": True, "label": l[2:12]})
        elif l.startswith("> "):
            x = para(runs(l[2:], CP["body_b"], CP["body_b"]), PP["quote"])
            blocks.append({"kind": "text", "h": [L15] * wl(l[2:], 15, 167), "label": l[2:12]})
        elif l.startswith(" - "):
            x = para(runs("- " + l[3:], CP["body"], CP["body_b"]), PP["sub"])
            blocks.append({"kind": "text", "h": [L15] * wl("- " + l[3:], 15, 160.5), "label": l[3:12]})
        elif l.startswith("- "):
            x = para(runs("○ " + l[2:], CP["body"], CP["body_b"]), PP["bul"])
            blocks.append({"kind": "text", "h": [L15] * wl("○ " + l[2:], 15, 163), "label": l[2:12]})
        else:
            x = para(runs(l, CP["body"], CP["body_b"]), PP["body"])
            blocks.append({"kind": "text", "h": [L15] * wl(l, 15, 170), "label": l[:12]})
        if first:
            # 첫 단락 앞에 구역 정의(secPr)·단 정의·쪽번호를 넣는다
            ctrl = (f'<hp:run charPrIDRef="{CP["body"]}">{secpr}<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" '
                    'colCount="1" sameSz="1" sameGap="0"/></hp:ctrl><hp:ctrl><hp:pageNum pos="BOTTOM_CENTER" '
                    'formatType="DIGIT" sideChar="-"/></hp:ctrl></hp:run>')
            x = x.replace(">", ">" + ctrl, 1)
            first = False
        body.append(x)

    section = sec_open + "".join(body) + "</hs:sec>"
    hpf = files["Contents/content.hpf"].decode("utf-8")
    hpf = re.sub(r"<opf:title>.*?</opf:title>", "<opf:title>D-FLOW 참가신청서</opf:title>", hpf)
    items = "".join(f'<opf:item id="{b}" href="BinData/{b}.jpg" media-type="image/jpeg" isEmbeded="1"/>' for b, _ in bins)
    hpf = hpf.replace("</opf:manifest>", items + "</opf:manifest>")
    prv = re.sub(r"[*#>|`]", "", md)[:1000]

    OUTDIR.mkdir(parents=True, exist_ok=True)
    # 연락처 미기입 빌드는 제출 파일명과 섞이지 않게 검수용 접미사를 붙인다
    out = OUTDIR / (f"{NAME}.hwpx" if not missing else f"{NAME} (검수용-연락처 미기입).hwpx")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", files["mimetype"], compress_type=zipfile.ZIP_STORED)
        for n, data in files.items():
            if n == "mimetype" or n == "Preview/PrvImage.png":
                continue
            if n == "Contents/header.xml":
                data = header.encode("utf-8")
            elif n == "Contents/section0.xml":
                data = section.encode("utf-8")
            elif n == "Contents/content.hpf":
                data = hpf.encode("utf-8")
            elif n == "Preview/PrvText.txt":
                data = prv.encode("utf-8")
            z.writestr(n, data)
        for b, p in bins:
            z.write(p, f"BinData/{b}.jpg", compress_type=zipfile.ZIP_STORED)

    pages, free = simulate(blocks)
    res = {"hwpx": str(out.name), "bytes": out.stat().st_size, "submission": submission, "contact_missing": missing,
           "figures": figs_used, "tables": tables, "sim_pages_not_measured": len(pages),
           "sim_page_starts": [pg[0][0] for pg in pages], "sim_free_bottom_mm": [round(f) for f in free],
           "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    (WORK / "build_hwpx_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("hwpx", "submission", "contact_missing", "sim_pages_not_measured")}, ensure_ascii=False))
    for n, (pg, fr) in enumerate(zip(pages, free), 1):
        print(f"p{n:02d} free {fr:5.0f}mm | " + " / ".join(lab for lab, _ in pg[:3]) + (" … " + pg[-1][0] if len(pg) > 3 else ""))


if __name__ == "__main__":
    main()
