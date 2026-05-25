"""
PM (Project Management) 도구 핸들러 — 자금관리, 프로젝트 등록/조회/리포트, 일정.

분리 계획 v4: A 도메인 (src/pm/).
연결 모듈: src/fund_table/, src/contracts/, src/pm/schedule/(향후).
"""

from src.chatbot.handlers._impl import (
    handle_get_fund_summary,
    handle_update_project_info,
    handle_add_project_note,
    handle_add_project_subcontract,
    handle_update_collection_status,
    handle_add_project_todo,
    handle_get_project_detail,
    handle_add_project_contact,
    handle_get_overdue_items,
    handle_compare_projects,
    handle_generate_project_report,
    handle_update_project_milestone,
    handle_get_project_schedule,
    handle_get_my_schedule,
)

# Gemini Function Calling 등록용 도구 매핑
TOOLS: dict[str, callable] = {
    "get_fund_summary": handle_get_fund_summary,
    "update_project_info": handle_update_project_info,
    "add_project_note": handle_add_project_note,
    "add_project_subcontract": handle_add_project_subcontract,
    "update_collection_status": handle_update_collection_status,
    "add_project_todo": handle_add_project_todo,
    "get_project_detail": handle_get_project_detail,
    "add_project_contact": handle_add_project_contact,
    "get_overdue_items": handle_get_overdue_items,
    "compare_projects": handle_compare_projects,
    "generate_project_report": handle_generate_project_report,
    "update_project_milestone": handle_update_project_milestone,
    "get_project_schedule": handle_get_project_schedule,
    "get_my_schedule": handle_get_my_schedule,
}

__all__ = list(TOOLS.keys()) + ["TOOLS"]
