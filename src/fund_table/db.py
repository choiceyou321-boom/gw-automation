"""
프로젝트 관리 SQLite DB 모듈
- 프로젝트별 관리표, 하도급상세, 연락처, 공종 관리
- GW 스크래핑 데이터 저장 (이체완료 내역, 예실대비현황)
"""
from __future__ import annotations

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
    # is_archived: 이전 프로젝트 보관 여부
    try:
        conn.execute("SELECT is_archived FROM projects LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE projects ADD COLUMN is_archived INTEGER DEFAULT 0")
        conn.commit()
    # timeline_start_month / timeline_end_month: 타임라인 표시 범위 (YYYY-MM)
    for col in ("timeline_start_month", "timeline_end_month"):
        try:
            conn.execute(f"SELECT {col} FROM projects LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute(f"ALTER TABLE projects ADD COLUMN {col} TEXT DEFAULT ''")
            conn.commit()

    # subcontracts 테이블에 changed_contract_amount 컬럼 추가 (변경계약금액)
    try:
        conn.execute("SELECT changed_contract_amount FROM subcontracts LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE subcontracts ADD COLUMN changed_contract_amount INTEGER DEFAULT 0")
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

    # ── 2026-03-27 마이그레이션: gw_projects_cache 확장 ──────────────────
    for col_def in [
        ("manager",        "TEXT DEFAULT ''"),
        ("client",         "TEXT DEFAULT ''"),
        ("department",     "TEXT DEFAULT ''"),
        ("project_type",   "TEXT DEFAULT ''"),
        ("status",         "TEXT DEFAULT ''"),
        ("contract_amount","INTEGER DEFAULT 0"),
        ("progress_rate",  "REAL DEFAULT 0"),
    ]:
        try:
            conn.execute(f"SELECT {col_def[0]} FROM gw_projects_cache LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute(f"ALTER TABLE gw_projects_cache ADD COLUMN {col_def[0]} {col_def[1]}")
            conn.commit()

    # ── 2026-03-27 마이그레이션: project_overview 확장 ──────────────────
    for col_def in [
        ("client",              "TEXT DEFAULT ''"),
        ("client_contact",      "TEXT DEFAULT ''"),
        ("client_phone",        "TEXT DEFAULT ''"),
        ("pm_name",             "TEXT DEFAULT ''"),
        ("site_manager",        "TEXT DEFAULT ''"),
        ("design_manager",      "TEXT DEFAULT ''"),
        ("gw_status",           "TEXT DEFAULT ''"),
        ("gw_project_type",     "TEXT DEFAULT ''"),
        ("gw_last_synced",      "TEXT DEFAULT ''"),
    ]:
        try:
            conn.execute(f"SELECT {col_def[0]} FROM project_overview LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute(f"ALTER TABLE project_overview ADD COLUMN {col_def[0]} {col_def[1]}")
            conn.commit()

    # ── 2026-03-27 마이그레이션: payment_history 확장 ──────────────────
    for col_def in [
        ("supply_amount",    "INTEGER DEFAULT 0"),
        ("tax_amount",       "INTEGER DEFAULT 0"),
        ("payment_type",     "TEXT DEFAULT ''"),
        ("trade_id",         "INTEGER"),
        ("gw_project_code",  "TEXT DEFAULT ''"),  # GW 사업코드 기반 매칭용 (2026-03-30)
    ]:
        try:
            conn.execute(f"SELECT {col_def[0]} FROM payment_history LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute(f"ALTER TABLE payment_history ADD COLUMN {col_def[0]} {col_def[1]}")
            conn.commit()

    # ── 2026-03-27 신규 테이블: 세금계산서, 예산변경이력, 수금예정, 리스크 ──
    conn.executescript("""
        -- 세금계산서 발행 내역 (GW 수금 모듈)
        CREATE TABLE IF NOT EXISTS gw_tax_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            issue_date TEXT DEFAULT '',
            invoice_number TEXT DEFAULT '',
            vendor_name TEXT DEFAULT '',
            vendor_biz_number TEXT DEFAULT '',
            supply_amount INTEGER DEFAULT 0,
            tax_amount INTEGER DEFAULT 0,
            total_amount INTEGER DEFAULT 0,
            invoice_type TEXT DEFAULT '',
            status TEXT DEFAULT '',
            description TEXT DEFAULT '',
            project_name TEXT DEFAULT '',
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
        );

        -- 예산 변경 이력 (BM 모듈 → 예산변경/전용 내역)
        CREATE TABLE IF NOT EXISTS gw_budget_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            change_date TEXT DEFAULT '',
            budget_code TEXT DEFAULT '',
            budget_name TEXT DEFAULT '',
            before_amount INTEGER DEFAULT 0,
            change_amount INTEGER DEFAULT 0,
            after_amount INTEGER DEFAULT 0,
            change_type TEXT DEFAULT '',
            reason TEXT DEFAULT '',
            approver TEXT DEFAULT '',
            approval_date TEXT DEFAULT '',
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
        );

        -- 수금 예정 내역 (GW 수금 모듈 → 수금예정 목록)
        CREATE TABLE IF NOT EXISTS gw_collection_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            scheduled_date TEXT DEFAULT '',
            category TEXT DEFAULT '',
            stage TEXT DEFAULT '',
            expected_amount INTEGER DEFAULT 0,
            collected_amount INTEGER DEFAULT 0,
            status TEXT DEFAULT '',
            invoice_number TEXT DEFAULT '',
            description TEXT DEFAULT '',
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
        );

        -- 자금집행 승인 현황 (GW 자금 모듈 → 집행승인 대기/완료)
        CREATE TABLE IF NOT EXISTS gw_payment_approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            request_date TEXT DEFAULT '',
            approval_date TEXT DEFAULT '',
            vendor_name TEXT DEFAULT '',
            amount INTEGER DEFAULT 0,
            supply_amount INTEGER DEFAULT 0,
            tax_amount INTEGER DEFAULT 0,
            fund_category TEXT DEFAULT '',
            budget_code TEXT DEFAULT '',
            status TEXT DEFAULT '',
            requester TEXT DEFAULT '',
            approver TEXT DEFAULT '',
            description TEXT DEFAULT '',
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
        );

        -- 프로젝트 리스크 이력 (수동 입력 + AI 감지)
        CREATE TABLE IF NOT EXISTS project_risk_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            risk_date TEXT DEFAULT '',
            risk_type TEXT DEFAULT '',
            severity TEXT DEFAULT 'medium',
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            impact TEXT DEFAULT '',
            mitigation TEXT DEFAULT '',
            resolved_date TEXT DEFAULT '',
            status TEXT DEFAULT 'open',
            created_by TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        -- 프로젝트 공정 일정 항목 (간트 차트용 자유형식)
        CREATE TABLE IF NOT EXISTS project_schedule_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            item_name TEXT NOT NULL DEFAULT '',
            start_date TEXT DEFAULT '',
            end_date TEXT DEFAULT '',
            status TEXT DEFAULT 'planned',
            color TEXT DEFAULT '#3b82f6',
            notes TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        -- 공종 마스터 (공정표 자동생성용, 전체 공사 유형 공유)
        CREATE TABLE IF NOT EXISTS construction_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_name TEXT NOT NULL,
            group_color TEXT DEFAULT '#6b7280',
            name TEXT NOT NULL UNIQUE,
            item_type TEXT DEFAULT 'bar',
            default_days INTEGER DEFAULT 0,
            predecessors TEXT DEFAULT '[]',
            steps TEXT DEFAULT '[]',
            sort_order INTEGER DEFAULT 0,
            is_custom INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- 공사 유형별 프리셋 (오피스, 상업시설, 병원, 식음, 주거 등)
        CREATE TABLE IF NOT EXISTS construction_presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            preset_name TEXT NOT NULL UNIQUE,
            trade_names TEXT DEFAULT '[]',
            is_custom INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- GW 계약 현황 (계약 등록 모듈)
        CREATE TABLE IF NOT EXISTS gw_contracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            contract_number TEXT DEFAULT '',
            contract_date TEXT DEFAULT '',
            contract_type TEXT DEFAULT '',
            vendor_name TEXT DEFAULT '',
            vendor_biz_number TEXT DEFAULT '',
            contract_amount INTEGER DEFAULT 0,
            supply_amount INTEGER DEFAULT 0,
            tax_amount INTEGER DEFAULT 0,
            start_date TEXT DEFAULT '',
            end_date TEXT DEFAULT '',
            status TEXT DEFAULT '',
            description TEXT DEFAULT '',
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
        );
    """)

    # ── 2026-03-27 마이그레이션: budget_actual 확장 (GW 예실데이터 전용 필드) ──
    for col_def in [
        ("gw_project_code", "TEXT DEFAULT ''"),   # GW 프로젝트 코드 (GS-25-0088)
        ("gisu",            "INTEGER DEFAULT 0"),  # 기수 (회계연도)
        ("def_nm",          "TEXT DEFAULT ''"),    # 구분명 (장/관/항/목)
        ("div_fg",          "INTEGER DEFAULT 0"),  # 구분 플래그 (1:장 2:관 3:항 4:목)
        ("is_leaf",         "INTEGER DEFAULT 0"),  # 말단 항목 여부
    ]:
        try:
            conn.execute(f"SELECT {col_def[0]} FROM budget_actual LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute(f"ALTER TABLE budget_actual ADD COLUMN {col_def[0]} {col_def[1]}")
            conn.commit()

    conn.commit()

    # ── project_schedule_items 신규 컬럼 마이그레이션 ─────────────────────
    for col, typedef in [
        ("group_name", "TEXT DEFAULT ''"),
        ("subtitle",   "TEXT DEFAULT ''"),
        ("item_type",  "TEXT DEFAULT 'bar'"),
        ("bar_color",  "TEXT DEFAULT ''"),
    ]:
        try:
            conn.execute(f"ALTER TABLE project_schedule_items ADD COLUMN {col} {typedef}")
            conn.commit()
        except Exception:
            pass  # 이미 존재

    # ── 성능 인덱스 (없으면 생성) ──────────────────────────────────────────
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_budget_actual_project
            ON budget_actual(project_id, gisu);
        CREATE INDEX IF NOT EXISTS idx_budget_actual_gw_code
            ON budget_actual(gw_project_code, gisu);
        CREATE INDEX IF NOT EXISTS idx_payment_history_project
            ON payment_history(project_id, confirmed_date);
        CREATE INDEX IF NOT EXISTS idx_payment_history_gw_code
            ON payment_history(gw_project_code);
        CREATE INDEX IF NOT EXISTS idx_todos_project
            ON project_todos(project_id, completed);
        CREATE INDEX IF NOT EXISTS idx_subcontracts_project
            ON subcontracts(project_id);
        CREATE INDEX IF NOT EXISTS idx_collections_project
            ON collections(project_id);
        CREATE INDEX IF NOT EXISTS idx_gcs_project
            ON gw_collection_schedule(project_id, scheduled_date);
        CREATE INDEX IF NOT EXISTS idx_gw_tax_invoices_project
            ON gw_tax_invoices(project_id);
        CREATE INDEX IF NOT EXISTS idx_gw_contracts_project
            ON gw_contracts(project_id);
        CREATE INDEX IF NOT EXISTS idx_notifications_project
            ON project_notifications(project_id, created_at);
    """)
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
        "grade", "sort_order", "project_code",
        "timeline_start_month", "timeline_end_month",
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
        rows = [(i, item["id"]) for i, item in enumerate(order)]
        with conn:
            conn.executemany("UPDATE projects SET sort_order = ? WHERE id = ?", rows)
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
        "estimate_amount", "contract_amount", "changed_contract_amount",
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
    """이체완료 내역 일괄 저장 (원자적 트랜잭션 + 자동 중복 제거)"""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        rows = []
        for r in records:
            pid = project_id or r.get("project_id")
            gw_code = r.get("gw_project_code", "")
            if not pid and gw_code:
                pid = find_project_id_by_gw_code_conn(conn, gw_code)
            rows.append((
                pid,
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
                gw_code,
                now,
            ))

        with conn:
            conn.executemany("""
                INSERT INTO payment_history (
                    project_id, accounting_unit, scheduled_date, confirmed_date,
                    fund_category, vendor_code, vendor_name, business_number,
                    bank_name, account_number, account_holder, description,
                    amount, department, employee_name, project_name,
                    gw_project_code, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)

        # 저장 후 자동 중복 제거
        deleted = 0
        if project_id:
            deleted = _deduplicate_payment_history_conn(conn, project_id)
        return {"success": True, "message": f"이체내역 {len(rows)}건 저장 완료 (중복 {deleted}건 제거)"}
    finally:
        conn.close()


def _deduplicate_payment_history_conn(conn, project_id: int) -> int:
    """기존 연결을 재사용해 이체내역 중복 제거 (내부 헬퍼)"""
    deleted = conn.execute("""
        DELETE FROM payment_history WHERE id NOT IN (
            SELECT MIN(id) FROM payment_history
            WHERE project_id = ?
            GROUP BY COALESCE(confirmed_date, scheduled_date), amount, description, vendor_name, account_number
        ) AND project_id = ?
    """, (project_id, project_id)).rowcount
    conn.commit()
    return deleted


def deduplicate_payment_history(project_id: int = None) -> int:
    """
    이체내역 중복 제거 (확정일+금액+적요+거래처명+계좌번호 기준, 오래된 행 삭제).
    중복 판단 시 project_id가 NULL인 행도 포함하여 gw_project_code 기준으로 그룹핑.
    """
    conn = get_db()
    try:
        if project_id:
            deleted = conn.execute("""
                DELETE FROM payment_history WHERE id NOT IN (
                    SELECT MIN(id) FROM payment_history
                    WHERE project_id = ?
                    GROUP BY COALESCE(confirmed_date, scheduled_date), amount, description, vendor_name, account_number
                ) AND project_id = ?
            """, (project_id, project_id)).rowcount
        else:
            # project_id가 NULL인 경우 gw_project_code를 대체 키로 사용
            deleted = conn.execute("""
                DELETE FROM payment_history WHERE id NOT IN (
                    SELECT MIN(id) FROM payment_history
                    GROUP BY
                        COALESCE(CAST(project_id AS TEXT), gw_project_code, ''),
                        COALESCE(confirmed_date, scheduled_date),
                        amount, description, vendor_name, account_number
                )
            """).rowcount
        conn.commit()
        return deleted
    finally:
        conn.close()


def list_payment_history(project_id: int = None, limit: int = 100,
                         gw_project_code: str = None) -> list[dict]:
    """
    이체완료 내역 조회.
    project_id가 없고 gw_project_code가 있으면 gw_project_code로도 조회.
    """
    conn = get_db()
    try:
        if project_id:
            rows = conn.execute(
                "SELECT * FROM payment_history WHERE project_id = ? ORDER BY confirmed_date DESC LIMIT ?",
                (project_id, limit)
            ).fetchall()
        elif gw_project_code:
            # gw_project_code 직접 매칭 + project_id 역추적 병행
            resolved_pid = find_project_id_by_gw_code_conn(conn, gw_project_code)
            if resolved_pid:
                rows = conn.execute(
                    """SELECT * FROM payment_history
                       WHERE project_id = ? OR gw_project_code = ?
                       ORDER BY confirmed_date DESC LIMIT ?""",
                    (resolved_pid, gw_project_code, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM payment_history WHERE gw_project_code = ? ORDER BY confirmed_date DESC LIMIT ?",
                    (gw_project_code, limit)
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

def save_budget_actual(records: list[dict], project_id: int = None,
                        gw_project_code: str = "", gisu: int = 0,
                        replace_project: bool = True) -> dict:
    """예실대비현황 일괄 저장 (GW RealGrid DataProvider 추출 데이터 포함)"""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        count = 0
        if replace_project and (project_id or gw_project_code):
            # 같은 프로젝트+기수 데이터는 교체
            if project_id:
                conn.execute("DELETE FROM budget_actual WHERE project_id = ? AND gisu = ?",
                             (project_id, gisu or 0))
            elif gw_project_code:
                conn.execute("DELETE FROM budget_actual WHERE gw_project_code = ? AND gisu = ?",
                             (gw_project_code, gisu or 0))
        rows = [
            (
                project_id or r.get("project_id"),
                r.get("project_name", ""),
                r.get("year", 0),
                r.get("budget_code", r.get("bgtCd", "")),
                r.get("budget_category", r.get("bgtNm", "")),
                r.get("budget_sub_category", ""),
                r.get("budget_amount", r.get("abgtSumAm", 0)),
                r.get("actual_amount", r.get("unitAm", 0)),
                r.get("difference", r.get("subAm", 0)),
                r.get("execution_rate", r.get("sumRt", 0)),
                gw_project_code or r.get("gw_project_code", ""),
                gisu or r.get("gisu", 0),
                r.get("def_nm", r.get("defNm", "")),
                r.get("div_fg", r.get("divFg", 0)),
                1 if r.get("is_leaf", r.get("lastYn") == "Y") else 0,
                now,
            )
            for r in records
        ]
        with conn:
            conn.executemany("""
                INSERT INTO budget_actual (
                    project_id, project_name, year, budget_code, budget_category,
                    budget_sub_category, budget_amount, actual_amount,
                    difference, execution_rate,
                    gw_project_code, gisu, def_nm, div_fg, is_leaf,
                    scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
        count = len(rows)
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
            "issue_operation", "issue_defect", "issue_other",
            # 2026-03-27 확장: GW 크롤러 수집 필드
            "client", "client_contact", "client_phone",
            "pm_name", "site_manager", "design_manager",
            "gw_status", "gw_project_type", "gw_last_synced",
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
                    "UPDATE collections SET category = ?, stage = ?, amount = ?, collected = ?, collection_date = ? WHERE id = ? AND project_id = ?",
                    (item.get("category", ""), item.get("stage", ""),
                     item.get("amount", 0), item.get("collected", 0),
                     item.get("collection_date", ""), cid, project_id)
                )
            else:
                # 신규 추가
                conn.execute(
                    "INSERT INTO collections (project_id, category, stage, amount, collected, collection_date) VALUES (?, ?, ?, ?, ?, ?)",
                    (project_id, item.get("category", ""), item.get("stage", ""),
                     item.get("amount", 0), item.get("collected", 0),
                     item.get("collection_date", ""))
                )
        conn.commit()
        return {"success": True, "message": f"수금현황 {len(items)}건 저장 완료"}
    finally:
        conn.close()


def get_portfolio_summary() -> list[dict]:
    """전체 프로젝트 포트폴리오 요약 (비교 뷰용) — 3쿼리로 N+1 제거"""
    conn = get_db()
    try:
        projects = conn.execute(
            "SELECT * FROM projects ORDER BY sort_order ASC, created_at DESC"
        ).fetchall()

        # 수금 현황 — 프로젝트별 일괄 집계
        coll_map: dict[int, dict] = {}
        for row in conn.execute("""
            SELECT project_id,
                   COALESCE(SUM(amount), 0) as coll_total,
                   COALESCE(SUM(CASE WHEN collected THEN amount ELSE 0 END), 0) as coll_collected
            FROM collections
            GROUP BY project_id
        """).fetchall():
            coll_map[row["project_id"]] = dict(row)

        # 지급 현황 — 프로젝트별 일괄 집계
        sub_map: dict[int, dict] = {}
        for row in conn.execute("""
            SELECT project_id,
                   COALESCE(SUM(contract_amount), 0) as payment_limit,
                   COALESCE(SUM(
                     CASE WHEN payment_1_confirmed THEN payment_1 ELSE 0 END +
                     CASE WHEN payment_2_confirmed THEN payment_2 ELSE 0 END +
                     CASE WHEN payment_3_confirmed THEN payment_3 ELSE 0 END +
                     CASE WHEN payment_4_confirmed THEN payment_4 ELSE 0 END
                   ), 0) as total_paid
            FROM subcontracts
            GROUP BY project_id
        """).fetchall():
            sub_map[row["project_id"]] = dict(row)

        result = []
        for p in projects:
            p = dict(p)
            pid = p["id"]
            total_order = (p.get("design_amount") or 0) + (p.get("construction_amount") or 0)
            coll = coll_map.get(pid, {"coll_total": 0, "coll_collected": 0})
            sub = sub_map.get(pid, {"payment_limit": 0, "total_paid": 0})
            coll_total = coll["coll_total"]
            coll_collected = coll["coll_collected"]
            payment_limit = sub["payment_limit"]
            total_paid = sub["total_paid"]
            result.append({
                "id": pid,
                "name": p["name"],
                "grade": p.get("grade") or "-",
                "category": p.get("category") or "-",
                "total_order": total_order,
                "execution_budget": p.get("execution_budget") or 0,
                "profit_amount": p.get("profit_amount") or 0,
                "profit_rate": p.get("profit_rate") or 0,
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
    """전체 프로젝트 + 하위 데이터 일괄 조회 (인사이트 생성용) — 8쿼리로 7N+1 제거"""
    conn = get_db()
    try:
        projects = [dict(r) for r in conn.execute(
            "SELECT * FROM projects ORDER BY sort_order ASC, created_at DESC"
        ).fetchall()]
        if not projects:
            return projects

        ids = [p["id"] for p in projects]
        placeholders = ",".join("?" * len(ids))

        def _group_by_pid(rows) -> dict:
            groups: dict[int, list] = {}
            for r in rows:
                pid = r["project_id"]
                groups.setdefault(pid, []).append(dict(r))
            return groups

        # 개요 — 1:1
        ov_map = {}
        for r in conn.execute(
            f"SELECT * FROM project_overview WHERE project_id IN ({placeholders})", ids
        ).fetchall():
            ov_map[r["project_id"]] = dict(r)

        # 마일스톤 / 인원 / 하도급 / 수금 / TODO / 자료실
        milestone_map = _group_by_pid(conn.execute(
            f"SELECT * FROM project_milestones WHERE project_id IN ({placeholders}) ORDER BY sort_order", ids
        ).fetchall())
        member_map = _group_by_pid(conn.execute(
            f"SELECT * FROM project_members WHERE project_id IN ({placeholders}) ORDER BY sort_order", ids
        ).fetchall())
        sub_map = _group_by_pid(conn.execute(
            f"SELECT * FROM subcontracts WHERE project_id IN ({placeholders})", ids
        ).fetchall())
        coll_map = _group_by_pid(conn.execute(
            f"SELECT * FROM collections WHERE project_id IN ({placeholders})", ids
        ).fetchall())
        todo_map = _group_by_pid(conn.execute(
            f"SELECT * FROM project_todos WHERE project_id IN ({placeholders}) "
            f"ORDER BY completed ASC, priority DESC", ids
        ).fetchall())
        material_map = _group_by_pid(conn.execute(
            f"SELECT * FROM project_materials WHERE project_id IN ({placeholders}) "
            f"ORDER BY created_at DESC", ids
        ).fetchall())

        for p in projects:
            pid = p["id"]
            ov_data = ov_map.get(pid, {})
            p["overview"] = ov_data
            p["milestones"] = milestone_map.get(pid, [])
            p["members"] = member_map.get(pid, [])
            p["subcontracts"] = sub_map.get(pid, [])
            p["collections"] = coll_map.get(pid, [])
            p["todos"] = todo_map.get(pid, [])
            p["materials"] = material_map.get(pid, [])
            p["issues"] = [
                ov_data[k] for k in
                ["issue_design", "issue_schedule", "issue_budget", "issue_operation", "issue_defect", "issue_other"]
                if ov_data.get(k)
            ]

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


def find_project_id_by_gw_code_conn(conn: sqlite3.Connection, gw_project_code: str) -> int | None:
    """
    이미 열린 커넥션으로 GW 사업코드 → project_id 조회.
    save_payment_history 내부에서 중복 연결 없이 사용하기 위한 헬퍼.
    우선순위: projects.project_code → project_overview(client 컬럼 없음) → gw_projects_cache
    """
    if not gw_project_code:
        return None
    # 1순위: projects.project_code 직접 매칭
    row = conn.execute(
        "SELECT id FROM projects WHERE project_code = ?", (gw_project_code,)
    ).fetchone()
    if row:
        return row["id"]
    # 2순위: gw_projects_cache → projects.project_code 참조
    cache_row = conn.execute(
        "SELECT code FROM gw_projects_cache WHERE code = ?", (gw_project_code,)
    ).fetchone()
    if cache_row:
        row = conn.execute(
            "SELECT id FROM projects WHERE project_code = ?", (cache_row["code"],)
        ).fetchone()
        if row:
            return row["id"]
    return None


def find_project_by_gw_code(gw_project_code: str) -> int | None:
    """
    GW 사업코드(예: GS-25-0088)로 fund_management.db의 project_id를 반환.
    우선순위:
      1. projects.project_code 직접 매칭
      2. gw_projects_cache 경유 → projects.project_code
      3. 프로젝트명 정규화(공백 제거, 소문자) 매칭 (gw_projects_cache.name 활용)
    반환값: project_id(int) 또는 None
    """
    if not gw_project_code:
        return None
    conn = get_db()
    try:
        pid = find_project_id_by_gw_code_conn(conn, gw_project_code)
        if pid:
            return pid
        # 3순위: gw_projects_cache.name → projects.name 정규화 매칭
        cache_row = conn.execute(
            "SELECT name FROM gw_projects_cache WHERE code = ?", (gw_project_code,)
        ).fetchone()
        if cache_row:
            gw_name_norm = cache_row["name"].lower().replace(" ", "")
            all_projects = conn.execute("SELECT id, name FROM projects").fetchall()
            for p in all_projects:
                p_norm = p["name"].lower().replace(" ", "")
                # 완전 포함 관계도 매칭
                if gw_name_norm == p_norm or gw_name_norm in p_norm or p_norm in gw_name_norm:
                    return p["id"]
        return None
    finally:
        conn.close()


def upsert_project_overview_gw_fields(project_id: int, fields: dict) -> dict:
    """
    GW 크롤링 결과를 project_overview 테이블의 GW 전용 컬럼에 저장/업데이트.
    기존 사용자 입력(project_category, location 등)은 건드리지 않음.

    fields 허용 키:
        pm_name, site_manager, design_manager,
        client, client_contact, client_phone,
        gw_status, gw_project_type, gw_last_synced
    """
    allowed = [
        "pm_name", "site_manager", "design_manager",
        "client", "client_contact", "client_phone",
        "gw_status", "gw_project_type", "gw_last_synced",
    ]
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None and v != ""}
    if not updates:
        return {"success": True, "message": "저장할 GW 필드가 없습니다."}

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM project_overview WHERE project_id = ?", (project_id,)
        ).fetchone()
        if existing:
            sets = [f"{k} = ?" for k in updates]
            sets.append("updated_at = CURRENT_TIMESTAMP")
            vals = list(updates.values()) + [project_id]
            conn.execute(
                f"UPDATE project_overview SET {', '.join(sets)} WHERE project_id = ?", vals
            )
        else:
            cols = ["project_id"] + list(updates.keys())
            vals = [project_id] + list(updates.values())
            placeholders = ", ".join(["?"] * len(cols))
            conn.execute(
                f"INSERT INTO project_overview ({', '.join(cols)}) VALUES ({placeholders})", vals
            )
        conn.commit()
        return {"success": True, "message": f"GW 필드 저장 완료: {list(updates.keys())}"}
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
    """GW 프로젝트 목록 캐시 저장 (전체 교체, 단일 트랜잭션)"""
    conn = get_db()
    try:
        rows_to_insert = [
            (p.get("code", "").strip(), p.get("name", "").strip(),
             p.get("start_date", ""), p.get("end_date", ""))
            for p in projects
            if p.get("code", "").strip()  # 코드 없는 항목 제외
        ]
        # DELETE → INSERT 원자적 실행 (크래시 시 빈 캐시 방지)
        with conn:
            conn.execute("DELETE FROM gw_projects_cache")
            conn.executemany(
                "INSERT OR REPLACE INTO gw_projects_cache (code, name, start_date, end_date) VALUES (?, ?, ?, ?)",
                rows_to_insert,
            )
        logger.info("GW 프로젝트 캐시 저장: %d개 (입력 %d개)", len(rows_to_insert), len(projects))
    finally:
        conn.close()


def search_gw_projects_cache(keyword: str) -> list[dict]:
    """GW 프로젝트 캐시에서 키워드 검색 (SQL LIKE 방식, 최대 100건, v2 확장 필드 포함)"""
    _COLS = "code, name, start_date, end_date, manager, client, department, project_type, status, contract_amount, progress_rate, cached_at"
    conn = get_db()
    try:
        kw = (keyword or "").strip()
        if not kw:
            rows = conn.execute(
                f"SELECT {_COLS} FROM gw_projects_cache ORDER BY name LIMIT 100"
            ).fetchall()
            return [dict(r) for r in rows]

        # 다중 토큰 AND 검색 — SQL LIKE로 서버사이드 필터링
        tokens = kw.split()
        conditions = " AND ".join(
            "(LOWER(code) LIKE ? OR LOWER(name) LIKE ?)" for _ in tokens
        )
        params = []
        for t in tokens:
            like = f"%{t.lower()}%"
            params.extend([like, like])
        rows = conn.execute(
            f"SELECT {_COLS} FROM gw_projects_cache WHERE {conditions} ORDER BY name LIMIT 100",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
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


# ─────────────────────────────────────────
# 세금계산서 (gw_tax_invoices)
# ─────────────────────────────────────────

def save_tax_invoices(records: list[dict], project_id: int = None) -> dict:
    """세금계산서 발행 내역 일괄 저장 (프로젝트별 전체 교체)"""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        rows = [
            (
                project_id or r.get("project_id"),
                r.get("issue_date", ""), r.get("invoice_number", ""),
                r.get("vendor_name", ""), r.get("vendor_biz_number", ""),
                r.get("supply_amount", 0), r.get("tax_amount", 0),
                r.get("total_amount", 0), r.get("invoice_type", ""),
                r.get("status", ""), r.get("description", ""),
                r.get("project_name", ""), now,
            )
            for r in records
        ]
        with conn:
            if project_id:
                conn.execute("DELETE FROM gw_tax_invoices WHERE project_id = ?", (project_id,))
            conn.executemany("""
                INSERT INTO gw_tax_invoices (
                    project_id, issue_date, invoice_number, vendor_name, vendor_biz_number,
                    supply_amount, tax_amount, total_amount, invoice_type, status,
                    description, project_name, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
        return {"success": True, "message": f"세금계산서 {len(rows)}건 저장 완료"}
    finally:
        conn.close()


def list_tax_invoices(project_id: int = None) -> list[dict]:
    """세금계산서 조회"""
    conn = get_db()
    try:
        query = "SELECT * FROM gw_tax_invoices WHERE 1=1"
        params = []
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        query += " ORDER BY issue_date DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─────────────────────────────────────────
# 예산 변경 이력 (gw_budget_changes)
# ─────────────────────────────────────────

def save_budget_changes(records: list[dict], project_id: int = None) -> dict:
    """예산 변경 이력 저장 (프로젝트별 전체 교체)"""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        if project_id:
            conn.execute("DELETE FROM gw_budget_changes WHERE project_id = ?", (project_id,))
        count = 0
        for r in records:
            pid = project_id or r.get("project_id")
            conn.execute("""
                INSERT INTO gw_budget_changes (
                    project_id, change_date, budget_code, budget_name,
                    before_amount, change_amount, after_amount,
                    change_type, reason, approver, approval_date, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pid, r.get("change_date",""), r.get("budget_code",""),
                r.get("budget_name",""), r.get("before_amount",0),
                r.get("change_amount",0), r.get("after_amount",0),
                r.get("change_type",""), r.get("reason",""),
                r.get("approver",""), r.get("approval_date",""), now,
            ))
            count += 1
        conn.commit()
        return {"success": True, "message": f"예산변경이력 {count}건 저장 완료"}
    finally:
        conn.close()


def list_budget_changes(project_id: int = None) -> list[dict]:
    """예산 변경 이력 조회"""
    conn = get_db()
    try:
        query = "SELECT * FROM gw_budget_changes WHERE 1=1"
        params = []
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        query += " ORDER BY change_date DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─────────────────────────────────────────
# 수금 예정 내역 (gw_collection_schedule)
# ─────────────────────────────────────────

def save_collection_schedule(records: list[dict], project_id: int = None) -> dict:
    """수금 예정 내역 저장 (프로젝트별 전체 교체)"""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        if project_id:
            conn.execute("DELETE FROM gw_collection_schedule WHERE project_id = ?", (project_id,))
        count = 0
        for r in records:
            pid = project_id or r.get("project_id")
            conn.execute("""
                INSERT INTO gw_collection_schedule (
                    project_id, scheduled_date, category, stage,
                    expected_amount, collected_amount, status,
                    invoice_number, description, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pid, r.get("scheduled_date",""), r.get("category",""),
                r.get("stage",""), r.get("expected_amount",0),
                r.get("collected_amount",0), r.get("status",""),
                r.get("invoice_number",""), r.get("description",""), now,
            ))
            count += 1
        conn.commit()
        return {"success": True, "message": f"수금예정 {count}건 저장 완료"}
    finally:
        conn.close()


def add_collection_schedule(project_id: int, **kwargs) -> dict:
    """수금 예정 항목 단건 추가 (수동 입력용)"""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        conn.execute("""
            INSERT INTO gw_collection_schedule (
                project_id, scheduled_date, category, stage,
                expected_amount, collected_amount, status,
                invoice_number, description, scraped_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            project_id,
            kwargs.get("scheduled_date", ""),
            kwargs.get("category", ""),
            kwargs.get("stage", kwargs.get("item_name", "")),
            kwargs.get("amount", kwargs.get("expected_amount", 0)),
            kwargs.get("collected_amount", 0),
            kwargs.get("status", "pending"),
            kwargs.get("invoice_number", ""),
            kwargs.get("description", ""),
            now,
        ))
        conn.commit()
        return {"success": True, "message": "수금 예정 항목 추가 완료"}
    finally:
        conn.close()


def list_collection_schedule(project_id: int = None, status: str = None) -> list[dict]:
    """수금 예정 내역 조회"""
    conn = get_db()
    try:
        query = "SELECT * FROM gw_collection_schedule WHERE 1=1"
        params = []
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY scheduled_date ASC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─────────────────────────────────────────
# 자금집행 승인 (gw_payment_approvals)
# ─────────────────────────────────────────

def save_payment_approvals(records: list[dict], project_id: int = None) -> dict:
    """자금집행 승인 현황 저장 (프로젝트별 전체 교체)"""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        if project_id:
            conn.execute("DELETE FROM gw_payment_approvals WHERE project_id = ?", (project_id,))
        count = 0
        for r in records:
            pid = project_id or r.get("project_id")
            conn.execute("""
                INSERT INTO gw_payment_approvals (
                    project_id, request_date, approval_date, vendor_name,
                    amount, supply_amount, tax_amount, fund_category,
                    budget_code, status, requester, approver,
                    description, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pid, r.get("request_date",""), r.get("approval_date",""),
                r.get("vendor_name",""), r.get("amount",0),
                r.get("supply_amount",0), r.get("tax_amount",0),
                r.get("fund_category",""), r.get("budget_code",""),
                r.get("status",""), r.get("requester",""),
                r.get("approver",""), r.get("description",""), now,
            ))
            count += 1
        conn.commit()
        return {"success": True, "message": f"자금집행승인 {count}건 저장 완료"}
    finally:
        conn.close()


def list_payment_approvals(project_id: int = None, status: str = None) -> list[dict]:
    """자금집행 승인 현황 조회"""
    conn = get_db()
    try:
        query = "SELECT * FROM gw_payment_approvals WHERE 1=1"
        params = []
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY request_date DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─────────────────────────────────────────
# 리스크 이력 (project_risk_log)
# ─────────────────────────────────────────

def add_risk(project_id: int, **kwargs) -> dict:
    """리스크 항목 추가"""
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO project_risk_log (
                project_id, risk_date, risk_type, severity, title,
                description, impact, mitigation, status, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            project_id,
            kwargs.get("risk_date", datetime.now().strftime("%Y-%m-%d")),
            kwargs.get("risk_type", ""),
            kwargs.get("severity", "medium"),
            kwargs.get("title", ""),
            kwargs.get("description", ""),
            kwargs.get("impact", ""),
            kwargs.get("mitigation", ""),
            kwargs.get("status", "open"),
            kwargs.get("created_by", ""),
        ))
        conn.commit()
        return {"success": True, "message": "리스크 항목 추가 완료"}
    finally:
        conn.close()


def list_risks(project_id: int, status: str = None) -> list[dict]:
    """리스크 이력 조회"""
    conn = get_db()
    try:
        query = "SELECT * FROM project_risk_log WHERE project_id = ?"
        params = [project_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY risk_date DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_risk(risk_id: int, **kwargs) -> dict:
    """리스크 항목 수정"""
    allowed = ["risk_type", "severity", "title", "description",
               "impact", "mitigation", "resolved_date", "status"]
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return {"success": False, "message": "수정할 항목이 없습니다."}
    updates["updated_at"] = datetime.now().isoformat()
    conn = get_db()
    try:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [risk_id]
        conn.execute(f"UPDATE project_risk_log SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return {"success": True, "message": "리스크 항목 수정 완료"}
    finally:
        conn.close()


# ─────────────────────────────────────────
# GW 계약 현황 (gw_contracts)
# ─────────────────────────────────────────

def save_gw_contracts(records: list[dict], project_id: int = None) -> dict:
    """GW 계약 현황 저장 (프로젝트별 전체 교체)"""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        if project_id:
            conn.execute("DELETE FROM gw_contracts WHERE project_id = ?", (project_id,))
        count = 0
        for r in records:
            pid = project_id or r.get("project_id")
            conn.execute("""
                INSERT INTO gw_contracts (
                    project_id, contract_number, contract_date, contract_type,
                    vendor_name, vendor_biz_number, contract_amount,
                    supply_amount, tax_amount, start_date, end_date,
                    status, description, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pid, r.get("contract_number",""), r.get("contract_date",""),
                r.get("contract_type",""), r.get("vendor_name",""),
                r.get("vendor_biz_number",""), r.get("contract_amount",0),
                r.get("supply_amount",0), r.get("tax_amount",0),
                r.get("start_date",""), r.get("end_date",""),
                r.get("status",""), r.get("description",""), now,
            ))
            count += 1
        conn.commit()
        return {"success": True, "message": f"계약 {count}건 저장 완료"}
    finally:
        conn.close()


def list_gw_contracts(project_id: int = None) -> list[dict]:
    """GW 계약 현황 조회"""
    conn = get_db()
    try:
        query = "SELECT * FROM gw_contracts WHERE 1=1"
        params = []
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        query += " ORDER BY contract_date DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─────────────────────────────────────────
# GW 프로젝트 캐시 — 확장된 저장/조회
# ─────────────────────────────────────────

def save_gw_projects_cache_v2(projects: list[dict]):
    """GW 프로젝트 캐시 저장 (확장 필드 포함, 전체 교체). NULL 방어 포함."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM gw_projects_cache")
        saved = 0
        skipped = 0
        for p in projects:
            code = str(p.get("code", "") or "").strip()
            name = str(p.get("name", "") or "").strip()
            if not code:
                skipped += 1
                continue
            # NULL/None 방어: 문자열 필드는 빈 문자열, 숫자 필드는 0 기본값
            try:
                contract_amount = int(p.get("contract_amount", 0) or 0)
            except (ValueError, TypeError):
                contract_amount = 0
            try:
                progress_rate = float(p.get("progress_rate", 0) or 0)
            except (ValueError, TypeError):
                progress_rate = 0
            conn.execute("""
                INSERT OR REPLACE INTO gw_projects_cache
                (code, name, start_date, end_date, manager, client,
                 department, project_type, status, contract_amount,
                 progress_rate, cached_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                code, name,
                str(p.get("start_date", "") or "").strip(),
                str(p.get("end_date", "") or "").strip(),
                str(p.get("manager", "") or "").strip(),
                str(p.get("client", "") or "").strip(),
                str(p.get("department", "") or "").strip(),
                str(p.get("project_type", "") or "").strip(),
                str(p.get("status", "") or "").strip(),
                contract_amount,
                progress_rate,
            ))
            saved += 1
        conn.commit()
        if skipped > 0:
            logger.warning(f"GW 프로젝트 캐시(v2): code 없는 항목 {skipped}개 스킵")
        logger.info(f"GW 프로젝트 캐시(v2) 저장: {saved}개")
    finally:
        conn.close()


# ─────────────────────────────────────────
# 공정 일정 항목 CRUD
# ─────────────────────────────────────────

def list_schedule_items(project_id: int) -> list[dict]:
    """공정 일정 항목 목록 조회"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM project_schedule_items WHERE project_id = ? ORDER BY sort_order",
            (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_schedule_items(project_id: int, items: list[dict]) -> dict:
    """공정 일정 항목 전체 교체 저장 (삭제 후 재삽입)"""
    conn = get_db()
    try:
        conn.execute("DELETE FROM project_schedule_items WHERE project_id = ?", (project_id,))
        for i, item in enumerate(items):
            conn.execute(
                """INSERT INTO project_schedule_items
                   (project_id, item_name, start_date, end_date, status, color, notes,
                    group_name, subtitle, item_type, bar_color, sort_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    item.get("item_name", ""),
                    item.get("start_date", ""),
                    item.get("end_date", ""),
                    item.get("status", "planned"),
                    item.get("color", "#3b82f6"),
                    item.get("notes", ""),
                    item.get("group_name", ""),
                    item.get("subtitle", ""),
                    item.get("item_type", "bar"),
                    item.get("bar_color", ""),
                    i,
                )
            )
        conn.commit()
        return {"success": True, "count": len(items)}
    except Exception as e:
        logger.error(f"일정 항목 저장 실패: {e}", exc_info=True)
        return {"success": False, "message": str(e)}
    finally:
        conn.close()


# ─────────────────────────────────────────
# 이전 프로젝트 보관
# ─────────────────────────────────────────

def set_project_archived(project_id: int, is_archived: bool) -> dict:
    """프로젝트 보관/복원"""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE projects SET is_archived = ? WHERE id = ?",
            (1 if is_archived else 0, project_id)
        )
        conn.commit()
        return {"success": True}
    except Exception as e:
        logger.error(f"프로젝트 보관 실패: {e}", exc_info=True)
        return {"success": False, "message": str(e)}
    finally:
        conn.close()


# ─────────────────────────────────────────
# 공종 마스터 (공정표 자동생성용) CRUD
# ─────────────────────────────────────────

def list_construction_trades() -> list[dict]:
    """전체 공종 마스터 목록 (sort_order 순)"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM construction_trades ORDER BY sort_order, id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_construction_trade(group_name: str, name: str, **kwargs) -> dict:
    """공종 추가"""
    conn = get_db()
    try:
        # sort_order 자동 계산: 같은 그룹 내 최대 + 1
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM construction_trades WHERE group_name = ?",
            (group_name,)
        ).fetchone()[0]

        conn.execute(
            """INSERT INTO construction_trades
               (group_name, group_color, name, item_type, default_days,
                predecessors, steps, sort_order, is_custom)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                group_name,
                kwargs.get("group_color", "#6b7280"),
                name,
                kwargs.get("item_type", "bar"),
                kwargs.get("default_days", 0),
                json.dumps(kwargs.get("predecessors", []), ensure_ascii=False),
                json.dumps(kwargs.get("steps", []), ensure_ascii=False),
                kwargs.get("sort_order", max_order + 1),
                kwargs.get("is_custom", 0),
            )
        )
        conn.commit()
        trade_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return {"success": True, "id": trade_id}
    except sqlite3.IntegrityError:
        return {"success": False, "message": f"공종 '{name}'이(가) 이미 존재합니다."}
    except Exception as e:
        logger.error(f"공종 추가 실패: {e}", exc_info=True)
        return {"success": False, "message": str(e)}
    finally:
        conn.close()


def update_construction_trade(trade_id: int, **kwargs) -> dict:
    """공종 수정"""
    conn = get_db()
    try:
        sets = []
        vals = []
        for key in ("group_name", "group_color", "name", "item_type",
                     "default_days", "sort_order", "is_custom"):
            if key in kwargs:
                sets.append(f"{key} = ?")
                vals.append(kwargs[key])
        # JSON 필드
        for key in ("predecessors", "steps"):
            if key in kwargs:
                sets.append(f"{key} = ?")
                vals.append(json.dumps(kwargs[key], ensure_ascii=False))
        if not sets:
            return {"success": False, "message": "수정할 필드가 없습니다."}
        vals.append(trade_id)
        conn.execute(
            f"UPDATE construction_trades SET {', '.join(sets)} WHERE id = ?",
            vals
        )
        conn.commit()
        return {"success": True}
    except sqlite3.IntegrityError:
        return {"success": False, "message": "공종명이 중복됩니다."}
    except Exception as e:
        logger.error(f"공종 수정 실패: {e}", exc_info=True)
        return {"success": False, "message": str(e)}
    finally:
        conn.close()


def delete_construction_trade(trade_id: int) -> dict:
    """공종 삭제"""
    conn = get_db()
    try:
        cursor = conn.execute(
            "DELETE FROM construction_trades WHERE id = ?", (trade_id,)
        )
        conn.commit()
        if cursor.rowcount == 0:
            return {"success": False, "message": "존재하지 않는 공종입니다."}
        return {"success": True}
    except Exception as e:
        logger.error(f"공종 삭제 실패: {e}", exc_info=True)
        return {"success": False, "message": str(e)}
    finally:
        conn.close()


def list_construction_presets() -> list[dict]:
    """공사 유형별 프리셋 목록"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM construction_presets ORDER BY id"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["trade_names"] = json.loads(d.get("trade_names", "[]"))
            result.append(d)
        return result
    finally:
        conn.close()


def save_construction_preset(preset_name: str, trade_names: list[str],
                             is_custom: int = 0) -> dict:
    """프리셋 저장 (upsert)"""
    conn = get_db()
    try:
        trade_names_json = json.dumps(trade_names, ensure_ascii=False)
        existing = conn.execute(
            "SELECT id FROM construction_presets WHERE preset_name = ?",
            (preset_name,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE construction_presets SET trade_names = ?, is_custom = ? WHERE id = ?",
                (trade_names_json, is_custom, existing["id"])
            )
        else:
            conn.execute(
                "INSERT INTO construction_presets (preset_name, trade_names, is_custom) VALUES (?, ?, ?)",
                (preset_name, trade_names_json, is_custom)
            )
        conn.commit()
        return {"success": True}
    except Exception as e:
        logger.error(f"프리셋 저장 실패: {e}", exc_info=True)
        return {"success": False, "message": str(e)}
    finally:
        conn.close()


def seed_construction_trades_from_master() -> dict:
    """process_map_master.py의 하드코딩 데이터를 DB에 시드 (멱등)"""
    from src.fund_table.process_map_master import PROCESS_GROUPS, TYPE_PRESETS

    conn = get_db()
    try:
        # 이미 데이터가 있으면 건너뜀
        count = conn.execute("SELECT COUNT(*) FROM construction_trades").fetchone()[0]
        if count > 0:
            return {"success": True, "message": f"이미 {count}개 공종이 존재합니다.", "seeded": 0}

        sort_idx = 0
        for group in PROCESS_GROUPS:
            group_name = group["group"]
            group_color = group["color"]
            for item in group["items"]:
                conn.execute(
                    """INSERT OR IGNORE INTO construction_trades
                       (group_name, group_color, name, item_type, default_days,
                        predecessors, steps, sort_order, is_custom)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                    (
                        group_name, group_color,
                        item["name"],
                        item.get("item_type", "bar"),
                        item.get("default_days", 0),
                        json.dumps(item.get("predecessors", []), ensure_ascii=False),
                        json.dumps(item.get("steps", []), ensure_ascii=False),
                        sort_idx,
                    )
                )
                sort_idx += 1

        # 프리셋 시드
        for preset_name, trade_list in TYPE_PRESETS.items():
            conn.execute(
                "INSERT OR IGNORE INTO construction_presets (preset_name, trade_names, is_custom) VALUES (?, ?, 0)",
                (preset_name, json.dumps(trade_list, ensure_ascii=False))
            )

        conn.commit()
        return {"success": True, "message": f"{sort_idx}개 공종 + {len(TYPE_PRESETS)}개 프리셋 시드 완료", "seeded": sort_idx}
    except Exception as e:
        logger.error(f"공종 시드 실패: {e}", exc_info=True)
        return {"success": False, "message": str(e)}
    finally:
        conn.close()

