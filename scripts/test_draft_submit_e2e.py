"""
임시보관문서 열기 + 결재상신 E2E 테스트 스크립트

사용법:
  # dry_run 모드 (상신 버튼 찾기만, 실제 상신 안 함) — 기본값
  python scripts/test_draft_submit_e2e.py

  # 실제 상신 실행
  python scripts/test_draft_submit_e2e.py --submit

  # 특정 문서 제목으로 열기
  python scripts/test_draft_submit_e2e.py --title "GS-25-0088"

주의:
  --submit 옵션 사용 시 실제 결재상신이 진행됩니다.
  반드시 테스트 문서로 확인 후 사용하세요.
"""

import sys
import logging
import argparse
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from playwright.sync_api import sync_playwright
from src.auth.login import login_and_get_context, close_session
from src.approval.approval_automation import ApprovalAutomation

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


def run(doc_title: str = None, do_submit: bool = False):
    """
    E2E 테스트 실행

    Args:
        doc_title: 열려는 문서 제목 (None이면 첫 번째 문서)
        do_submit: True면 실제 상신 실행, False면 dry_run (버튼 확인만)
    """
    logger.info("=" * 60)
    logger.info(f"임시보관문서 열기 + 결재상신 E2E 테스트")
    logger.info(f"  doc_title: {doc_title or '(첫 번째 문서)'}")
    logger.info(f"  dry_run  : {not do_submit}")
    logger.info("=" * 60)

    pw = sync_playwright().start()
    browser, context, page = login_and_get_context(
        playwright_instance=pw, headless=False
    )
    page.set_viewport_size({"width": 1920, "height": 1080})

    try:
        automation = ApprovalAutomation(page=page, context=context)

        # 임시보관문서 열기 + 결재상신 (or dry_run)
        result = automation.open_draft_and_submit(
            doc_title=doc_title,
            dry_run=not do_submit,
        )

        # 결과 출력
        logger.info("=" * 60)
        logger.info(f"결과: success={result.get('success')}")
        logger.info(f"메시지: {result.get('message')}")
        if result.get("doc_title"):
            logger.info(f"문서: {result.get('doc_title')}")
        logger.info("=" * 60)

        if result.get("success"):
            logger.info("E2E 테스트 성공!")
        else:
            logger.error("E2E 테스트 실패!")
            sys.exit(1)

    except Exception as e:
        logger.error(f"테스트 중 예외 발생: {e}", exc_info=True)
        sys.exit(1)
    finally:
        close_session(browser)
        pw.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="임시보관문서 열기 + 결재상신 E2E 테스트")
    parser.add_argument("--title", type=str, default=None, help="열려는 문서 제목 (없으면 첫 번째 문서)")
    parser.add_argument("--submit", action="store_true", help="실제 결재상신 실행 (기본값: dry_run)")
    args = parser.parse_args()

    run(doc_title=args.title, do_submit=args.submit)
