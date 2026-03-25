"""
프로젝트 관리 SQLite DB 모듈
- 프로젝트별 관리표, 하도급상세, 연락처, 공종 관리
- GW 스크래핑 데이터 저장 (이체완료 내역, 예실대비현황)
"""

import json
import sqlite3
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("fund_db")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "fund_management.db"


import threading

_db_initialized = False
_db_init_lock = threading.Lock()


def get_db() -> sqlite3.Connection:
    """SQLite 연결 반환 + 테이블 자동 생성 (최초 1회, 스레드 안전)"""
    global _db_initialized
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    if not _db_initialized:
        with _db_init_lock:
            if not _db_initialized:
                _create_tables(conn)
                _db_initialized = True

    return conn


def _create_tables(conn: sqlite3.Connection):
    """테이블 스키마 생성"""
    conn.executescript("""
        -- 프로젝트 목록
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            design_amount INTEGER DEFAULT 0,
            construction_amount INTEGER DEFAULT 0,
            execution_budget INTEGER DEFAULT 0,
            profit_amount INTEGER DEFAULT 0,
            profit_rate REAL DEFAULT 0,
            status TEXT DEFAULT 'active',
            grade TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            owner_gw_id TEXT DEFAULT '',
            project_code TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- 프로젝트별 공종 (사용자가 프로젝트마다 다르게 추가)
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            UNIQUE(project_id, name)
        );

        -- 하도급 상세 (공종별 업체 정보)
        CREATE TABLE IF NOT EXISTS subcontracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            trade_id INTEGER,
            company_name TEXT NOT NULL,
            account_category TEXT DEFAULT '',
            has_estimate INTEGER DEFAULT 0,
            has_contract INTEGER DEFAULT 0,
            has_vendor_reg INTEGER DEFAULT 0,
            estimate_amount INTEGER DEFAULT 0,
            contract_amount INTEGER DEFAULT 0,
            payment_1 INTEGER DEFAULT 0,
            payment_2 INTEGER DEFAULT 0,
            payment_3 INTEGER DEFAULT 0,
            payment_4 INTEGER DEFAULT 0,
            remaining_amount INTEGER DEFAULT 0,
            payment_rate REAL DEFAULT 0,
            payment_1_confirmed INTEGER DEFAULT 0,
            payment_2_confirmed INTEGER DEFAULT 0,
            payment_3_confirmed INTEGER DEFAULT 0,
            payment_4_confirmed INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (trade_id) REFERENCES trades(id) ON DELETE SET NULL
        );

        -- 거래처 연락처
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            trade_name TEXT DEFAULT '',
            company_name TEXT NOT NULL,
            contact_person TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        -- 수금현황 (설계/시공 단계별 수금)
        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            stage TEXT NOT NULL,
            amount INTEGER DEFAULT 0,
            collected INTEGER DEFAULT 0,
            collection_date TEXT DEFAULT '',
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        -- 프로젝트 개요 (배정인원, 면적, 이슈, 진행상황 등)
        CREATE TABLE IF NOT EXISTS project_overview (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            project_category TEXT DEFAULT '',
            location TEXT DEFAULT '',
            usage TEXT DEFAULT '',
            scale TEXT DEFAULT '',
            area_pyeong REAL DEFAULT 0,
            design_start TEXT DEFAULT '',
            design_end TEXT DEFAULT '',
            construction_start TEXT DEFAULT '',
            construction_end TEXT DEFAULT '',
            open_date TEXT DEFAULT '',
            current_status TEXT DEFAULT '',
            design_contract_date TEXT DEFAULT '',
            design_contract_amount INTEGER DEFAULT 0,
            construction_contract_date TEXT DEFAULT '',
            construction_contract_amount INTEGER DEFAULT 0,
            issue_design TEXT DEFAULT '',
            issue_schedule TEXT DEFAULT '',
            issue_budget TEXT DEFAULT '',
            issue_operation TEXT DEFAULT '',
            issue_defect TEXT DEFAULT '',
            issue_other TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        -- 프로젝트 배정인원
        CREATE TABLE IF NOT EXISTS project_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            name TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        -- 프로젝트 진행 마일스톤 (체크리스트)
        CREATE TABLE IF NOT EXISTS project_milestones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            completed INTEGER DEFAULT 0,
            date TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        -- GW 이체완료 내역 (스크래핑 데이터, 표시 전용)
        CREATE TABLE IF NOT EXISTS payment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            accounting_unit TEXT DEFAULT '',
            scheduled_date TEXT DEFAULT '',
            confirmed_date TEXT DEFAULT '',
            fund_category TEXT DEFAULT '',
            vendor_code TEXT DEFAULT '',
            vendor_name TEXT DEFAULT '',
            business_number TEXT DEFAULT '',
            bank_name TEXT DEFAULT '',
            account_number TEXT DEFAULT '',
            account_holder TEXT DEFAULT '',
            description TEXT DEFAULT '',
            amount INTEGER DEFAULT 0,
            department TEXT DEFAULT '',
            employee_name TEXT DEFAULT '',
            project_name TEXT DEFAULT '',
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- 프로젝트별 TODO 리스트
        CREATE TABLE IF NOT EXISTS project_todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            content TEXT NOT NULL,
            completed INTEGER DEFAULT 0,
            priority TEXT DEFAULT 'medium',
            category TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        -- AI 인사이트 캐시
        CREATE TABLE IF NOT EXISTS project_insights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            insight_type TEXT DEFAULT 'strategy',
            content TEXT NOT NULL,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        -- 프로젝트 자료실 (파일/텍스트/메모)
        CREATE TABLE IF NOT EXISTS project_materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            material_type TEXT DEFAULT 'file',
            file_name TEXT DEFAULT '',
            file_path TEXT DEFAULT '',
            mime_type TEXT DEFAULT '',
            content_text TEXT DEFAULT '',
            description TEXT DEFAULT '',
            extracted_data TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        -- 프로젝트 알림
        CREATE TABLE IF NOT EXISTS project_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            notification_type TEXT DEFAULT 'info',
            message TEXT NOT NULL,
            read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        -- GW 예실대비현황 (스크래핑 데이터)
        CREATE TABLE IF NOT EXISTS budget_actual (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            project_name TEXT DEFAULT '',
            year INTEGER DEFAULT 0,
            budget_code TEXT DEFAULT '',
            budget_category TEXT DEFAULT '',
            budget_sub_category TEXT DEFAULT '',
            budget_amount INTEGER DEFAULT 0,
            actual_amount INTEGER DEFAULT 0,
            difference INTEGER DEFAULT 0,
            execution_rate REAL DEFAULT 0,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
        );

        -- GW 프로젝트 캐시 (전체 목록을 한번 가져와서 로컬 검색)
        CREATE TABLE IF NOT EXISTS gw_projects_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            start_date TEXT DEFAULT '',
            end_date TEXT DEFAULT '',
            cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- 프로젝트 별칭 (다양한 이름으로 같은 프로젝트를 찾기 위한 메타데이터)
        CREATE TABLE IF NOT EXISTS project_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            alias TEXT NOT NULL,
            alias_type TEXT DEFAULT 'manual',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            UNIQUE(project_id, alias)
        );
    """)
    conn.commit()

    # grade, sort_order, owner_gw_id 컬럼 마이그레이션
    try:
        conn.execute("SELECT grade FROM projects LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE projects ADD COLUMN grade TEXT DEFAULT ''")
        conn.commit()
    try:
        conn.execute("SELECT sort_order FROM projects LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE projects ADD COLUMN sort_order INTEGER DEFAULT 0")
        conn.commit()
    try:
        conn.execute("SELECT owner_gw_id FROM projects LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE projects ADD COLUMN owner_gw_id TEXT DEFAULT ''")
        conn.commit()
    # project_code: GW 사업코드 (예: GS-25-0088)
    try:
        conn.execute("SELECT project_code FROM projects LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE projects ADD COLUMN project_code TEXT DEFAULT ''")
        conn.commit()

    # contacts 테이블에 note, trade_id 컬럼 추가
    try:
        conn.execute("SELECT note FROM contacts LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE contacts ADD COLUMN note TEXT DEFAULT ''")
        conn.commit()
    try:
        conn.execute("SELECT trade_id FROM contacts LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE contacts ADD COLUMN trade_id INTEGER")
        conn.commit()


# ─────────────────────────────────────────
# 프로젝트 CRUD
# ─────────────────────────────────────────

def list_projects() -> list[dict]:
    """전체 프로젝트 목록"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY sort_order ASC, created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_project(project_id: int) -> dict | None:
    """프로젝트 상세"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_project(name: str, **kwargs) -> dict:
    """프로젝트 생성"""
    conn = get_db()
    try:
        fields = ["name"]
        values = [name]
        allowed = [
            "description", "design_amount", "construction_amount",
            "execution_budget", "profit_amount", "profit_rate", "status",
            "grade", "sort_order", "owner_gw_id", "project_code"
        ]
        for k in allowed:
            if k in kwargs and kwargs[k] is not None:
                fields.append(k)
                values.append(kwargs[k])

        placeholders = ", ".join("?" * len(fields))
        field_names = ", ".join(fields)
        cur = conn.execute(
            f"INSERT INTO projects ({field_names}) VALUES ({placeholders})",
            values
        )
        conn.commit()
        project_id = cur.lastrowid
        return {"success": True, "id": project_id, "message": f"프로젝트 '{name}' 생성 완료"}
    except sqlite3.IntegrityError:
        return {"success": False, "message": f"프로젝트 '{name}'이(가) 이미 존재합니다."}
    finally:
        conn.close()


def check_project_owner(project_id: int, gw_id: str) -> bool:
    """프로젝트 소유자 검증. 소유자가 비어있으면 모든 사용자 허용 (하위 호환)"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT owner_gw_id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not row:
            return False
        owner = row["owner_gw_id"]
        return not owner or owner == gw_id
    finally:
        conn.close()


def update_project(project_id: int, **kwargs) -> dict:
    """프로젝트 정보 수정"""
    allowed = [
        "name", "description", "design_amount", "construction_amount",
        "execution_budget", "profit_amount", "profit_rate", "status",
        "grade", "sort_order", "project_code"
    ]
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return {"success": False, "message": "수정할 항목이 없습니다."}

    updates["updated_at"] = datetime.now().isoformat()
    conn = get_db()
    try:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [project_id]
        conn.execute(f"UPDATE projects SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return {"success": True, "message": "프로젝트 수정 완료"}
    finally:
        conn.close()


def delete_project(project_id: int) -> dict:
    """프로젝트 삭제 (CASCADE로 하위 데이터 모두 삭제)"""
    conn = get_db()
    try:
        row = conn.execute("SELECT name FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            return {"success": False, "message": "존재하지 않는 프로젝트입니다."}
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
        return {"success": True, "message": f"프로젝트 '{row['name']}' 삭제 완료"}
    finally:
        conn.close()


def reorder_projects(order: list[dict]) -> dict:
    """프로젝트 순서 일괄 업데이트"""
    conn = get_db()
    try:
        for i, item in enumerate(order):
            conn.execute(
                "UPDATE projects SET sort_order = ? WHERE id = ?",
                (i, item["id"])
            )
        conn.commit()
        return {"success": True, "message": f"{len(order)}개 프로젝트 순서 저장"}
    except Exception as e:
        logger.error("프로젝트 순서 저장 실패: %s", e)
        return {"success": False, "message": "순서 저장 중 오류가 발생했습니다."}
    finally:
        conn.close()


# ─────────────────────────────────────────
# 공종 CRUD
# ─────────────────────────────────────────

def list_trades(project_id: int) -> list[dict]:
    """프로젝트의 공종 목록"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM trades WHERE project_id = ? ORDER BY sort_order, id",
            (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_trade(project_id: int, name: str, sort_order: int = 0) -> dict:
    """공종 추가"""
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO trades (project_id, name, sort_order) VALUES (?, ?, ?)",
            (project_id, name, sort_order)
        )
        conn.commit()
        trade_id = cur.lastrowid
        return {"success": True, "id": trade_id, "message": f"공종 '{name}' 추가 완료"}
    except sqlite3.IntegrityError:
        return {"success": False, "message": f"공종 '{name}'이(가) 이미 존재합니다."}
    finally:
        conn.close()


def update_trade(trade_id: int, name: str = None, sort_order: int = None) -> dict:
    """공종 수정"""
    updates = {}
    if name is not None:
        updates["name"] = name
    if sort_order is not None:
        updates["sort_order"] = sort_order
    if not updates:
        return {"success": False, "message": "수정할 항목이 없습니다."}

    conn = get_db()
    try:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [trade_id]
        conn.execute(f"UPDATE trades SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return {"success": True, "message": "공종 수정 완료"}
    finally:
        conn.close()


def delete_trade(trade_id: int) -> dict:
    """공종 삭제"""
    conn = get_db()
    try:
        row = conn.execute("SELECT name FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if not row:
            return {"success": False, "message": "존재하지 않는 공종입니다."}
        conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
        conn.commit()
        return {"success": True, "message": f"공종 '{row['name']}' 삭제 완료"}
    finally:
        conn.close()


# ─────────────────────────────────────────
# 하도급 상세 CRUD
# ─────────────────────────────────────────

def list_subcontracts(project_id: int) -> list[dict]:
    """프로젝트의 하도급 목록 (공종명 포함)"""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT s.*, t.name as trade_name
            FROM subcontracts s
            LEFT JOIN trades t ON s.trade_id = t.id
            WHERE s.project_id = ?
            ORDER BY s.sort_order, s.id
        """, (project_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_subcontract(project_id: int, company_name: str, **kwargs) -> dict:
    """하도급 업체 추가"""
    conn = get_db()
    try:
        fields = ["project_id", "company_name"]
        values = [project_id, company_name]
        allowed = [
            "trade_id", "account_category", "has_estimate", "has_contract",
            "has_vendor_reg", "estimate_amount", "contract_amount",
            "payment_1", "payment_2", "payment_3", "payment_4",
            "remaining_amount", "payment_rate",
            "payment_1_confirmed", "payment_2_confirmed",
            "payment_3_confirmed", "payment_4_confirmed", "sort_order"
        ]
        for k in allowed:
            if k in kwargs and kwargs[k] is not None:
                fields.append(k)
                values.append(kwargs[k])

        placeholders = ", ".join("?" * len(fields))
        field_names = ", ".join(fields)
        cur = conn.execute(
            f"INSERT INTO subcontracts ({field_names}) VALUES ({placeholders})", values
        )
        conn.commit()
        sub_id = cur.lastrowid
        return {"success": True, "id": sub_id, "message": f"업체 '{company_name}' 추가 완료"}
    finally:
        conn.close()


def update_subcontract(sub_id: int, **kwargs) -> dict:
    """하도급 업체 정보 수정"""
    allowed = [
        "company_name", "trade_id", "account_category",
        "has_estimate", "has_contract", "has_vendor_reg",
        "estimate_amount", "contract_amount",
        "payment_1", "payment_2", "payment_3", "payment_4",
        "remaining_amount", "payment_rate",
        "payment_1_confirmed", "payment_2_confirmed",
        "payment_3_confirmed", "payment_4_confirmed", "sort_order"
    ]
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return {"success": False, "message": "수정할 항목이 없습니다."}

    updates["updated_at"] = datetime.now().isoformat()
    conn = get_db()
    try:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [sub_id]
        conn.execute(f"UPDATE subcontracts SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return {"success": True, "message": "수정 완료"}
    finally:
        conn.close()


def delete_subcontract(sub_id: int) -> dict:
    """하도급 업체 삭제"""
    conn = get_db()
    try:
        conn.execute("DELETE FROM subcontracts WHERE id = ?", (sub_id,))
        conn.commit()
        return {"success": True, "message": "삭제 완료"}
    finally:
        conn.close()


# ─────────────────────────────────────────
# 연락처 CRUD
# ─────────────────────────────────────────

def list_contacts(project_id: int) -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM contacts WHERE project_id = ? ORDER BY id",
            (project_id,)
        ).fetchall()
        # 프론트엔드 호환: company_name → vendor_name 별칭 추가
        results = []
        for r in rows:
            d = dict(r)
            d["vendor_name"] = d.get("company_name", "")
            results.append(d)
        return results
    finally:
        conn.close()


def add_contact(project_id: int, company_name: str, **kwargs) -> dict:
    conn = get_db()
    try:
        fields = ["project_id", "company_name"]
        values = [project_id, company_name]
        for k in ["trade_name", "trade_id", "contact_person", "phone", "email", "note"]:
            if k in kwargs and kwargs[k] is not None:
                fields.append(k)
                values.append(kwargs[k])
        placeholders = ", ".join("?" * len(fields))
        field_names = ", ".join(fields)
        conn.execute(
            f"INSERT INTO contacts ({field_names}) VALUES ({placeholders})", values
        )
        conn.commit()
        return {"success": True, "message": f"연락처 '{company_name}' 추가 완료"}
    finally:
        conn.close()


def update_contact(contact_id: int, **kwargs) -> dict:
    allowed = ["trade_name", "trade_id", "company_name", "contact_person", "phone", "email", "note"]
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return {"success": False, "message": "수정할 항목이 없습니다."}
    conn = get_db()
    try:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [contact_id]
        conn.execute(f"UPDATE contacts SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return {"success": True, "message": "연락처 수정 완료"}
    finally:
        conn.close()


def delete_contact(contact_id: int) -> dict:
    conn = get_db()
    try:
        conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
        conn.commit()
        return {"success": True, "message": "삭제 완료"}
    finally:
        conn.close()


# ─────────────────────────────────────────
# 이체완료 내역 (GW 스크래핑 데이터)
# ─────────────────────────────────────────

def save_payment_history(records: list[dict], project_id: int = None) -> dict:
    """이체완료 내역 일괄 저장"""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        count = 0
        for r in records:
            conn.execute("""
                INSERT INTO payment_history (
                    project_id, accounting_unit, scheduled_date, confirmed_date,
                    fund_category, vendor_code, vendor_name, business_number,
                    bank_name, account_number, account_holder, description,
                    amount, department, employee_name, project_name, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project_id or r.get("project_id"),
                r.get("accounting_unit", ""),
                r.get("scheduled_date", ""),
                r.get("confirmed_date", ""),
                r.get("fund_category", ""),
                r.get("vendor_code", ""),
                r.get("vendor_name", ""),
                r.get("business_number", ""),
                r.get("bank_name", ""),
                r.get("account_number", ""),
                r.get("account_holder", ""),
                r.get("description", ""),
                r.get("amount", 0),
                r.get("department", ""),
                r.get("employee_name", ""),
                r.get("project_name", ""),
                now,
            ))
            count += 1
        conn.commit()
        return {"success": True, "message": f"이체내역 {count}건 저장 완료"}
    finally:
        conn.close()


def list_payment_history(project_id: int = None, limit: int = 100) -> list[dict]:
    """이체완료 내역 조회"""
    conn = get_db()
    try:
        if project_id:
            rows = conn.execute(
                "SELECT * FROM payment_history WHERE project_id = ? ORDER BY confirmed_date DESC LIMIT ?",
                (project_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM payment_history ORDER BY confirmed_date DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─────────────────────────────────────────
# 예실대비현황 (GW 스크래핑 데이터)
# ─────────────────────────────────────────

def save_budget_actual(records: list[dict], project_id: int = None) -> dict:
    """예실대비현황 일괄 저장"""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        count = 0
        for r in records:
            conn.execute("""
                INSERT INTO budget_actual (
                    project_id, project_name, year, budget_code, budget_category,
                    budget_sub_category, budget_amount, actual_amount,
                    difference, execution_rate, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project_id or r.get("project_id"),
                r.get("project_name", ""),
                r.get("year", 0),
                r.get("budget_code", ""),
                r.get("budget_category", ""),
                r.get("budget_sub_category", ""),
                r.get("budget_amount", 0),
                r.get("actual_amount", 0),
                r.get("difference", 0),
                r.get("execution_rate", 0),
                now,
            ))
            count += 1
        conn.commit()
        return {"success": True, "message": f"예실대비 {count}건 저장 완료"}
    finally:
        conn.close()


def list_budget_actual(project_id: int = None, year: int = None) -> list[dict]:
    """예실대비현황 조회"""
    conn = get_db()
    try:
        query = "SELECT * FROM budget_actual WHERE 1=1"
        params = []
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        if year:
            query += " AND year = ?"
            params.append(year)
        query += " ORDER BY year DESC, budget_category"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─────────────────────────────────────────
# 프로젝트 개요 (배정인원, 면적, 이슈 등)
# ─────────────────────────────────────────

def get_project_overview(project_id: int) -> dict:
    """프로젝트 개요 조회"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM project_overview WHERE project_id = ?", (project_id,)
        ).fetchone()
        overview = dict(row) if row else {}

        members = conn.execute(
            "SELECT * FROM project_members WHERE project_id = ? ORDER BY sort_order",
            (project_id,)
        ).fetchall()
        overview["members"] = [dict(m) for m in members]

        milestones = conn.execute(
            "SELECT * FROM project_milestones WHERE project_id = ? ORDER BY sort_order",
            (project_id,)
        ).fetchall()
        overview["milestones"] = [dict(ms) for ms in milestones]
        return overview
    finally:
        conn.close()


def save_project_overview(project_id: int, data: dict) -> dict:
    """프로젝트 개요 저장 (upsert)"""
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM project_overview WHERE project_id = ?", (project_id,)
        ).fetchone()

        fields = [
            "project_category", "location", "usage", "scale", "area_pyeong",
            "design_start", "design_end", "construction_start", "construction_end",
            "open_date", "current_status",
            "design_contract_date", "design_contract_amount",
            "construction_contract_date", "construction_contract_amount",
            "issue_design", "issue_schedule", "issue_budget",
            "issue_operation", "issue_defect", "issue_other"
        ]

        if existing:
            sets = []
            vals = []
            for f in fields:
                if f in data:
                    sets.append(f"{f} = ?")
                    vals.append(data[f])
            sets.append("updated_at = CURRENT_TIMESTAMP")
            vals.append(project_id)
            conn.execute(
                f"UPDATE project_overview SET {', '.join(sets)} WHERE project_id = ?",
                vals
            )
        else:
            cols = ["project_id"]
            vals = [project_id]
            for f in fields:
                if f in data:
                    cols.append(f)
                    vals.append(data[f])
            placeholders = ", ".join(["?"] * len(cols))
            conn.execute(
                f"INSERT INTO project_overview ({', '.join(cols)}) VALUES ({placeholders})",
                vals
            )

        # 배정인원 저장
        if "members" in data:
            conn.execute("DELETE FROM project_members WHERE project_id = ?", (project_id,))
            for i, m in enumerate(data["members"]):
                conn.execute(
                    "INSERT INTO project_members (project_id, role, name, sort_order) VALUES (?, ?, ?, ?)",
                    (project_id, m.get("role", ""), m.get("name", ""), i)
                )

        # 마일스톤 저장 (전체 교체 방식: 삭제 후 재삽입)
        if "milestones" in data:
            conn.execute("DELETE FROM project_milestones WHERE project_id = ?", (project_id,))
            for i, ms in enumerate(data["milestones"]):
                conn.execute(
                    "INSERT INTO project_milestones (project_id, name, completed, date, sort_order) VALUES (?, ?, ?, ?, ?)",
                    (project_id, ms.get("name", ""), ms.get("completed", 0), ms.get("date", ""), i)
                )

        conn.commit()
        return {"success": True, "message": "프로젝트 개요 저장 완료"}
    finally:
        conn.close()


# ─────────────────────────────────────────
# 자금현황 요약 (챗봇용)
# ─────────────────────────────────────────

def list_collections(project_id: int) -> list[dict]:
    """수금현황 조회"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM collections WHERE project_id = ? ORDER BY id",
            (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_collection(collection_id: int, **kwargs) -> dict:
    """수금현황 항목 업데이트 (금액, 수금완료 등)"""
    allowed = ["amount", "collected", "collection_date"]
    conn = get_db()
    try:
        sets = []
        vals = []
        for k, v in kwargs.items():
            if k in allowed:
                sets.append(f"{k} = ?")
                vals.append(v)
        if not sets:
            return {"success": False, "message": "수정할 항목이 없습니다."}
        vals.append(collection_id)
        conn.execute(
            f"UPDATE collections SET {', '.join(sets)} WHERE id = ?", vals
        )
        conn.commit()
        return {"success": True, "message": "수금현황 수정 완료"}
    finally:
        conn.close()


def save_collections_bulk(project_id: int, items: list[dict]) -> dict:
    """수금현황 일괄 저장 (기존 데이터 업데이트 or 신규 추가)"""
    conn = get_db()
    try:
        for item in items:
            cid = item.get("id")
            if cid:
                # 기존 업데이트 (category, stage 포함)
                conn.execute(
                    "UPDATE collections SET category = ?, stage = ?, amount = ?, collected = ? WHERE id = ? AND project_id = ?",
                    (item.get("category", ""), item.get("stage", ""),
                     item.get("amount", 0), item.get("collected", 0), cid, project_id)
                )
            else:
                # 신규 추가
                conn.execute(
                    "INSERT INTO collections (project_id, category, stage, amount, collected) VALUES (?, ?, ?, ?, ?)",
                    (project_id, item.get("category", ""), item.get("stage", ""),
                     item.get("amount", 0), item.get("collected", 0))
                )
        conn.commit()
        return {"success": True, "message": f"수금현황 {len(items)}건 저장 완료"}
    finally:
        conn.close()


def get_portfolio_summary() -> list[dict]:
    """전체 프로젝트 포트폴리오 요약 (비교 뷰용)"""
    conn = get_db()
    try:
        projects = conn.execute(
            "SELECT * FROM projects ORDER BY sort_order ASC, created_at DESC"
        ).fetchall()
        result = []
        for p in projects:
            p = dict(p)
            pid = p["id"]
            total_order = (p.get("design_amount") or 0) + (p.get("construction_amount") or 0)
            exec_budget = p.get("execution_budget") or 0

            # 수금 현황
            coll_rows = conn.execute(
                "SELECT amount, collected FROM collections WHERE project_id = ?", (pid,)
            ).fetchall()
            coll_total = sum(r["amount"] or 0 for r in coll_rows)
            coll_collected = sum(r["amount"] or 0 for r in coll_rows if r["collected"])

            # 지급 현황
            sub_row = conn.execute("""
                SELECT COALESCE(SUM(contract_amount), 0) as payment_limit,
                       COALESCE(SUM(
                         CASE WHEN payment_1_confirmed THEN payment_1 ELSE 0 END +
                         CASE WHEN payment_2_confirmed THEN payment_2 ELSE 0 END +
                         CASE WHEN payment_3_confirmed THEN payment_3 ELSE 0 END +
                         CASE WHEN payment_4_confirmed THEN payment_4 ELSE 0 END
                       ), 0) as total_paid
                FROM subcontracts WHERE project_id = ?
            """, (pid,)).fetchone()

            payment_limit = sub_row["payment_limit"]
            total_paid = sub_row["total_paid"]
            profit = p.get("profit_amount") or 0
            profit_rate = p.get("profit_rate") or 0

            result.append({
                "id": pid,
                "name": p["name"],
                "grade": p.get("grade") or "-",
                "category": p.get("category") or "-",
                "total_order": total_order,
                "execution_budget": exec_budget,
                "profit_amount": profit,
                "profit_rate": profit_rate,
                "coll_total": coll_total,
                "coll_collected": coll_collected,
                "coll_rate": round(coll_collected / coll_total * 100, 1) if coll_total else 0,
                "payment_limit": payment_limit,
                "total_paid": total_paid,
                "payment_rate": round(total_paid / payment_limit * 100, 1) if payment_limit else 0,
            })
        return result
    finally:
        conn.close()


def get_fund_summary(project_id: int) -> dict:
    """프로젝트 자금현황 요약 (챗봇 응답용)"""
    conn = get_db()
    try:
        project = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not project:
            return {"error": "프로젝트를 찾을 수 없습니다."}

        p = dict(project)

        # 하도급 합계
        sub_stats = conn.execute("""
            SELECT
                COUNT(*) as total_companies,
                COALESCE(SUM(contract_amount), 0) as total_contract,
                COALESCE(SUM(payment_1 + payment_2 + payment_3 + payment_4), 0) as total_paid,
                COALESCE(SUM(remaining_amount), 0) as total_remaining
            FROM subcontracts WHERE project_id = ?
        """, (project_id,)).fetchone()

        # 공종 수
        trade_count = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE project_id = ?", (project_id,)
        ).fetchone()[0]

        return {
            "project_name": p["name"],
            "design_amount": p["design_amount"],
            "construction_amount": p["construction_amount"],
            "total_order": p["design_amount"] + p["construction_amount"],
            "execution_budget": p["execution_budget"],
            "profit_amount": p["profit_amount"],
            "profit_rate": p["profit_rate"],
            "trade_count": trade_count,
            "total_companies": sub_stats["total_companies"],
            "total_contract": sub_stats["total_contract"],
            "total_paid": sub_stats["total_paid"],
            "total_remaining": sub_stats["total_remaining"],
        }
    finally:
        conn.close()


def get_all_projects_summary() -> list[dict]:
    """전체 프로젝트 자금 요약 리스트 (단일 쿼리)"""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT
                p.id, p.name, p.design_amount, p.construction_amount,
                p.execution_budget, p.profit_amount, p.profit_rate,
                COUNT(DISTINCT t.id) as trade_count,
                COUNT(DISTINCT s.id) as total_companies,
                COALESCE(SUM(s.contract_amount), 0) as total_contract,
                COALESCE(SUM(s.payment_1 + s.payment_2 + s.payment_3 + s.payment_4), 0) as total_paid,
                COALESCE(SUM(s.remaining_amount), 0) as total_remaining
            FROM projects p
            LEFT JOIN trades t ON t.project_id = p.id
            LEFT JOIN subcontracts s ON s.project_id = p.id
            GROUP BY p.id
            ORDER BY p.sort_order ASC, p.created_at DESC
        """).fetchall()

        summaries = []
        for r in rows:
            summaries.append({
                "project_name": r["name"],
                "design_amount": r["design_amount"],
                "construction_amount": r["construction_amount"],
                "total_order": r["design_amount"] + r["construction_amount"],
                "execution_budget": r["execution_budget"],
                "profit_amount": r["profit_amount"],
                "profit_rate": r["profit_rate"],
                "trade_count": r["trade_count"],
                "total_companies": r["total_companies"],
                "total_contract": r["total_contract"],
                "total_paid": r["total_paid"],
                "total_remaining": r["total_remaining"],
            })
        return summaries
    finally:
        conn.close()


# ─────────────────────────────────────────
# 프로젝트 TODO CRUD
# ─────────────────────────────────────────

def list_todos(project_id: int = None) -> list[dict]:
    """TODO 목록 조회 (project_id=None이면 전체)"""
    conn = get_db()
    try:
        if project_id:
            rows = conn.execute(
                "SELECT * FROM project_todos WHERE project_id = ? ORDER BY completed ASC, priority DESC, created_at DESC",
                (project_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT t.*, p.name as project_name FROM project_todos t LEFT JOIN projects p ON t.project_id = p.id ORDER BY t.completed ASC, t.priority DESC, t.created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_todo(project_id: int, content: str, priority: str = "medium", category: str = "") -> dict:
    """TODO 생성"""
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO project_todos (project_id, content, priority, category) VALUES (?, ?, ?, ?)",
            (project_id, content, priority, category)
        )
        conn.commit()
        return {"success": True, "id": cur.lastrowid}
    finally:
        conn.close()


def update_todo(todo_id: int, **kwargs) -> dict:
    """TODO 수정"""
    allowed = ["content", "completed", "priority", "category", "project_id"]
    conn = get_db()
    try:
        sets, vals = [], []
        for k, v in kwargs.items():
            if k in allowed:
                sets.append(f"{k} = ?")
                vals.append(v)
        if not sets:
            return {"success": False, "message": "수정할 필드가 없습니다."}
        vals.append(todo_id)
        conn.execute(f"UPDATE project_todos SET {', '.join(sets)} WHERE id = ?", vals)
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


def delete_todo(todo_id: int) -> dict:
    """TODO 삭제"""
    conn = get_db()
    try:
        conn.execute("DELETE FROM project_todos WHERE id = ?", (todo_id,))
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


# ─────────────────────────────────────────
# AI 인사이트 캐시
# ─────────────────────────────────────────

def save_insight(project_id: int, content: str, insight_type: str = "strategy") -> dict:
    """인사이트 저장 (기존 동일 타입 교체)
    project_id=0 또는 None → 포트폴리오 전체 인사이트 (NULL로 저장)
    """
    conn = get_db()
    try:
        # project_id=0은 포트폴리오 전체 → NULL로 저장 (FK 제약 우회)
        db_pid = None if (not project_id or project_id == 0) else project_id
        if db_pid is None:
            conn.execute(
                "DELETE FROM project_insights WHERE project_id IS NULL AND insight_type = ?",
                (insight_type,)
            )
        else:
            conn.execute(
                "DELETE FROM project_insights WHERE project_id = ? AND insight_type = ?",
                (db_pid, insight_type)
            )
        conn.execute(
            "INSERT INTO project_insights (project_id, insight_type, content) VALUES (?, ?, ?)",
            (db_pid, insight_type, content)
        )
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


def get_insights(project_id: int = None) -> list[dict]:
    """인사이트 조회"""
    conn = get_db()
    try:
        if project_id:
            rows = conn.execute(
                "SELECT i.*, p.name as project_name FROM project_insights i LEFT JOIN projects p ON i.project_id = p.id WHERE i.project_id = ? ORDER BY i.generated_at DESC",
                (project_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT i.*, p.name as project_name FROM project_insights i LEFT JOIN projects p ON i.project_id = p.id ORDER BY i.generated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_projects_full_data() -> list[dict]:
    """전체 프로젝트 + 하위 데이터 일괄 조회 (인사이트 생성용)"""
    conn = get_db()
    try:
        projects = [dict(r) for r in conn.execute(
            "SELECT * FROM projects ORDER BY sort_order ASC, created_at DESC"
        ).fetchall()]

        for p in projects:
            pid = p["id"]
            # 개요
            ov = conn.execute("SELECT * FROM project_overview WHERE project_id = ?", (pid,)).fetchone()
            p["overview"] = dict(ov) if ov else {}
            # 마일스톤
            p["milestones"] = [dict(r) for r in conn.execute(
                "SELECT * FROM project_milestones WHERE project_id = ? ORDER BY sort_order", (pid,)
            ).fetchall()]
            # 인원
            p["members"] = [dict(r) for r in conn.execute(
                "SELECT * FROM project_members WHERE project_id = ? ORDER BY sort_order", (pid,)
            ).fetchall()]
            # 하도급
            p["subcontracts"] = [dict(r) for r in conn.execute(
                "SELECT * FROM subcontracts WHERE project_id = ?", (pid,)
            ).fetchall()]
            # 수금
            p["collections"] = [dict(r) for r in conn.execute(
                "SELECT * FROM collections WHERE project_id = ?", (pid,)
            ).fetchall()]
            # TODO
            p["todos"] = [dict(r) for r in conn.execute(
                "SELECT * FROM project_todos WHERE project_id = ? ORDER BY completed ASC, priority DESC", (pid,)
            ).fetchall()]
            # 이슈 추출
            ov_data = p["overview"]
            issues = []
            for key in ["issue_design", "issue_schedule", "issue_budget", "issue_operation", "issue_defect", "issue_other"]:
                if ov_data.get(key):
                    issues.append(ov_data[key])
            p["issues"] = issues

            # 자료실
            p["materials"] = [dict(r) for r in conn.execute(
                "SELECT * FROM project_materials WHERE project_id = ? ORDER BY created_at DESC", (pid,)
            ).fetchall()]

        return projects
    finally:
        conn.close()


# ─────────────────────────────────────────
# 프로젝트 자료실 CRUD
# ─────────────────────────────────────────

def add_material(project_id: int, material_type: str = "file", **kwargs) -> dict:
    """자료 추가"""
    conn = get_db()
    try:
        fields = ["project_id", "material_type"]
        values = [project_id, material_type]
        allowed = ["file_name", "file_path", "mime_type", "content_text", "description", "extracted_data"]
        for k in allowed:
            if k in kwargs and kwargs[k] is not None:
                fields.append(k)
                values.append(kwargs[k])
        placeholders = ", ".join("?" * len(fields))
        field_names = ", ".join(fields)
        cur = conn.execute(
            f"INSERT INTO project_materials ({field_names}) VALUES ({placeholders})", values
        )
        conn.commit()
        return {"success": True, "id": cur.lastrowid}
    finally:
        conn.close()


def list_materials(project_id: int) -> list[dict]:
    """프로젝트 자료 목록"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM project_materials WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_material(material_id: int) -> dict | None:
    """자료 상세"""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM project_materials WHERE id = ?", (material_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_material(material_id: int) -> dict:
    """자료 삭제"""
    conn = get_db()
    try:
        row = conn.execute("SELECT file_path FROM project_materials WHERE id = ?", (material_id,)).fetchone()
        if not row:
            return {"success": False, "message": "자료를 찾을 수 없습니다."}
        conn.execute("DELETE FROM project_materials WHERE id = ?", (material_id,))
        conn.commit()
        # 파일 삭제
        if row["file_path"]:
            fp = PROJECT_ROOT / row["file_path"]
            if fp.exists():
                fp.unlink()
        return {"success": True, "message": "자료 삭제 완료"}
    finally:
        conn.close()


# ─────────────────────────────────────────
# 알림 CRUD
# ─────────────────────────────────────────

def create_notification(project_id: int | None, notification_type: str, message: str) -> dict:
    """알림 생성"""
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO project_notifications (project_id, notification_type, message) VALUES (?, ?, ?)",
            (project_id, notification_type, message)
        )
        conn.commit()
        return {"success": True, "id": cur.lastrowid}
    finally:
        conn.close()


def list_notifications(limit: int = 50) -> list[dict]:
    """알림 목록"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT n.*, p.name as project_name FROM project_notifications n LEFT JOIN projects p ON n.project_id = p.id ORDER BY n.created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_notifications_read() -> dict:
    """모든 알림 읽음 처리"""
    conn = get_db()
    try:
        conn.execute("UPDATE project_notifications SET read = 1 WHERE read = 0")
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


def check_and_generate_notifications():
    """프로젝트 상태 확인 후 알림 자동 생성"""
    conn = get_db()
    try:
        now = datetime.now()
        # 마일스톤 기한 초과
        overdue = conn.execute("""
            SELECT pm.name as milestone_name, pm.date, p.name as project_name, p.id as project_id
            FROM project_milestones pm
            JOIN projects p ON pm.project_id = p.id
            WHERE pm.completed = 0 AND pm.date != '' AND pm.date < ?
        """, (now.strftime("%Y-%m-%d"),)).fetchall()

        for ms in overdue:
            # 중복 확인
            existing = conn.execute(
                "SELECT id FROM project_notifications WHERE message LIKE ? AND created_at > datetime('now', '-1 day')",
                (f"%{ms['milestone_name']}%기한 초과%",)
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO project_notifications (project_id, notification_type, message) VALUES (?, ?, ?)",
                    (ms["project_id"], "overdue", f"[{ms['project_name']}] '{ms['milestone_name']}' 기한 초과 ({ms['date']})")
                )

        # 수금 미완료 (큰 금액)
        uncollected = conn.execute("""
            SELECT c.stage, c.amount, p.name as project_name, p.id as project_id
            FROM collections c
            JOIN projects p ON c.project_id = p.id
            WHERE c.collected = 0 AND c.amount > 10000000
        """).fetchall()

        for uc in uncollected:
            existing = conn.execute(
                "SELECT id FROM project_notifications WHERE message LIKE ? AND created_at > datetime('now', '-7 day')",
                (f"%{uc['project_name']}%{uc['stage']}%미수금%",)
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO project_notifications (project_id, notification_type, message) VALUES (?, ?, ?)",
                    (uc["project_id"], "collection",
                     f"[{uc['project_name']}] '{uc['stage']}' 미수금 {uc['amount']:,}원")
                )

        conn.commit()
    except Exception as e:
        logger.error("알림 생성 실패: %s", e)
    finally:
        conn.close()


# ─────────────────────────────────────────
# 프로젝트 별칭 (alias) 관리
# ─────────────────────────────────────────

def get_project_aliases(project_id: int) -> list[str]:
    """프로젝트의 별칭 목록 반환"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT alias FROM project_aliases WHERE project_id = ? ORDER BY alias",
            (project_id,)
        ).fetchall()
        return [r["alias"] for r in rows]
    finally:
        conn.close()


def add_project_alias(project_id: int, alias: str, alias_type: str = "manual") -> dict:
    """프로젝트에 별칭 추가"""
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO project_aliases (project_id, alias, alias_type) VALUES (?, ?, ?)",
            (project_id, alias.strip(), alias_type)
        )
        conn.commit()
        return {"success": True, "project_id": project_id, "alias": alias}
    finally:
        conn.close()


def remove_project_alias(project_id: int, alias: str) -> dict:
    """프로젝트 별칭 삭제"""
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM project_aliases WHERE project_id = ? AND alias = ?",
            (project_id, alias.strip())
        )
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


def find_project_by_alias(search_name: str) -> dict | None:
    """별칭 테이블에서 프로젝트 검색 (부분 일치)"""
    if not search_name:
        return None
    conn = get_db()
    try:
        search_lower = search_name.lower().strip()
        # 정확 일치 우선
        row = conn.execute(
            "SELECT p.* FROM project_aliases a JOIN projects p ON p.id = a.project_id WHERE LOWER(a.alias) = ?",
            (search_lower,)
        ).fetchone()
        if row:
            return dict(row)
        # 부분 일치
        rows = conn.execute(
            "SELECT p.*, a.alias FROM project_aliases a JOIN projects p ON p.id = a.project_id WHERE LOWER(a.alias) LIKE ?",
            (f"%{search_lower}%",)
        ).fetchall()
        if rows:
            return dict(rows[0])
        return None
    finally:
        conn.close()


def get_all_aliases() -> list[dict]:
    """전체 프로젝트 별칭 목록 (프로젝트명 포함)"""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT a.id, a.project_id, p.name as project_name, a.alias, a.alias_type
            FROM project_aliases a
            JOIN projects p ON p.id = a.project_id
            ORDER BY a.project_id, a.alias
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─────────────────────────────────────────
# GW 프로젝트 캐시
# ─────────────────────────────────────────

def save_gw_projects_cache(projects: list[dict]):
    """GW 프로젝트 목록 캐시 저장 (전체 교체)"""
    conn = get_db()
    try:
        conn.execute("DELETE FROM gw_projects_cache")
        saved = 0
        for p in projects:
            code = p.get("code", "").strip()
            name = p.get("name", "").strip()
            # 코드가 비어있으면 UNIQUE 제약 위반 가능 → 건너뛰기
            if not code:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO gw_projects_cache (code, name, start_date, end_date) VALUES (?, ?, ?, ?)",
                (code, name, p.get("start_date", ""), p.get("end_date", ""))
            )
            saved += 1
        conn.commit()
        logger.info(f"GW 프로젝트 캐시 저장: {saved}개 (입력 {len(projects)}개)")
    finally:
        conn.close()


def search_gw_projects_cache(keyword: str) -> list[dict]:
    """GW 프로젝트 캐시에서 키워드 검색 (부분 일치, 토큰 기반)"""
    conn = get_db()
    try:
        kw = (keyword or "").strip().lower()
        tokens = [t for t in kw.split() if t] if kw else []

        rows = conn.execute(
            "SELECT code, name, start_date, end_date FROM gw_projects_cache ORDER BY name"
        ).fetchall()

        if not tokens:
            return [dict(r) for r in rows]

        results = []
        for r in rows:
            text = (r["code"] + " " + r["name"]).lower()
            if all(t in text for t in tokens):
                results.append(dict(r))
        return results
    finally:
        conn.close()


def get_gw_cache_info() -> dict:
    """GW 캐시 상태 (개수, 마지막 업데이트)"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt, MAX(cached_at) as last_update FROM gw_projects_cache"
        ).fetchone()
        return {"count": row["cnt"], "last_update": row["last_update"]}
    finally:
        conn.close()
