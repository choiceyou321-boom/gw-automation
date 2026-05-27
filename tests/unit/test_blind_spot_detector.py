"""
Blind Spot Detector 테스트
- 8가지 detector 함수 + run_all_detectors 통합 테스트
"""
import pytest
from datetime import datetime, timedelta, date
from src.pm.fund_table.blind_spot_detector import (
    detect_overdue_milestones,
    detect_stale_high_todos,
    detect_delayed_collections,
    detect_unset_collections,
    detect_profit_drop,
    detect_budget_overrun,
    detect_idle_projects,
    detect_empty_overview,
    run_all_detectors,
)


def test_detect_overdue_milestones():
    """임박한 마일스톤 감지"""
    today = date.today()
    project_data = {
        "id": 1,
        "name": "프로젝트 A",
        "milestones": [
            {
                "id": 1,
                "name": "설계 완료",
                "completed": 0,
                "date": (today - timedelta(days=1)).isoformat(),
            },  # 지난 일정
            {
                "id": 2,
                "name": "시공 시작",
                "completed": 1,
                "date": (today + timedelta(days=3)).isoformat(),
            },  # 완료됨 (skip)
            {
                "id": 3,
                "name": "시공 완료",
                "completed": 0,
                "date": (today + timedelta(days=5)).isoformat(),
            },  # 7일 이내
        ],
    }

    result = detect_overdue_milestones(project_data)
    assert result is not None
    assert result["issue_type"] == "overdue_milestones"
    assert len(result["details"]) == 2
    assert result["severity"] == "critical"  # 지난 일정이 있으므로


def test_detect_stale_high_todos():
    """방치된 높은 우선순위 할일 감지"""
    now = datetime.now()
    project_data = {
        "id": 1,
        "name": "프로젝트 A",
        "todos": [
            {
                "id": 1,
                "content": "발주처 연락",
                "completed": 0,
                "priority": "high",
                "created_at": (now - timedelta(days=10)).isoformat(),
            },  # 10일 전, 미완료, 높은 우선순위
            {
                "id": 2,
                "content": "문서 정리",
                "completed": 0,
                "priority": "medium",
                "created_at": (now - timedelta(days=15)).isoformat(),
            },  # 15일 전이지만 우선순위 낮음 (skip)
            {
                "id": 3,
                "content": "최종 점검",
                "completed": 1,
                "priority": "high",
                "created_at": (now - timedelta(days=20)).isoformat(),
            },  # 완료됨 (skip)
        ],
    }

    result = detect_stale_high_todos(project_data)
    assert result is not None
    assert result["issue_type"] == "stale_high_todos"
    assert len(result["details"]) == 1
    assert result["details"][0]["content"] == "발주처 연락"


def test_detect_delayed_collections():
    """지연된 수금 감지"""
    today = date.today()
    project_data = {
        "id": 1,
        "name": "프로젝트 A",
        "collections": [
            {
                "id": 1,
                "category": "설계료",
                "stage": "계약금",
                "amount": 10_000_000,
                "collected": 0,
                "collection_date": (today - timedelta(days=5)).isoformat(),
            },  # 5일 지남, 미수금
            {
                "id": 2,
                "category": "설계료",
                "stage": "잔금",
                "amount": 5_000_000,
                "collected": 1,
                "collection_date": (today - timedelta(days=3)).isoformat(),
            },  # 수금됨 (skip)
            {
                "id": 3,
                "category": "시공료",
                "stage": "계약금",
                "amount": 20_000_000,
                "collected": 0,
                "collection_date": (today + timedelta(days=2)).isoformat(),
            },  # 아직 안 지남 (skip)
        ],
    }

    result = detect_delayed_collections(project_data)
    assert result is not None
    assert result["issue_type"] == "delayed_collections"
    assert len(result["details"]) == 1
    assert result["details"][0]["days_late"] == 5
    assert "10,000,000" in result["summary"]


def test_detect_unset_collections():
    """미설정 수금 감지"""
    project_data = {
        "id": 1,
        "name": "프로젝트 A",
        "subcontracts": [
            {
                "id": 1,
                "company_name": "A건설",
                "contract_amount": 50_000_000,
            },
            {
                "id": 2,
                "company_name": "B인테리어",
                "contract_amount": 30_000_000,
            },
        ],
        "collections": [],  # 비어있음
    }

    result = detect_unset_collections(project_data)
    assert result is not None
    assert result["issue_type"] == "unset_collections"
    assert result["details"]["subcontracts_count"] == 2
    assert result["details"]["total_contract"] == 80_000_000


def test_detect_unset_collections_skip():
    """수금이 설정된 경우 skip"""
    project_data = {
        "id": 1,
        "name": "프로젝트 A",
        "subcontracts": [
            {
                "id": 1,
                "company_name": "A건설",
                "contract_amount": 50_000_000,
            },
        ],
        "collections": [
            {
                "id": 1,
                "category": "설계료",
                "amount": 50_000_000,
            },
        ],
    }

    result = detect_unset_collections(project_data)
    assert result is None  # 수금이 있으므로 skip


def test_detect_profit_drop():
    """수익성 악화 감지 — 적자"""
    project_data = {
        "id": 1,
        "name": "프로젝트 A",
        "profit_amount": -5_000_000,
        "profit_rate": -10.0,
    }

    result = detect_profit_drop(project_data)
    assert result is not None
    assert result["issue_type"] == "profit_drop"
    assert result["severity"] == "critical"
    assert "-5,000,000" in result["summary"]


def test_detect_profit_drop_low_margin():
    """수익성 악화 감지 — 낮은 마진율"""
    project_data = {
        "id": 1,
        "name": "프로젝트 A",
        "profit_amount": 3_000_000,
        "profit_rate": 3.0,  # 3% (위험)
    }

    result = detect_profit_drop(project_data)
    assert result is not None
    assert result["issue_type"] == "profit_drop"
    assert result["severity"] == "warning"


def test_detect_budget_overrun():
    """예산 초과 위험 감지"""
    project_data = {
        "id": 1,
        "name": "프로젝트 A",
        "execution_budget": 100_000_000,
        "subcontracts": [
            {
                "id": 1,
                "payment_1": 50_000_000,
                "payment_1_confirmed": 1,
                "payment_2": 45_000_000,
                "payment_2_confirmed": 1,
                "payment_3": 0,
                "payment_3_confirmed": 0,
                "payment_4": 0,
                "payment_4_confirmed": 0,
            },
        ],
    }

    result = detect_budget_overrun(project_data)
    assert result is not None
    assert result["issue_type"] == "budget_overrun"
    assert result["severity"] == "warning"  # 95% 실행
    assert "95" in result["summary"]


def test_detect_idle_projects():
    """진행 없는 프로젝트 감지"""
    thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
    project_data = {
        "id": 1,
        "name": "프로젝트 A",
        "todos": [
            {
                "id": 1,
                "content": "할일 1",
                "created_at": thirty_days_ago,
            },
        ],
        "milestones": [
            {
                "id": 1,
                "name": "마일스톤 1",
                "date": thirty_days_ago,
            },
        ],
    }

    result = detect_idle_projects(project_data)
    assert result is not None
    assert result["issue_type"] == "idle_projects"
    assert result["severity"] == "info"


def test_detect_empty_overview():
    """미작성 프로젝트 개요 감지"""
    project_data = {
        "id": 1,
        "name": "프로젝트 A",
        "overview": {
            "client": "",  # 비어있음
            "construction_start": "",  # 비어있음
        },
        "subcontracts": [],  # 비어있음
    }

    result = detect_empty_overview(project_data)
    assert result is not None
    assert result["issue_type"] == "empty_overview"
    assert "발주처" in str(result["details"]["missing_fields"])
    assert "하도급 정보" in str(result["details"]["missing_fields"])
    assert "시작일" in str(result["details"]["missing_fields"])


def test_run_all_detectors():
    """통합 detector 실행"""
    today = date.today()
    now = datetime.now()

    projects = [
        {
            "id": 1,
            "name": "프로젝트 1",
            "profit_amount": -5_000_000,
            "profit_rate": -10.0,
            "execution_budget": 100_000_000,
            "overview": {"client": ""},
            "milestones": [
                {
                    "id": 1,
                    "name": "마일스톤",
                    "completed": 0,
                    "date": (today - timedelta(days=1)).isoformat(),
                }
            ],
            "subcontracts": [],
            "collections": [],
            "todos": [],
        },
    ]

    results = run_all_detectors(projects)
    assert len(results) > 0
    assert any(r["issue_type"] == "profit_drop" for r in results)
    assert any(r["issue_type"] == "overdue_milestones" for r in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
