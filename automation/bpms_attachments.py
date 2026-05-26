"""
═══════════════════════════════════════════════════════════════
  BPMS 첨부파일 일괄 다운로드 (Playwright 버전)
  ───────────────────────────────────────────────────────────
  기존 download_projects.py (Selenium) + zip_프로젝트별_압축풀기.py
  를 하나로 통합 → Playwright 로 재작성.

  사용:
    python bpms_attachments.py HN25080268 HN25090002 ...
    python bpms_attachments.py --pjts HN25080268,HN25090002,...
    python bpms_attachments.py --pjts-file pjts.txt
═══════════════════════════════════════════════════════════════
"""

import sys
import os
import re
import time
import json
import zipfile
import argparse
from pathlib import Path

# ──── stdout UTF-8 강제 ────────────────────────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ──── 환경 ──────────────────────────────────────────────
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", r"C:\playwright_browsers")
USER_DATA_DIR = r"C:\playwright_userdata"
os.makedirs(USER_DATA_DIR, exist_ok=True)

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ──── 설정 ──────────────────────────────────────────────
LOGIN_URL   = "https://gschargev.lightning.force.com/lightning/page/home"

# NAS 의 attachments 폴더 (없으면 자동 생성)
NAS_ATTACH_DIR = Path(r"\\GSChargev_NAS\EV사업실\[영업현황 자동화_NAS]\attachments")

# 자동 압축해제 후 원본 ZIP 삭제? (False = _zips 폴더에 백업 보관)
DELETE_ZIP_AFTER_EXTRACT = False


# ──── 유틸 ──────────────────────────────────────────────
def banner(msg: str):
    print("\n" + "=" * 60)
    print(f"  {msg}")
    print("=" * 60, flush=True)


def log(msg: str):
    print(msg, flush=True)


def is_download_target(folder_name: str) -> bool:
    """다운로드 대상: 숫자로 시작 또는 'CN' 으로 시작 (기존 룰 유지)"""
    if not folder_name:
        return False
    if folder_name[0].isdigit():
        return True
    if folder_name.upper().startswith("CN"):
        return True
    return False


def safe_filename(name: str) -> str:
    """파일 시스템에 안전한 이름 (Windows 금지 문자 제거)"""
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip()


# ──── Salesforce 로그인 확인 ─────────────────────────────
def is_logged_in(page) -> bool:
    """로그인 페이지가 아닌 실제 SF UI 가 떴는지 검사"""
    try:
        url = page.url or ""
        if "login" in url.lower():
            return False
        if "lightning" in url.lower():
            return True
        # 검색 버튼이 있으면 로그인됨
        if page.locator("button.search-button").count() > 0:
            return True
    except Exception:
        pass
    return False


def find_logged_in_page(context):
    """여러 탭 중 로그인된 페이지 찾기 (SSO 가 새 창 띄울 수 있음)"""
    for p in context.pages:
        try:
            if is_logged_in(p):
                return p
        except Exception:
            continue
    return None


def wait_home_ready(page, timeout_s: int = 60) -> bool:
    """Lightning 홈 페이지가 실제로 준비됐는지 확인 (검색 버튼 visible)
       SSO/Toopher 리다이렉트가 끝날 때까지 기다림"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            # lightning URL 로 진입했고, 검색 버튼이 보이면 준비 완료
            url = page.url or ""
            if "lightning" in url.lower():
                if page.locator("button.search-button").count() > 0:
                    page.locator("button.search-button").first.wait_for(
                        state="visible", timeout=5000
                    )
                    return True
        except Exception:
            pass
        time.sleep(1.5)
    return False


def manual_login_wait(context, page, timeout_s: int = 180):
    """수동 로그인 대기 — 이미 세션이 살아있으면 즉시 통과
       반환: 로그인된 page (Lightning 홈 준비 완료) 또는 None"""
    log("🔐 로그인 상태 확인...")
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        log(f"  ⚠ 페이지 이동 중 오류: {e}")

    start = time.time()
    while time.time() - start < timeout_s:
        active = find_logged_in_page(context)
        if active:
            # 로그인 통과 — 이제 홈이 실제로 준비될 때까지 추가 대기
            log("  로그인 감지 — Lightning 홈 로드 대기...")
            if wait_home_ready(active, timeout_s=60):
                log("✅ 로그인됨 + 홈 준비 완료")
                return active
            else:
                log("  ⚠ 홈 로드 지연 — 직접 이동 시도")
                try:
                    active.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
                    if wait_home_ready(active, timeout_s=30):
                        log("✅ 로그인됨 + 홈 준비 완료 (재시도)")
                        return active
                except Exception:
                    pass
        time.sleep(2)

    log("❌ 로그인 시간 초과")
    return None


# ──── 검색 → 상세 페이지 진입 ────────────────────────────
def open_project_detail(page, pjt_code: str) -> bool:
    """전역 검색에 PJT 코드 입력 → 첫 검색결과 클릭 → 상세 진입"""
    try:
        page.goto(LOGIN_URL, wait_until="commit", timeout=30000)
        time.sleep(3)
    except Exception:
        pass

    # 검색 버튼 클릭
    try:
        page.locator("button.search-button").first.click(timeout=15000)
    except Exception as e:
        log(f"  ❌ 검색 버튼 클릭 실패: {e}")
        return False

    # 검색 입력창
    try:
        search_input = page.locator('input[type="search"].slds-input').first
        search_input.wait_for(state="visible", timeout=10000)
        search_input.click()
        search_input.fill("")
        search_input.fill(pjt_code)
        time.sleep(1)
        search_input.press("Enter")
    except Exception as e:
        log(f"  ❌ 검색어 입력 실패: {e}")
        return False

    log("  🔍 검색 완료, 결과 대기...")
    time.sleep(6)

    # 검색 결과 테이블에서 PJT 코드 포함된 첫 행의 링크 클릭
    try:
        # data-refid='recordId' 가 있는 a 태그를 우선
        links = page.locator(f"table tr:has-text('{pjt_code}') a[data-refid='recordId']")
        if links.count() > 0:
            links.first.click()
        else:
            # fallback — 어떤 a 태그든
            fallback = page.locator(f"table tr:has-text('{pjt_code}') a").first
            fallback.click(timeout=10000)
    except Exception as e:
        log(f"  ❌ 검색 결과 없음 또는 클릭 실패: {e}")
        return False

    log("  📂 상세페이지 진입")
    time.sleep(6)
    return True


# ──── "업로드 된 파일 리스트" 탭 클릭 ────────────────────
def click_uploaded_tab(page) -> bool:
    log("  📑 '업로드 된 파일 리스트' 탭 클릭 시도")

    # 여러 후보 셀렉터
    selectors = [
        "//a[contains(., '업로드 된 파일 리스트')]",
        "//span[contains(., '업로드 된 파일 리스트')]",
        "//*[@title='업로드 된 파일 리스트']",
        "//*[@data-label='업로드 된 파일 리스트']",
    ]

    for sel in selectors:
        try:
            loc = page.locator(f"xpath={sel}").first
            if loc.count() > 0:
                loc.scroll_into_view_if_needed()
                time.sleep(1)
                loc.click(timeout=5000)
                time.sleep(5)
                log("  ✅ 탭 클릭 완료")
                return True
        except Exception:
            continue

    # 마지막 수단 — JS 강제 클릭
    log("  ⚠ 일반 클릭 실패, JS 강제 클릭 시도")
    try:
        clicked = page.evaluate("""() => {
            var nodes = document.querySelectorAll('a, span, li, div');
            for (var i = 0; i < nodes.length; i++) {
                var t = (nodes[i].textContent || '').trim();
                if (t.indexOf('업로드 된 파일 리스트') > -1) {
                    nodes[i].click();
                    return true;
                }
            }
            return false;
        }""")
        if clicked:
            time.sleep(5)
            return True
    except Exception:
        pass

    return False


# ──── 다운로드 행 추출 + 폴더명 ──────────────────────────
def get_download_rows(page):
    """'파일 일괄 다운로드' 버튼이 있는 모든 행 반환"""
    rows = page.locator(
        "xpath=//button[contains(.,'파일 일괄 다운로드')]/ancestor::*[self::li or self::tr or self::div][1]"
    )
    return rows


def get_folder_name(row) -> str:
    """행의 첫 줄 텍스트를 폴더명으로 사용"""
    try:
        text = row.inner_text(timeout=3000)
        if not text:
            return ""
        return text.split("\n")[0].strip()
    except Exception:
        return ""


# ──── 단일 행 ZIP 다운로드 ───────────────────────────────
def download_row(page, row, target_zip_path: Path) -> bool:
    try:
        row.scroll_into_view_if_needed()
        time.sleep(1)

        btn = row.locator("xpath=.//button[contains(.,'파일 일괄 다운로드')]").first
        if btn.count() == 0:
            log(f"    ❌ 버튼 못 찾음")
            return False

        # Playwright 의 download API — Save As 다이얼로그 안 뜸
        with page.expect_download(timeout=180_000) as dl_info:
            btn.click()

        download = dl_info.value
        target_zip_path.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(target_zip_path))
        log(f"    📦 저장: {target_zip_path.name}")
        return True

    except PWTimeout:
        log(f"    ❌ 다운로드 타임아웃")
        return False
    except Exception as e:
        log(f"    ❌ 다운로드 실패: {e}")
        return False


# ──── ZIP 자동 압축해제 ──────────────────────────────────
def extract_zip(zip_path: Path, target_dir: Path) -> int:
    """ZIP → target_dir 에 압축해제. 반환: 추출된 파일 수"""
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            names = zf.namelist()
            zf.extractall(target_dir)
            return len(names)
    except Exception as e:
        log(f"    ⚠ 압축해제 실패: {e}")
        return 0


# ──── 한 PJT 처리 ────────────────────────────────────────
def process_pjt(page, pjt_code: str) -> dict:
    """한 PJT 의 모든 첨부파일 다운로드 + 압축해제"""
    pjt_dir = NAS_ATTACH_DIR / pjt_code
    zips_dir = pjt_dir / "_zips"
    pjt_dir.mkdir(parents=True, exist_ok=True)
    zips_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "pjt": pjt_code,
        "downloaded": 0,
        "extracted": 0,
        "skipped": 0,
        "errors": [],
    }

    # 1. 상세 진입
    if not open_project_detail(page, pjt_code):
        result["errors"].append("프로젝트 검색/진입 실패")
        return result

    # 2. 업로드 탭 클릭
    if not click_uploaded_tab(page):
        result["errors"].append("'업로드 된 파일 리스트' 탭 클릭 실패")
        return result

    # 3. 행 추출
    rows = get_download_rows(page)
    n = rows.count()
    if n == 0:
        result["errors"].append("다운로드 가능한 항목 없음")
        return result
    log(f"  📋 행 {n}개 발견")

    # 4. 각 행 처리
    processed = set()
    for i in range(n):
        row = rows.nth(i)
        try:
            folder_name = get_folder_name(row)
            if not folder_name:
                continue

            log(f"  📁 [{i+1}/{n}] {folder_name}")

            if not is_download_target(folder_name):
                log(f"    ⏭ 스킵 (대상 아님)")
                result["skipped"] += 1
                continue

            # 폴더명 정규화
            if folder_name.upper().startswith("CN"):
                safe_folder = "CN"
            else:
                safe_folder = safe_filename(folder_name)

            if safe_folder in processed:
                log(f"    ⏭ 중복 스킵")
                continue
            processed.add(safe_folder)

            zip_path = zips_dir / f"{safe_folder}.zip"
            extract_target = pjt_dir / safe_folder

            # 이미 추출된 폴더 있으면 스킵 (재실행 안전)
            if extract_target.exists() and any(extract_target.iterdir()):
                log(f"    ⏭ 이미 추출됨")
                result["skipped"] += 1
                continue

            # 다운로드
            ok = download_row(page, row, zip_path)
            if not ok:
                result["errors"].append(f"{folder_name} 다운로드 실패")
                continue

            result["downloaded"] += 1

            # 자동 압축해제
            extracted = extract_zip(zip_path, extract_target)
            if extracted > 0:
                result["extracted"] += extracted
                log(f"    📂 {extracted}개 파일 추출")

            if DELETE_ZIP_AFTER_EXTRACT and zip_path.exists():
                zip_path.unlink()

            time.sleep(2)

        except Exception as e:
            log(f"  ❌ 행 처리 오류: {e}")
            result["errors"].append(str(e))
            continue

    return result


# ──── 메인 ──────────────────────────────────────────────
def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("pjts", nargs="*", help="PJT 코드 목록 (공백 구분)")
    ap.add_argument("--pjts", dest="pjts_csv", help="콤마 구분 PJT 목록")
    ap.add_argument("--pjts-file", dest="pjts_file", help="줄 단위 PJT 파일")
    args = ap.parse_args()

    pjts = list(args.pjts)
    if args.pjts_csv:
        pjts.extend([p.strip() for p in args.pjts_csv.split(",") if p.strip()])
    if args.pjts_file and Path(args.pjts_file).exists():
        with open(args.pjts_file, "r", encoding="utf-8") as f:
            pjts.extend([line.strip() for line in f if line.strip()])

    # 중복 제거 + 대문자 정규화
    seen = set()
    cleaned = []
    for p in pjts:
        p = p.strip().upper()
        if p and p not in seen:
            seen.add(p)
            cleaned.append(p)
    return cleaned


def main():
    pjt_list = parse_args()
    if not pjt_list:
        log("❌ PJT 코드가 지정되지 않았습니다.")
        log("   사용: python bpms_attachments.py HN25080268 HN25090002")
        sys.exit(2)

    banner(f"BPMS 첨부파일 일괄 다운로드 ({len(pjt_list)}건)")
    log(f"📁 저장 위치: {NAS_ATTACH_DIR}")
    log(f"📋 대상: {', '.join(pjt_list[:5])}" + (f" ... 외 {len(pjt_list)-5}건" if len(pjt_list) > 5 else ""))

    NAS_ATTACH_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            accept_downloads=True,
            locale="ko-KR",
            no_viewport=True,
            args=["--start-maximized"],
        )
        page = context.pages[0] if context.pages else context.new_page()

        # 로그인 대기
        active_page = manual_login_wait(context, page, timeout_s=180)
        if not active_page:
            log("❌ 로그인 실패 — 종료")
            context.close()
            sys.exit(3)
        page = active_page

        # 각 PJT 처리
        all_results = []
        total_dl = 0
        total_ex = 0
        total_err = 0
        for idx, pjt in enumerate(pjt_list, 1):
            banner(f"[{idx}/{len(pjt_list)}] {pjt}")
            try:
                r = process_pjt(page, pjt)
            except Exception as e:
                r = {"pjt": pjt, "downloaded": 0, "extracted": 0, "skipped": 0,
                     "errors": [f"치명적 오류: {e}"]}
            all_results.append(r)
            total_dl += r["downloaded"]
            total_ex += r["extracted"]
            total_err += len(r["errors"])

        # 종합 결과
        banner("작업 종합 결과")
        log(f"📦 다운로드 ZIP: {total_dl}개")
        log(f"📂 추출 파일:   {total_ex}개")
        log(f"❌ 오류:         {total_err}건")

        if total_err > 0:
            log("\n--- 오류 상세 ---")
            for r in all_results:
                if r["errors"]:
                    log(f"  [{r['pjt']}] {'; '.join(r['errors'][:3])}")

        # JSON 결과 (server.py 가 파싱 가능)
        log("\n=== RESULT_JSON ===")
        log(json.dumps({
            "total_pjts": len(pjt_list),
            "downloaded": total_dl,
            "extracted": total_ex,
            "errors": total_err,
            "details": all_results,
        }, ensure_ascii=False))
        log("=== END_RESULT_JSON ===")

        time.sleep(3)
        context.close()


if __name__ == "__main__":
    main()
