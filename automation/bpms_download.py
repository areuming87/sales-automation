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

# ──── 설정 ────────────────────────────────────────────────
LOGIN_URL = "https://gschargev.lightning.force.com/lightning/page/home"
SCRIPT_DIR = Path(__file__).parent
DOWNLOAD_DIR = SCRIPT_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

# 세션 저장 — 다음 실행 시 자동 로그인 시도용 (선택)
STORAGE_STATE = SCRIPT_DIR / "session_state.json"

REPORTS = [
    ("영업정보",   "https://gschargev.lightning.force.com/lightning/r/Report/00OTJ00000q8ns12AA/view?queryScope=userFolders"),
    ("충전기정보", "https://gschargev.lightning.force.com/lightning/r/Report/00OTJ00000mDkau2AC/view?queryScope=userFolders"),
    ("전암검외",   "https://gschargev.lightning.force.com/lightning/r/Report/00OTJ00000qOHpp2AG/view?queryScope=userFolders"),
    ("세금계산서", "https://gschargev.lightning.force.com/lightning/r/Report/00OTJ00000qLYOz2AO/view?queryScope=userFolders"),
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


# ──── 단계 2. 보고서뷰 한 개 다운로드 ────────────────────
def download_report(page, name, url, attempt=1):
    print(f"\n📥 [{name}] 다운로드 시작 ... ({url[:50]}...)")
    page.goto(url, wait_until="domcontentloaded", timeout=120000)

    # Lightning 보고서 UI 로딩 대기
    print("  ⏳ 보고서 로딩 대기 중...")
    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except PWTimeout:
        pass  # 무한 폴링되는 경우가 있음 — 일정 시간 후 진행
    time.sleep(5)

    # ── 1. 편집 버튼 옆 ▼ (chevron-down) 메뉴 열기
    print("  🔽 메뉴 버튼 클릭...")
    chevron_clicked = False
    selectors_chevron = [
        # 편집 버튼 바로 옆에 있는 메뉴 토글 (가장 일반적인 Lightning 패턴)
        'button[title*="더"][aria-haspopup="true"]',
        'button[aria-label*="더"][aria-haspopup="true"]',
        'lightning-button-menu button',
        'button.slds-button[aria-haspopup="true"]:not([disabled])',
    ]
    for sel in selectors_chevron:
        try:
            loc = page.locator(sel).last
            if loc.count() > 0 and loc.is_visible(timeout=2000):
                loc.click(timeout=5000)
                chevron_clicked = True
                print(f"     ✓ 메뉴 열림 ({sel})")
                break
        except Exception:
            continue

    if not chevron_clicked:
        # 수동 시도 — 사용자가 직접 메뉴 열도록 안내
        print("  ⚠ 자동으로 메뉴를 못 찾았습니다. 브라우저에서 직접:")
        print("     1) 우측 상단 '편집' 옆 ▼ 클릭")
        print("     2) '내보내기' 클릭")
        print("     3) 팝업에서 '내보내기' 클릭")
        input("     완료 후 Enter (다음 보고서로 넘어감)... ")
        return None

    time.sleep(1)

    # ── 2. "내보내기" 메뉴 아이템 클릭
    print("  📤 '내보내기' 클릭...")
    try:
        # 메뉴 아이템은 보통 a 태그 또는 lightning-menu-item 안에 있음
        export_clicked = False
        for sel in [
            'a:has-text("내보내기")',
            '[role="menuitem"]:has-text("내보내기")',
            'span:has-text("내보내기")',
        ]:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.click(timeout=5000)
                    export_clicked = True
                    break
            except Exception:
                continue
        if not export_clicked:
            raise Exception("'내보내기' 메뉴 아이템을 찾지 못함")
    except Exception as e:
        print(f"  ✗ 실패: {e}")
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
        safe = safe_filename(name)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        suggested = download.suggested_filename or "report.xlsx"
        target = DOWNLOAD_DIR / f"{safe}_{timestamp}_{suggested}"
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


# ──── 메인 ────────────────────────────────────────────────
def main():
    banner("BPMS 보고서 자동 다운로드")
    print(f"📁 저장 폴더: {DOWNLOAD_DIR}")
    print(f"📋 다운로드 대상: {len(REPORTS)}개 보고서뷰")

    with sync_playwright() as p:
        # 한국어 Locale + 다운로드 허용 + 사용자 친화적 브라우저
        browser = p.chromium.launch(
            headless=False,
            args=["--start-maximized"],
        )
        context_args = {
            "accept_downloads": True,
            "locale": "ko-KR",
            "viewport": None,  # --start-maximized 와 조합
        }
        # 저장된 세션 있으면 로드 (다음번 자동 로그인용)
        if STORAGE_STATE.exists():
            context_args["storage_state"] = str(STORAGE_STATE)
            print("  💾 저장된 세션 발견 — 자동 로그인 시도")

        context = browser.new_context(**context_args)
        page = context.new_page()

        # 1. 로그인 페이지 → 사용자 대기
        manual_login(page)

        # 로그인 끝났으면 세션 저장 (다음번 자동 로그인용)
        try:
            context.storage_state(path=str(STORAGE_STATE))
            print(f"  💾 세션 저장됨 → {STORAGE_STATE.name}")
        except Exception:
            pass

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

        input("✅ 종료하려면 Enter ... ")
        browser.close()


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
