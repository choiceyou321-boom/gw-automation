"""
Smart Import AI 모듈 단위 테스트
- analyzer: 텍스트 분류 및 필드 추출
- applier: DB 반영
"""
import json
import pytest
from src.pm.smart_import.analyzer import analyze, get_analysis, clear_analysis
from src.pm.smart_import.applier import apply
from src.pm.fund_table import db


class TestAnalyzer:
    """Analyzer 모듈 테스트"""

    def test_analyze_estimate(self):
        """견적서 텍스트 분류"""
        text = """
        견적서
        업체: 삼성건설
        공종: 메탈스터드
        견적금액: 5,000,000원
        """
        result = analyze(text)

        assert result["analysis_id"].startswith("ai-")
        assert result["detected_type"] in ["estimate", "unknown"]  # AI 미사용 시 규칙 기반
        assert "extracted_fields" in result
        assert "missing_fields" in result
        assert "preview" in result

    def test_analyze_schedule(self):
        """일정 텍스트 분류"""
        text = """
        공정표
        항목: 기초공사
        시작일: 2026-06-01
        종료일: 2026-07-31
        """
        result = analyze(text)

        assert result["analysis_id"].startswith("ai-")
        assert result["detected_type"] in ["schedule", "unknown"]

    def test_analyze_with_project_hint(self):
        """프로젝트 힌트 포함"""
        text = "새로운 거래처: 현대건설, 전화: 02-1234-5678"
        result = analyze(text, hint_project_id=1)

        assert result["analysis_id"].startswith("ai-")

    def test_get_analysis_caching(self):
        """분석 결과 캐싱"""
        text = "테스트 텍스트"
        result = analyze(text)
        analysis_id = result["analysis_id"]

        # 캐시에서 조회
        cached = get_analysis(analysis_id)
        assert cached is not None
        assert cached["analysis_id"] == analysis_id

    def test_clear_analysis(self):
        """분석 결과 캐시 제거"""
        text = "테스트 텍스트"
        result = analyze(text)
        analysis_id = result["analysis_id"]

        # 제거
        assert clear_analysis(analysis_id) is True
        assert get_analysis(analysis_id) is None

    def test_missing_fields_for_estimate(self):
        """견적서 필드 확인"""
        text = "견적서 관련"
        result = analyze(text)

        # 규칙 기반 detection이면 missing_fields가 있음
        if result["detected_type"] == "estimate":
            assert any(f["field"] == "company_name" for f in result["missing_fields"])


class TestApplier:
    """Applier 모듈 테스트"""

    @pytest.fixture
    def setup_project(self):
        """테스트 프로젝트 생성"""
        conn = db.get_db()
        cursor = conn.execute(
            "INSERT INTO projects (name, owner_gw_id) VALUES (?, ?)",
            ("Smart Import Test Project", "test_user")
        )
        conn.commit()
        project_id = cursor.lastrowid
        yield project_id
        # 정리
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
        conn.close()

    def test_apply_estimate(self, setup_project):
        """견적서 적용"""
        project_id = setup_project

        analysis = {
            "detected_type": "estimate",
            "extracted_fields": {
                "company_name": "삼성건설",
                "trade_name": "메탈스터드",
                "estimate_amount": 5000000
            }
        }

        user_answers = {
            "company_name": "삼성건설",
            "trade_name": "메탈스터드",
            "estimate_amount": "5000000"
        }

        result = apply(analysis, user_answers, project_id)

        assert result["success"] is True
        assert "subcontracts" in result["created_ids"]
        assert len(result["created_ids"]["subcontracts"]) > 0

        # DB 확인
        conn = db.get_db()
        subcontract = conn.execute(
            "SELECT * FROM subcontracts WHERE id = ?",
            (result["created_ids"]["subcontracts"][0],)
        ).fetchone()
        assert subcontract is not None
        assert subcontract["company_name"] == "삼성건설"
        conn.close()

    def test_apply_contacts(self, setup_project):
        """연락처 적용"""
        project_id = setup_project

        analysis = {
            "detected_type": "contacts",
            "extracted_fields": {
                "company_name": "현대건설"
            }
        }

        user_answers = {
            "company_name": "현대건설",
            "contact_person": "김영진",
            "phone": "02-1234-5678",
            "email": "contact@hyundai.com"
        }

        result = apply(analysis, user_answers, project_id)

        assert result["success"] is True
        assert "contacts" in result["created_ids"]

    def test_apply_milestone(self, setup_project):
        """마일스톤 적용"""
        project_id = setup_project

        analysis = {
            "detected_type": "milestone",
            "extracted_fields": {
                "name": "기초공사 완료"
            }
        }

        user_answers = {
            "name": "기초공사 완료",
            "target_date": "2026-07-31"
        }

        result = apply(analysis, user_answers, project_id)

        assert result["success"] is True
        assert "milestones" in result["created_ids"]

    def test_apply_collection(self, setup_project):
        """수금 적용"""
        project_id = setup_project

        analysis = {
            "detected_type": "collection",
            "extracted_fields": {
                "amount": 10000000
            }
        }

        user_answers = {
            "amount": "10000000",
            "category": "설계",
            "collection_date": "2026-05-28"
        }

        result = apply(analysis, user_answers, project_id)

        assert result["success"] is True
        assert "collections" in result["created_ids"]

    def test_apply_overview(self, setup_project):
        """개요 적용"""
        project_id = setup_project

        analysis = {
            "detected_type": "overview",
            "extracted_fields": {}
        }

        user_answers = {
            "location": "서울시 강남구",
            "usage": "오피스빌딩",
            "area_pyeong": "1000",
            "current_status": "기초공사 중"
        }

        result = apply(analysis, user_answers, project_id)

        assert result["success"] is True

    def test_apply_unknown_type(self, setup_project):
        """미분류 타입 처리"""
        project_id = setup_project

        analysis = {
            "detected_type": "unknown",
            "extracted_fields": {}
        }

        user_answers = {}

        result = apply(analysis, user_answers, project_id)

        assert result["success"] is False


class TestEndToEnd:
    """통합 테스트"""

    @pytest.fixture
    def setup_project(self):
        """테스트 프로젝트 생성"""
        conn = db.get_db()
        cursor = conn.execute(
            "INSERT INTO projects (name, owner_gw_id) VALUES (?, ?)",
            ("E2E Test Project", "test_user")
        )
        conn.commit()
        project_id = cursor.lastrowid
        yield project_id
        # 정리
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
        conn.close()

    def test_full_flow(self, setup_project):
        """전체 흐름: 분석 → 적용"""
        project_id = setup_project

        # 1. 분석
        text = """
        업체명: 삼성건설
        공종: 메탈스터드
        견적금액: 5,000,000원
        """
        analysis_result = analyze(text, hint_project_id=project_id)

        assert "analysis_id" in analysis_result
        analysis_id = analysis_result["analysis_id"]

        # 2. 캐시 확인
        cached = get_analysis(analysis_id)
        assert cached is not None

        # 3. 적용
        user_answers = {
            "company_name": "삼성건설",
            "trade_name": "메탈스터드",
            "estimate_amount": "5000000"
        }

        # 캐시된 분석 결과 사용
        result = apply(cached, user_answers, project_id)

        assert result["success"] is True

        # 4. 캐시 정리
        assert clear_analysis(analysis_id) is True
