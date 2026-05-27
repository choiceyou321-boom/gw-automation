"""
v5.6+ 신규 endpoint 테스트
- GET /portfolio/groups
- GET /kanban
- GET /digest/weekly
"""

import pytest
from datetime import datetime, timedelta


@pytest.fixture
def fund_db(tmp_path, monkeypatch):
    """격리된 fund_db 모듈 (임시 DB)"""
    import src.pm.fund_table.db as mod
    monkeypatch.setattr(mod, "_db_initialized", False)
    monkeypatch.setattr(mod, "DB_PATH", tmp_path / "fund.db")
    monkeypatch.setattr(mod, "DATA_DIR", tmp_path)
    return mod


@pytest.fixture
def sample_projects(fund_db):
    """테스트용 프로젝트 3개 생성 (status별)"""
    p1 = fund_db.create_project("활성프로젝트", status="active", project_code="GS-25-0001")["id"]
    p2 = fund_db.create_project("완료프로젝트", status="completed", project_code="GS-25-0002")["id"]
    p3 = fund_db.create_project("임차프로젝트", status="lease", project_code="GS-25-0003")["id"]
    return [p1, p2, p3]


@pytest.fixture
def sample_todos(fund_db, sample_projects):
    """테스트용 TODO 생성 (status별)"""
    p1, p2, p3 = sample_projects

    # In Progress (priority='high')
    todo1 = fund_db.create_todo(p1, "작업 1", priority="high", category="설계")["id"]

    # In Progress (priority='high')
    todo2 = fund_db.create_todo(p1, "작업 2", priority="high", category="시공")["id"]

    # Blocked (category='blocked')
    todo3 = fund_db.create_todo(p2, "작업 3", priority="low", category="blocked")["id"]

    # Done (completed=1)
    todo4 = fund_db.create_todo(p3, "작업 4", priority="medium", category="준공")["id"]
    fund_db.update_todo(todo4, completed=1)

    # Backlog (priority='medium', category 보통)
    todo5 = fund_db.create_todo(p1, "작업 5", priority="medium", category="감리")["id"]

    return [todo1, todo2, todo3, todo4, todo5]


@pytest.fixture
def sample_notifications(fund_db, sample_projects):
    """테스트용 알림 생성"""
    p1 = sample_projects[0]
    conn = fund_db.get_db()
    try:
        conn.execute(
            "INSERT INTO project_notifications (project_id, notification_type, message, read) VALUES (?, ?, ?, ?)",
            (p1, "milestone", "마일스톤 도래", 0)
        )
        conn.execute(
            "INSERT INTO project_notifications (project_id, notification_type, message, read) VALUES (?, ?, ?, ?)",
            (p1, "overdue", "마일스톤 초과", 1)
        )
        conn.commit()
    finally:
        conn.close()


class TestPortfolioGroups:
    """GET /portfolio/groups 테스트"""

    def test_list_projects_grouped_by_status(self, fund_db, sample_projects):
        """프로젝트 status별 그룹화"""
        grouped = fund_db.list_projects_grouped_by_status()

        # active, completed, lease 카테고리 확인
        assert "active" in grouped
        assert "completed" in grouped
        assert "lease" in grouped
        assert "other" in grouped

        # 각 그룹의 프로젝트 확인
        assert len(grouped["active"]) == 1
        assert len(grouped["completed"]) == 1
        assert len(grouped["lease"]) == 1

        # 프로젝트 정보 구조
        p = grouped["active"][0]
        assert "id" in p
        assert "name" in p
        assert "project_code" in p
        assert "status" in p

    def test_portfolio_groups_endpoint(self, fund_db, sample_projects, client):
        """GET /portfolio/groups endpoint 테스트"""
        response = client.get("/api/pm/portfolio/groups")
        assert response.status_code == 200
        data = response.json()

        assert "active" in data
        assert "completed" in data
        assert "lease" in data
        assert len(data["active"]) == 1
        assert len(data["completed"]) == 1
        assert len(data["lease"]) == 1


class TestKanbanBoard:
    """GET /kanban 테스트"""

    def test_list_todos_grouped_by_status_all(self, fund_db, sample_todos):
        """모든 TODO status별 그룹화"""
        grouped = fund_db.list_todos_grouped_by_status()

        # 4개 카테고리 확인
        assert "backlog" in grouped
        assert "in_progress" in grouped
        assert "blocked" in grouped
        assert "done" in grouped

        # 각 그룹의 TODO 개수 확인
        # in_progress: todo1, todo2 (priority='high')
        # blocked: todo3 (category='blocked')
        # done: todo4 (completed=1)
        # backlog: todo5 (priority='medium')
        assert len(grouped["in_progress"]) == 2
        assert len(grouped["blocked"]) == 1
        assert len(grouped["done"]) == 1
        assert len(grouped["backlog"]) >= 1

    def test_list_todos_grouped_by_status_filtered(self, fund_db, sample_todos, sample_projects):
        """프로젝트 필터링 후 TODO status별 그룹화"""
        p1 = sample_projects[0]
        grouped = fund_db.list_todos_grouped_by_status(project_id=p1)

        # p1의 TODO만 포함: todo1, todo2 (in_progress), todo5 (backlog)
        total = sum(len(v) for v in grouped.values())
        assert total == 3  # todo1, todo2, todo5

    def test_kanban_endpoint_all(self, fund_db, sample_todos, client):
        """GET /kanban endpoint 테스트 (전체)"""
        response = client.get("/api/pm/kanban")
        assert response.status_code == 200
        data = response.json()

        assert "backlog" in data
        assert "in_progress" in data
        assert "blocked" in data
        assert "done" in data

    def test_kanban_endpoint_filtered(self, fund_db, sample_todos, sample_projects, client):
        """GET /kanban endpoint 테스트 (project_id 필터)"""
        p1 = sample_projects[0]
        response = client.get(f"/api/pm/kanban?project_id={p1}")
        assert response.status_code == 200
        data = response.json()

        # p1의 TODO만 포함 (3개)
        total = sum(len(v) for v in data.values())
        assert total == 3


class TestWeeklyDigest:
    """GET /digest/weekly 테스트"""

    def test_get_weekly_digest_data(self, fund_db, sample_projects, sample_notifications):
        """주간 다이제스트 데이터 생성"""
        digest = fund_db.get_weekly_digest_data()

        # 응답 구조 확인
        assert "generated_at" in digest
        assert "unread_notifications" in digest
        assert "upcoming_milestones" in digest
        assert "overdue_milestones" in digest
        assert "recent_payments" in digest
        assert "new_contracts" in digest

        # generated_at는 ISO 형식
        assert "T" in digest["generated_at"]

        # 미읽음 알림 (sample_notifications에서 1개)
        assert digest["unread_notifications"] >= 1

        # 목록들은 리스트
        assert isinstance(digest["upcoming_milestones"], list)
        assert isinstance(digest["overdue_milestones"], list)
        assert isinstance(digest["recent_payments"], list)
        assert isinstance(digest["new_contracts"], list)

    def test_weekly_digest_endpoint(self, fund_db, sample_projects, sample_notifications, client):
        """GET /digest/weekly endpoint 테스트"""
        response = client.get("/api/pm/digest/weekly")
        assert response.status_code == 200
        data = response.json()

        # 응답 구조 확인
        assert "generated_at" in data
        assert "unread_notifications" in data
        assert "upcoming_milestones" in data
        assert "overdue_milestones" in data
        assert "recent_payments" in data
        assert "new_contracts" in data

        # 타입 확인
        assert isinstance(data["unread_notifications"], int)
        assert isinstance(data["upcoming_milestones"], list)


# FastAPI TestClient 테스트 (실제 endpoint 호출)
@pytest.fixture
def client(fund_db, monkeypatch):
    """FastAPI TestClient"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    # require_auth 모킹
    def mock_require_auth(request):
        pass

    monkeypatch.setattr("src.pm.fund_table.routes.require_auth", mock_require_auth)

    app = FastAPI()
    from src.pm.fund_table.routes import router
    app.include_router(router, prefix="/api/pm")
    return TestClient(app)
