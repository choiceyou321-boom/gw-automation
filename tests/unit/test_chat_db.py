"""
chat_db.py 유닛 테스트
- 세션 생성/조회/삭제
- 메시지 저장/조회
- 미지원 요청 로그
"""

import pytest


@pytest.fixture
def chat_db(tmp_path, monkeypatch):
    """격리된 chat_db 모듈 (임시 DB)"""
    import src.chatbot.chat_db as mod
    monkeypatch.setattr(mod, "_db_initialized", False)
    monkeypatch.setattr(mod, "DB_PATH", tmp_path / "chat.db")
    monkeypatch.setattr(mod, "DATA_DIR", tmp_path)
    return mod


# ─────────────────────────────────────────
# 세션 관리
# ─────────────────────────────────────────

class TestSession:
    def test_get_or_create_session_new(self, chat_db):
        """신규 세션 생성"""
        session = chat_db.get_or_create_session("user1", "sess1", "첫번째 대화")
        assert session["session_id"] == "sess1"
        assert session["gw_id"] == "user1"
        assert session["title"] == "첫번째 대화"

    def test_get_or_create_session_existing(self, chat_db):
        """기존 세션 반환"""
        chat_db.get_or_create_session("user1", "sess1", "원래제목")
        session = chat_db.get_or_create_session("user1", "sess1", "새제목")
        # 기존 세션이 반환되므로 제목 변경 없음
        assert session["title"] == "원래제목"

    def test_list_sessions(self, chat_db):
        """세션 목록 조회"""
        chat_db.get_or_create_session("user1", "sess1", "대화1")
        chat_db.get_or_create_session("user1", "sess2", "대화2")
        sessions = chat_db.list_sessions("user1")
        assert len(sessions) == 2

    def test_list_sessions_empty(self, chat_db):
        """세션 없는 사용자"""
        sessions = chat_db.list_sessions("nobody")
        assert sessions == []

    def test_delete_session(self, chat_db):
        """세션 삭제"""
        chat_db.get_or_create_session("user1", "sess1")
        result = chat_db.delete_session("user1", "sess1")
        assert result["success"] is True
        sessions = chat_db.list_sessions("user1")
        assert len(sessions) == 0

    def test_delete_session_nonexistent(self, chat_db):
        """존재하지 않는 세션 삭제"""
        result = chat_db.delete_session("user1", "nosess")
        assert result["success"] is False

    def test_update_session_title(self, chat_db):
        """세션 제목 업데이트"""
        chat_db.get_or_create_session("user1", "sess1", "원래제목")
        result = chat_db.update_session_title("user1", "sess1", "새로운제목")
        assert result["success"] is True


# ─────────────────────────────────────────
# 메시지 저장/조회
# ─────────────────────────────────────────

class TestMessages:
    def test_save_and_get_messages(self, chat_db):
        """메시지 저장 및 조회"""
        chat_db.get_or_create_session("user1", "sess1")
        chat_db.save_message("user1", "sess1", "user", "안녕하세요")
        chat_db.save_message("user1", "sess1", "assistant", "안녕하세요! 무엇을 도와드릴까요?")

        history = chat_db.get_session_history("user1", "sess1")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "안녕하세요"
        assert history[1]["role"] == "assistant"

    def test_message_with_action(self, chat_db):
        """액션 포함 메시지"""
        chat_db.get_or_create_session("user1", "sess1")
        chat_db.save_message(
            "user1", "sess1", "assistant", "회의실을 예약했습니다.",
            action="reserve_meeting_room",
            action_result='{"success": true}'
        )
        history = chat_db.get_session_history("user1", "sess1")
        assert history[0]["action"] == "reserve_meeting_room"

    def test_message_with_file_count(self, chat_db):
        """파일 첨부 메시지"""
        chat_db.get_or_create_session("user1", "sess1")
        chat_db.save_message("user1", "sess1", "user", "이 파일 분석해주세요", file_count=2)
        history = chat_db.get_session_history("user1", "sess1")
        assert history[0]["file_count"] == 2

    def test_get_history_limit(self, chat_db):
        """메시지 조회 제한"""
        chat_db.get_or_create_session("user1", "sess1")
        for i in range(50):
            chat_db.save_message("user1", "sess1", "user", f"메시지 {i}")

        history = chat_db.get_session_history("user1", "sess1", limit=10)
        assert len(history) == 10
        # 최신 10개가 시간순으로 반환
        assert history[0]["content"] == "메시지 40"
        assert history[-1]["content"] == "메시지 49"

    def test_empty_history(self, chat_db):
        """빈 세션 히스토리"""
        history = chat_db.get_session_history("user1", "nosess")
        assert history == []

    def test_delete_session_removes_messages(self, chat_db):
        """세션 삭제 시 메시지도 삭제"""
        chat_db.get_or_create_session("user1", "sess1")
        chat_db.save_message("user1", "sess1", "user", "테스트")
        chat_db.delete_session("user1", "sess1")
        history = chat_db.get_session_history("user1", "sess1")
        assert history == []


# ─────────────────────────────────────────
# 미지원 요청 로그
# ─────────────────────────────────────────

class TestUnsupportedRequests:
    def test_save_and_list(self, chat_db):
        """미지원 요청 저장 및 조회"""
        chat_db.save_unsupported_request("user1", "unknown_action", "이걸 해주세요", "상세 내용")
        requests = chat_db.list_unsupported_requests()
        assert len(requests) == 1
        assert requests[0]["gw_id"] == "user1"
        assert requests[0]["request_type"] == "unknown_action"

    def test_delete_unsupported_request(self, chat_db):
        """미지원 요청 삭제"""
        chat_db.save_unsupported_request("user1", "test", "테스트 요청")
        requests = chat_db.list_unsupported_requests()
        assert chat_db.delete_unsupported_request(requests[0]["id"]) is True

    def test_delete_nonexistent_request(self, chat_db):
        """존재하지 않는 요청 삭제"""
        assert chat_db.delete_unsupported_request(9999) is False
