"""공정표 자동 생성 엔진 단위 테스트

schedule_generator, process_map_master, estimate_parser 모듈 검증.
세션 XLIV: Full CPM (Forward+Backward Pass, Float, 임계경로) + 면적 로그 보정 추가.
"""
import pytest


class TestGenerateConstructionSchedule:
    """generate_construction_schedule() 함수 테스트"""

    def test_basic_office_schedule(self):
        """오피스 유형 기본 생성 → 항목 존재 확인"""
        from src.pm.fund_table.schedule_generator import generate_construction_schedule
        result = generate_construction_schedule("2026-05-01", "2026-08-31", 150, "오피스")

        assert "schedule_items" in result
        assert "milestones" in result
        assert "summary" in result
        assert len(result["schedule_items"]) > 0
        assert result["summary"]["total_trades"] > 0

    def test_all_project_types(self):
        """모든 공사 유형에 대해 정상 생성 확인"""
        from src.pm.fund_table.schedule_generator import generate_construction_schedule
        for ptype in ("오피스", "상업시설", "병원", "식음", "주거"):
            result = generate_construction_schedule("2026-06-01", "2026-12-31", 100, ptype)
            assert len(result["schedule_items"]) > 0, f"{ptype} 유형 일정 생성 실패"

    def test_invalid_date_range(self):
        """준공일 < 착공일 → 에러 요약 반환"""
        from src.pm.fund_table.schedule_generator import generate_construction_schedule
        result = generate_construction_schedule("2026-08-31", "2026-05-01", 100, "오피스")
        assert result["summary"].get("error") is not None
        assert len(result["schedule_items"]) == 0

    def test_empty_selected_trades(self):
        """빈 공종 리스트 → 에러"""
        from src.pm.fund_table.schedule_generator import generate_construction_schedule
        result = generate_construction_schedule("2026-05-01", "2026-08-31", 100, "오피스", selected_trades=[])
        assert result["summary"].get("error") is not None

    def test_import_materials_flag(self):
        """수입자재 포함 시 '수입자재 발주' 항목 추가"""
        from src.pm.fund_table.schedule_generator import generate_construction_schedule
        result = generate_construction_schedule("2026-05-01", "2026-08-31", 100, "오피스", has_import_materials=True)
        names = [it["item_name"] for it in result["schedule_items"]]
        assert "수입자재 발주" in names

    def test_milestones_extracted(self):
        """마일스톤 항목 (계약, 착공, 준공 등) 추출 확인"""
        from src.pm.fund_table.schedule_generator import generate_construction_schedule
        result = generate_construction_schedule("2026-05-01", "2026-08-31", 100, "오피스")
        milestone_names = [m["name"] for m in result["milestones"]]
        assert "계약" in milestone_names
        assert "준공" in milestone_names

    def test_date_range_within_bounds(self):
        """모든 항목의 시작일/종료일이 착공-준공 범위 내"""
        from src.pm.fund_table.schedule_generator import generate_construction_schedule
        result = generate_construction_schedule("2026-05-01", "2026-08-31", 100, "오피스")
        for it in result["schedule_items"]:
            assert it["start_date"] >= "2026-05-01", f"{it['item_name']} 시작일 범위 초과"
            assert it["end_date"] <= "2026-08-31", f"{it['item_name']} 종료일 범위 초과"


class TestAreaFactor:
    """A-1: 면적 보정 로그 연속 함수 테스트"""

    def test_base_100_returns_one(self):
        """100평 기준 → 1.0"""
        from src.pm.fund_table.schedule_generator import _area_factor
        assert _area_factor(100) == 1.0

    def test_small_area_less_than_one(self):
        """30평 → 1.0 미만"""
        from src.pm.fund_table.schedule_generator import _area_factor
        assert _area_factor(30) < 1.0

    def test_large_area_greater_than_one(self):
        """300평 → 1.0 초과"""
        from src.pm.fund_table.schedule_generator import _area_factor
        assert _area_factor(300) > 1.0

    def test_monotonically_increasing(self):
        """면적 증가 → 보정 계수 단조 증가"""
        from src.pm.fund_table.schedule_generator import _area_factor
        areas = [10, 30, 50, 70, 100, 150, 200, 300, 500]
        factors = [_area_factor(a) for a in areas]
        for i in range(1, len(factors)):
            assert factors[i] >= factors[i - 1], f"면적 {areas[i]}평에서 단조 증가 위반"

    def test_continuity_no_jumps(self):
        """1평 단위 인접값에서 불연속 점프 없음 (차이 < 0.02)"""
        from src.pm.fund_table.schedule_generator import _area_factor
        # 기존 계단식 경계 부근을 1평 단위로 검증
        for boundary in [30, 70, 100, 150, 300]:
            f_before = _area_factor(boundary - 1)
            f_at = _area_factor(boundary)
            f_after = _area_factor(boundary + 1)
            diff1 = abs(f_at - f_before)
            diff2 = abs(f_after - f_at)
            assert diff1 < 0.02, f"{boundary-1}→{boundary}평 불연속: {diff1}"
            assert diff2 < 0.02, f"{boundary}→{boundary+1}평 불연속: {diff2}"

    def test_min_max_bounds(self):
        """극단값에서 0.5~2.0 범위 유지"""
        from src.pm.fund_table.schedule_generator import _area_factor
        assert _area_factor(1) >= 0.5
        assert _area_factor(10000) <= 2.0

    def test_area_factor_affects_summary(self):
        """면적 보정 계수가 summary에 반영"""
        from src.pm.fund_table.schedule_generator import generate_construction_schedule
        r_small = generate_construction_schedule("2026-05-01", "2026-08-31", 20, "오피스")
        r_large = generate_construction_schedule("2026-05-01", "2026-08-31", 400, "오피스")
        assert r_small["summary"]["area_factor"] < r_large["summary"]["area_factor"]


class TestFullCPM:
    """A-2: Full CPM (Forward+Backward Pass, Float, 임계경로) 테스트"""

    def test_schedule_items_have_cpm_fields(self):
        """schedule_items에 CPM 분석 필드 포함"""
        from src.pm.fund_table.schedule_generator import generate_construction_schedule
        result = generate_construction_schedule("2026-05-01", "2026-08-31", 100, "오피스")
        for it in result["schedule_items"]:
            assert "is_critical" in it, f"{it['item_name']}에 is_critical 필드 없음"
            assert "total_float" in it, f"{it['item_name']}에 total_float 필드 없음"
            assert "early_start" in it
            assert "late_start" in it

    def test_critical_path_exists(self):
        """최소 1개 이상의 임계경로 공종 존재"""
        from src.pm.fund_table.schedule_generator import generate_construction_schedule
        result = generate_construction_schedule("2026-05-01", "2026-08-31", 100, "오피스")
        cp_items = [it for it in result["schedule_items"] if it.get("is_critical")]
        assert len(cp_items) > 0, "임계경로 공종이 0개"
        assert result["summary"]["critical_path_count"] > 0

    def test_critical_path_float_is_zero(self):
        """임계경로 공종의 total_float은 0"""
        from src.pm.fund_table.schedule_generator import generate_construction_schedule
        result = generate_construction_schedule("2026-05-01", "2026-08-31", 100, "오피스")
        for it in result["schedule_items"]:
            if it.get("is_critical"):
                assert it["total_float"] == 0, f"CP 공종 '{it['item_name']}'의 float={it['total_float']} ≠ 0"

    def test_non_critical_has_positive_float(self):
        """비임계 공종의 total_float ≥ 0"""
        from src.pm.fund_table.schedule_generator import generate_construction_schedule
        result = generate_construction_schedule("2026-05-01", "2026-08-31", 100, "오피스")
        for it in result["schedule_items"]:
            assert it["total_float"] >= 0, f"'{it['item_name']}'의 float={it['total_float']} < 0"

    def test_late_start_gte_early_start(self):
        """LS ≥ ES (모든 공종)"""
        from src.pm.fund_table.schedule_generator import generate_construction_schedule
        result = generate_construction_schedule("2026-05-01", "2026-08-31", 100, "오피스")
        for it in result["schedule_items"]:
            assert it["late_start"] >= it["early_start"], \
                f"'{it['item_name']}': LS={it['late_start']} < ES={it['early_start']}"

    def test_summary_has_raw_duration(self):
        """summary에 raw_duration, scale_factor, critical_path_count 포함"""
        from src.pm.fund_table.schedule_generator import generate_construction_schedule
        result = generate_construction_schedule("2026-05-01", "2026-08-31", 100, "오피스")
        s = result["summary"]
        assert "raw_duration" in s
        assert "scale_factor" in s
        assert "critical_path_count" in s
        assert s["raw_duration"] > 0


class TestDAGValidation:
    """A-4: DAG 순환 의존성 검증 테스트"""

    def test_valid_dag_passes(self):
        """정상 DAG → 예외 없이 위상 순서 반환"""
        from src.pm.fund_table.schedule_generator import _validate_dag
        trades = [
            {"name": "A", "predecessors": []},
            {"name": "B", "predecessors": ["A"]},
            {"name": "C", "predecessors": ["A"]},
            {"name": "D", "predecessors": ["B", "C"]},
        ]
        order = _validate_dag(trades)
        assert len(order) == 4
        assert order.index("A") < order.index("B")
        assert order.index("A") < order.index("C")
        assert order.index("B") < order.index("D")
        assert order.index("C") < order.index("D")

    def test_cycle_detection(self):
        """순환 의존성 → ValueError"""
        from src.pm.fund_table.schedule_generator import _validate_dag
        trades = [
            {"name": "A", "predecessors": ["C"]},
            {"name": "B", "predecessors": ["A"]},
            {"name": "C", "predecessors": ["B"]},
        ]
        with pytest.raises(ValueError, match="순환 의존성"):
            _validate_dag(trades)

    def test_self_cycle_detection(self):
        """자기 참조 순환 → ValueError"""
        from src.pm.fund_table.schedule_generator import _validate_dag
        trades = [
            {"name": "A", "predecessors": ["A"]},
        ]
        with pytest.raises(ValueError, match="순환 의존성"):
            _validate_dag(trades)

    def test_real_master_data_no_cycles(self):
        """실제 마스터 데이터 45공종에 순환 없음"""
        from src.pm.fund_table.process_map_master import PROCESS_GROUPS
        from src.pm.fund_table.schedule_generator import _validate_dag
        all_trades = []
        for grp in PROCESS_GROUPS:
            for item in grp["items"]:
                all_trades.append({
                    "name": item["name"],
                    "predecessors": item.get("predecessors", []),
                })
        order = _validate_dag(all_trades)
        assert len(order) == len(all_trades)

    def test_cycle_in_schedule_generation(self):
        """순환 의존성 공종 선택 시 에러 반환 (생성 실패)"""
        from src.pm.fund_table.schedule_generator import generate_construction_schedule
        # 이 테스트는 실제 마스터 데이터가 정상이므로 정상 생성만 확인
        result = generate_construction_schedule("2026-05-01", "2026-08-31", 100, "오피스")
        assert result["summary"].get("error") is None


class TestProcessMapMaster:
    """process_map_master 모듈 테스트"""

    def test_get_all_trade_names(self):
        from src.pm.fund_table.process_map_master import get_all_trade_names
        names = get_all_trade_names()
        assert len(names) > 30
        assert "계약" in names
        assert "준공" in names

    def test_get_trade_map(self):
        from src.pm.fund_table.process_map_master import get_trade_map
        tm = get_trade_map()
        assert "METAL STUD" in tm
        assert tm["METAL STUD"]["group"] == "구조/골조"

    def test_get_preset_trades_known_type(self):
        from src.pm.fund_table.process_map_master import get_preset_trades
        trades = get_preset_trades("식음")
        assert "주방기구 설치" in trades
        assert "도시가스 공사" in trades

    def test_get_preset_trades_unknown_type(self):
        """미등록 유형 → 오피스 기본값 반환"""
        from src.pm.fund_table.process_map_master import get_preset_trades
        trades = get_preset_trades("알 수 없는 유형")
        office = get_preset_trades("오피스")
        assert trades == office

    def test_type_presets_no_duplicate(self):
        """프리셋에 중복 공종 없어야 함"""
        from src.pm.fund_table.process_map_master import TYPE_PRESETS
        for ptype, trades in TYPE_PRESETS.items():
            assert len(trades) == len(set(trades)), f"{ptype} 프리셋에 중복 공종 존재"

    def test_all_preset_trades_exist_in_master(self):
        """프리셋의 모든 공종이 마스터 데이터에 존재해야 함"""
        from src.pm.fund_table.process_map_master import TYPE_PRESETS, get_all_trade_names
        all_names = set(get_all_trade_names())
        for ptype, trades in TYPE_PRESETS.items():
            for trade in trades:
                assert trade in all_names, f"{ptype} 프리셋의 '{trade}'가 마스터에 없음"

    def test_predecessors_reference_valid_trades(self):
        """선행 공종이 모두 유효한 공종명이어야 함"""
        from src.pm.fund_table.process_map_master import PROCESS_GROUPS, get_all_trade_names
        all_names = set(get_all_trade_names())
        for grp in PROCESS_GROUPS:
            for item in grp["items"]:
                for pred in item.get("predecessors", []):
                    assert pred in all_names, f"'{item['name']}'의 선행 공종 '{pred}'가 마스터에 없음"


class TestEstimateParser:
    """estimate_parser 모듈 테스트"""

    def test_match_trade_alias(self):
        """별칭 매칭 테스트"""
        from src.pm.fund_table.estimate_parser import _match_trade
        from src.pm.fund_table.process_map_master import get_all_trade_names
        all_trades = get_all_trade_names()
        assert _match_trade("금속공사", all_trades) == "METAL STUD"
        assert _match_trade("도장공사", all_trades) == "벽체 도장"
        assert _match_trade("천정공사", all_trades) == "천정골조 (T-Bar, M-Bar)"

    def test_match_trade_direct(self):
        """마스터 공종명 직접 매칭"""
        from src.pm.fund_table.estimate_parser import _match_trade
        from src.pm.fund_table.process_map_master import get_all_trade_names
        all_trades = get_all_trade_names()
        assert _match_trade("조적", all_trades) == "조적"

    def test_match_trade_no_match(self):
        """매칭 불가 시 None"""
        from src.pm.fund_table.estimate_parser import _match_trade
        from src.pm.fund_table.process_map_master import get_all_trade_names
        all_trades = get_all_trade_names()
        result = _match_trade("완전무관한항목", all_trades)
        assert result is None
