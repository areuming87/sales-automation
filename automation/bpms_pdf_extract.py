r"""
═══════════════════════════════════════════════════════════════
  BPMS 첨부파일 PDF 데이터 추출
  ───────────────────────────────────────────────────────────
  attachments\<PJT>\ 안의 PDF 들에서 누리집 입력 필드 추출

  대상 PDF (파일명 키워드로 식별):
    - 사업자등록증            → 기관명(법인명) ⚠ 보통 스캔본 → OCR 필요
    - 현장실사 확인서          → 설치방식, 전기수전방식, 조사자 성명/연락처

  사용:
    python bpms_pdf_extract.py HL26030060 HN25080268 ...
    python bpms_pdf_extract.py --all
    python bpms_pdf_extract.py --dump HL26030060
═══════════════════════════════════════════════════════════════
"""

import sys
import os
import re
import json
import argparse
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ATTACH_ROOT = Path(r"\\GSChargev_NAS\EV사업실\[영업현황 자동화_NAS]\attachments")

# Tesseract 실행 파일 경로 (Windows 기본 설치 위치)
TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"C:\Tesseract-OCR\tesseract.exe",
]


# ──── PDF 텍스트 추출 ──────────────────────────────────
def _read_pdf_text(pdf_path: Path) -> str:
    """PDF → 전체 텍스트 (pdfplumber → pypdf fallback). 스캔본은 빈 문자열."""
    text = ""
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                text += t + "\n"
        if text.strip():
            return text
    except Exception as e:
        print(f"    ⚠ pdfplumber 실패: {e}", flush=True)

    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        for page in reader.pages:
            t = page.extract_text() or ""
            text += t + "\n"
    except Exception as e:
        print(f"    ⚠ pypdf 실패: {e}", flush=True)

    return text


# ──── OCR (PyMuPDF + Tesseract) ───────────────────────
_ocr_setup_done = False
_ocr_available = False

def _setup_ocr():
    """OCR 라이브러리·바이너리 사용 가능한지 1회 확인"""
    global _ocr_setup_done, _ocr_available
    if _ocr_setup_done:
        return _ocr_available
    _ocr_setup_done = True
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image  # noqa
    except ImportError as e:
        print(f"  ⚠ OCR 미설치: {e}  (pip install PyMuPDF pytesseract Pillow)", flush=True)
        return False

    # Tesseract 실행 파일 찾기
    found = None
    for cand in TESSERACT_CANDIDATES:
        if Path(cand).exists():
            found = cand
            break
    if found:
        pytesseract.pytesseract.tesseract_cmd = found
        print(f"  🔍 Tesseract 발견: {found}", flush=True)
    else:
        # PATH 에 있으면 사용
        try:
            import subprocess
            subprocess.run(["tesseract", "--version"],
                           capture_output=True, check=True, timeout=5)
            print(f"  🔍 Tesseract: PATH 사용", flush=True)
        except Exception:
            print(f"  ⚠ Tesseract 미설치 — 설치 후 사용 가능", flush=True)
            print(f"     https://github.com/UB-Mannheim/tesseract/wiki", flush=True)
            return False

    _ocr_available = True
    return True


def _convert_pdf_to_searchable(pdf_path: Path, dpi: int = 400) -> bool:
    """스캔본 PDF → 검색가능 PDF 로 변환 (덮어쓰기 + 원본은 _original_scan/ 백업)
       반환: True 성공, False 실패"""
    if not _setup_ocr():
        return False
    try:
        import fitz, pytesseract, io, shutil
        from PIL import Image

        new_doc = fitz.open()
        with fitz.open(str(pdf_path)) as src:
            for page in src:
                pix = page.get_pixmap(dpi=dpi)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                pdf_bytes = pytesseract.image_to_pdf_or_hocr(
                    img, lang="kor+eng", extension="pdf", config="--psm 6"
                )
                with fitz.open("pdf", pdf_bytes) as page_doc:
                    new_doc.insert_pdf(page_doc)

        # 원본 백업 + 검색가능 PDF 로 교체
        backup_dir = pdf_path.parent / "_original_scan"
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / pdf_path.name
        if not backup_path.exists():
            shutil.copy2(str(pdf_path), str(backup_path))

        tmp_path = pdf_path.with_suffix(pdf_path.suffix + ".tmp")
        new_doc.save(str(tmp_path))
        new_doc.close()
        shutil.move(str(tmp_path), str(pdf_path))
        return True
    except Exception as e:
        print(f"    ⚠ PDF → 검색가능 변환 실패: {e}", flush=True)
        return False


def _ocr_pdf_text(pdf_path: Path, dpi: int = 400) -> str:
    """스캔본 PDF → OCR 텍스트. 페이지별 OCR + 다중 PSM 시도.
       OCR 불가 시 빈 문자열."""
    if not _setup_ocr():
        return ""
    try:
        import fitz
        import pytesseract
        from PIL import Image

        text_parts = []
        with fitz.open(str(pdf_path)) as doc:
            n_pages = len(doc)
            print(f"    📄 PDF 페이지 수: {n_pages}", flush=True)
            for i, page in enumerate(doc, 1):
                pix = page.get_pixmap(dpi=dpi)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

                # PSM 6 (uniform block) — 사업자등록증 같은 폼 문서에 효과적
                cfg = "--psm 6"
                t = pytesseract.image_to_string(img, lang="kor+eng", config=cfg)

                # 만약 짧으면 PSM 3 (auto) 재시도
                if len(t.strip()) < 100:
                    t2 = pytesseract.image_to_string(img, lang="kor+eng")
                    if len(t2.strip()) > len(t.strip()):
                        t = t2

                # 그래도 짧으면 더 높은 DPI 로 한 번 더
                if len(t.strip()) < 100 and dpi < 600:
                    pix2 = page.get_pixmap(dpi=600)
                    img2 = Image.frombytes("RGB", (pix2.width, pix2.height), pix2.samples)
                    t3 = pytesseract.image_to_string(img2, lang="kor+eng", config="--psm 6")
                    if len(t3.strip()) > len(t.strip()):
                        t = t3

                print(f"    📄 페이지 {i}/{n_pages}: {len(t.strip())}자 추출", flush=True)
                text_parts.append(f"--- PAGE {i} ---\n{t}")

        return "\n".join(text_parts)
    except Exception as e:
        print(f"    ⚠ OCR 실패: {e}", flush=True)
        return ""


# ──── 파일 찾기 ────────────────────────────────────────
def find_pdfs_in_pjt(pjt: str) -> dict:
    """PJT 폴더 안에서 대상 PDF 찾기.
       반환: {'business': [Path, ...], 'inspection': [Path, ...]}"""
    pjt_dir = ATTACH_ROOT / pjt
    result = {"business": [], "inspection": []}

    if not pjt_dir.exists():
        return result

    # 재귀적으로 모든 PDF 찾기 (단, _zips / _original_scan 폴더는 제외)
    for pdf in pjt_dir.rglob("*.pdf"):
        if "_zips" in pdf.parts or "_original_scan" in pdf.parts:
            continue
        name = pdf.name
        # 사업자등록증 / 고유번호증 매칭 (둘 다 business 로)
        # "기타서류_..._고유번호증.pdf" 같은 파일명도 인식
        if "사업자등록증" in name or "고유번호증" in name:
            result["business"].append(pdf)
        # 현장실사 확인서 매칭 (공백 유무 모두, "사전컨설팅" 도 포함)
        elif re.search(r"현장실사\s*확인서|사전\s*컨설팅", name):
            result["inspection"].append(pdf)

    return result


# ──── 정규식 패턴 ──────────────────────────────────────
# ──── 키워드 사전 ────────────────────────────────────
# 설치방식 (설치타입) — 체크박스 ■ 옆에 나오는 값들
INSTALL_METHOD_VALUES = ["벽부형", "스탠드형", "스탠드"]
# 정규화: PDF 의 "스탠드" → 누리집 표준 "스탠드형"
INSTALL_METHOD_NORMALIZE = {
    "스탠드": "스탠드형",
    "벽부": "벽부형",
}

# 전기수전방식 (전력인입) — 체크박스 ■ 옆 값
POWER_METHOD_VALUES = ["한전불입", "모자분할", "잔체전력", "전체전력"]


def _clean(value: str) -> str:
    if not value:
        return ""
    v = re.sub(r"\s+", " ", value).strip()
    v = re.sub(r"[\(\)\[\]\.,;]+$", "", v).strip()
    return v


def _normalize_korean_name(name: str) -> str:
    """'남 문 호' → '남문호' (자모 사이 공백 제거)"""
    return re.sub(r"\s+", "", name).strip()


def _normalize_korean_spacing(text: str) -> str:
    """OCR 의 자모 분리 띄어쓰기 정상화
       '장 유 덕 산 아 내' → '장유덕산아내'
       3글자 이상 연속으로 한 글자씩 띄어진 패턴만 압축 (정상 띄어쓰기 보존)"""
    if not text:
        return text
    return re.sub(
        r"([가-힣])(?:\s+([가-힣])){2,}",
        lambda m: re.sub(r"\s+", "", m.group(0)),
        text
    )


# 잘못 추출되는 대표자 후보들 (OCR 면책문구·헤더 등에서 오인식)
REP_BLACKLIST = {
    "변경", "정정", "임을", "임을증명", "임을증명하지", "증명하지",
    "공란", "없음", "해당없음", "본점", "지점",
    "신고", "발급", "교부", "사업자", "기관명", "법인명", "단체명",
    "aoa", "tara",
}


def _is_valid_korean_name(name: str) -> bool:
    """대표자 이름인지 검증 — 한국 이름은 보통 2-4자 한글"""
    if not name:
        return False
    if name in REP_BLACKLIST:
        return False
    # 한글 2-5자 + 영어 허용
    if not re.match(r"^[가-힣A-Za-z]{2,5}$", name):
        return False
    return True


# ──── 사업자등록증 / 고유번호증 추출 ─────────────────
# 사업자등록증과 고유번호증은 필드명만 다르고 의미 동일:
#   사업자등록증              고유번호증
#   ────────────              ────────────
#   등록번호       ←→         고유번호
#   법인명(단체명) ←→         단체명
#   대표자         ←→         대표자 성명

def extract_business(text: str, filename: str = "") -> dict:
    """사업자등록증/고유번호증 PDF → 법인명/단체명 + 대표자 + 등록번호
       OCR 띄어쓰기 허용. '발급 사유' 영역은 절대 건드리지 않음."""
    out = {}

    is_unique_no = "고유번호증" in (filename or "") \
        or bool(re.search(r"고\s*유\s*번\s*호\s*증", text))

    # ⚠ "발 급 사 유 : 정정 / 변경" 같은 후미 영역은 잘못 매칭되기 쉬움
    # → text 에서 "발급사유" 이후 부분을 잘라내고 검색 (단, 너무 위면 정상 데이터 손실)
    # 발급사유는 보통 가장 마지막에 나옴 → 그 이후 절단
    text_main = text
    m_issue = re.search(r"발\s*급\s*사\s*유", text)
    if m_issue:
        text_main = text[:m_issue.start()]

    # ── 법인명 / 단체명 ───────────────────────
    org_patterns = [
        # 사업자등록증
        r"법\s*인\s*명\s*\(?\s*단\s*체\s*명\s*\)?\s*[:：]\s*([^\n\r]+?)(?=\s*대\s*표\s*자|\s*개\s*업|\s*$|\n)",
        r"법\s*인\s*명\s*[:：]\s*([^\n\r]+?)(?=\s*대\s*표\s*자|\s*개\s*업|\s*$|\n)",
        r"상\s*호\s*\(?\s*법\s*인\s*명\s*\)?\s*[:：]\s*([^\n\r]+?)(?=\s*대\s*표\s*자|\s*개\s*업|\s*$|\n)",
        r"상\s*호\s*[:：]\s*([^\n\r]+?)(?=\s*대\s*표\s*자|\s*성\s*명|\s*개\s*업|\s*$|\n)",
        # 고유번호증
        r"단\s*체\s*명\s*[:：]\s*([^\n\r]+?)(?=\s*대\s*표\s*자|\s*소\s*재\s*지|\s*$|\n)",
        r"기\s*관\s*명\s*[:：]\s*([^\n\r]+?)(?=\s*대\s*표\s*자|\s*소\s*재\s*지|\s*$|\n)",
    ]
    for pat in org_patterns:
        m = re.search(pat, text_main)
        if m:
            val = _clean(m.group(1))
            val = re.sub(r"\s*(?:법인명|성\s*명|대\s*표\s*자|생\s*년\s*월\s*일|개\s*업\s*일|소\s*재\s*지).*$", "", val).strip()
            val = re.sub(r"[\|｜\"'\\/]+$", "", val).strip()
            # ⭐ OCR 자모 띄어쓰기 정상화 — "장 유 덕 산..." → "장유덕산..."
            val = _normalize_korean_spacing(val)
            val = re.sub(r"\s+", " ", val).strip()  # 다중 공백 → 단일 공백
            korean_chars = re.findall(r"[가-힣]", val)
            if val and len(val) >= 3 and len(korean_chars) >= 2:
                out["org_name"] = val
                break

    # ── 대표자 / 대표자 성명 ─────────────────
    # "발급사유" 이후 잘라낸 text_main 에서만 검색
    rep_patterns = [
        # "대 표 자 성 명 : 하연옥" (고유번호증 정식 표기)
        r"대\s*표\s*자\s*성\s*명\s*[:：]\s*([가-힣]{2,5})\b",
        # "대 표 자 : 이신경" → "생년", "개업" 등 직전까지
        r"대\s*표\s*자\s*[:：]\s*([가-힣]{2,4}(?:\s[가-힣]{1,2}){0,2})\s*(?=생\s*년|개\s*업|법\s*인|소\s*재|\s*\d|$|\n)",
        # "대 표 자 : 김이남" (다음 콘텍스트 없을 때)
        r"대\s*표\s*자\s*[:：]\s*([가-힣]{2,5})\b",
    ]
    for pat in rep_patterns:
        for m in re.finditer(pat, text_main):
            val = _normalize_korean_name(m.group(1))
            if _is_valid_korean_name(val):
                out["org_rep"] = val
                break
        if out.get("org_rep"):
            break

    # ── 등록번호 / 고유번호 — XXX-XX-XXXXX ────
    biz_patterns = [
        r"등\s*록\s*번\s*호\s*[:：]?\s*(\d{3}\s*-\s*\d{2}\s*-\s*\d{5})",
        r"고\s*유\s*번\s*호\s*[:：]?\s*(\d{3}\s*-\s*\d{2}\s*-\s*\d{5})",
        r"사\s*업\s*자\s*(?:등\s*록\s*)?번\s*호\s*[:：]?\s*(\d{3}\s*-\s*\d{2}\s*-\s*\d{5})",
        r"(\d{3}-\d{2}-\d{5})",  # 마지막 수단
    ]
    for pat in biz_patterns:
        m = re.search(pat, text)  # 등록번호는 전체 text 에서 (위쪽)
        if m:
            val = re.sub(r"\s+", "", m.group(1))
            if re.match(r"^\d{3}-\d{2}-\d{5}$", val):
                out["org_biz_no"] = val
                break

    if is_unique_no:
        out["_cert_type"] = "고유번호증"
    else:
        out["_cert_type"] = "사업자등록증"

    return out


# ──── 현장실사 확인서 추출 ───────────────────────────
def extract_inspection(text: str) -> dict:
    """현장실사 확인서 PDF 텍스트에서 4개 필드 추출"""
    out = {}

    # 1) 설치방식 — "■<설치값>" 형태로 검색
    for val in INSTALL_METHOD_VALUES:
        if re.search(rf"■\s*{val}", text):
            out["install_method"] = INSTALL_METHOD_NORMALIZE.get(val, val)
            break

    # 2) 전기수전방식
    for val in POWER_METHOD_VALUES:
        if re.search(rf"■\s*{val}", text):
            out["power_method"] = val
            break

    # 3) 조사자 정보 — "7. 조사자" 섹션 이후만 검색
    inspector_section = ""
    m = re.search(r"7\.\s*조사자[\s\S]{0,500}", text)
    if m:
        inspector_section = m.group(0)
    else:
        # fallback: "조사자" 키워드 이후 500자
        m = re.search(r"조사자[\s\S]{0,500}", text)
        if m:
            inspector_section = m.group(0)

    if inspector_section:
        # 조사자 성명 — "성명 <한글이름> 조사일" 형태
        m2 = re.search(r"성\s*명\s+([가-힣\s]{2,15})\s+조\s*사\s*일", inspector_section)
        if m2:
            name = _normalize_korean_name(m2.group(1))
            if name and len(name) >= 2:
                out["contact_name"] = name

        # 조사자 연락처 — "연락처 <전화>" 형태
        m3 = re.search(r"연\s*락\s*처\s+(\d{2,3}\s*-?\s*\d{3,4}\s*-?\s*\d{4})", inspector_section)
        if m3:
            out["contact_phone"] = re.sub(r"\s+", "", m3.group(1))

        # 조사자 회사 (상호) — 보너스
        m4 = re.search(r"상\s*호\s+([가-힣A-Za-z0-9\(\)\s]+?)\s+연\s*락\s*처", inspector_section)
        if m4:
            out["inspector_company"] = _clean(m4.group(1))

    return out


# ──── PJT 처리 ─────────────────────────────────────────
def process_pjt(pjt: str, dump_text: bool = False) -> dict:
    pjt = pjt.strip().upper()
    print(f"\n=== {pjt} ===", flush=True)

    pdfs = find_pdfs_in_pjt(pjt)
    result = {
        "pjt": pjt,
        "found": {
            "business": [str(p.relative_to(ATTACH_ROOT)) for p in pdfs["business"]],
            "inspection": [str(p.relative_to(ATTACH_ROOT)) for p in pdfs["inspection"]],
        },
        "extracted": {},
        "errors": [],
    }

    if not pdfs["business"] and not pdfs["inspection"]:
        result["errors"].append("대상 PDF 없음 (사업자등록증 / 현장실사 확인서 모두 못 찾음)")
        print("  ❌ 대상 PDF 없음", flush=True)
        return result

    # 사업자등록증 — 텍스트 없으면 알PDF 로 OCR 필요 (안내만)
    for pdf in pdfs["business"]:
        print(f"  📄 사업자등록증: {pdf.name}", flush=True)
        text = _read_pdf_text(pdf)
        used_ocr = False
        if not text.strip():
            result["errors"].append(f"{pdf.name}: 텍스트 없음 — 알PDF 로 OCR 필요")
            print("    ⚠ 텍스트 없음 (스캔본) — 알PDF 일괄편집 OCR 후 다시 시도하세요.", flush=True)
            result["extracted"]["_needs_ocr"] = True
            continue
        if dump_text:
            print(f"    --- 추출 텍스트 ({'OCR' if used_ocr else 'TEXT'}) ---", flush=True)
            print(text[:8000], flush=True)
            print("    --- 끝 ---", flush=True)
        extracted = extract_business(text, filename=pdf.name)
        for k, v in extracted.items():
            result["extracted"][k] = v
            if not k.startswith("_"):
                print(f"    ✓ {k}: {v}", flush=True)
            elif k == "_cert_type":
                print(f"    ℹ 증서 유형: {v}", flush=True)
        if used_ocr:
            result["extracted"]["_business_via_ocr"] = True

    # 현장실사 확인서 — 텍스트 없으면 알PDF 로 OCR 필요 (안내만)
    for pdf in pdfs["inspection"]:
        print(f"  📄 현장실사 확인서: {pdf.name}", flush=True)
        text = _read_pdf_text(pdf)
        if not text.strip():
            result["errors"].append(f"{pdf.name}: 텍스트 없음 — 알PDF 로 OCR 필요")
            print("    ⚠ 텍스트 없음 (스캔본) — 알PDF 일괄편집 OCR 후 다시 시도하세요.", flush=True)
            result["extracted"]["_needs_ocr"] = True
            continue
        if dump_text:
            print("    --- 추출 텍스트 ---", flush=True)
            print(text[:4000], flush=True)
            print("    --- 끝 ---", flush=True)
        extracted = extract_inspection(text)
        for k, v in extracted.items():
            result["extracted"][k] = v
            print(f"    ✓ {k}: {v}", flush=True)

    return result


# ──── 메인 ─────────────────────────────────────────────
def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("pjts", nargs="*", help="PJT 코드 목록")
    ap.add_argument("--pjts", dest="pjts_csv")
    ap.add_argument("--all", action="store_true", help="attachments 폴더 전체 처리")
    ap.add_argument("--dump", dest="dump_pjt", help="해당 PJT 의 PDF 텍스트 원본 출력 (정규식 디버깅)")
    ap.add_argument("--no-auto-ocr", action="store_true",
                    help="자동 Tesseract OCR 변환 비활성화 (알PDF batch 결과 사용 시)")
    args = ap.parse_args()

    pjts = list(args.pjts)
    if args.pjts_csv:
        pjts.extend([p.strip() for p in args.pjts_csv.split(",") if p.strip()])

    if args.dump_pjt:
        return [args.dump_pjt.strip().upper()], True
    if args.all:
        if not ATTACH_ROOT.exists():
            print(f"❌ attachments 폴더 없음: {ATTACH_ROOT}")
            sys.exit(2)
        all_pjts = [d.name for d in ATTACH_ROOT.iterdir() if d.is_dir() and not d.name.startswith("_")]
        return sorted(all_pjts), False

    seen, cleaned = set(), []
    for p in pjts:
        p = p.strip().upper()
        if p and p not in seen:
            seen.add(p)
            cleaned.append(p)
    return cleaned, False


def main():
    pjt_list, dump_mode = parse_args()
    if not pjt_list:
        print("❌ PJT 코드 지정 필요. 예:")
        print("   python bpms_pdf_extract.py HL26030060")
        print("   python bpms_pdf_extract.py --all")
        print("   python bpms_pdf_extract.py --dump HL26030060")
        sys.exit(2)

    print(f"📂 attachments 루트: {ATTACH_ROOT}")
    print(f"📋 대상 {len(pjt_list)}건" + (" (DUMP 모드)" if dump_mode else ""))

    results = []
    summary = {"total": len(pjt_list), "matched": 0, "errors": 0}
    for pjt in pjt_list:
        try:
            r = process_pjt(pjt, dump_text=dump_mode)
        except Exception as e:
            r = {"pjt": pjt, "extracted": {}, "errors": [f"치명: {e}"]}
        results.append(r)
        if r["extracted"]:
            summary["matched"] += 1
        if r["errors"]:
            summary["errors"] += 1

    # 결과 종합
    print("\n" + "=" * 60)
    print(f"📊 처리: {summary['total']}건 · 추출 성공: {summary['matched']}건 · 오류 포함: {summary['errors']}건")
    print("=" * 60)

    # JSON 결과 (server.py 파싱용)
    print("\n=== RESULT_JSON ===")
    print(json.dumps({"summary": summary, "results": results}, ensure_ascii=False))
    print("=== END_RESULT_JSON ===")


if __name__ == "__main__":
    main()
