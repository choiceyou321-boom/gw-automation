"""
GW 데이터 자동 동기화 스케줄러
- APScheduler로 주기적으로 GW 크롤링 3단계 실행
- 환경변수: GW_SYNC_CRON (기본 "0 8 * * *"), GW_SYNC_ENABLED (기본 "true")
- 중복 실행 방지: threading.Event 플래그
"""

import os
import logging
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

# 중복 실행 방지 플래그 (외부에서도 import하여 사용)
sync_running = threading.Event()

# 스케줄러 인스턴스 (apscheduler 미설치 시 None)
_scheduler = None


def _parse_cron(cron_expr: str) -> dict:
    """cron 표현식 '분 시 일 월 요일' → APScheduler CronTrigger 파라미터"""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"잘못된 cron 형식: '{cron_expr}' (5개 필드 필요)")
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


def _get_sync_gw_id() -> str:
    """동기화에 사용할 GW 계정 ID 반환 (관리자 계정)"""
    admin_ids = os.environ.get("ADMIN_GW_IDS", os.environ.get("ADMIN_GW_ID", ""))
    if not admin_ids:
        return ""
    # 첫 번째 관리자 ID 사용
    return admin_ids.split(",")[0].strip()


def run_sync():
    """
    GW 동기화 3단계 실행 (동기 함수).
    중복 실행 방지 플래그 관리 포함.
    결과를 notifications 테이블에 저장.
    """
    if sync_running.is_set():
        logger.warning("GW 동기화가 이미 진행 중입니다. 건너뜁니다.")
        return

    sync_running.set()
    start_time = datetime.now()
    logger.info("=== GW 자동 동기화 시작 (%s) ===", start_time.strftime("%Y-%m-%d %H:%M:%S"))

    gw_id = _get_sync_gw_id()
    if not gw_id:
        logger.error("GW 동기화 실패: 관리자 GW ID가 설정되지 않음 (ADMIN_GW_IDS 환경변수)")
        sync_running.clear()
        return

    errors = []
    stage_results = {}

    # 1단계: 프로젝트 등록정보 크롤링
    try:
        from src.fund_table.project_crawler import crawl_all_project_info
        proj_result = crawl_all_project_info(gw_id)
        stage_results["project_info"] = proj_result
        if not proj_result.get("success"):
            errors.append(f"프로젝트정보: {proj_result.get('error', '실패')}")
        else:
            count = sum(1 for r in proj_result.get("results", []) if r.get("status") == "success")
            logger.info("1단계(프로젝트정보) 완료: %d건 성공", count)
    except Exception as e:
        stage_results["project_info"] = {"success": False, "error": str(e)}
        errors.append(f"프로젝트정보: {e}")
        logger.error("1단계(프로젝트정보) 오류: %s", e, exc_info=True)

    # 2단계: 예실대비현황(사업별) 크롤링
    try:
        from src.fund_table.budget_crawler_by_project import crawl_all_by_project
        byprj_result = crawl_all_by_project(gw_id)
        stage_results["budget_by_project"] = byprj_result
        if not byprj_result.get("success"):
            errors.append(f"예실대비(사업별): {byprj_result.get('error', '실패')}")
        else:
            count = sum(1 for r in byprj_result.get("results", []) if r.get("status") == "success")
            logger.info("2단계(예실대비 사업별) 완료: %d건 성공", count)
    except Exception as e:
        stage_results["budget_by_project"] = {"success": False, "error": str(e)}
        errors.append(f"예실대비(사업별): {e}")
        logger.error("2단계(예실대비 사업별) 오류: %s", e, exc_info=True)

    # 3단계: 예실대비현황(상세) 합계 크롤링
    try:
        from src.fund_table.budget_crawler import crawl_all_summary
        summary_result = crawl_all_summary(gw_id)
        stage_results["budget_summary"] = summary_result
        if not summary_result.get("success"):
            errors.append(f"예실대비(합계): {summary_result.get('error', '실패')}")
        else:
            count = sum(1 for r in summary_result.get("results", []) if r.get("status") == "success")
            logger.info("3단계(예실대비 합계) 완료: %d건 성공", count)
    except Exception as e:
        stage_results["budget_summary"] = {"success": False, "error": str(e)}
        errors.append(f"예실대비(합계): {e}")
        logger.error("3단계(예실대비 합계) 오류: %s", e, exc_info=True)

    # 결과 요약
    elapsed = (datetime.now() - start_time).total_seconds()
    success = len(errors) < 3  # 3단계 모두 실패가 아니면 부분 성공으로 간주

    if success:
        msg = f"GW 자동 동기화 완료 ({elapsed:.0f}초)"
        if errors:
            msg += f" — 일부 오류: {'; '.join(errors)}"
    else:
        msg = f"GW 자동 동기화 실패 ({elapsed:.0f}초): {'; '.join(errors)}"

    logger.info("=== %s ===", msg)

    # notifications 테이블에 결과 저장
    try:
        from src.fund_table import db
        noti_type = "sync_success" if success else "sync_error"
        db.create_notification(
            project_id=None,
            notification_type=noti_type,
            message=msg,
        )
    except Exception as e:
        logger.error("동기화 결과 알림 저장 실패: %s", e)

    sync_running.clear()


def start_scheduler():
    """APScheduler 시작. apscheduler 미설치 시 경고만 출력."""
    global _scheduler

    enabled = os.environ.get("GW_SYNC_ENABLED", "true").lower()
    if enabled not in ("true", "1", "yes"):
        logger.info("GW 자동 동기화 비활성화 (GW_SYNC_ENABLED=%s)", enabled)
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning(
            "apscheduler가 설치되지 않아 GW 자동 동기화를 시작할 수 없습니다. "
            "설치: pip install apscheduler"
        )
        return

    cron_expr = os.environ.get("GW_SYNC_CRON", "0 8 * * *")
    try:
        cron_params = _parse_cron(cron_expr)
    except ValueError as e:
        logger.error("GW_SYNC_CRON 파싱 오류: %s — 기본값(매일 08:00) 사용", e)
        cron_params = {"minute": "0", "hour": "8", "day": "*", "month": "*", "day_of_week": "*"}

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        run_sync,
        CronTrigger(**cron_params),
        id="gw_sync",
        name="GW 데이터 자동 동기화",
        replace_existing=True,
        misfire_grace_time=3600,  # 최대 1시간 지연 허용
    )
    _scheduler.start()
    logger.info(
        "GW 자동 동기화 스케줄러 시작 (cron: %s)", cron_expr
    )


def stop_scheduler():
    """APScheduler 종료."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("GW 자동 동기화 스케줄러 종료")
