"""
═══════════════════════════════════════════════════════════════
  BPMS 보고서 자동 다운로드 (Salesforce + Playwright)
  ───────────────────────────────────────────────────────────
  사용 방법:
    1) 처음 1회만:  install.bat 실행 (Playwright + Chromium 설치)
    2) 실행:        python bpms_download.py
    3) 브라우저가 자동으로 열림 → 직접 로그인 → Enter
    4) 자동으로 4개 보고서 다운로드 → downloads/ 폴더에 저장
═══════════════════════════════════════════════════════════════
"""

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from pathlib import Path
import time
import sys
import os

# ⚠ 한글 사용자명(서아름) 경로에서 Playwright 프로세스 spawn 실패 회피
# → 브라우저 + 유저 데이터 디렉토리를 ASCII 경로로 강제
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", r"C:\playwright_browsers")
USER_DATA_DIR = r"C:\playwright_userdata"
os.makedirs(USER_DATA_DIR, exist_ok=True)

# ──── 설정 ────────────────────────────────────────────────
LOGIN_URL = "https://gschargev.lightning.force.com/lightning/page/home"
# 다운로드 후 자동 업로드할 웹앱 URL (GitHub Pages 배포본)
WEBAPP_URL = "https://areuming87.github.io/sales-automation/bpms.html"
# 로컬 테스트하려면 위 줄 주석 처리하고 아래 사용:
# WEBAPP_URL = f"file:///{(Path(__file__).parent.parent / 'bpms.html').as_posix()}"

SCRIPT_DIR = Path(__file__).parent
DOWNLOAD_DIR = SCRIPT_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

# 세션 저장 — persistent context 가 자동으로 USER_DATA_DIR 안에 보관함
STORAGE_STATE = SCRIPT_DIR / "session_state.json"

REPORTS = [
    # (저장될 파일명(.xlsx 자동 추가), 보고서뷰 URL)
    ("BPMS_영업현황 자동화_영업정보",   "https://gschargev.lightning.force.com/lightning/r/Report/00OTJ00000q8ns12AA/view?queryScope=userFolders"),
    ("BPMS_영업현황 자동화_충전기정보", "https://gschargev.lightning.force.com/lightning/r/Report/00OTJ00000mDkau2AC/view?queryScope=userFolders"),
    ("BPMS_영업현황 자동화_전암검 외",  "https://gschargev.lightning.force.com/lightning/r/Report/00OTJ00000qOHpp2AG/view?queryScope=userFolders"),
    ("BPMS_영업현황 자동화_세금계산서", "https://gschargev.lightning.force.com/lightning/r/Report/00OTJ00000qLYOz2AO/view?queryScope=userFolders"),
]


# ──── 유틸 ────────────────────────────────────────────────
def banner(text):
    bar = "═" * 60
    print(f"\n{bar}\n  {text}\n{bar}")


def safe_filename(name):
    return name.replace("/", "_").replace("\\", "_").replace(" ", "_")


# ──── 단계 1. 로그인 페이지 열고 사용자 대기 ─────────────
def manual_login(page):
    print("브라우저를 Salesforce 로그인 페이지로 이동합니다...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)

    print("\n" + "▼" * 60)
    print("  👤 브라우저에서 직접 로그인해주세요.")
    print("  로그인 완료 후 메인 화면(Lightning 대시보드)이 보이면")
    print("  아래에서 Enter 키를 누르세요.")
    print("▲" * 60)
    input("\n  ➤ 로그인 완료 후 Enter 키 입력: ")


# ──── Salesforce 리다이렉트 대응 안전한 navigation ────────
def safe_goto(page, url, max_retries=3):
    """Salesforce는 my.salesforce.com 으로 SSO 리다이렉트 하기 때문에
    page.goto 가 'interrupted by another navigation' 으로 실패할 수 있음.
    재시도 + 리다이렉트 안정화 대기."""
    last_err = None
    for i in range(max_retries):
        try:
            # commit = 네비게이션 시작만 확인 (리다이렉트 발생해도 OK)
            page.goto(url, wait_until="commit", timeout=60000)
            # URL이 우리가 원하는 곳에 안착했는지 확인 (최대 20초)
            target_path = url.split('?')[0].split('://')[-1].split('/', 1)[-1]
            for _ in range(20):
                cur = page.url
                if target_path in cur or 'Report' in cur:
                    # 우리 URL에 도착 — DOM이 어느 정도 만들어졌는지 짧게 확인
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except PWTimeout:
                        pass
                    return True
                time.sleep(0.5)
            # URL 안 바뀌면 한 번 더 시도
            print(f"  ⚠ URL 안착 안 됨 (현재: {page.url[:80]}...) — 재시도")
            continue
        except Exception as e:
            last_err = e
            msg = str(e)
            if "interrupted by another navigation" in msg or "Timeout" in msg:
                print(f"  ⚠ 리다이렉트 인터럽트 ({i+1}/{max_retries}) — 재시도...")
                time.sleep(3)
                # 한 번 더 같은 URL로 시도 — 두번째는 보통 성공
                continue
            raise
    if last_err:
        raise last_err
    return False


# ──── 단계 2. 보고서뷰 한 개 다운로드 ────────────────────
def download_report(page, name, url, attempt=1):
    print(f"\n📥 [{name}] 다운로드 시작 ...")
    print(f"  🌐 {url[:70]}...")

    # Salesforce SSO 리다이렉트 대응 navigation
    try:
        safe_goto(page, url)
    except Exception as e:
        print(f"  ✗ 페이지 이동 실패: {e}")
        return None

    # Lightning 보고서 UI 로딩 대기 — networkidle 안 쓰고 '편집' 버튼 등장으로 판정
    # (Salesforce는 백그라운드 폴링이 끊임없어서 networkidle 이벤트가 안 발동 → 매번 60초 풀 대기 발생)
    print("  ⏳ 편집 버튼 표시 대기 중...")
    t0 = time.time()
    edit_visible = False
    try:
        # 편집 버튼이 보이면 UI 준비 완료로 간주
        page.get_by_role('button', name='편집').first.wait_for(state='visible', timeout=60000)
        edit_visible = True
        elapsed = time.time() - t0
        print(f"     ✓ 준비 완료 ({elapsed:.1f}초)")
    except PWTimeout:
        print(f"     ⚠ 편집 버튼 미발견 — 그래도 진행")
    # 마지막 안정화 대기 — 보고서 사이즈에 따라 다소 차이
    time.sleep(2.5)

    # ── 1. 편집 옆 ▼ 메뉴 열기 (Lightning Shadow DOM/iframe 대응)
    print("  🔽 [편집 옆 ▼] 메뉴 열기...")
    chevron_clicked = False

    # 가능한 메뉴 버튼 aria-label 후보 (Salesforce는 한국어/영어 혼재 가능)
    MENU_ARIA_NAMES = [
        '기타 작업 표시', '더 많은 옵션', '추가 작업 표시', '추가 작업',
        '다른 옵션 표시', '더보기', '추가 옵션',
        'Show More Actions', 'More actions', 'Show more actions',
        'More options', 'More', 'Show actions',
    ]

    # iframe까지 모두 탐색
    frames_to_try = [page] + [f for f in page.frames if f != page.main_frame]

    for frame in frames_to_try:
        if chevron_clicked:
            break
        for aria_name in MENU_ARIA_NAMES:
            try:
                # get_by_role: Shadow DOM 통과 가능
                btn = frame.get_by_role('button', name=aria_name).first
                if btn.count() == 0:
                    continue
                if not btn.is_visible(timeout=1500):
                    continue
                btn.click(timeout=4000)

                # ⭐ 메뉴 애니메이션·렌더링 대기 (충분히 길게 — 3초)
                print(f"     ⏳ 메뉴 펼쳐짐 대기 (3초)... (aria-label: \"{aria_name}\")")
                time.sleep(3)

                # 검증: "내보내기" 메뉴 아이템 보이면 정상
                export_item = frame.get_by_role('menuitem', name='내보내기').first
                if export_item.count() == 0:
                    export_item = frame.get_by_text('내보내기', exact=True).first
                if export_item.count() > 0 and export_item.is_visible(timeout=3000):
                    chevron_clicked = True
                    print(f"     ✓ 메뉴 열림 확인")
                    # 내보내기 클릭
                    print("  📤 '내보내기' 메뉴 클릭...")
                    export_item.click(timeout=5000)
                    break
                else:
                    # 이 메뉴가 아니었음 — ESC로 닫고 다음 후보
                    page.keyboard.press('Escape')
                    time.sleep(0.8)
            except Exception:
                continue

    # 폴백 1: 편집 텍스트 옆의 menu 버튼을 텍스트 기반으로 찾기
    if not chevron_clicked:
        try:
            print("     ↻ 폴백: 편집 텍스트 기반 매칭...")
            edit_btn = page.get_by_role('button', name='편집').first
            if edit_btn.count() > 0:
                container = edit_btn.locator('xpath=ancestor::*[contains(@class, "slds-button-group") or contains(@class, "button-group") or self::lightning-button-group][1]')
                if container.count() > 0:
                    menu_btn = container.locator('button[aria-haspopup]').last
                    if menu_btn.count() > 0:
                        menu_btn.click(timeout=4000)
                        # ⭐ 메뉴 펼쳐짐 대기 3초
                        time.sleep(3)
                        export_item = page.get_by_role('menuitem', name='내보내기').first
                        if export_item.count() > 0 and export_item.is_visible(timeout=3000):
                            chevron_clicked = True
                            print(f"     ✓ 폴백 성공")
                            print("  📤 '내보내기' 메뉴 클릭...")
                            export_item.click(timeout=5000)
        except Exception:
            pass

    # 모두 실패 → 디버그 스크린샷 + 사용자 수동 안내
    if not chevron_clicked:
        debug_path = SCRIPT_DIR / f"debug_{safe_filename(name)}_{int(time.time())}.png"
        try:
            page.screenshot(path=str(debug_path), full_page=False)
            print(f"  🖼 디버그 스크린샷 저장: {debug_path.name}")
        except Exception:
            pass
        print("  ⚠ 자동으로 메뉴를 못 찾았습니다. 브라우저에서 직접:")
        print("     1) 우측 상단 '편집' 옆 ▼ 클릭")
        print("     2) '내보내기' 클릭")
        print("     3) 팝업에서 '내보내기' 클릭")
        input("     완료 후 Enter (다음 보고서로 넘어감)... ")
        return None

    time.sleep(2)

    # ── 3. 팝업 → '내보내기' 버튼 클릭 + 다운로드 캡처
    print("  💾 파일 다운로드 중...")
    try:
        with page.expect_download(timeout=180000) as download_info:
            # 팝업 안의 '내보내기' 버튼 (보통 modal/dialog 안에 있음)
            popup_btn = None
            for sel in [
                'div[role="dialog"] button:has-text("내보내기")',
                '.modal-container button:has-text("내보내기")',
                'section.slds-modal__container button:has-text("내보내기")',
                # 마지막 폴백 — 페이지에서 가장 마지막에 보이는 내보내기 버튼
                'button:has-text("내보내기"):not([aria-haspopup])',
            ]:
                loc = page.locator(sel).last
                if loc.count() > 0:
                    popup_btn = loc
                    break
            if popup_btn is None:
                raise Exception("팝업의 '내보내기' 버튼을 찾지 못함")
            popup_btn.click(timeout=10000)

        download = download_info.value
        # 지정된 파일명으로 저장 (확장자는 다운로드된 원본 따라감, 보통 .xlsx)
        suggested = download.suggested_filename or "report.xlsx"
        ext = Path(suggested).suffix or ".xlsx"
        target = DOWNLOAD_DIR / f"{name}{ext}"
        # 기존 파일이 있으면 덮어쓰기 (먼저 삭제)
        if target.exists():
            try:
                target.unlink()
            except Exception:
                pass
        download.save_as(target)
        print(f"  ✓ 저장 완료: {target.name}")
        return target

    except Exception as e:
        print(f"  ✗ 다운로드 실패: {e}")
        # 재시도 1회
        if attempt < 2:
            print(f"  🔄 재시도 ({attempt+1}/2)...")
            time.sleep(3)
            return download_report(page, name, url, attempt=attempt+1)
        return None


# ──── 단계 3. 웹앱 자동 업로드 (선택) ─────────────────────
def auto_upload_to_webapp(page, downloaded):
    """다운로드된 엑셀들을 bpms.html 웹앱에 자동 업로드 + 매칭 적용
    downloaded: [(name, status_str, detail), ...]
                detail은 성공 시 Path, 실패 시 str/None"""
    # Path 객체이고 실제로 존재하는 파일만 필터
    successes = [
        (name, detail) for name, status, detail in downloaded
        if isinstance(detail, Path) and detail.exists()
    ]
    if not successes:
        print("\n⚠ 업로드할 파일이 없습니다.")
        return

    banner("웹앱 자동 업로드")
    print(f"  🌐 대상: {WEBAPP_URL}")
    print(f"  📤 업로드 대상: {len(successes)}개 파일\n")

    # 웹앱 이동
    page.goto(WEBAPP_URL, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=20000)
    except PWTimeout:
        pass
    time.sleep(2)

    for name, fp in successes:
        print(f"\n📤 [{name}] {fp.name}")
        try:
            # ① 숨겨진 <input type="file"> 에 직접 파일 설정 (handleUpload 우회)
            file_input = page.locator('#fileInput')
            file_input.set_input_files(str(fp))
            print("  ⏳ 매핑 모달 열림 대기...")

            # ② 매핑 모달 열림 대기
            page.wait_for_selector('#xlsModal.active', timeout=30000)
            time.sleep(1)

            # ③ 분석 완료 대기 (적용 버튼이 활성화될 때까지)
            print("  🔍 분석 진행 중...")
            try:
                page.wait_for_function(
                    """() => {
                        const m = document.getElementById('xlsModal');
                        const b = document.getElementById('btnXlsApply');
                        if (!m || !m.classList.contains('active')) return false;
                        return b && !b.disabled;
                    }""",
                    timeout=90000
                )
            except PWTimeout:
                # 전체 행이 신규/오류라서 적용 버튼이 비활성화일 수도 있음
                print("  ⚠ 적용 가능한 데이터가 없는 것 같음 (또는 분석 시간 초과)")

            # ④ 매칭 결과 카운트 출력 (참고용)
            try:
                cnt_match = page.locator('#xlsCntMatch').text_content() or '?'
                cnt_new   = page.locator('#xlsCntNew').text_content() or '?'
                cnt_err   = page.locator('#xlsCntErr').text_content() or '?'
                print(f"  📊 분석: 매칭 {cnt_match} / 신규 {cnt_new} / 오류 {cnt_err}")
            except Exception:
                pass

            # ⑤ 적용 버튼 클릭
            btn = page.locator('#btnXlsApply')
            disabled = btn.is_disabled()
            if disabled:
                print("  ⚠ 적용 버튼 비활성 — 모달 닫고 다음")
                page.locator('#xlsModal .xls-close').click()
                time.sleep(1)
                continue

            print("  ✅ 매칭 적용하기 클릭...")
            btn.click()

            # ⑥ 모달 닫힘 대기
            try:
                page.wait_for_function(
                    """() => !document.getElementById('xlsModal').classList.contains('active')""",
                    timeout=60000
                )
                print(f"  ✓ {name} 업로드 완료")
            except PWTimeout:
                print(f"  ⚠ 모달 닫힘 확인 못 함 (실제 적용은 됐을 가능성 높음)")

            time.sleep(2)  # 다음 업로드 전 안정화
        except Exception as e:
            print(f"  ✗ {name} 업로드 실패: {e}")
            # 모달 열린 상태로 남아있으면 닫기
            try:
                if page.locator('#xlsModal.active').count() > 0:
                    page.keyboard.press('Escape')
                    time.sleep(0.5)
            except Exception:
                pass

    banner("웹앱 업로드 완료")
    print(f"  🔗 웹앱 보기: {WEBAPP_URL}")
    print("  💡 브라우저에서 결과를 확인하세요. (담당자별·검색 필터 등도 사용 가능)\n")


# ──── 메인 ────────────────────────────────────────────────
def main():
    banner("BPMS 보고서 자동 다운로드")
    print(f"📁 저장 폴더: {DOWNLOAD_DIR}")
    print(f"📋 다운로드 대상: {len(REPORTS)}개 보고서뷰")

    with sync_playwright() as p:
        # ⚠ launch_persistent_context — ASCII 경로 사용 (한글 spawn 에러 회피)
        # no_viewport=True + --start-maximized = 사용자가 직접 켠 브라우저와 동일한 풀스크린
        print(f"  💾 브라우저 데이터 폴더: {USER_DATA_DIR}")
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            accept_downloads=True,
            locale="ko-KR",
            no_viewport=True,           # 윈도우 크기 그대로 = 풀스크린
            args=["--start-maximized"],
        )
        page = context.pages[0] if context.pages else context.new_page()

        # 1. 로그인 페이지 → 사용자 대기
        manual_login(page)

        # persistent context 는 자동으로 user_data_dir 에 세션 저장됨
        print(f"  💾 다음 실행 시 자동 로그인 됩니다 (세션 유지)")

        # 2. 각 보고서 다운로드
        results = []
        for name, url in REPORTS:
            try:
                path = download_report(page, name, url)
                results.append((name, "✓ 성공" if path else "✗ 실패", path))
            except KeyboardInterrupt:
                print("\n  ⚠ 사용자가 중단했습니다.")
                break
            except Exception as e:
                results.append((name, "✗ 오류", str(e)))
                print(f"  ✗ {name} 오류: {e}")

        # 3. 결과 요약
        banner("다운로드 결과")
        for name, status, detail in results:
            print(f"  {status}  {name}")
            if isinstance(detail, Path):
                print(f"        → {detail.name}")
        print(f"\n📁 저장 위치: {DOWNLOAD_DIR}")
        success_cnt = sum(1 for _, s, _ in results if "성공" in s)
        print(f"\n📊 {success_cnt}/{len(REPORTS)} 성공\n")

        # 4. 다운로드 성공 건이 있으면 웹앱 자동 업로드 진행
        if success_cnt > 0:
            ans = input("🌐 웹앱에 자동 업로드 하시겠습니까? (Y/n): ").strip().lower()
            if ans in ('', 'y', 'yes'):
                try:
                    auto_upload_to_webapp(page, results)
                except Exception as e:
                    print(f"\n✗ 자동 업로드 중 오류: {e}")
            else:
                print("\n  ℹ 업로드 건너뜀. 수동으로 업로드하려면:")
                print(f"     {WEBAPP_URL}")

        input("\n✅ 종료하려면 Enter ... ")
        context.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n사용자가 취소했습니다.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 예기치 못한 오류: {e}")
        import traceback
        traceback.print_exc()
        input("\nEnter 키를 누르면 종료됩니다... ")
        sys.exit(1)
