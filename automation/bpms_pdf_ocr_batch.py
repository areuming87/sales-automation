"""
═══════════════════════════════════════════════════════════════
  스캔본 PDF → 검색가능(OCR) PDF 일괄 변환
  ───────────────────────────────────────────────────────────
  attachments/ 폴더의 PDF 들을 한 번에 OCR 처리해서
  텍스트 레이어가 포함된 PDF 로 교체.
  (이렇게 하면 이후 PDF 분석 시 pdfplumber 만으로 100% 추출)

  기본: 분석에 필요한 3종 PDF 만 처리 (사업자등록증/고유번호증/현장실사확인서)
        + 텍스트 이미 있는 PDF 는 자동 스킵 → 진짜 필요한 것만 OCR

  사용:
    python bpms_pdf_ocr_batch.py HL26030060            # 해당 PJT 의 대상 PDF 만
    python bpms_pdf_ocr_batch.py HL26030060 HL26040001 # 여러 PJT
    python bpms_pdf_ocr_batch.py --all                 # 전체 PJT, 대상 PDF 만
    python bpms_pdf_ocr_batch.py --all-pdfs HL26030060 # 모든 PDF (계약서 등 포함)
═══════════════════════════════════════════════════════════════
"""

import sys
import os
import re
import shutil
import argparse
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", r"C:\playwright_browsers")

ATTACH_ROOT = Path(r"\\GSChargev_NAS\EV사업실\[영업현황 자동화_NAS]\attachments")

TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"C:\Tesseract-OCR\tesseract.exe",
]

# OCR 적용 임계값 — pdfplumber 추출 텍스트가 이 값보다 적으면 스캔본 판정
SCAN_THRESHOLD = 100

# OCR DPI (높을수록 정확하지만 느림)
OCR_DPI = 400

# ⭐ 기본 대상 PDF — 분석에 필요한 3종 (파일명에 포함되어야 함)
DEFAULT_TARGET_KEYWORDS = [
    "사업자등록증",  # 사업자등록증/고유번호증 둘 다 매칭
    "고유번호증",
    "현장실사",      # "현장실사 확인서" / "현장실사확인서" 둘 다
]


def log(msg: str):
    print(msg, flush=True)


# ──── Tesseract 셋업 ───────────────────────────────
def setup_tesseract():
    try:
        import pytesseract
        found = None
        for cand in TESSERACT_CANDIDATES:
            if Path(cand).exists():
                found = cand
                break
        if found:
            pytesseract.pytesseract.tesseract_cmd = found
            return True
        # PATH 시도
        import subprocess
        try:
            subprocess.run(["tesseract", "--version"],
                           capture_output=True, check=True, timeout=5)
            return True
        except Exception:
            return False
    except ImportError:
        return False


# ──── PDF 텍스트 추출 (이미 OCR 됐는지 확인용) ──
def get_text_length(pdf_path: Path) -> int:
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            total = ""
            for page in pdf.pages:
                total += page.extract_text() or ""
        return len(total.strip())
    except Exception:
        return 0


# ──── 단일 PDF → 검색가능 PDF 변환 ─────────────────
def ocr_pdf_to_searchable(input_path: Path, output_path: Path) -> bool:
    """스캔본 PDF → 텍스트 레이어 포함 PDF.
       반환: True 성공, False 실패"""
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
        import io

        new_doc = fitz.open()
        with fitz.open(str(input_path)) as src:
            n_pages = len(src)
            for i, page in enumerate(src, 1):
                pix = page.get_pixmap(dpi=OCR_DPI)
                img_bytes = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_bytes))

                # Tesseract → 한 페이지짜리 검색가능 PDF 생성
                pdf_bytes = pytesseract.image_to_pdf_or_hocr(
                    img, lang="kor+eng", extension="pdf",
                    config="--psm 6"
                )

                # 생성된 PDF 를 new_doc 에 추가
                with fitz.open("pdf", pdf_bytes) as page_doc:
                    new_doc.insert_pdf(page_doc)
                log(f"      페이지 {i}/{n_pages} OCR 완료")

        # 임시 파일에 먼저 저장 후 이동 (중간 실패 대비)
        tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        new_doc.save(str(tmp_path))
        new_doc.close()

        # 원본 백업 (같은 폴더가 아니면)
        if input_path != output_path:
            # 다른 위치로 출력
            shutil.move(str(tmp_path), str(output_path))
        else:
            # 원본 덮어쓰기 — 먼저 백업
            backup_dir = input_path.parent / "_original_scan"
            backup_dir.mkdir(exist_ok=True)
            backup_path = backup_dir / input_path.name
            if not backup_path.exists():
                shutil.copy2(str(input_path), str(backup_path))
            shutil.move(str(tmp_path), str(input_path))

        return True

    except Exception as e:
        log(f"      ❌ OCR 실패: {e}")
        return False


# ──── PJT 폴더 처리 ────────────────────────────────
def process_pjt_folder(pjt_dir: Path, keywords: list, force: bool = False) -> dict:
    """PJT 폴더 안의 대상 PDF 만 검사 → 스캔본이면 OCR 변환.
       keywords=None 또는 빈 리스트면 모든 PDF 대상."""
    result = {"scanned": 0, "non_target": 0, "already_text": 0,
              "converted": 0, "failed": 0}

    if not pjt_dir.exists():
        return result

    for pdf in pjt_dir.rglob("*.pdf"):
        # _zips 와 _original_scan 폴더는 제외
        if "_zips" in pdf.parts or "_original_scan" in pdf.parts:
            continue

        # 대상 키워드 필터 — 어느 하나라도 파일명에 포함되면 대상
        if keywords:
            if not any(kw in pdf.name for kw in keywords):
                result["non_target"] += 1
                continue

        result["scanned"] += 1

        text_len = get_text_length(pdf)
        if text_len >= SCAN_THRESHOLD and not force:
            result["already_text"] += 1
            continue

        log(f"  📄 {pdf.relative_to(pjt_dir.parent)} ({text_len}자 → OCR 필요)")

        ok = ocr_pdf_to_searchable(pdf, pdf)
        if ok:
            new_len = get_text_length(pdf)
            log(f"      ✓ 완료 ({text_len}자 → {new_len}자)")
            result["converted"] += 1
        else:
            result["failed"] += 1

    return result


# ──── 메인 ──────────────────────────────────────────
def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("pjts", nargs="*")
    ap.add_argument("--all", action="store_true", help="attachments 폴더 전체 PJT")
    ap.add_argument("--all-pdfs", action="store_true",
                    help="대상 키워드 무시하고 모든 PDF 처리 (계약서 등 포함)")
    ap.add_argument("--pattern", default="",
                    help="추가 키워드 (기본 3종에 더해서 매칭)")
    ap.add_argument("--force", action="store_true", help="이미 텍스트 있어도 다시 OCR")
    return ap.parse_args()


def main():
    args = parse_args()

    if not setup_tesseract():
        log("❌ Tesseract 미설치 — 먼저 설치하세요:")
        log("   https://github.com/UB-Mannheim/tesseract/wiki")
        sys.exit(2)

    if args.all:
        if not ATTACH_ROOT.exists():
            log(f"❌ attachments 폴더 없음: {ATTACH_ROOT}")
            sys.exit(2)
        pjt_list = sorted([
            d.name for d in ATTACH_ROOT.iterdir()
            if d.is_dir() and not d.name.startswith("_")
        ])
    else:
        pjt_list = [p.strip().upper() for p in args.pjts if p.strip()]
        pjt_list = list(dict.fromkeys(pjt_list))

    if not pjt_list:
        log("❌ PJT 코드 미지정. 사용:")
        log("   python bpms_pdf_ocr_batch.py HL26030060")
        log("   python bpms_pdf_ocr_batch.py --all")
        log("   python bpms_pdf_ocr_batch.py --all-pdfs HL26030060   (모든 PDF)")
        sys.exit(2)

    # 키워드 결정
    if args.all_pdfs:
        keywords = []  # 빈 리스트 = 필터 없음 = 모든 PDF
    else:
        keywords = list(DEFAULT_TARGET_KEYWORDS)
        if args.pattern:
            keywords.append(args.pattern)

    log(f"📂 대상 PJT: {len(pjt_list)}개")
    if keywords:
        log(f"🎯 처리할 PDF 키워드: {', '.join(keywords)}")
        log(f"   (그 외 PDF — 계약서/회의록/건축물대장 등 — 은 자동 스킵)")
    else:
        log("⚠ 모든 PDF 처리 모드 (--all-pdfs)")
    log(f"📐 OCR DPI: {OCR_DPI}")
    log("=" * 60)

    total = {"scanned": 0, "non_target": 0, "already_text": 0,
             "converted": 0, "failed": 0}
    for idx, pjt in enumerate(pjt_list, 1):
        log(f"\n[{idx}/{len(pjt_list)}] {pjt}")
        pjt_dir = ATTACH_ROOT / pjt
        r = process_pjt_folder(pjt_dir, keywords=keywords, force=args.force)
        for k in total:
            total[k] += r[k]
        log(f"  📊 비대상스킵: {r['non_target']} · 텍스트있음(스킵): {r['already_text']} · OCR변환: {r['converted']} · 실패: {r['failed']}")

    log("\n" + "=" * 60)
    log(f"📊 전체 처리 결과:")
    log(f"  ⏭ 비대상 PDF 스킵: {total['non_target']} (계약서·회의록 등)")
    log(f"  ⏭ 텍스트 이미 있음 스킵: {total['already_text']}")
    log(f"  ✓ OCR 변환 완료: {total['converted']}")
    log(f"  ❌ 실패: {total['failed']}")
    log(f"\n원본 스캔본은 각 폴더의 '_original_scan/' 에 백업됨.")


if __name__ == "__main__":
    main()
