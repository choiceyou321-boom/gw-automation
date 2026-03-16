#!/usr/bin/env python3
"""
Google Sheets → SQLite 일회성 임포트 스크립트
스프레드시트의 4개 시트(대시보드, 하도급상세, 연락처, 지급내역)를 읽어서 fund_management.db에 저장
"""

import os
import sys
import logging

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

import gspread
from google.oauth2.service_account import Credentials

from src.fund_table.db import (
    create_project, add_trade, add_subcontract,
    add_contact, save_payment_history, list_trades,
)

logger = logging.getLogger("sheets_import")

CREDENTIALS_PATH = os.path.join(PROJECT_ROOT, "config", "google_service_account.json")

# 기본 스프레드시트 ID (종로 오블리브 프로젝트_자금관리표&거래처 현황)
DEFAULT_SPREADSHEET_ID = "1LcmZPsDC-rqi2jofQup9G8xo6MOTVupSei0oZMm8nzE"


# ─── 유틸리티 ─────────────────────────────────────────────────────

def _parse_int(value: str) -> int:
    """문자열 → int 변환 (쉼표 제거, 빈값은 0)"""
    if not value or not isinstance(value, str):
        return 0
    cleaned = value.strip().replace(",", "").replace(" ", "")
    if not cleaned or cleaned == "-":
        return 0
    try:
        # 소수점이 있으면 반올림
        return int(float(cleaned))
    except (ValueError, TypeError):
        return 0


def _parse_float(value: str) -> float:
    """문자열 → float 변환 (%, 쉼표 제거)"""
    if not value or not isinstance(value, str):
        return 0.0
    cleaned = value.strip().replace(",", "").replace("%", "").replace(" ", "")
    if not cleaned or cleaned == "-":
        return 0.0
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def _parse_ox(value: str) -> int:
    """O/X → 1/0 변환"""
    if not value or not isinstance(value, str):
        return 0
    v = value.strip().upper()
    if v in ("O", "○", "YES", "Y", "1"):
        return 1
    return 0


def _parse_bool(value: str) -> int:
    """TRUE/FALSE → 1/0 변환"""
    if not value or not isinstance(value, str):
        return 0
    v = value.strip().upper()
    if v in ("TRUE", "1", "O", "YES", "Y"):
        return 1
    return 0


def _safe_str(value) -> str:
    """안전한 문자열 변환"""
    if value is None:
        return ""
    return str(value).strip()


# ─── Google Sheets 연결 ───────────────────────────────────────────

def connect():
    """Google Sheets API 연결 (서비스 계정)"""
    if not os.path.exists(CREDENTIALS_PATH):
        raise FileNotFoundError(
            f"서비스 계정 키 파일이 없습니다: {CREDENTIALS_PATH}\n"
            f"config/google_service_account.json 파일을 확인해주세요."
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    client = gspread.authorize(creds)
    return client


# ─── 시트별 임포트 함수 ───────────────────────────────────────────

def _import_dashboard(ws, project_id: int) -> dict:
    """
    대시보드 시트 → projects 테이블 업데이트
    행 1~10에 설계/시공 수주액, 실행예산, 수익금 등이 있음
    """
    rows = ws.get_all_values()
    print(f"  [대시보드] {len(rows)}행 읽기 완료")

    # 대시보드에서 주요 금액 추출
    # 행 구조가 스프레드시트마다 다를 수 있으므로, 라벨을 기준으로 탐색
    info = {
        "design_amount": 0,
        "construction_amount": 0,
        "execution_budget": 0,
        "profit_amount": 0,
        "profit_rate": 0.0,
    }

    for row in rows:
        # 각 셀을 순회하면서 라벨 키워드 매칭
        for i, cell in enumerate(row):
            cell_text = _safe_str(cell)
            if not cell_text:
                continue

            # 값은 라벨 오른쪽에 있는 첫 번째 비어있지 않은 셀
            val = ""
            for j in range(i + 1, min(i + 4, len(row))):
                candidate = _safe_str(row[j])
                if candidate:
                    val = candidate
                    break

            if "설계" in cell_text and "수주" in cell_text:
                info["design_amount"] = _parse_int(val)
            elif "시공" in cell_text and "수주" in cell_text:
                info["construction_amount"] = _parse_int(val)
            elif "실행" in cell_text and "예산" in cell_text and "율" not in cell_text:
                info["execution_budget"] = _parse_int(val)
            elif "수익금" in cell_text and "이익" not in cell_text:
                info["profit_amount"] = _parse_int(val)
            elif "이익율" in cell_text or "이익률" in cell_text:
                info["profit_rate"] = _parse_float(val)

    # DB 업데이트 (create_project은 이미 호출된 상태이므로 update 사용)
    from src.fund_table.db import update_project
    result = update_project(project_id, **info)

    found = sum(1 for v in info.values() if v != 0 and v != 0.0)
    print(f"  [대시보드] 프로젝트 정보 {found}개 항목 업데이트")
    return info


def _import_subcontracts(ws, project_id: int) -> int:
    """
    하도급상세 시트 → trades + subcontracts 테이블
    컬럼: NUM, 공종명, 업체명, 계정과목, 견적서/계약/거래처등록(O/X),
           견적금액, 계약금액, 1~4차지급, 잔여대금, 지급율, 1~4차지급확인
    """
    rows = ws.get_all_values()
    print(f"  [하도급상세] {len(rows)}행 읽기 완료")

    if len(rows) < 2:
        print("  [하도급상세] 데이터 행이 없습니다")
        return 0

    # 헤더 행 찾기 (NUM 또는 번호가 포함된 행)
    header_idx = 0
    for i, row in enumerate(rows):
        row_text = " ".join(_safe_str(c) for c in row).lower()
        if "num" in row_text or "번호" in row_text or "공종" in row_text:
            header_idx = i
            break

    # 헤더 파싱 — 컬럼 인덱스 매핑
    header = [_safe_str(c) for c in rows[header_idx]]
    col_map = {}
    for idx, h in enumerate(header):
        hl = h.lower().replace(" ", "")
        if "공종" in hl:
            col_map["trade"] = idx
        elif "업체" in hl or "회사" in hl:
            col_map["company"] = idx
        elif "계정" in hl and "과목" in hl:
            col_map["account"] = idx
        elif "견적서" in hl or ("견적" in hl and "금액" not in hl):
            col_map["has_estimate"] = idx
        elif "계약" in hl and "금액" not in hl and "등록" not in hl:
            col_map["has_contract"] = idx
        elif "거래처" in hl and "등록" in hl:
            col_map["has_vendor"] = idx
        elif "견적" in hl and "금액" in hl:
            col_map["estimate_amount"] = idx
        elif "계약" in hl and "금액" in hl:
            col_map["contract_amount"] = idx
        elif "1차" in hl and "지급" in hl and "확인" not in hl:
            col_map["payment_1"] = idx
        elif "2차" in hl and "지급" in hl and "확인" not in hl:
            col_map["payment_2"] = idx
        elif "3차" in hl and "지급" in hl and "확인" not in hl:
            col_map["payment_3"] = idx
        elif "4차" in hl and "지급" in hl and "확인" not in hl:
            col_map["payment_4"] = idx
        elif "잔여" in hl or "잔액" in hl:
            col_map["remaining"] = idx
        elif "지급율" in hl or "지급률" in hl:
            col_map["payment_rate"] = idx
        elif "1차" in hl and "확인" in hl:
            col_map["confirmed_1"] = idx
        elif "2차" in hl and "확인" in hl:
            col_map["confirmed_2"] = idx
        elif "3차" in hl and "확인" in hl:
            col_map["confirmed_3"] = idx
        elif "4차" in hl and "확인" in hl:
            col_map["confirmed_4"] = idx

    print(f"  [하도급상세] 컬럼 매핑: {list(col_map.keys())}")

    # 공종 → trade_id 캐시
    trade_cache = {}
    sort_order = 0
    count = 0

    # 데이터 행 순회 (헤더 다음 행부터)
    for row_idx in range(header_idx + 1, len(rows)):
        row = rows[row_idx]
        if len(row) == 0:
            continue

        # 빈 행 건너뛰기 (업체명 또는 공종명이 없으면)
        company = _safe_str(row[col_map["company"]]) if "company" in col_map else ""
        trade_name = _safe_str(row[col_map["trade"]]) if "trade" in col_map else ""

        if not company and not trade_name:
            continue
        if not company:
            # 공종명만 있는 경우 — 공종 구분 행일 수 있음
            continue

        # 공종 등록/조회
        trade_id = None
        if trade_name:
            if trade_name not in trade_cache:
                result = add_trade(project_id, trade_name, sort_order)
                if result.get("success"):
                    trade_cache[trade_name] = result["id"]
                    sort_order += 1
                else:
                    # 이미 존재하면 DB에서 조회
                    trades = list_trades(project_id)
                    for t in trades:
                        if t["name"] == trade_name:
                            trade_cache[trade_name] = t["id"]
                            break
            trade_id = trade_cache.get(trade_name)

        # 하도급 데이터 추출
        kwargs = {}
        if trade_id:
            kwargs["trade_id"] = trade_id

        if "account" in col_map:
            kwargs["account_category"] = _safe_str(row[col_map["account"]])
        if "has_estimate" in col_map:
            kwargs["has_estimate"] = _parse_ox(row[col_map["has_estimate"]])
        if "has_contract" in col_map:
            kwargs["has_contract"] = _parse_ox(row[col_map["has_contract"]])
        if "has_vendor" in col_map:
            kwargs["has_vendor_reg"] = _parse_ox(row[col_map["has_vendor"]])
        if "estimate_amount" in col_map:
            kwargs["estimate_amount"] = _parse_int(row[col_map["estimate_amount"]])
        if "contract_amount" in col_map:
            kwargs["contract_amount"] = _parse_int(row[col_map["contract_amount"]])
        if "payment_1" in col_map:
            kwargs["payment_1"] = _parse_int(row[col_map["payment_1"]])
        if "payment_2" in col_map:
            kwargs["payment_2"] = _parse_int(row[col_map["payment_2"]])
        if "payment_3" in col_map:
            kwargs["payment_3"] = _parse_int(row[col_map["payment_3"]])
        if "payment_4" in col_map:
            kwargs["payment_4"] = _parse_int(row[col_map["payment_4"]])
        if "remaining" in col_map:
            kwargs["remaining_amount"] = _parse_int(row[col_map["remaining"]])
        if "payment_rate" in col_map:
            kwargs["payment_rate"] = _parse_float(row[col_map["payment_rate"]])
        if "confirmed_1" in col_map:
            kwargs["payment_1_confirmed"] = _parse_bool(row[col_map["confirmed_1"]])
        if "confirmed_2" in col_map:
            kwargs["payment_2_confirmed"] = _parse_bool(row[col_map["confirmed_2"]])
        if "confirmed_3" in col_map:
            kwargs["payment_3_confirmed"] = _parse_bool(row[col_map["confirmed_3"]])
        if "confirmed_4" in col_map:
            kwargs["payment_4_confirmed"] = _parse_bool(row[col_map["confirmed_4"]])

        kwargs["sort_order"] = count

        result = add_subcontract(project_id, company, **kwargs)
        if result.get("success"):
            count += 1

    print(f"  [하도급상세] {count}건 임포트, 공종 {len(trade_cache)}개 생성")
    return count


def _import_contacts(ws, project_id: int) -> int:
    """
    연락처 시트 → contacts 테이블
    컬럼: 공종, 업체명, 담당자, 연락처, 이메일
    """
    rows = ws.get_all_values()
    print(f"  [연락처] {len(rows)}행 읽기 완료")

    if len(rows) < 2:
        print("  [연락처] 데이터 행이 없습니다")
        return 0

    # 헤더 행 찾기 — "업체명"이 셀 단위로 존재하는 행
    header_idx = 0
    for i, row in enumerate(rows):
        cells = [_safe_str(c) for c in row]
        # 셀 단위 매칭: "업체명" 또는 "업체" + "담당자" 가 별개 셀로 존재해야 진짜 헤더
        if any("업체" in c for c in cells) and any("담당" in c for c in cells):
            header_idx = i
            break

    header = [_safe_str(c) for c in rows[header_idx]]
    col_map = {}
    for idx, h in enumerate(header):
        hl = h.replace(" ", "")
        if "공종" in hl:
            col_map["trade"] = idx
        elif "업체" in hl or "회사" in hl:
            col_map["company"] = idx
        elif ("담당" in hl) and "person" not in col_map:
            # 첫 번째 담당자 컬럼만 사용
            col_map["person"] = idx
        elif ("연락" in hl or "전화" in hl or "휴대" in hl) and "phone" not in col_map:
            # 첫 번째 연락처 컬럼만 사용
            col_map["phone"] = idx
        elif "이메일" in hl or "메일" in hl or "email" in hl.lower():
            col_map["email"] = idx

    print(f"  [연락처] 컬럼 매핑: {list(col_map.keys())}")

    count = 0
    for row_idx in range(header_idx + 1, len(rows)):
        row = rows[row_idx]
        if len(row) == 0:
            continue

        company = _safe_str(row[col_map["company"]]) if "company" in col_map else ""
        if not company:
            continue

        kwargs = {}
        if "trade" in col_map:
            kwargs["trade_name"] = _safe_str(row[col_map["trade"]])
        if "person" in col_map:
            kwargs["contact_person"] = _safe_str(row[col_map["person"]])
        if "phone" in col_map:
            kwargs["phone"] = _safe_str(row[col_map["phone"]])
        if "email" in col_map:
            kwargs["email"] = _safe_str(row[col_map["email"]])

        result = add_contact(project_id, company, **kwargs)
        if result.get("success"):
            count += 1

    print(f"  [연락처] {count}건 임포트")
    return count


def _import_payment_history(ws, project_id: int) -> int:
    """
    지급내역 시트 → payment_history 테이블
    컬럼: 회계단위, 예정일, 확정일, 자금과목, 거래처코드, 거래처명,
           사업자번호, 은행, 계좌번호, 예금주, 적요, 금액, 사용부서, 사원명, 프로젝트
    """
    rows = ws.get_all_values()
    print(f"  [지급내역] {len(rows)}행 읽기 완료")

    if len(rows) < 2:
        print("  [지급내역] 데이터 행이 없습니다")
        return 0

    # 헤더 행 찾기
    header_idx = 0
    for i, row in enumerate(rows):
        row_text = " ".join(_safe_str(c) for c in row)
        if "회계" in row_text or "거래처" in row_text or "예정일" in row_text:
            header_idx = i
            break

    header = [_safe_str(c) for c in rows[header_idx]]
    col_map = {}
    for idx, h in enumerate(header):
        hl = h.replace(" ", "")
        if "회계" in hl and "단위" in hl:
            col_map["accounting_unit"] = idx
        elif "예정" in hl and "일" in hl:
            col_map["scheduled_date"] = idx
        elif "확정" in hl and "일" in hl:
            col_map["confirmed_date"] = idx
        elif "자금" in hl and "과목" in hl:
            col_map["fund_category"] = idx
        elif "거래처" in hl and "코드" in hl:
            col_map["vendor_code"] = idx
        elif "거래처" in hl and ("명" in hl or "이름" in hl):
            col_map["vendor_name"] = idx
        elif "사업자" in hl:
            col_map["business_number"] = idx
        elif "은행" in hl:
            col_map["bank_name"] = idx
        elif "계좌" in hl and "번호" in hl:
            col_map["account_number"] = idx
        elif "예금주" in hl:
            col_map["account_holder"] = idx
        elif "적요" in hl:
            col_map["description"] = idx
        elif "금액" in hl:
            col_map["amount"] = idx
        elif "사용" in hl and "부서" in hl:
            col_map["department"] = idx
        elif "사원" in hl and "명" in hl:
            col_map["employee_name"] = idx
        elif "프로젝트" in hl:
            col_map["project_name"] = idx

    # 거래처명이 매핑 안 됐을 경우 — "거래처" 단독 키워드로 재시도
    if "vendor_name" not in col_map:
        for idx, h in enumerate(header):
            hl = h.replace(" ", "")
            if "거래처" in hl and idx not in col_map.values():
                col_map["vendor_name"] = idx
                break

    print(f"  [지급내역] 컬럼 매핑: {list(col_map.keys())}")

    # 레코드 수집
    records = []
    for row_idx in range(header_idx + 1, len(rows)):
        row = rows[row_idx]
        if len(row) == 0:
            continue

        # 빈 행 건너뛰기 (금액 또는 거래처명이 없으면)
        amount_str = _safe_str(row[col_map["amount"]]) if "amount" in col_map else ""
        vendor_str = _safe_str(row[col_map["vendor_name"]]) if "vendor_name" in col_map else ""
        if not amount_str and not vendor_str:
            continue

        record = {}
        # 문자열 필드
        for key in ["accounting_unit", "scheduled_date", "confirmed_date",
                     "fund_category", "vendor_code", "vendor_name",
                     "business_number", "bank_name", "account_number",
                     "account_holder", "description", "department",
                     "employee_name", "project_name"]:
            if key in col_map:
                record[key] = _safe_str(row[col_map[key]])
            else:
                record[key] = ""

        # 금액 필드 (숫자)
        if "amount" in col_map:
            record["amount"] = _parse_int(row[col_map["amount"]])
        else:
            record["amount"] = 0

        records.append(record)

    # DB 일괄 저장
    if records:
        result = save_payment_history(records, project_id)
        count = len(records)
        print(f"  [지급내역] {count}건 임포트")
        return count
    else:
        print("  [지급내역] 임포트할 데이터가 없습니다")
        return 0


# ─── 메인 임포트 함수 ─────────────────────────────────────────────

def import_from_sheets(spreadsheet_id: str = None):
    """
    스프레드시트의 4개 시트를 읽어서 SQLite DB에 임포트
    1. 대시보드 → projects 테이블 (금액 정보 업데이트)
    2. 하도급상세 → trades + subcontracts 테이블
    3. 연락처 → contacts 테이블
    4. 지급내역 → payment_history 테이블
    """
    sid = spreadsheet_id or DEFAULT_SPREADSHEET_ID

    # Google Sheets 연결
    print("Google Sheets 연결 중...")
    client = connect()
    print("연결 성공!")

    # 스프레드시트 열기
    spreadsheet = client.open_by_key(sid)
    print(f"스프레드시트: {spreadsheet.title}")
    print(f"시트 목록: {[ws.title for ws in spreadsheet.worksheets()]}")
    print()

    # 프로젝트 생성 (스프레드시트 제목에서 프로젝트명 추출)
    project_name = spreadsheet.title.split("_")[0].strip()
    if not project_name:
        project_name = spreadsheet.title

    result = create_project(project_name)
    if result.get("success"):
        project_id = result["id"]
        print(f"프로젝트 생성: '{project_name}' (ID: {project_id})")
    else:
        # 이미 존재하면 기존 프로젝트 ID 조회
        from src.fund_table.db import list_projects
        projects = list_projects()
        project_id = None
        for p in projects:
            if p["name"] == project_name:
                project_id = p["id"]
                break
        if not project_id:
            print(f"오류: 프로젝트 생성 실패 — {result.get('message')}")
            return
        print(f"기존 프로젝트 사용: '{project_name}' (ID: {project_id})")

    print()

    # 시트별 임포트
    worksheets = {ws.title: ws for ws in spreadsheet.worksheets()}
    stats = {"dashboard": 0, "subcontracts": 0, "contacts": 0, "payments": 0}

    # 1) 대시보드
    for name in ["대시보드", "Dashboard"]:
        if name in worksheets:
            _import_dashboard(worksheets[name], project_id)
            stats["dashboard"] = 1
            print()
            break
    else:
        print("  [대시보드] 시트를 찾을 수 없습니다 — 건너뜀")
        print()

    # 2) 하도급상세
    for name in ["하도급상세", "하도급 상세", "Subcontracts"]:
        if name in worksheets:
            stats["subcontracts"] = _import_subcontracts(worksheets[name], project_id)
            print()
            break
    else:
        print("  [하도급상세] 시트를 찾을 수 없습니다 — 건너뜀")
        print()

    # 3) 연락처
    for name in ["연락처", "Contacts", "거래처연락처"]:
        if name in worksheets:
            stats["contacts"] = _import_contacts(worksheets[name], project_id)
            print()
            break
    else:
        print("  [연락처] 시트를 찾을 수 없습니다 — 건너뜀")
        print()

    # 4) 지급내역 (시트명에 "지급내역"이 포함된 것을 찾음)
    payment_ws = None
    for ws_name, ws in worksheets.items():
        if "지급내역" in ws_name or "지급" in ws_name:
            payment_ws = ws
            break
    if payment_ws:
        stats["payments"] = _import_payment_history(payment_ws, project_id)
    else:
        print("  [지급내역] 시트를 찾을 수 없습니다 — 건너뜀")

    # 결과 요약
    print()
    print("=" * 50)
    print("임포트 완료!")
    print(f"  프로젝트: {project_name} (ID: {project_id})")
    print(f"  대시보드: {'업데이트됨' if stats['dashboard'] else '건너뜀'}")
    print(f"  하도급상세: {stats['subcontracts']}건")
    print(f"  연락처: {stats['contacts']}건")
    print(f"  지급내역: {stats['payments']}건")
    print("=" * 50)

    return {
        "project_id": project_id,
        "project_name": project_name,
        "stats": stats,
    }


# ─── 실행 ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # 커맨드라인 인자로 스프레드시트 ID를 받을 수 있음
    sid = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SPREADSHEET_ID
    print(f"스프레드시트 ID: {sid}")
    print()

    import_from_sheets(sid)
