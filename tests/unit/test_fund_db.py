"""
fund_db.py 유닛 테스트
- 프로젝트 CRUD
- 공종 CRUD
- 하도급 상세 CRUD
- 연락처 CRUD
- 수금현황
- 자금현황 요약
"""

import pytest


@pytest.fixture
def fund_db(tmp_path, monkeypatch):
    """격리된 fund_db 모듈 (임시 DB)"""
    import src.fund_table.db as mod
    monkeypatch.setattr(mod, "_db_initialized", False)
    monkeypatch.setattr(mod, "DB_PATH", tmp_path / "fund.db")
    monkeypatch.setattr(mod, "DATA_DIR", tmp_path)
    return mod


@pytest.fixture
def sample_project(fund_db):
    """테스트용 프로젝트 1개 생성"""
    result = fund_db.create_project("테스트프로젝트", design_amount=100_000_000, construction_amount=500_000_000)
    return result["id"]


# ─────────────────────────────────────────
# 프로젝트 CRUD
# ─────────────────────────────────────────

class TestProjectCRUD:
    def test_create_project(self, fund_db):
        result = fund_db.create_project("종로 오블리브")
        assert result["success"] is True
        assert result["id"] > 0

    def test_create_duplicate_project(self, fund_db):
        fund_db.create_project("종로 오블리브")
        result = fund_db.create_project("종로 오블리브")
        assert result["success"] is False
        assert "이미 존재" in result["message"]

    def test_list_projects(self, fund_db):
        fund_db.create_project("프로젝트A")
        fund_db.create_project("프로젝트B")
        projects = fund_db.list_projects()
        assert len(projects) == 2

    def test_get_project(self, fund_db, sample_project):
        project = fund_db.get_project(sample_project)
        assert project["name"] == "테스트프로젝트"
        assert project["design_amount"] == 100_000_000

    def test_get_project_nonexistent(self, fund_db):
        assert fund_db.get_project(9999) is None

    def test_update_project(self, fund_db, sample_project):
        result = fund_db.update_project(sample_project, name="수정프로젝트", profit_rate=12.5)
        assert result["success"] is True
        project = fund_db.get_project(sample_project)
        assert project["name"] == "수정프로젝트"
        assert project["profit_rate"] == 12.5

    def test_update_project_no_changes(self, fund_db, sample_project):
        result = fund_db.update_project(sample_project)
        assert result["success"] is False

    def test_delete_project(self, fund_db, sample_project):
        result = fund_db.delete_project(sample_project)
        assert result["success"] is True
        assert fund_db.get_project(sample_project) is None

    def test_delete_nonexistent_project(self, fund_db):
        result = fund_db.delete_project(9999)
        assert result["success"] is False


# ─────────────────────────────────────────
# 공종 CRUD
# ─────────────────────────────────────────

class TestTradeCRUD:
    def test_add_trade(self, fund_db, sample_project):
        result = fund_db.add_trade(sample_project, "전기공사")
        assert result["success"] is True
        assert result["id"] > 0

    def test_add_duplicate_trade(self, fund_db, sample_project):
        fund_db.add_trade(sample_project, "전기공사")
        result = fund_db.add_trade(sample_project, "전기공사")
        assert result["success"] is False

    def test_list_trades(self, fund_db, sample_project):
        fund_db.add_trade(sample_project, "전기공사", sort_order=1)
        fund_db.add_trade(sample_project, "설비공사", sort_order=2)
        trades = fund_db.list_trades(sample_project)
        assert len(trades) == 2
        assert trades[0]["name"] == "전기공사"

    def test_update_trade(self, fund_db, sample_project):
        result = fund_db.add_trade(sample_project, "전기공사")
        fund_db.update_trade(result["id"], name="전기설비공사")
        trades = fund_db.list_trades(sample_project)
        assert trades[0]["name"] == "전기설비공사"

    def test_delete_trade(self, fund_db, sample_project):
        result = fund_db.add_trade(sample_project, "전기공사")
        fund_db.delete_trade(result["id"])
        assert fund_db.list_trades(sample_project) == []


# ─────────────────────────────────────────
# 하도급 상세 CRUD
# ─────────────────────────────────────────

class TestSubcontractCRUD:
    def test_add_subcontract(self, fund_db, sample_project):
        result = fund_db.add_subcontract(
            sample_project, "대한전기",
            contract_amount=50_000_000, payment_1=10_000_000
        )
        assert result["success"] is True

    def test_list_subcontracts_with_trade(self, fund_db, sample_project):
        trade = fund_db.add_trade(sample_project, "전기공사")
        fund_db.add_subcontract(
            sample_project, "대한전기",
            trade_id=trade["id"], contract_amount=50_000_000
        )
        subs = fund_db.list_subcontracts(sample_project)
        assert len(subs) == 1
        assert subs[0]["trade_name"] == "전기공사"
        assert subs[0]["contract_amount"] == 50_000_000

    def test_update_subcontract(self, fund_db, sample_project):
        result = fund_db.add_subcontract(sample_project, "대한전기", contract_amount=50_000_000)
        fund_db.update_subcontract(result["id"], payment_1=20_000_000)
        subs = fund_db.list_subcontracts(sample_project)
        assert subs[0]["payment_1"] == 20_000_000

    def test_delete_subcontract(self, fund_db, sample_project):
        result = fund_db.add_subcontract(sample_project, "대한전기")
        fund_db.delete_subcontract(result["id"])
        assert fund_db.list_subcontracts(sample_project) == []

    def test_cascade_delete(self, fund_db, sample_project):
        """프로젝트 삭제 시 하도급 데이터도 삭제"""
        fund_db.add_subcontract(sample_project, "대한전기")
        fund_db.delete_project(sample_project)
        assert fund_db.list_subcontracts(sample_project) == []


# ─────────────────────────────────────────
# 연락처 CRUD
# ─────────────────────────────────────────

class TestContactCRUD:
    def test_add_contact(self, fund_db, sample_project):
        result = fund_db.add_contact(
            sample_project, "대한전기",
            contact_person="김전기", phone="010-1234-5678"
        )
        assert result["success"] is True

    def test_list_contacts(self, fund_db, sample_project):
        fund_db.add_contact(sample_project, "대한전기", phone="010-1111-1111")
        fund_db.add_contact(sample_project, "한국설비", phone="010-2222-2222")
        contacts = fund_db.list_contacts(sample_project)
        assert len(contacts) == 2

    def test_update_contact(self, fund_db, sample_project):
        fund_db.add_contact(sample_project, "대한전기")
        contacts = fund_db.list_contacts(sample_project)
        fund_db.update_contact(contacts[0]["id"], phone="010-9999-9999")
        updated = fund_db.list_contacts(sample_project)
        assert updated[0]["phone"] == "010-9999-9999"

    def test_delete_contact(self, fund_db, sample_project):
        fund_db.add_contact(sample_project, "대한전기")
        contacts = fund_db.list_contacts(sample_project)
        fund_db.delete_contact(contacts[0]["id"])
        assert fund_db.list_contacts(sample_project) == []


# ─────────────────────────────────────────
# 수금현황
# ─────────────────────────────────────────

class TestCollections:
    def test_save_collections_bulk(self, fund_db, sample_project):
        items = [
            {"category": "설계", "stage": "1차", "amount": 30_000_000, "collected": 0},
            {"category": "설계", "stage": "2차", "amount": 30_000_000, "collected": 30_000_000},
        ]
        result = fund_db.save_collections_bulk(sample_project, items)
        assert result["success"] is True
        assert "2건" in result["message"]

    def test_list_collections(self, fund_db, sample_project):
        items = [{"category": "설계", "stage": "1차", "amount": 10_000_000, "collected": 0}]
        fund_db.save_collections_bulk(sample_project, items)
        collections = fund_db.list_collections(sample_project)
        assert len(collections) == 1
        assert collections[0]["amount"] == 10_000_000

    def test_update_collection(self, fund_db, sample_project):
        items = [{"category": "시공", "stage": "착공금", "amount": 50_000_000, "collected": 0}]
        fund_db.save_collections_bulk(sample_project, items)
        coll = fund_db.list_collections(sample_project)[0]
        result = fund_db.update_collection(coll["id"], collected=50_000_000)
        assert result["success"] is True


# ─────────────────────────────────────────
# 자금현황 요약
# ─────────────────────────────────────────

class TestFundSummary:
    def test_get_fund_summary(self, fund_db, sample_project):
        fund_db.add_trade(sample_project, "전기공사")
        fund_db.add_subcontract(
            sample_project, "대한전기",
            contract_amount=50_000_000, payment_1=10_000_000
        )
        summary = fund_db.get_fund_summary(sample_project)
        assert summary["project_name"] == "테스트프로젝트"
        assert summary["total_order"] == 600_000_000  # 1억 + 5억
        assert summary["trade_count"] == 1
        assert summary["total_companies"] == 1
        assert summary["total_contract"] == 50_000_000
        assert summary["total_paid"] == 10_000_000

    def test_get_fund_summary_nonexistent(self, fund_db):
        result = fund_db.get_fund_summary(9999)
        assert "error" in result

    def test_get_all_projects_summary(self, fund_db):
        fund_db.create_project("프로젝트A", design_amount=100_000_000)
        fund_db.create_project("프로젝트B", design_amount=200_000_000)
        summaries = fund_db.get_all_projects_summary()
        assert len(summaries) == 2

    def test_get_all_projects_summary_empty(self, fund_db):
        summaries = fund_db.get_all_projects_summary()
        assert summaries == []


# ─────────────────────────────────────────
# GW 프로젝트 캐시
# ─────────────────────────────────────────

class TestGwProjectsCache:
    def test_save_and_search_cache(self, fund_db):
        """캐시 저장 후 키워드 검색"""
        projects = [
            {"code": "GS-25-0088", "name": "종로 오블리브", "start_date": "2025-01-01", "end_date": "2025-12-31"},
            {"code": "GS-25-0100", "name": "강남 메디빌더", "start_date": "2025-03-01", "end_date": "2026-06-30"},
        ]
        fund_db.save_gw_projects_cache(projects)
        results = fund_db.search_gw_projects_cache("종로")
        assert len(results) == 1
        assert results[0]["code"] == "GS-25-0088"

    def test_save_filters_empty_code(self, fund_db):
        """빈 code가 있는 항목은 건너뜀"""
        projects = [
            {"code": "", "name": "빈코드"},
            {"code": "GS-25-0001", "name": "유효프로젝트"},
        ]
        fund_db.save_gw_projects_cache(projects)
        results = fund_db.search_gw_projects_cache("")
        assert len(results) == 1
        assert results[0]["name"] == "유효프로젝트"

    def test_search_by_code(self, fund_db):
        """코드로 검색"""
        fund_db.save_gw_projects_cache([
            {"code": "GS-25-0088", "name": "종로 오블리브"},
        ])
        results = fund_db.search_gw_projects_cache("GS-25-0088")
        assert len(results) == 1

    def test_search_empty_keyword_returns_all(self, fund_db):
        """빈 키워드 → 전체 반환"""
        fund_db.save_gw_projects_cache([
            {"code": "GS-25-0001", "name": "프로젝트A"},
            {"code": "GS-25-0002", "name": "프로젝트B"},
        ])
        results = fund_db.search_gw_projects_cache("")
        assert len(results) == 2

    def test_search_multiple_tokens(self, fund_db):
        """여러 토큰 AND 검색"""
        fund_db.save_gw_projects_cache([
            {"code": "GS-25-0088", "name": "종로 오블리브"},
            {"code": "GS-25-0100", "name": "종로 메디빌더"},
        ])
        results = fund_db.search_gw_projects_cache("종로 오블리브")
        assert len(results) == 1
        assert results[0]["name"] == "종로 오블리브"

    def test_save_replaces_existing(self, fund_db):
        """두 번째 저장이 기존 데이터를 대체"""
        fund_db.save_gw_projects_cache([
            {"code": "GS-25-0001", "name": "이전이름"},
        ])
        fund_db.save_gw_projects_cache([
            {"code": "GS-25-0099", "name": "새프로젝트"},
        ])
        results = fund_db.search_gw_projects_cache("")
        assert len(results) == 1
        assert results[0]["code"] == "GS-25-0099"

    def test_search_no_match(self, fund_db):
        """매칭 결과 없음"""
        fund_db.save_gw_projects_cache([
            {"code": "GS-25-0001", "name": "종로 오블리브"},
        ])
        results = fund_db.search_gw_projects_cache("강남")
        assert results == []
