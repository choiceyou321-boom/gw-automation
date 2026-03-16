"""
자금관리 SQLite DB 모듈
- 프로젝트별 자금관리표, 하도급상세, 연락처, 공종 관리
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


def get_db() -> sqlite3.Connection:
    """SQLite 연결 반환 + 테이블 자동 생성"""
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _create_tables(conn)
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

        -- GW 예실대비현황 (스크래핑 데이터)
        CREATE TABLE IF NOT EXISTS budget_actual (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            project_name TEXT DEFAULT '',
            year INTEGER DEFAULT 0,
            budget_category TEXT DEFAULT '',
            budget_sub_category TEXT DEFAULT '',
            budget_amount INTEGER DEFAULT 0,
            actual_amount INTEGER DEFAULT 0,
            difference INTEGER DEFAULT 0,
            execution_rate REAL DEFAULT 0,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
        );
    """)
    conn.commit()

    # grade, sort_order 컬럼 마이그레이션
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
            "grade", "sort_order"
        ]
        for k in allowed:
            if k in kwargs and kwargs[k] is not None:
                fields.append(k)
                values.append(kwargs[k])

        placeholders = ", ".join("?" * len(fields))
        field_names = ", ".join(fields)
        conn.execute(
            f"INSERT INTO projects ({field_names}) VALUES ({placeholders})",
            values
        )
        conn.commit()
        project_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return {"success": True, "id": project_id, "message": f"프로젝트 '{name}' 생성 완료"}
    except sqlite3.IntegrityError:
        return {"success": False, "message": f"프로젝트 '{name}'이(가) 이미 존재합니다."}
    finally:
        conn.close()


def update_project(project_id: int, **kwargs) -> dict:
    """프로젝트 정보 수정"""
    allowed = [
        "name", "description", "design_amount", "construction_amount",
        "execution_budget", "profit_amount", "profit_rate", "status",
        "grade", "sort_order"
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
        conn.execute(
            "INSERT INTO trades (project_id, name, sort_order) VALUES (?, ?, ?)",
            (project_id, name, sort_order)
        )
        conn.commit()
        trade_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
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
        conn.execute(
            f"INSERT INTO subcontracts ({field_names}) VALUES ({placeholders})", values
        )
        conn.commit()
        sub_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
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
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_contact(project_id: int, company_name: str, **kwargs) -> dict:
    conn = get_db()
    try:
        fields = ["project_id", "company_name"]
        values = [project_id, company_name]
        for k in ["trade_name", "contact_person", "phone", "email"]:
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
    allowed = ["trade_name", "company_name", "contact_person", "phone", "email"]
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
                    project_id, project_name, year, budget_category,
                    budget_sub_category, budget_amount, actual_amount,
                    difference, execution_rate, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project_id or r.get("project_id"),
                r.get("project_name", ""),
                r.get("year", 0),
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

        # 마일스톤 저장 (체크 상태만 업데이트)
        if "milestones" in data:
            for ms in data["milestones"]:
                ms_id = ms.get("id")
                if ms_id:
                    conn.execute(
                        "UPDATE project_milestones SET completed = ? WHERE id = ? AND project_id = ?",
                        (ms.get("completed", 0), ms_id, project_id)
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
                # 기존 업데이트
                conn.execute(
                    "UPDATE collections SET amount = ?, collected = ? WHERE id = ? AND project_id = ?",
                    (item.get("amount", 0), item.get("collected", 0), cid, project_id)
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
    """전체 프로젝트 자금 요약 리스트"""
    projects = list_projects()
    summaries = []
    for p in projects:
        summary = get_fund_summary(p["id"])
        if "error" not in summary:
            summaries.append(summary)
    return summaries
