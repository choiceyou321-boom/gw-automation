"""GW 자격 증명 검증 함수 단위 테스트

validate_gw_credentials()는 Playwright를 사용하므로
login_and_get_context를 mock하여 테스트한다.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestValidateGwCredentials:
    """validate_gw_credentials() 함수 테스트"""

    @patch("src.shared.auth.login.sync_playwright")
    @patch("src.shared.auth.login.login_and_get_context")
    @patch("src.shared.auth.login.close_session")
    def test_valid_credentials(self, mock_close, mock_login, mock_pw):
        """유효한 자격 증명 → valid=True, 리소스 정리 확인"""
        from src.shared.auth.login import validate_gw_credentials

        mock_pw_instance = MagicMock()
        mock_pw.return_value.start.return_value = mock_pw_instance
        mock_login.return_value = (MagicMock(), MagicMock(), MagicMock())

        result = validate_gw_credentials("testuser", "testpw")

        assert result["valid"] is True
        assert result["error"] is None
        mock_login.assert_called_once()
        mock_close.assert_called()
        mock_pw_instance.stop.assert_called_once()

    @patch("src.shared.auth.login.sync_playwright")
    @patch("src.shared.auth.login.login_and_get_context")
    def test_invalid_credentials_login_failure(self, mock_login, mock_pw):
        """잘못된 자격 증명 (RuntimeError) → valid=False"""
        from src.shared.auth.login import validate_gw_credentials

        mock_pw_instance = MagicMock()
        mock_pw.return_value.start.return_value = mock_pw_instance
        mock_login.side_effect = RuntimeError("로그인 실패 - data/debug_login_failed.png 확인")

        result = validate_gw_credentials("baduser", "badpw")

        assert result["valid"] is False
        assert "로그인 실패" in result["error"]

    @patch("src.shared.auth.login.sync_playwright")
    @patch("src.shared.auth.login.login_and_get_context")
    def test_gw_server_connection_error(self, mock_login, mock_pw):
        """GW 서버 연결 실패 (일반 Exception) → valid=False"""
        from src.shared.auth.login import validate_gw_credentials

        mock_pw_instance = MagicMock()
        mock_pw.return_value.start.return_value = mock_pw_instance
        mock_login.side_effect = Exception("Connection refused")

        result = validate_gw_credentials("user", "pw")

        assert result["valid"] is False
        assert "GW 서버 연결 실패" in result["error"]

    @patch("src.shared.auth.login.sync_playwright")
    @patch("src.shared.auth.login.login_and_get_context")
    def test_playwright_cleanup_on_failure(self, mock_login, mock_pw):
        """실패 시에도 Playwright 정리 보장"""
        from src.shared.auth.login import validate_gw_credentials

        mock_pw_instance = MagicMock()
        mock_pw.return_value.start.return_value = mock_pw_instance
        mock_login.side_effect = RuntimeError("로그인 실패")

        validate_gw_credentials("user", "pw")

        # pw.stop()이 호출되었는지 확인
        mock_pw_instance.stop.assert_called_once()

    @patch("src.shared.auth.login._validation_semaphore")
    def test_semaphore_timeout(self, mock_sem):
        """세마포어 획득 실패 → valid=False, 대기 시간 초과 메시지"""
        from src.shared.auth.login import validate_gw_credentials

        mock_sem.acquire.return_value = False  # 타임아웃 시뮬레이션

        result = validate_gw_credentials("user", "pw")

        assert result["valid"] is False
        assert "대기 시간 초과" in result["error"]

    @patch("src.shared.auth.login.sync_playwright")
    @patch("src.shared.auth.login.login_and_get_context")
    def test_id_field_not_found(self, mock_login, mock_pw):
        """GW 페이지 구조 변경 (ID 필드 없음) → 서버 연결 실패 메시지"""
        from src.shared.auth.login import validate_gw_credentials

        mock_pw_instance = MagicMock()
        mock_pw.return_value.start.return_value = mock_pw_instance
        mock_login.side_effect = RuntimeError("ID 입력 필드(#reqLoginId)를 찾을 수 없습니다")

        result = validate_gw_credentials("user", "pw")

        assert result["valid"] is False
        assert "입력 필드" in result["error"]


class TestGwErrorToUserMessage:
    """gw_error_to_user_message() 함수 테스트"""

    def test_login_failure_message(self):
        from src.shared.auth.login import gw_error_to_user_message
        msg = gw_error_to_user_message("로그인 실패 - data/debug_login_failed.png 확인")
        assert "아이디 또는 비밀번호" in msg

    def test_server_connection_message(self):
        from src.shared.auth.login import gw_error_to_user_message
        msg = gw_error_to_user_message("GW 서버 연결 실패: Connection refused")
        assert "서버에 연결할 수 없습니다" in msg

    def test_input_field_message(self):
        from src.shared.auth.login import gw_error_to_user_message
        msg = gw_error_to_user_message("ID 입력 필드(#reqLoginId)를 찾을 수 없습니다")
        assert "서버에 연결할 수 없습니다" in msg

    def test_semaphore_timeout_message(self):
        from src.shared.auth.login import gw_error_to_user_message
        msg = gw_error_to_user_message("GW 검증 대기 시간 초과 (다른 검증이 진행 중)")
        assert "다른 사용자" in msg

    def test_empty_error(self):
        from src.shared.auth.login import gw_error_to_user_message
        msg = gw_error_to_user_message("")
        assert "인증에 실패" in msg

    def test_unknown_error(self):
        from src.shared.auth.login import gw_error_to_user_message
        msg = gw_error_to_user_message("알 수 없는 오류 XYZ")
        assert "XYZ" in msg
