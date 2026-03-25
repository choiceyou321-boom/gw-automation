"""
scheduler.py 유닛 테스트
- _parse_cron 파싱
- _get_sync_gw_id 관리자 ID 반환
- start_scheduler / stop_scheduler 동작
- GW_SYNC_ENABLED=false 시 미시작
- apscheduler 미설치 시 경고만 출력
- run_sync 중복 실행 방지
"""

import threading
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def reset_scheduler():
    """매 테스트마다 스케줄러 상태 초기화"""
    import src.fund_table.scheduler as mod
    mod._scheduler = None
    mod.sync_running.clear()
    yield
    mod._scheduler = None
    mod.sync_running.clear()


@pytest.fixture
def sched():
    """scheduler 모듈"""
    import src.fund_table.scheduler as mod
    return mod


# ─────────────────────────────────────────
# _parse_cron 테스트
# ─────────────────────────────────────────

class TestParseCron:
    def test_default_cron(self, sched):
        """기본 cron 표현식 파싱"""
        result = sched._parse_cron("0 8 * * *")
        assert result == {
            "minute": "0",
            "hour": "8",
            "day": "*",
            "month": "*",
            "day_of_week": "*",
        }

    def test_complex_cron(self, sched):
        """복잡한 cron 표현식"""
        result = sched._parse_cron("30 6,18 1-15 1,7 mon-fri")
        assert result["minute"] == "30"
        assert result["hour"] == "6,18"
        assert result["day"] == "1-15"

    def test_invalid_cron_too_few_fields(self, sched):
        """필드 수 부족 시 ValueError"""
        with pytest.raises(ValueError, match="5개 필드"):
            sched._parse_cron("0 8 *")

    def test_invalid_cron_too_many_fields(self, sched):
        """필드 수 초과 시 ValueError"""
        with pytest.raises(ValueError, match="5개 필드"):
            sched._parse_cron("0 8 * * * *")


# ─────────────────────────────────────────
# _get_sync_gw_id 테스트
# ─────────────────────────────────────────

class TestGetSyncGwId:
    def test_from_admin_gw_ids(self, sched, monkeypatch):
        """ADMIN_GW_IDS에서 첫 번째 ID 반환"""
        monkeypatch.setenv("ADMIN_GW_IDS", "tgjeon,kimcs")
        assert sched._get_sync_gw_id() == "tgjeon"

    def test_from_admin_gw_id_fallback(self, sched, monkeypatch):
        """ADMIN_GW_IDS 없으면 ADMIN_GW_ID 폴백"""
        monkeypatch.delenv("ADMIN_GW_IDS", raising=False)
        monkeypatch.setenv("ADMIN_GW_ID", "admin1")
        assert sched._get_sync_gw_id() == "admin1"

    def test_empty_when_no_env(self, sched, monkeypatch):
        """환경변수 없으면 빈 문자열"""
        monkeypatch.delenv("ADMIN_GW_IDS", raising=False)
        monkeypatch.delenv("ADMIN_GW_ID", raising=False)
        assert sched._get_sync_gw_id() == ""


# ─────────────────────────────────────────
# start_scheduler 테스트
# ─────────────────────────────────────────

class TestStartScheduler:
    def test_disabled_by_env(self, sched, monkeypatch):
        """GW_SYNC_ENABLED=false면 스케줄러 미시작"""
        monkeypatch.setenv("GW_SYNC_ENABLED", "false")
        sched.start_scheduler()
        assert sched._scheduler is None

    def test_disabled_by_no(self, sched, monkeypatch):
        """GW_SYNC_ENABLED=no도 비활성화"""
        monkeypatch.setenv("GW_SYNC_ENABLED", "no")
        sched.start_scheduler()
        assert sched._scheduler is None

    def test_apscheduler_import_error(self, sched, monkeypatch):
        """apscheduler 미설치 시 ImportError 처리 (경고만 출력, 에러 안 남)"""
        monkeypatch.setenv("GW_SYNC_ENABLED", "true")
        # apscheduler import를 실패하도록 모킹
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "apscheduler" in name:
                raise ImportError("No module named 'apscheduler'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            sched.start_scheduler()  # 에러 없이 종료
        assert sched._scheduler is None


# ─────────────────────────────────────────
# stop_scheduler 테스트
# ─────────────────────────────────────────

class TestStopScheduler:
    def test_stop_when_none(self, sched):
        """스케줄러 없을 때 stop 호출 → 에러 없음"""
        sched._scheduler = None
        sched.stop_scheduler()
        assert sched._scheduler is None

    def test_stop_when_running(self, sched):
        """스케줄러가 있을 때 shutdown 호출"""
        mock_scheduler = MagicMock()
        sched._scheduler = mock_scheduler
        sched.stop_scheduler()
        mock_scheduler.shutdown.assert_called_once_with(wait=False)
        assert sched._scheduler is None


# ─────────────────────────────────────────
# run_sync 중복 실행 방지 테스트
# ─────────────────────────────────────────

class TestRunSync:
    def test_skip_when_already_running(self, sched):
        """이미 실행 중이면 건너뜀"""
        sched.sync_running.set()
        # run_sync 내부에서 즉시 return해야 함
        sched.run_sync()
        # 여전히 set 상태 (clear 호출 안 됨 = 내부 로직 미진입)
        assert sched.sync_running.is_set()

    def test_clears_flag_on_no_admin(self, sched, monkeypatch):
        """관리자 ID 없으면 플래그 해제 후 종료"""
        monkeypatch.delenv("ADMIN_GW_IDS", raising=False)
        monkeypatch.delenv("ADMIN_GW_ID", raising=False)
        sched.run_sync()
        assert not sched.sync_running.is_set()
