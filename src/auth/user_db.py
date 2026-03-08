"""
사용자 DB 모듈 (SQLite + Fernet 암호화)
- 회원가입, 로그인 검증, 프로필 관리
- GW 비밀번호는 Fernet 대칭 암호화 (Playwright 로그인에 복호화 필요)
- approval_config: 사용자별 결재선 설정 (JSON)
"""

import os
import json
import sqlite3
import logging
from pathlib import Path
from cryptography.fernet import Fernet
from dotenv import load_dotenv

# 프로젝트 경로
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"

load_dotenv(CONFIG_DIR / ".env")

logger = logging.getLogger("user_db")

DB_PATH = DATA_DIR / "users.db"


def _get_fernet() -> Fernet:
    """Fernet 인스턴스 반환. ENCRYPTION_KEY 없으면 자동 생성."""
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        key = Fernet.generate_key().decode()
        # .env에 자동 추가
        env_path = CONFIG_DIR / ".env"
        with open(env_path, "a", encoding="utf-8") as f:
            f.write(f"\n# 사용자 비밀번호 암호화 키 (자동 생성)\nENCRYPTION_KEY={key}\n")
        os.environ["ENCRYPTION_KEY"] = key
        logger.info("ENCRYPTION_KEY 자동 생성 완료")
    return Fernet(key.encode() if isinstance(key, str) else key)


def _get_db() -> sqlite3.Connection:
    """SQLite 연결 반환 + 테이블 자동 생성"""
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            gw_id TEXT PRIMARY KEY,
            gw_pw_encrypted TEXT NOT NULL,
            name TEXT NOT NULL,
            position TEXT DEFAULT '',
            emp_seq TEXT DEFAULT '',
            dept_seq TEXT DEFAULT '',
            email_addr TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 기존 테이블에 approval_config 컬럼 추가 (없으면 추가, 있으면 무시)
    try:
        conn.execute("ALTER TABLE users ADD COLUMN approval_config TEXT DEFAULT ''")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e):
            raise  # 예상치 못한 DB 오류는 재발생
    conn.commit()
    return conn


def register(gw_id: str, gw_pw: str, name: str, position: str = "") -> dict:
    """
    사용자 등록.
    반환: {"success": bool, "message": str}
    """
    conn = _get_db()
    try:
        # 중복 체크
        existing = conn.execute(
            "SELECT gw_id FROM users WHERE gw_id = ?", (gw_id,)
        ).fetchone()
        if existing:
            return {"success": False, "message": "이미 등록된 아이디입니다."}

        # 비밀번호 암호화
        fernet = _get_fernet()
        encrypted_pw = fernet.encrypt(gw_pw.encode()).decode()

        conn.execute(
            "INSERT INTO users (gw_id, gw_pw_encrypted, name, position) VALUES (?, ?, ?, ?)",
            (gw_id, encrypted_pw, name, position),
        )
        conn.commit()
        logger.info(f"사용자 등록 완료: {gw_id} ({name})")
        return {"success": True, "message": "회원가입이 완료되었습니다."}
    finally:
        conn.close()


def verify_login(gw_id: str, gw_pw: str) -> dict | None:
    """
    로그인 검증. 비밀번호 일치 시 사용자 정보 반환.
    반환: {"gw_id", "name", "position", ...} 또는 None
    """
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE gw_id = ?", (gw_id,)
        ).fetchone()
        if not row:
            return None

        fernet = _get_fernet()
        try:
            decrypted = fernet.decrypt(row["gw_pw_encrypted"].encode()).decode()
        except Exception:
            logger.error(f"비밀번호 복호화 실패: {gw_id}")
            return None

        if decrypted != gw_pw:
            return None

        return {
            "gw_id": row["gw_id"],
            "name": row["name"],
            "position": row["position"],
            "emp_seq": row["emp_seq"],
            "dept_seq": row["dept_seq"],
            "email_addr": row["email_addr"],
            "approval_config": row["approval_config"] or "",
        }
    finally:
        conn.close()


def get_user(gw_id: str) -> dict | None:
    """사용자 정보 조회 (비밀번호 제외)"""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT gw_id, name, position, emp_seq, dept_seq, email_addr, approval_config FROM users WHERE gw_id = ?",
            (gw_id,),
        ).fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()


def update_profile(gw_id: str, **kwargs) -> dict:
    """
    프로필 업데이트. 허용 필드: name, position, emp_seq, dept_seq, email_addr
    반환: {"success": bool, "message": str}
    """
    allowed = {"name", "position", "emp_seq", "dept_seq", "email_addr"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}

    if not updates:
        return {"success": False, "message": "업데이트할 항목이 없습니다."}

    conn = _get_db()
    try:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [gw_id]
        conn.execute(
            f"UPDATE users SET {set_clause} WHERE gw_id = ?", values
        )
        conn.commit()
        logger.info(f"프로필 업데이트: {gw_id} → {updates}")
        return {"success": True, "message": "프로필이 업데이트되었습니다."}
    finally:
        conn.close()


def get_decrypted_password(gw_id: str) -> str | None:
    """GW 비밀번호 복호화 반환 (Playwright 로그인용)"""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT gw_pw_encrypted FROM users WHERE gw_id = ?", (gw_id,)
        ).fetchone()
        if not row:
            return None
        fernet = _get_fernet()
        return fernet.decrypt(row["gw_pw_encrypted"].encode()).decode()
    finally:
        conn.close()


def list_users() -> list[dict]:
    """전체 사용자 목록 (비밀번호 제외)"""
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT gw_id, name, position, emp_seq, dept_seq, email_addr, created_at FROM users ORDER BY created_at"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def delete_user(gw_id: str) -> dict:
    """사용자 삭제. 반환: {"success": bool, "message": str}"""
    conn = _get_db()
    try:
        existing = conn.execute("SELECT gw_id FROM users WHERE gw_id = ?", (gw_id,)).fetchone()
        if not existing:
            return {"success": False, "message": "존재하지 않는 사용자입니다."}
        conn.execute("DELETE FROM users WHERE gw_id = ?", (gw_id,))
        conn.commit()
        logger.info(f"사용자 삭제: {gw_id}")
        return {"success": True, "message": f"사용자 '{gw_id}'가 삭제되었습니다."}
    finally:
        conn.close()


def get_approval_config(gw_id: str) -> dict:
    """
    사용자별 결재선 설정 조회.
    반환 예시: {"default": {"agree": "신동관", "final": "최기영"}, "간단": {"final": "최기영"}}
    설정이 없으면 빈 dict 반환.
    """
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT approval_config FROM users WHERE gw_id = ?", (gw_id,)
        ).fetchone()
        if not row or not row["approval_config"]:
            return {}
        try:
            return json.loads(row["approval_config"])
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"approval_config JSON 파싱 실패: {gw_id}")
            return {}
    finally:
        conn.close()


def set_approval_config(gw_id: str, config: dict) -> dict:
    """
    사용자별 결재선 설정 저장.
    config 예시: {"default": {"agree": "신동관", "final": "최기영"}}
    반환: {"success": bool, "message": str}
    """
    conn = _get_db()
    try:
        existing = conn.execute(
            "SELECT gw_id FROM users WHERE gw_id = ?", (gw_id,)
        ).fetchone()
        if not existing:
            return {"success": False, "message": "존재하지 않는 사용자입니다."}

        config_json = json.dumps(config, ensure_ascii=False)
        conn.execute(
            "UPDATE users SET approval_config = ? WHERE gw_id = ?",
            (config_json, gw_id),
        )
        conn.commit()
        logger.info(f"결재선 설정 저장: {gw_id} → {config}")
        return {"success": True, "message": "결재선 설정이 저장되었습니다."}
    finally:
        conn.close()


def get_company_info(gw_id: str) -> dict:
    """사용자의 companyInfo 반환 (API 호출용)"""
    user = get_user(gw_id)
    if not user:
        return {}

    info = {
        "compSeq": "1000",
        "groupSeq": "gcmsAmaranth36068",
        "deptSeq": user.get("dept_seq") or "2017",
        "emailAddr": user.get("email_addr") or gw_id,
        "emailDomain": "glowseoul.co.kr",
    }
    # empSeq가 있으면 포함 (예약 생성에 필수)
    if user.get("emp_seq"):
        info["empSeq"] = user["emp_seq"]
    return info
