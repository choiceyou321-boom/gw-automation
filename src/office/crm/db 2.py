"""
CRM SQLite 저장소.

연락처(contacts) 테이블 1개로 단순 구성. 향후 멀티 테넌트 분리 시
owner_gw_id 컬럼이 tenant_id 역할.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from src.office.crm.models import BusinessCard, Contact

_DB_DIR = Path(__file__).resolve().parents[3] / "data"
DEFAULT_DB_PATH = _DB_DIR / "crm.db"

_init_lock = threading.Lock()
_initialized_paths: set[str] = set()


def _utc_now_iso() -> str:
    """timezone-aware UTC now → ISO string (Z 접미사 없이 +00:00 형식)."""
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """SQLite 연결 + 최초 1회 스키마 보장.

    db_path가 None이면 모듈 변수 DEFAULT_DB_PATH를 동적으로 조회한다.
    (default 인자에 모듈 변수를 직접 쓰면 monkeypatch가 안 먹기 때문)
    """
    path = Path(db_path if db_path is not None else DEFAULT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    with _init_lock:
        if str(path) not in _initialized_paths:
            _ensure_schema(conn)
            _initialized_paths.add(str(path))
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            company TEXT NOT NULL DEFAULT '',
            department TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            phone_mobile TEXT NOT NULL DEFAULT '',
            phone_office TEXT NOT NULL DEFAULT '',
            fax TEXT NOT NULL DEFAULT '',
            address TEXT NOT NULL DEFAULT '',
            website TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            tags_json TEXT NOT NULL DEFAULT '[]',
            owner_gw_id TEXT NOT NULL DEFAULT '',
            google_resource_name TEXT NOT NULL DEFAULT '',
            project_codes_json TEXT NOT NULL DEFAULT '[]',
            image_path TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_contacts_owner ON contacts(owner_gw_id);
        CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email);
        CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(phone_mobile);
        CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company);
        """
    )
    conn.commit()


def _row_to_contact(row: sqlite3.Row) -> Contact:
    return Contact(
        id=row["id"],
        name=row["name"], company=row["company"],
        department=row["department"], title=row["title"],
        email=row["email"],
        phone_mobile=row["phone_mobile"], phone_office=row["phone_office"],
        fax=row["fax"], address=row["address"], website=row["website"],
        note=row["note"],
        tags=json.loads(row["tags_json"] or "[]"),
        owner_gw_id=row["owner_gw_id"],
        google_resource_name=row["google_resource_name"],
        project_codes=json.loads(row["project_codes_json"] or "[]"),
        image_path=row["image_path"],
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
    )


def insert_contact(
    card: BusinessCard,
    owner_gw_id: str = "",
    note: str = "",
    tags: Iterable[str] | None = None,
    project_codes: Iterable[str] | None = None,
    db_path: Path | str | None = None,
) -> int:
    """BusinessCard → contacts 테이블 INSERT. id 반환."""
    now = _utc_now_iso()
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO contacts (
                name, company, department, title, email,
                phone_mobile, phone_office, fax, address, website,
                note, tags_json, owner_gw_id, google_resource_name,
                project_codes_json, image_path, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card.name, card.company, card.department, card.title, card.email,
                card.phone_mobile, card.phone_office, card.fax, card.address, card.website,
                note, json.dumps(list(tags or []), ensure_ascii=False),
                owner_gw_id, "",
                json.dumps(list(project_codes or []), ensure_ascii=False),
                card.image_path, now, now,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def get_contact(contact_id: int, db_path: Path | str | None = None) -> Optional[Contact]:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
        return _row_to_contact(row) if row else None
    finally:
        conn.close()


def list_contacts(
    owner_gw_id: Optional[str] = None,
    company: Optional[str] = None,
    limit: int = 100,
    db_path: Path | str | None = None,
) -> list[Contact]:
    conn = _connect(db_path)
    try:
        clauses, params = [], []
        if owner_gw_id is not None:
            clauses.append("owner_gw_id = ?")
            params.append(owner_gw_id)
        if company is not None:
            clauses.append("company LIKE ?")
            params.append(f"%{company}%")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM contacts {where} ORDER BY updated_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [_row_to_contact(r) for r in rows]
    finally:
        conn.close()


def update_contact_google_resource(
    contact_id: int,
    resource_name: str,
    db_path: Path | str | None = None,
) -> None:
    """Google Contacts 동기화 후 resource_name 기록."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE contacts SET google_resource_name = ?, updated_at = ? WHERE id = ?",
            (resource_name, _utc_now_iso(), contact_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_contact(contact_id: int, db_path: Path | str | None = None) -> bool:
    conn = _connect(db_path)
    try:
        cur = conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def find_duplicate(
    name: str,
    phone_mobile: str = "",
    email: str = "",
    db_path: Path | str | None = None,
) -> Optional[Contact]:
    """동일 이름 + (휴대폰 또는 이메일) 일치 시 기존 연락처 반환."""
    if not name or (not phone_mobile and not email):
        return None
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM contacts WHERE name = ? AND (phone_mobile = ? OR email = ?)",
            (name, phone_mobile or "_", email or "_"),
        ).fetchall()
        return _row_to_contact(rows[0]) if rows else None
    finally:
        conn.close()
