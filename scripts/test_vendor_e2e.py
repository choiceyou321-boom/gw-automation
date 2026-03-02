"""
거래처등록 E2E 테스트
- ApprovalAutomation.create_vendor_registration() 실제 호출
- 팝업 기반 양식 열기 → 제목/본문 입력 → 보관 검증
"""
import sys
import time
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "config" / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("vendor_e2e")

OUT_DIR = ROOT / "data" / "vendor_test"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def run():
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session
    from src.auth.user_db import get_decrypted_password
    from src.approval.approval_automation import ApprovalAutomation

    gw_id = "tgjeon"
    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw:
        print("[ERROR] 비밀번호를 가져올 수 없습니다")
        return

    pw_inst = sync_playwright().start()
    browser, context, page = login_and_get_context(
        playwright_instance=pw_inst,
        headless=True,
        user_id=gw_id,
        user_pw=gw_pw,
    )
    page.set_viewport_size({"width": 1920, "height": 1080})

    # 불필요한 팝업 정리
    for p in context.pages:
        if p != page:
            try: p.close()
            except: pass

    print("[1] 로그인 성공")

    # ApprovalAutomation 인스턴스 (context 전달 필수 - 팝업 감지용)
    automation = ApprovalAutomation(page=page, context=context)

    # 테스트 데이터 (하넬 거래처 정보 - 테스트용)
    test_data = {
        "title": "(주)하넬무역",  # 양식 기본 제목의 (거래처명) 부분만 교체됨
        "vendor_name": "(주)하넬무역",
        "ceo_name": "김하넬",
        "business_number": "123-45-67890",
        "contact_email": "test@hanel.co.kr",
        "bank_name": "국민은행",
        "account_number": "123-456-789012",
        "account_holder": "(주)하넬무역",
        "note": "E2E 테스트 거래처 (삭제 예정)",
        "trade_type": "매입",
        "department": "PO본부 PM팀",
        "applicant_name": "전태규",
    }

    print("\n[2] create_vendor_registration() 호출...")
    print(f"    제목: {test_data['title']}")
    print(f"    거래처: {test_data['vendor_name']}")

    result = automation.create_vendor_registration(test_data)

    print(f"\n[3] 결과:")
    print(f"    success: {result.get('success')}")
    print(f"    message: {result.get('message')}")

    # 스크린샷 목록 확인
    ss_dir = ROOT / "data" / "approval_screenshots"
    if ss_dir.exists():
        vendor_shots = sorted(ss_dir.glob("vendor_*.png"))
        error_shots = sorted(ss_dir.glob("error_vendor_*.png"))
        print(f"\n[4] 스크린샷:")
        for s in vendor_shots:
            print(f"    {s.name}")
        if error_shots:
            print(f"  에러 스크린샷:")
            for s in error_shots:
                print(f"    {s.name}")

    close_session(browser)
    pw_inst.stop()

    if result.get("success"):
        print("\n=== E2E 테스트 성공 ===")
    else:
        print("\n=== E2E 테스트 실패 ===")

    print("done!")


if __name__ == "__main__":
    run()
