"""세금계산서 발행 기록 SQLite 저장소."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Optional

from src.office.tax_invoice.models import (
    InvoiceStatus,
    Party,
    TaxInvoiceDraft,
    TaxInvoiceLine,
    TaxInvoiceRecord,
    TaxInvoiceResult,
    InvoiceType,
)

_DB_DIR = Path(__file__).resolve().parents[3] / "data"
DEFAULT_DB_PATH = _DB_DIR / "tax_invoice.db"

_init_lock = threading.Lock()
_initialized_paths: set[str] = set()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path if db_path is not None else DEFAULT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    with _init_lock:
        if str(path) not in _initialized_paths:
            _ensure_schema(conn)
            _initialized_paths.add(str(path))
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tax_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL,
            owner_gw_id TEXT NOT NULL DEFAULT '',
            project_code TEXT NOT NULL DEFAULT '',
            document_no TEXT NOT NULL DEFAULT '',
            supplier_biz_no TEXT NOT NULL,
            supplier_name TEXT NOT NULL,
            buyer_biz_no TEXT NOT NULL,
            buyer_name TEXT NOT NULL,
            issue_date TEXT NOT NULL,
            invoice_type TEXT NOT NULL DEFAULT '01',
            total_supply INTEGER NOT NULL DEFAULT 0,
            total_tax INTEGER NOT NULL DEFAULT 0,
            total_amount INTEGER NOT NULL DEFAULT 0,
            nts_id TEXT NOT NULL DEFAULT '',
            provider_id TEXT NOT NULL DEFAULT '',
            provider_name TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            draft_json TEXT NOT NULL,
            result_json TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ti_owner ON tax_invoices(owner_gw_id);
        CREATE INDEX IF NOT EXISTS idx_ti_project ON tax_invoices(project_code);
        CREATE INDEX IF NOT EXISTS idx_ti_status ON tax_invoices(status);
        CREATE INDEX IF NOT EXISTS idx_ti_buyer ON tax_invoices(buyer_biz_no);
        """
    )
    conn.commit()


def _serialize_draft(draft: TaxInvoiceDraft) -> str:
    data = {
        "supplier": asdict(draft.supplier),
        "buyer": asdict(draft.buyer),
        "issue_date": draft.issue_date.isoformat(),
        "invoice_type": draft.invoice_type.value,
        "lines": [asdict(l) for l in draft.lines],
        "purpose": draft.purpose,
        "remark": draft.remark,
        "project_code": draft.project_code,
        "document_no": draft.document_no,
    }
    return json.dumps(data, ensure_ascii=False)


def _deserialize_draft(text: str) -> TaxInvoiceDraft:
    d = json.loads(text)
    return TaxInvoiceDraft(
        supplier=Party(**d["supplier"]),
        buyer=Party(**d["buyer"]),
        issue_date=date.fromisoformat(d["issue_date"]),
        invoice_type=InvoiceType(d["invoice_type"]),
        lines=[TaxInvoiceLine(**l) for l in d["lines"]],
        purpose=d.get("purpose", ""),
        remark=d.get("remark", ""),
        project_code=d.get("project_code", ""),
        document_no=d.get("document_no", ""),
    )


def insert_invoice(
    draft: TaxInvoiceDraft,
    result: TaxInvoiceResult,
    owner_gw_id: str = "",
    provider_name: str = "",
    db_path: Path | str | None = None,
) -> int:
    now = _utc_now_iso()
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO tax_invoices (
                status, owner_gw_id, project_code, document_no,
                supplier_biz_no, supplier_name, buyer_biz_no, buyer_name,
                issue_date, invoice_type,
                total_supply, total_tax, total_amount,
                nts_id, provider_id, provider_name, error_message,
                draft_json, result_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.status.value, owner_gw_id, draft.project_code, draft.document_no,
                draft.supplier.business_number, draft.supplier.company_name,
                draft.buyer.business_number, draft.buyer.company_name,
                draft.issue_date.isoformat(), draft.invoice_type.value,
                draft.total_supply, draft.total_tax, draft.total_amount,
                result.nts_id, result.provider_id, provider_name, result.error_message,
                _serialize_draft(draft),
                json.dumps({"raw_response": result.raw_response}, ensure_ascii=False),
                now, now,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def _row_to_record(row: sqlite3.Row) -> TaxInvoiceRecord:
    draft = _deserialize_draft(row["draft_json"]) if row["draft_json"] else None
    result_payload = json.loads(row["result_json"] or "{}")
    result = TaxInvoiceResult(
        success=(row["status"] not in ("failed", "cancelled")),
        status=InvoiceStatus(row["status"]),
        nts_id=row["nts_id"],
        provider_id=row["provider_id"],
        error_message=row["error_message"],
        raw_response=result_payload.get("raw_response", {}),
    )
    return TaxInvoiceRecord(
        id=row["id"],
        draft=draft,
        result=result,
        status=InvoiceStatus(row["status"]),
        owner_gw_id=row["owner_gw_id"],
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
    )


def get_invoice(invoice_id: int, db_path: Path | str | None = None) -> Optional[TaxInvoiceRecord]:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM tax_invoices WHERE id = ?", (invoice_id,)).fetchone()
        return _row_to_record(row) if row else None
    finally:
        conn.close()


def list_invoices(
    owner_gw_id: Optional[str] = None,
    project_code: Optional[str] = None,
    status: Optional[InvoiceStatus] = None,
    limit: int = 100,
    db_path: Path | str | None = None,
) -> list[TaxInvoiceRecord]:
    conn = _connect(db_path)
    try:
        clauses, params = [], []
        if owner_gw_id is not None:
            clauses.append("owner_gw_id = ?")
            params.append(owner_gw_id)
        if project_code is not None:
            clauses.append("project_code = ?")
            params.append(project_code)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM tax_invoices {where} ORDER BY updated_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [_row_to_record(r) for r in rows]
    finally:
        conn.close()


def update_invoice_status(
    invoice_id: int,
    status: InvoiceStatus,
    provider_id: str = "",
    nts_id: str = "",
    error_message: str = "",
    db_path: Path | str | None = None,
) -> None:
    conn = _connect(db_path)
    try:
        sets, params = ["status = ?", "updated_at = ?"], [status.value, _utc_now_iso()]
        if provider_id:
            sets.append("provider_id = ?")
            params.append(provider_id)
        if nts_id:
            sets.append("nts_id = ?")
            params.append(nts_id)
        if error_message:
            sets.append("error_message = ?")
            params.append(error_message)
        params.append(invoice_id)
        conn.execute(f"UPDATE tax_invoices SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
    finally:
        conn.close()
