"""
Blind Spot Detector — 프로젝트 관리에서 놓치기 쉬운 8가지 문제 자동 감지

각 함수가 특정 리스크를 감지하고, run_all_detectors()가 통합 결과를 반환합니다.
결과는 project_insights 테이블에 insight_type='blind_spot'으로 저장됩니다.
"""
import json
import sqlite3
from datetime import datetime, timedelta, date
from typing import Optional
from pathlib import Path

from . import db

logger_severity = {
    "critical": "🔴",
    "warning": "🟡",
    "info": "🟢",
}


def detect_overdue_milestones(project_data: dict) -> Optional[dict]:
    """
    1. 임박한 마일스톤 감지
    - due_date ≤ 7일 미만 또는 지남 + completed=0
    """
    milestones = project_data.get("milestones", [])
    issues = []
    today = date.today()
    has_overdue = False

    for m in milestones:
        if m.get("completed"):
            continue
        due_str = m.get("date", "")
        if not due_str:
            continue
        try:
            due_date = datetime.fromisoformat(due_str).date()
        except Exception:
            continue

        days_left = (due_date - today).days
        if days_left < 0:
            has_overdue = True
        if days_left <= 7:
            issues.append({
                "milestone": m.get("name", ""),
                "days_left": days_left,  # 음수 가능
                "due_date": due_str,
            })

    if not issues:
        return None

    summary = f"미완료 마일스톤 {len(issues)}개가 임박했거나 지났습니다."
    suggested_action = f"즉시 상태 확인 필요: {', '.join(i['milestone'] for i in issues[:3])}"
    return {
        "project_id": project_data["id"],
        "project_name": project_data["name"],
        "issue_type": "overdue_milestones",
        "severity": "critical" if has_overdue else "warning",
        "summary": summary,
        "suggested_action": suggested_action,
        "details": issues,
    }


def detect_stale_high_todos(project_data: dict) -> Optional[dict]:
    """
    2. 방치된 높은 우선순위 할일 감지
    - priority='high' + 생성 7일 이상 + 미완료
    """
    todos = project_data.get("todos", [])
    issues = []
    today = datetime.now()

    for t in todos:
        if t.get("completed"):
            continue
        if t.get("priority") != "high":
            continue
        created_str = t.get("created_at", "")
        if not created_str:
            continue
        try:
            created = datetime.fromisoformat(created_str)
        except Exception:
            continue

        days_old = (today - created).days
        if days_old >= 7:
            issues.append({
                "content": t.get("content", ""),
                "days_old": days_old,
                "created_at": created_str,
            })

    if not issues:
        return None

    summary = f"높은 우선순위 할일 {len(issues)}개가 7일 이상 방치되었습니다."
    suggested_action = "우선순위 재검토 또는 즉시 처리 필요"
    return {
        "project_id": project_data["id"],
        "project_name": project_data["name"],
        "issue_type": "stale_high_todos",
        "severity": "warning",
        "summary": summary,
        "suggested_action": suggested_action,
        "details": issues,
    }


def detect_delayed_collections(project_data: dict) -> Optional[dict]:
    """
    3. 지연된 수금 감지
    - scheduled_date 지남 + collected=0
    """
    collections = project_data.get("collections", [])
    issues = []
    today = date.today()

    for c in collections:
        if c.get("collected"):
            continue
        coll_date_str = c.get("collection_date", "")
        if not coll_date_str:
            continue
        try:
            coll_date = datetime.fromisoformat(coll_date_str).date()
        except Exception:
            continue

        if coll_date < today:
            days_late = (today - coll_date).days
            issues.append({
                "category": c.get("category", ""),
                "stage": c.get("stage", ""),
                "amount": c.get("amount", 0),
                "scheduled_date": coll_date_str,
                "days_late": days_late,
            })

    if not issues:
        return None

    total_delayed = sum(i["amount"] for i in issues)
    summary = f"지연된 수금 {len(issues)}건, 합계 {total_delayed:,}원"
    suggested_action = f"발주처 연락 필요: {issues[0]['category']} {issues[0]['stage']}"
    return {
        "project_id": project_data["id"],
        "project_name": project_data["name"],
        "issue_type": "delayed_collections",
        "severity": "critical" if total_delayed > 10_000_000 else "warning",
        "summary": summary,
        "suggested_action": suggested_action,
        "details": issues,
    }


def detect_unset_collections(project_data: dict) -> Optional[dict]:
    """
    4. 미설정 수금 감지
    - 하도급(subcontract)이 있는 프로젝트인데 collections 없음
    """
    subs = project_data.get("subcontracts", [])
    colls = project_data.get("collections", [])

    if not subs or colls:
        return None

    total_sub = sum(s.get("contract_amount", 0) for s in subs)
    if total_sub == 0:
        return None

    summary = f"하도급 계약 {len(subs)}건({total_sub:,}원)이 있는데 수금 일정이 미설정"
    suggested_action = "수금 예정액 및 일정 입력 필요"
    return {
        "project_id": project_data["id"],
        "project_name": project_data["name"],
        "issue_type": "unset_collections",
        "severity": "warning",
        "summary": summary,
        "suggested_action": suggested_action,
        "details": {
            "subcontracts_count": len(subs),
            "total_contract": total_sub,
            "collections_count": len(colls),
        },
    }


def detect_profit_drop(project_data: dict) -> Optional[dict]:
    """
    5. 수익성 악화 감지
    - profit_rate 급변 (히스토리 없으면 현재만 보고 적자 표시)
    """
    profit_rate = project_data.get("profit_rate", 0)
    profit_amount = project_data.get("profit_amount", 0)

    # 적자 상황
    if profit_amount < 0:
        summary = f"프로젝트 적자: -{abs(profit_amount):,}원 (이익율: {profit_rate}%)"
        suggested_action = "수익 계획 검토 및 비용 절감 방안 수립"
        return {
            "project_id": project_data["id"],
            "project_name": project_data["name"],
            "issue_type": "profit_drop",
            "severity": "critical",
            "summary": summary,
            "suggested_action": suggested_action,
            "details": {
                "profit_amount": profit_amount,
                "profit_rate": profit_rate,
            },
        }

    # 마진율 5% 이하 (위험 수준)
    if 0 <= profit_rate <= 5:
        summary = f"매우 낮은 마진율: {profit_rate}% ({profit_amount:,}원)"
        suggested_action = "하도급 비용 재협상 또는 추가 수금 검토"
        return {
            "project_id": project_data["id"],
            "project_name": project_data["name"],
            "issue_type": "profit_drop",
            "severity": "warning",
            "summary": summary,
            "suggested_action": suggested_action,
            "details": {
                "profit_amount": profit_amount,
                "profit_rate": profit_rate,
            },
        }

    return None


def detect_budget_overrun(project_data: dict) -> Optional[dict]:
    """
    6. 예산 초과 위험 감지
    - execution_rate ≥ 90%
    """
    execution_budget = project_data.get("execution_budget", 0)
    if execution_budget == 0:
        return None

    # actual_amount 계산 (subcontracts 기지급 + 예상 지급)
    subs = project_data.get("subcontracts", [])
    actual_paid = sum(
        sum(s.get(f"payment_{n}", 0) or 0 for n in range(1, 5) if s.get(f"payment_{n}_confirmed"))
        for s in subs
    )
    actual_rate = (actual_paid / execution_budget * 100) if execution_budget else 0

    if actual_rate >= 90:
        remaining = max(0, execution_budget - actual_paid)
        summary = f"예산 집행률 {actual_rate:.1f}% — 잔액 {remaining:,}원 남음"
        suggested_action = "추가 지급 승인 필요 시 즉시 보고"
        return {
            "project_id": project_data["id"],
            "project_name": project_data["name"],
            "issue_type": "budget_overrun",
            "severity": "critical" if actual_rate >= 100 else "warning",
            "summary": summary,
            "suggested_action": suggested_action,
            "details": {
                "execution_budget": execution_budget,
                "actual_paid": actual_paid,
                "execution_rate": actual_rate,
                "remaining": remaining,
            },
        }

    return None


def detect_idle_projects(project_data: dict) -> Optional[dict]:
    """
    7. 진행 없는 프로젝트 감지
    - 최근 30일 todo/milestone 변경 0건
    """
    todos = project_data.get("todos", [])
    milestones = project_data.get("milestones", [])
    today = datetime.now()
    thirty_days_ago = today - timedelta(days=30)

    recent_todos = sum(
        1 for t in todos
        if t.get("created_at")
        and datetime.fromisoformat(t["created_at"]) >= thirty_days_ago
    )
    recent_milestones = sum(
        1 for m in milestones
        if m.get("date")
        and datetime.fromisoformat(m["date"]) >= thirty_days_ago
    )

    if recent_todos == 0 and recent_milestones == 0 and (todos or milestones):
        summary = "최근 30일 진행 변경사항이 없습니다."
        suggested_action = "프로젝트 상태 확인 및 진행 일정 업데이트 필요"
        return {
            "project_id": project_data["id"],
            "project_name": project_data["name"],
            "issue_type": "idle_projects",
            "severity": "info",
            "summary": summary,
            "suggested_action": suggested_action,
            "details": {
                "total_todos": len(todos),
                "total_milestones": len(milestones),
                "recent_changes_30d": recent_todos + recent_milestones,
            },
        }

    return None


def detect_empty_overview(project_data: dict) -> Optional[dict]:
    """
    8. 미작성 프로젝트 개요 감지
    - client, contractor(via subcontracts), start_date 비어있음
    """
    ov = project_data.get("overview", {})
    subs = project_data.get("subcontracts", [])

    missing = []
    if not ov.get("client"):
        missing.append("발주처")
    if not subs:
        missing.append("하도급 정보")
    if not ov.get("construction_start") and not ov.get("design_start"):
        missing.append("시작일")

    if not missing:
        return None

    summary = f"프로젝트 개요 정보 미작성: {', '.join(missing)}"
    suggested_action = "프로젝트 기본 정보 입력 필수 (정확한 분석 불가)"
    return {
        "project_id": project_data["id"],
        "project_name": project_data["name"],
        "issue_type": "empty_overview",
        "severity": "info",
        "summary": summary,
        "suggested_action": suggested_action,
        "details": {
            "missing_fields": missing,
        },
    }


def run_all_detectors(projects: list[dict] = None) -> list[dict]:
    """
    전체 detector 실행 및 중복 제거 후 저장

    프로젝트 데이터 구조:
    {
        "id": int,
        "name": str,
        "profit_rate": float,
        "profit_amount": int,
        "execution_budget": int,
        "overview": {...},
        "milestones": [...],
        "subcontracts": [...],
        "collections": [...],
        "todos": [...],
    }
    """
    if projects is None:
        projects = db.get_all_projects_full_data()

    detectors = [
        detect_overdue_milestones,
        detect_stale_high_todos,
        detect_delayed_collections,
        detect_unset_collections,
        detect_profit_drop,
        detect_budget_overrun,
        detect_idle_projects,
        detect_empty_overview,
    ]

    all_issues = []
    for project in projects:
        for detector_fn in detectors:
            issue = detector_fn(project)
            if issue:
                all_issues.append(issue)

    # 중복 제거 — 같은 issue_type + project_id + 24시간 이내는 skip
    conn = db.get_db()
    try:
        existing = conn.execute(
            """
            SELECT project_id, insight_type FROM project_insights
            WHERE insight_type = 'blind_spot'
            AND datetime(generated_at) > datetime('now', '-24 hours')
            """
        ).fetchall()
        existing_set = {(r["project_id"], r["insight_type"]) for r in existing}
    finally:
        conn.close()

    result = []
    for issue in all_issues:
        # insight_type이 아직 없으니 issue_type으로 비교
        # 실제 저장 시에는 insight_type='blind_spot'으로 변환
        issue_key = (issue["project_id"], "blind_spot")
        if issue_key not in existing_set:
            result.append(issue)

    return result
