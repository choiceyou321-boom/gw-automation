"""
GW (Groupware Automation) 도구 핸들러 — 회의실/결재/근태/메일.

분리 계획 v4: B 도메인 (src/gw/).
연결 모듈: src/approval/, src/meeting/, src/mail/, src/vision/(향후 src/gw/).
"""

from src.chatbot.handlers._impl import (
    # 회의실 예약
    handle_reserve_meeting_room,
    handle_check_reservation_status,
    handle_check_available_rooms,
    handle_cancel_meeting_reservation,
    handle_list_my_reservations,
    handle_cleanup_test_reservations,
    # 전자결재
    handle_submit_expense_approval,
    handle_submit_draft_approval,
    handle_submit_approval_form,
    handle_start_approval_wizard_fn,
    handle_add_cc_to_approval_doc,
    # 근태신청
    handle_request_annual_leave,
    handle_request_overtime,
    handle_request_outside_work,
    # 메일
    handle_get_mail_summary,
)

TOOLS: dict[str, callable] = {
    "reserve_meeting_room": handle_reserve_meeting_room,
    "check_reservation_status": handle_check_reservation_status,
    "check_available_rooms": handle_check_available_rooms,
    "cancel_meeting_reservation": handle_cancel_meeting_reservation,
    "list_my_reservations": handle_list_my_reservations,
    "cleanup_test_reservations": handle_cleanup_test_reservations,
    "submit_expense_approval": handle_submit_expense_approval,
    "submit_draft_approval": handle_submit_draft_approval,
    "submit_approval_form": handle_submit_approval_form,
    "start_approval_wizard": handle_start_approval_wizard_fn,
    "add_cc_to_approval_doc": handle_add_cc_to_approval_doc,
    "request_annual_leave": handle_request_annual_leave,
    "request_overtime": handle_request_overtime,
    "request_outside_work": handle_request_outside_work,
    "get_mail_summary": handle_get_mail_summary,
}

__all__ = list(TOOLS.keys()) + ["TOOLS"]
