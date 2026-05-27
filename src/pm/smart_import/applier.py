"""
분석 결과를 프로젝트 DB에 반영하는 모듈
- 도메인 타입별 DB 테이블에 데이터 삽입/업데이트
"""
import logging
from typing import Optional

from src.pm.fund_table import db

logger = logging.getLogger("smart_import_applier")


def apply(
    analysis_result: dict,
    user_answers: dict,
    project_id: int
) -> dict:
    """
    분석 결과를 사용자 답변과 함께 DB에 적용

    Args:
        analysis_result: analyzer.analyze() 반환값
        user_answers: 사용자가 채운 필드들 {"field": "value"}
        project_id: 대상 프로젝트 ID

    Returns:
        {
            "success": true,
            "message": "견적서 1건이 추가되었습니다",
            "created_ids": {"subcontracts": [123]},
        }
    """
    detected_type = analysis_result.get("detected_type", "unknown")

    # 타입별 핸들러 라우팅
    handlers = {
        "estimate": _apply_estimate,
        "meeting": _apply_meeting,
        "schedule": _apply_schedule,
        "milestone": _apply_milestone,
        "contacts": _apply_contacts,
        "collection": _apply_collection,
        "overview": _apply_overview,
        "unknown": _apply_unknown,
    }

    handler = handlers.get(detected_type, _apply_unknown)
    return handler(analysis_result, user_answers, project_id)


def _apply_estimate(analysis: dict, answers: dict, project_id: int) -> dict:
    """견적서 → subcontracts 테이블에 추가"""
    conn = db.get_db()
    try:
        # 공종 먼저 조회/생성
        trade_name = answers.get("trade_name") or analysis.get("extracted_fields", {}).get("trade_name", "기타")
        trade_id = _get_or_create_trade(conn, project_id, trade_name)

        # 하도급 추가
        company_name = answers.get("company_name") or analysis.get("extracted_fields", {}).get("company_name", "미정")
        estimate_amount = int(answers.get("estimate_amount") or analysis.get("extracted_fields", {}).get("estimate_amount") or 0)

        cursor = conn.execute("""
            INSERT INTO subcontracts (project_id, trade_id, company_name, estimate_amount)
            VALUES (?, ?, ?, ?)
        """, (project_id, trade_id, company_name, estimate_amount))

        conn.commit()
        subcontract_id = cursor.lastrowid

        return {
            "success": True,
            "message": f"견적서 1건이 추가되었습니다: {company_name}",
            "created_ids": {"subcontracts": [subcontract_id]},
        }

    except Exception as e:
        logger.error(f"견적서 적용 실패: {e}")
        return {
            "success": False,
            "message": f"견적서 추가 실패: {str(e)}",
            "created_ids": {},
        }
    finally:
        conn.close()


def _apply_meeting(analysis: dict, answers: dict, project_id: int) -> dict:
    """회의록 → project_notes 테이블 (미구현, todos로 폴백)"""
    # project_notes 테이블이 없으면 project_milestones으로 임시 저장
    conn = db.get_db()
    try:
        title = answers.get("title") or analysis.get("extracted_fields", {}).get("title", "회의")
        summary = answers.get("summary") or analysis.get("extracted_fields", {}).get("summary", "")

        # 마일스톤으로 임시 저장 (회의 기록)
        cursor = conn.execute("""
            INSERT INTO project_milestones (project_id, name)
            VALUES (?, ?)
        """, (project_id, f"📋 {title}"))

        conn.commit()
        milestone_id = cursor.lastrowid

        return {
            "success": True,
            "message": f"회의 기록이 마일스톤으로 추가되었습니다",
            "created_ids": {"milestones": [milestone_id]},
        }

    except Exception as e:
        logger.error(f"회의 적용 실패: {e}")
        return {
            "success": False,
            "message": f"회의 기록 추가 실패: {str(e)}",
            "created_ids": {},
        }
    finally:
        conn.close()


def _apply_schedule(analysis: dict, answers: dict, project_id: int) -> dict:
    """일정 → project_milestones 테이블"""
    conn = db.get_db()
    try:
        item_name = answers.get("item_name") or analysis.get("extracted_fields", {}).get("item_name", "일정")
        target_date = answers.get("start_date") or answers.get("target_date") or ""

        cursor = conn.execute("""
            INSERT INTO project_milestones (project_id, name, date)
            VALUES (?, ?, ?)
        """, (project_id, item_name, target_date))

        conn.commit()
        milestone_id = cursor.lastrowid

        return {
            "success": True,
            "message": f"일정 1건이 추가되었습니다: {item_name}",
            "created_ids": {"milestones": [milestone_id]},
        }

    except Exception as e:
        logger.error(f"일정 적용 실패: {e}")
        return {
            "success": False,
            "message": f"일정 추가 실패: {str(e)}",
            "created_ids": {},
        }
    finally:
        conn.close()


def _apply_milestone(analysis: dict, answers: dict, project_id: int) -> dict:
    """마일스톤 → project_milestones 테이블"""
    conn = db.get_db()
    try:
        name = answers.get("name") or analysis.get("extracted_fields", {}).get("name", "마일스톤")
        target_date = answers.get("target_date") or ""

        cursor = conn.execute("""
            INSERT INTO project_milestones (project_id, name, date)
            VALUES (?, ?, ?)
        """, (project_id, name, target_date))

        conn.commit()
        milestone_id = cursor.lastrowid

        return {
            "success": True,
            "message": f"마일스톤 1건이 추가되었습니다: {name}",
            "created_ids": {"milestones": [milestone_id]},
        }

    except Exception as e:
        logger.error(f"마일스톤 적용 실패: {e}")
        return {
            "success": False,
            "message": f"마일스톤 추가 실패: {str(e)}",
            "created_ids": {},
        }
    finally:
        conn.close()


def _apply_contacts(analysis: dict, answers: dict, project_id: int) -> dict:
    """연락처 → contacts 테이블"""
    conn = db.get_db()
    try:
        company_name = answers.get("company_name") or analysis.get("extracted_fields", {}).get("company_name", "미정")
        contact_person = answers.get("contact_person") or ""
        phone = answers.get("phone") or ""
        email = answers.get("email") or ""

        cursor = conn.execute("""
            INSERT INTO contacts (project_id, company_name, contact_person, phone, email)
            VALUES (?, ?, ?, ?, ?)
        """, (project_id, company_name, contact_person, phone, email))

        conn.commit()
        contact_id = cursor.lastrowid

        return {
            "success": True,
            "message": f"연락처 1건이 추가되었습니다: {company_name}",
            "created_ids": {"contacts": [contact_id]},
        }

    except Exception as e:
        logger.error(f"연락처 적용 실패: {e}")
        return {
            "success": False,
            "message": f"연락처 추가 실패: {str(e)}",
            "created_ids": {},
        }
    finally:
        conn.close()


def _apply_collection(analysis: dict, answers: dict, project_id: int) -> dict:
    """수금 → collections 테이블"""
    conn = db.get_db()
    try:
        amount = int(answers.get("amount") or analysis.get("extracted_fields", {}).get("amount") or 0)
        category = answers.get("category") or analysis.get("extracted_fields", {}).get("category", "설계")
        collection_date = answers.get("collection_date") or ""
        stage = category  # 설계/시공

        cursor = conn.execute("""
            INSERT INTO collections (project_id, category, stage, amount, collected, collection_date)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (project_id, "수금", stage, amount, amount, collection_date))

        conn.commit()
        collection_id = cursor.lastrowid

        return {
            "success": True,
            "message": f"수금 기록 1건이 추가되었습니다: {amount:,}원",
            "created_ids": {"collections": [collection_id]},
        }

    except Exception as e:
        logger.error(f"수금 적용 실패: {e}")
        return {
            "success": False,
            "message": f"수금 기록 추가 실패: {str(e)}",
            "created_ids": {},
        }
    finally:
        conn.close()


def _apply_overview(analysis: dict, answers: dict, project_id: int) -> dict:
    """개요 → project_overview 테이블"""
    conn = db.get_db()
    try:
        location = answers.get("location") or ""
        usage = answers.get("usage") or ""
        area_pyeong = float(answers.get("area_pyeong") or 0)
        current_status = answers.get("current_status") or ""

        # 기존 overview가 있는지 확인
        existing = conn.execute(
            "SELECT id FROM project_overview WHERE project_id = ?", (project_id,)
        ).fetchone()

        if existing:
            # 업데이트
            conn.execute("""
                UPDATE project_overview
                SET location = ?, usage = ?, area_pyeong = ?, current_status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE project_id = ?
            """, (location, usage, area_pyeong, current_status, project_id))
            overview_id = existing["id"]
            action = "업데이트"
        else:
            # 신규 생성
            cursor = conn.execute("""
                INSERT INTO project_overview (project_id, location, usage, area_pyeong, current_status)
                VALUES (?, ?, ?, ?, ?)
            """, (project_id, location, usage, area_pyeong, current_status))
            overview_id = cursor.lastrowid
            action = "추가"

        conn.commit()

        return {
            "success": True,
            "message": f"프로젝트 개요가 {action}되었습니다",
            "created_ids": {"overview": [overview_id]},
        }

    except Exception as e:
        logger.error(f"개요 적용 실패: {e}")
        return {
            "success": False,
            "message": f"프로젝트 개요 처리 실패: {str(e)}",
            "created_ids": {},
        }
    finally:
        conn.close()


def _apply_unknown(analysis: dict, answers: dict, project_id: int) -> dict:
    """분류 불가능한 경우 → 사용자에게 재질문"""
    return {
        "success": False,
        "message": "입력 내용을 분류할 수 없습니다. 더 자세한 정보를 제공해주세요.",
        "created_ids": {},
    }


def _get_or_create_trade(conn, project_id: int, trade_name: str) -> int:
    """공종이 없으면 생성"""
    existing = conn.execute(
        "SELECT id FROM trades WHERE project_id = ? AND name = ?",
        (project_id, trade_name)
    ).fetchone()

    if existing:
        return existing["id"]

    cursor = conn.execute(
        "INSERT INTO trades (project_id, name) VALUES (?, ?)",
        (project_id, trade_name)
    )
    conn.commit()
    return cursor.lastrowid
