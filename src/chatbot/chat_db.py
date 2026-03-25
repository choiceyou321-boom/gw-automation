"""
대화 히스토리 DB 모듈 (SQLite)
- 세션 관리, 메시지 저장/조회
- user_db.py의 _get_db() 패턴 참고
"""

import sqlite3
import logging
from pathlib import Path
from datetime import datetime

# 프로젝트 경로
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "chatbot"

logger = logging.getLogger("chat_db")

DB_PATH = DATA_DIR / "chat_history.db"


_db_initialized = False


def _get_db() -> sqlite3.Connection:
    """SQLite 연결 반환 + 테이블 자동 생성 (최초 1회)"""
    global _db_initialized
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    if not _db_initialized:
        # 세션 테이블
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT,
                gw_id TEXT,
                title TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (gw_id, session_id)
            )
        """)

        # 메시지 테이블
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                gw_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                action TEXT,
                action_result TEXT,
                file_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # messages 조회 성능을 위한 인덱스
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages (gw_id, session_id, id)
        """)
        conn.commit()
        _db_initialized = True

    return conn


def save_message(
    gw_id: str,
    session_id: str,
    role: str,
    content: str,
    action: str = None,
    action_result: str = None,
    file_count: int = 0,
):
    """메시지 저장 (user 또는 assistant)"""
    conn = _get_db()
    try:
        conn.execute(
            """INSERT INTO messages (session_id, gw_id, role, content, action, action_result, file_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, gw_id, role, content, action, action_result, file_count),
        )
        # 세션의 updated_at 갱신
        conn.execute(
            """UPDATE sessions SET updated_at = CURRENT_TIMESTAMP
               WHERE gw_id = ? AND session_id = ?""",
            (gw_id, session_id),
        )
        conn.commit()
        logger.debug(f"메시지 저장: {gw_id}/{session_id} ({role})")
    finally:
        conn.close()


def get_session_history(gw_id: str, session_id: str, limit: int = 40) -> list[dict]:
    """세션의 최신 메시지 조회 (limit개)"""
    conn = _get_db()
    try:
        # 최신 limit개를 가져오되, 시간순 정렬
        rows = conn.execute(
            """SELECT role, content, action, action_result, file_count, created_at
               FROM messages
               WHERE gw_id = ? AND session_id = ?
               ORDER BY id DESC
               LIMIT ?""",
            (gw_id, session_id, limit),
        ).fetchall()
        # 역순으로 뒤집어서 시간순 반환
        result = [dict(row) for row in reversed(rows)]
        return result
    finally:
        conn.close()


def list_sessions(gw_id: str) -> list[dict]:
    """
    사용자의 세션 목록 (최신순)
    각 세션의 마지막 메시지 미리보기 포함
    """
    conn = _get_db()
    try:
        rows = conn.execute(
            """SELECT s.session_id, s.title, s.created_at, s.updated_at,
                      (SELECT content FROM messages m
                       WHERE m.gw_id = s.gw_id AND m.session_id = s.session_id
                       ORDER BY m.id DESC LIMIT 1) AS last_message
               FROM sessions s
               WHERE s.gw_id = ?
               ORDER BY s.updated_at DESC""",
            (gw_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def delete_session(gw_id: str, session_id: str) -> dict:
    """세션 + 메시지 삭제"""
    conn = _get_db()
    try:
        # 존재 여부 확인
        existing = conn.execute(
            "SELECT session_id FROM sessions WHERE gw_id = ? AND session_id = ?",
            (gw_id, session_id),
        ).fetchone()
        if not existing:
            return {"success": False, "message": "존재하지 않는 세션입니다."}

        # 메시지 삭제
        conn.execute(
            "DELETE FROM messages WHERE gw_id = ? AND session_id = ?",
            (gw_id, session_id),
        )
        # 세션 삭제
        conn.execute(
            "DELETE FROM sessions WHERE gw_id = ? AND session_id = ?",
            (gw_id, session_id),
        )
        conn.commit()
        logger.info(f"세션 삭제: {gw_id}/{session_id}")
        return {"success": True, "message": "대화가 삭제되었습니다."}
    finally:
        conn.close()


def get_or_create_session(gw_id: str, session_id: str, title: str = "") -> dict:
    """세션 조회 또는 생성. 세션 정보 dict 반환."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT session_id, gw_id, title, created_at, updated_at FROM sessions WHERE gw_id = ? AND session_id = ?",
            (gw_id, session_id),
        ).fetchone()

        if row:
            return dict(row)

        # 신규 세션 생성
        conn.execute(
            "INSERT INTO sessions (session_id, gw_id, title) VALUES (?, ?, ?)",
            (session_id, gw_id, title),
        )
        conn.commit()
        logger.info(f"세션 생성: {gw_id}/{session_id}")

        row = conn.execute(
            "SELECT session_id, gw_id, title, created_at, updated_at FROM sessions WHERE gw_id = ? AND session_id = ?",
            (gw_id, session_id),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def update_session_title(gw_id: str, session_id: str, title: str) -> dict:
    """세션 제목 업데이트"""
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE sessions SET title = ? WHERE gw_id = ? AND session_id = ?",
            (title, gw_id, session_id),
        )
        conn.commit()
        logger.info(f"세션 제목 업데이트: {gw_id}/{session_id} → {title}")
        return {"success": True, "message": "세션 제목이 업데이트되었습니다."}
    finally:
        conn.close()


# ─────────────────────────────────────────
# 미지원 요청 로그
# ─────────────────────────────────────────

def _ensure_unsupported_table(conn: sqlite3.Connection):
    """미지원 요청 테이블 생성 (없으면)"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS unsupported_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gw_id TEXT NOT NULL,
            request_type TEXT NOT NULL,
            user_message TEXT NOT NULL,
            detail TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_unsupported_created
        ON unsupported_requests (created_at DESC)
    """)
    conn.commit()


def save_unsupported_request(
    gw_id: str,
    request_type: str,
    user_message: str,
    detail: str = "",
) -> None:
    """미지원 요청 기록 저장"""
    conn = _get_db()
    try:
        _ensure_unsupported_table(conn)
        conn.execute(
            """INSERT INTO unsupported_requests (gw_id, request_type, user_message, detail)
               VALUES (?, ?, ?, ?)""",
            (gw_id, request_type, user_message, detail),
        )
        conn.commit()
        logger.info(f"미지원 요청 기록: {gw_id} → {request_type} ({detail})")
    finally:
        conn.close()


def list_unsupported_requests(limit: int = 200) -> list[dict]:
    """미지원 요청 목록 조회 (최신순)"""
    conn = _get_db()
    try:
        _ensure_unsupported_table(conn)
        rows = conn.execute(
            """SELECT id, gw_id, request_type, user_message, detail, created_at
               FROM unsupported_requests
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def delete_unsupported_request(request_id: int) -> bool:
    """미지원 요청 단건 삭제"""
    conn = _get_db()
    try:
        _ensure_unsupported_table(conn)
        cursor = conn.execute(
            "DELETE FROM unsupported_requests WHERE id = ?", (request_id,)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
