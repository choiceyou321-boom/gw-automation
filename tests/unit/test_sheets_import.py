"""
sheets_import.py PM 시트 관련 함수 유닛 테스트
- _find_project_starts: 프로젝트 시작 행 찾기
- _parse_grade_map: 등급 범례 파싱
- _detect_grade: 프로젝트 등급 판별
"""

import pytest


@pytest.fixture
def si():
    """sheets_import 모듈 (Google API 호출 없이 유틸 함수만 사용)"""
    from src.fund_table import sheets_import as mod
    return mod


# ─────────────────────────────────────────
# _find_project_starts 테스트
# ─────────────────────────────────────────

class TestFindProjectStarts:
    def test_finds_project_rows(self, si):
        """col B=숫자, col C=이름인 행을 찾음"""
        rows = [
            ["", "", "", ""],            # 0: 빈 행
            ["", "1등급", "", ""],        # 1: 등급 헤더
            ["", "1", "종로 오블리브", ""],  # 2: 프로젝트
            ["", "", "하도급 내역", ""],   # 3: 빈 B값
            ["", "2", "강남 메디빌더", ""],  # 4: 프로젝트
        ]
        starts = si._find_project_starts(rows)
        assert starts == [2, 4]

    def test_empty_rows(self, si):
        """빈 행 목록 → 빈 결과"""
        assert si._find_project_starts([]) == []

    def test_no_matching_rows(self, si):
        """매칭되는 행 없음"""
        rows = [
            ["", "텍스트", "이름", ""],
            ["", "", "", ""],
        ]
        assert si._find_project_starts(rows) == []

    def test_b_digit_c_empty_excluded(self, si):
        """col B=숫자이지만 col C 비어있으면 제외"""
        rows = [
            ["", "1", "", ""],
        ]
        assert si._find_project_starts(rows) == []

    def test_short_row_excluded(self, si):
        """컬럼 3개 미만 행은 무시"""
        rows = [
            ["", "1"],
        ]
        assert si._find_project_starts(rows) == []


# ─────────────────────────────────────────
# _parse_grade_map 테스트
# ─────────────────────────────────────────

class TestParseGradeMap:
    def test_parses_grade_labels(self, si):
        """등급 라벨 파싱"""
        rows = [
            ["", "", "", ""],
            ["", "", "", ""],
            ["", "", "", ""],
            ["1등급", "17", "KOM, 2~3차 보고"],
            ["2등급", "5", "KOM, 2차 보고"],
        ]
        result = si._parse_grade_map(rows)
        assert "1등급" in result
        assert "2등급" in result
        assert result["1등급"]["label"] == "1등급"

    def test_empty_rows(self, si):
        """빈 행 → 빈 결과"""
        assert si._parse_grade_map([]) == {}

    def test_no_grade_found(self, si):
        """등급 키워드 없음"""
        rows = [
            ["프로젝트명", "코드", "설명"],
        ]
        assert si._parse_grade_map(rows) == {}

    def test_ignores_non_digit_start(self, si):
        """'등급' 포함하지만 숫자로 시작하지 않으면 제외"""
        rows = [
            ["상등급", "특등급", "최고등급"],
        ]
        assert si._parse_grade_map(rows) == {}


# ─────────────────────────────────────────
# _detect_grade 테스트
# ─────────────────────────────────────────

class TestDetectGrade:
    def test_finds_grade_above(self, si):
        """프로젝트 행 위쪽 등급 헤더 감지"""
        rows = [
            ["1등급", "", "", ""],        # 0
            ["", "1", "프로젝트A", ""],    # 1
        ]
        assert si._detect_grade(1, rows) == "1등급"

    def test_default_4grade(self, si):
        """등급 헤더 없으면 기본 4등급"""
        rows = [
            ["", "", "", ""],
            ["", "1", "프로젝트A", ""],
        ]
        assert si._detect_grade(1, rows) == "4등급"

    def test_finds_nearest_grade(self, si):
        """가장 가까운 위쪽 등급 헤더를 찾음"""
        rows = [
            ["1등급", "", "", ""],        # 0
            ["", "1", "프로젝트A", ""],    # 1
            ["2등급", "", "", ""],        # 2
            ["", "2", "프로젝트B", ""],    # 3
        ]
        assert si._detect_grade(1, rows) == "1등급"
        assert si._detect_grade(3, rows) == "2등급"

    def test_first_row_no_header(self, si):
        """첫 행이 프로젝트면 기본 4등급"""
        rows = [
            ["", "1", "프로젝트A", ""],
        ]
        assert si._detect_grade(0, rows) == "4등급"
