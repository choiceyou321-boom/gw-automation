#!/usr/bin/env python3
"""
Google Sheets → SQLite 일회성 임포트 스크립트
스프레드시트의 5개 시트(대시보드, 하도급상세, 연락처, 지급내역, 수금현황)를 읽어서 fund_management.db에 저장
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
    save_collections_bulk,
)

logger = logging.getLogger("sheets_import")

CREDENTIALS_PATH = os.path.join(PROJECT_ROOT, "config", "google_service_account.json")

# 기본 스프레드시트 ID (종로 오블리브 프로젝트_프로젝트 관리표&거래처 현황)
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


def _import_collections(ws, project_id: int) -> int:
    """
    수금현황 시트 → collections 테이블

    지원하는 시트 레이아웃 2가지:

    (A) 대시보드 통합형 (setup_google_sheets.py beautify_sheet 레이아웃)
        행14: 대분류 — "설계" / "시공" (병합 셀)
        행15: 소분류 — 계약금, 1차 중도금, 2차 중도금, 잔금, ...
        행16: 금액
        행17: 수금완료 — TRUE/FALSE

    (B) 독립 시트형 (행 단위 테이블)
        헤더: 카테고리(또는 구분), 단계, 금액, 수금완료
        데이터 행: 설계, 계약금, 100000000, TRUE
    """
    rows = ws.get_all_values()
    print(f"  [수금현황] {len(rows)}행 읽기 완료")

    if len(rows) < 2:
        print("  [수금현황] 데이터 행이 없습니다")
        return 0

    # --- 레이아웃 감지 ---
    # (B) 독립 시트형: 헤더에 "카테고리"/"구분" + "단계" + "금액" 키워드가 있는 행 찾기
    table_header_idx = _find_table_header(rows)
    if table_header_idx is not None:
        return _import_collections_table(rows, table_header_idx, project_id)

    # (A) 대시보드 통합형: "설계"/"시공" 대분류 + 소분류 + 금액 + 수금완료 행 탐색
    return _import_collections_matrix(rows, project_id)


def _find_table_header(rows: list) -> int | None:
    """독립 시트형 헤더 행 탐색 — 카테고리+단계+금액 키워드가 있는 행 반환"""
    for i, row in enumerate(rows):
        cells = [_safe_str(c).replace(" ", "") for c in row]
        has_category = any(k in c for c in cells for k in ("카테고리", "구분", "분류"))
        has_stage = any(k in c for c in cells for k in ("단계", "항목", "stage"))
        has_amount = any("금액" in c or "amount" in c.lower() for c in cells)
        if has_category and has_stage and has_amount:
            return i
    return None


def _import_collections_table(rows: list, header_idx: int, project_id: int) -> int:
    """
    독립 시트형 수금현황 파싱 (행 단위 테이블)
    헤더: 카테고리, 단계, 금액, 수금완료
    """
    header = [_safe_str(c).replace(" ", "") for c in rows[header_idx]]
    col_map = {}
    for idx, h in enumerate(header):
        if any(k in h for k in ("카테고리", "구분", "분류")):
            col_map["category"] = idx
        elif any(k in h for k in ("단계", "항목")):
            col_map["stage"] = idx
        elif "금액" in h:
            col_map["amount"] = idx
        elif any(k in h for k in ("수금완료", "수금", "완료", "collected")):
            col_map["collected"] = idx

    if "category" not in col_map or "stage" not in col_map:
        logger.warning("수금현황 테이블형: 카테고리/단계 컬럼을 찾을 수 없습니다")
        print("  [수금현황] 카테고리/단계 컬럼을 찾을 수 없습니다 — 건너뜀")
        return 0

    print(f"  [수금현황] 테이블형 컬럼 매핑: {list(col_map.keys())}")

    items = []
    for row_idx in range(header_idx + 1, len(rows)):
        row = rows[row_idx]
        if len(row) == 0:
            continue

        category = _safe_str(row[col_map["category"]]) if "category" in col_map else ""
        stage = _safe_str(row[col_map["stage"]]) if "stage" in col_map else ""
        if not category or not stage:
            continue

        amount = _parse_int(row[col_map["amount"]]) if "amount" in col_map else 0
        collected = _parse_bool(row[col_map["collected"]]) if "collected" in col_map else 0

        items.append({
            "category": category,
            "stage": stage,
            "amount": amount,
            "collected": collected,
        })

    if items:
        save_collections_bulk(project_id, items)
        print(f"  [수금현황] {len(items)}건 임포트 (테이블형)")
        return len(items)
    else:
        print("  [수금현황] 임포트할 데이터가 없습니다")
        return 0


def _import_collections_matrix(rows: list, project_id: int) -> int:
    """
    대시보드 통합형 수금현황 파싱 (매트릭스 레이아웃)

    구조 (setup_google_sheets.py 기준):
        대분류 행: "설계" / "시공" (셀 병합, 같은 행)
        소분류 행: 계약금, 1차 중도금, 2차 중도금, 잔금, ...
        금액 행:   라벨 "금액" + 각 단계별 금액
        수금완료 행: 라벨 "수금완료"/"수금" + TRUE/FALSE
    """
    # 1) "수금" 관련 섹션 시작 행 찾기 — "수금 현황" 또는 "수금현황" 라벨
    section_start = None
    for i, row in enumerate(rows):
        row_text = " ".join(_safe_str(c) for c in row)
        if "수금" in row_text and ("현황" in row_text or "수금완료" in row_text):
            section_start = i
            break

    if section_start is None:
        # 폴백: "설계"와 "시공"이 같은 행에 있는 행 찾기
        for i, row in enumerate(rows):
            cells = [_safe_str(c) for c in row]
            if any("설계" == c or "설계" in c for c in cells) and any("시공" == c or "시공" in c for c in cells):
                section_start = max(0, i - 1)
                break

    if section_start is None:
        logger.warning("수금현황 매트릭스형: 수금현황 섹션을 찾을 수 없습니다")
        print("  [수금현황] 수금현황 섹션을 찾을 수 없습니다 — 건너뜀")
        return 0

    # 2) 섹션 내에서 대분류, 소분류, 금액, 수금완료 행 탐색
    category_row_idx = None
    sub_header_row_idx = None
    amount_row_idx = None
    collected_row_idx = None

    # section_start 부터 최대 10행 범위에서 탐색
    search_end = min(section_start + 10, len(rows))
    for i in range(section_start, search_end):
        row = rows[i]
        cells = [_safe_str(c) for c in row]

        # 대분류 행: "설계" 또는 "시공" 텍스트가 있는 행
        has_design = any(c == "설계" or c.strip() == "설계" for c in cells)
        has_construction = any(c == "시공" or c.strip() == "시공" for c in cells)
        if (has_design or has_construction) and category_row_idx is None:
            category_row_idx = i
            continue

        # 소분류 행: "계약금" 키워드가 있는 행
        if any("계약금" in c for c in cells) and sub_header_row_idx is None:
            sub_header_row_idx = i
            continue

        # 금액 행: "금액" 라벨이 있는 행
        if any(c.strip() == "금액" for c in cells) and amount_row_idx is None:
            amount_row_idx = i
            continue

        # 수금완료 행: "수금완료" 또는 "수금" 라벨이 있는 행
        if any(c.strip() in ("수금완료", "수금") for c in cells) and collected_row_idx is None:
            collected_row_idx = i
            continue

    # 최소한 소분류 + 금액 OR 수금완료가 있어야 파싱 가능
    if sub_header_row_idx is None:
        logger.warning("수금현황 매트릭스형: 소분류 헤더(계약금 등)를 찾을 수 없습니다")
        print("  [수금현황] 소분류 헤더를 찾을 수 없습니다 — 건너뜀")
        return 0

    # 3) 대분류(설계/시공) 영역 매핑 — 카테고리별 열 범위 결정
    category_ranges = {}  # {카테고리명: (start_col, end_col)}
    if category_row_idx is not None:
        cat_row = rows[category_row_idx]
        current_cat = None
        for col_idx, cell in enumerate(cat_row):
            cell_text = _safe_str(cell)
            if cell_text in ("설계", "시공"):
                if current_cat:
                    # 이전 카테고리 종료
                    category_ranges[current_cat] = (category_ranges[current_cat], col_idx)
                current_cat = cell_text
                category_ranges[current_cat] = col_idx  # 시작 열 (임시)
        # 마지막 카테고리 종료
        if current_cat and isinstance(category_ranges.get(current_cat), int):
            category_ranges[current_cat] = (category_ranges[current_cat], len(cat_row))

    # 4) 소분류 헤더에서 단계명 + 열 인덱스 수집
    sub_row = rows[sub_header_row_idx]
    stage_columns = []  # [(열인덱스, 단계명)]
    for col_idx, cell in enumerate(sub_row):
        stage_name = _safe_str(cell)
        if stage_name and stage_name not in ("금액", "수금완료", "수금", "수금율"):
            stage_columns.append((col_idx, stage_name))

    if not stage_columns:
        print("  [수금현황] 단계명을 찾을 수 없습니다 — 건너뜀")
        return 0

    # 5) 각 단계에 카테고리 매핑
    def _get_category(col_idx: int) -> str:
        """열 인덱스 → 카테고리 반환"""
        for cat_name, (start, end) in category_ranges.items():
            if start <= col_idx < end:
                return cat_name
        # 카테고리 행이 없으면 열 위치로 추정 (앞쪽=설계, 뒤쪽=시공)
        if stage_columns:
            mid = len(stage_columns) // 2
            mid_col = stage_columns[mid][0]
            return "설계" if col_idx < mid_col else "시공"
        return "기타"

    # 6) 데이터 수집
    items = []
    for col_idx, stage_name in stage_columns:
        category = _get_category(col_idx) if category_ranges else "기타"

        # 금액
        amount = 0
        if amount_row_idx is not None:
            amount_row = rows[amount_row_idx]
            if col_idx < len(amount_row):
                amount = _parse_int(amount_row[col_idx])

        # 수금완료
        collected = 0
        if collected_row_idx is not None:
            collected_row = rows[collected_row_idx]
            if col_idx < len(collected_row):
                collected = _parse_bool(collected_row[col_idx])

        # 금액이 0이고 수금도 안 됐으면 빈 단계로 판단하여 건너뜀
        if amount == 0 and collected == 0:
            continue

        items.append({
            "category": category,
            "stage": stage_name,
            "amount": amount,
            "collected": collected,
        })

    if items:
        save_collections_bulk(project_id, items)
        print(f"  [수금현황] {len(items)}건 임포트 (매트릭스형)")
        return len(items)
    else:
        print("  [수금현황] 임포트할 데이터가 없습니다")
        return 0


# ─── 메인 임포트 함수 ─────────────────────────────────────────────

def import_from_sheets(spreadsheet_id: str = None):
    """
    스프레드시트의 5개 시트를 읽어서 SQLite DB에 임포트
    1. 대시보드 → projects 테이블 (금액 정보 업데이트)
    2. 하도급상세 → trades + subcontracts 테이블
    3. 연락처 → contacts 테이블
    4. 지급내역 → payment_history 테이블
    5. 수금현황 → collections 테이블
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
    stats = {
        "dashboard": 0, "subcontracts": 0, "contacts": 0,
        "payments": 0, "collections": 0,
    }

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

    print()

    # 5) 수금현황
    collection_ws = None
    # 독립 시트 탐색
    for name in ["수금현황", "수금", "Collections", "수금 현황"]:
        if name in worksheets:
            collection_ws = worksheets[name]
            break
    # 독립 시트가 없으면 대시보드에서 수금현황 매트릭스 탐색
    if collection_ws is None:
        for name in ["대시보드", "Dashboard"]:
            if name in worksheets:
                collection_ws = worksheets[name]
                break

    if collection_ws:
        stats["collections"] = _import_collections(collection_ws, project_id)
    else:
        print("  [수금현황] 시트를 찾을 수 없습니다 — 건너뜀")

    # 결과 요약
    print()
    print("=" * 50)
    print("임포트 완료!")
    print(f"  프로젝트: {project_name} (ID: {project_id})")
    print(f"  대시보드: {'업데이트됨' if stats['dashboard'] else '건너뜀'}")
    print(f"  하도급상세: {stats['subcontracts']}건")
    print(f"  연락처: {stats['contacts']}건")
    print(f"  지급내역: {stats['payments']}건")
    print(f"  수금현황: {stats['collections']}건")
    print("=" * 50)

    return {
        "project_id": project_id,
        "project_name": project_name,
        "stats": stats,
    }


# ─── PM팀 Official 시트 임포트 ─────────────────────────────────────

PM_OFFICIAL_SHEET_ID = "1zABshhlzDB_bkBPMpV4OY11xtHXYeQaHZPITaX75lOA"


def _find_project_starts(rows: list) -> list[int]:
    """프로젝트 시작 행 인덱스 찾기 (col B=숫자, col C=이름)"""
    starts = []
    for i, row in enumerate(rows):
        if len(row) > 2:
            b_val = _safe_str(row[1]).strip()
            c_val = _safe_str(row[2]).strip()
            if b_val.isdigit() and c_val:
                starts.append(i)
    return starts


def _parse_grade_map(rows: list) -> dict:
    """
    시트 상단 등급 범례 파싱 (예: '1등급', '17', 'KOM, 2~3차 보고, ...').
    rows[3~8] 범위에서 등급명이 있는 행을 탐색.
    반환: { '1등급': {...}, '2등급': {...}, ... }
    """
    grade_map = {}
    for i in range(0, min(10, len(rows))):
        row = rows[i]
        for j, cell in enumerate(row):
            ct = _safe_str(cell).strip()
            if ct and "등급" in ct and ct[0].isdigit():
                grade_map[ct] = {"label": ct}
    return grade_map


def _detect_grade(row_idx: int, rows: list) -> str:
    """
    프로젝트 행에서 등급 판별.
    등급 구간 헤더(1등급/2등급/...)가 프로젝트 시작 행보다 위에 있으면
    해당 프로젝트는 그 등급에 속함.
    """
    # 프로젝트 행 위쪽을 올라가면서 등급 헤더 탐색
    for i in range(row_idx - 1, -1, -1):
        row = rows[i]
        for cell in row:
            ct = _safe_str(cell).strip()
            if ct and "등급" in ct and ct[0].isdigit():
                return ct
    return "4등급"


def _parse_pm_project(rows: list, start: int, end: int, name: str) -> dict:
    """
    PM Official 시트에서 하나의 프로젝트 블록 파싱.
    반환: { name, grade, members, milestones, overview, collections }
    """
    proj = {
        "name": name,
        "grade": _detect_grade(start, rows),
        "members": [],
        "milestones": [],
        "overview": {},
        "collections": [],
    }

    role_keywords = {
        "PM", "공간", "시공", "미술", "시각", "파머스", "개발", "운영",
        "인테리어", "건축", "조경", "구조", "기계", "전기", "소방", "브랜드",
    }

    for r in range(start, end):
        row = rows[r]
        if len(row) < 5:
            continue

        col_d = _safe_str(row[3]).strip()  # 역할 또는 라벨
        col_e = _safe_str(row[4]).strip()  # 이름 또는 값

        # 배정인원
        if col_d in role_keywords and col_e:
            extra = _safe_str(row[5]).strip() if len(row) > 5 else ""
            full_name = f"{col_e}, {extra}" if extra and extra not in col_e else col_e
            proj["members"].append({"role": col_d, "name": full_name})

        # 개요 정보 (라벨 → 값 매핑)
        if col_d == "위치" and col_e:
            proj["overview"]["location"] = col_e
        elif col_d == "용도" and col_e:
            proj["overview"]["usage"] = col_e
        elif col_d == "규모" and col_e:
            proj["overview"]["scale"] = col_e
        elif "연면적" in col_d and col_e:
            try:
                area = float(col_e.replace(",", ""))
                if not proj["overview"].get("area_pyeong"):
                    proj["overview"]["area_pyeong"] = area
            except ValueError:
                pass
        elif "카테고리" in col_d and col_e:
            proj["overview"]["project_category"] = col_e

        # 마일스톤 (col H=이름, col J=체크, col K=날짜)
        if len(row) > 9:
            ms_name = _safe_str(row[7]).strip()
            ms_check = _safe_str(row[9]).strip()
            ms_date = _safe_str(row[10]).strip() if len(row) > 10 else ""

            skip_labels = {"일정\n체크", "일정 체크", "일정체크", ""}
            if ms_name and ms_name not in skip_labels:
                if not any(m["name"] == ms_name for m in proj["milestones"]):
                    proj["milestones"].append({
                        "name": ms_name,
                        "completed": 1 if ms_check.upper() == "TRUE" else 0,
                        "date": ms_date,
                    })

        # 이슈사항 (col M~O 영역)
        if len(row) > 14:
            issue_label = _safe_str(row[13]).strip()
            issue_val = _safe_str(row[14]).strip()

            issue_map = {
                "디자인/인허가": "issue_design",
                "일정": "issue_schedule",
                "예산": "issue_budget",
                "운영": "issue_operation",
                "하자": "issue_defect",
                "기타": "issue_other",
            }
            if issue_label in issue_map and issue_val:
                # 여러 컬럼에 걸쳐있을 수 있음
                vals = [issue_val]
                for c in range(15, min(len(row), 22)):
                    v = _safe_str(row[c]).strip()
                    if v:
                        vals.append(v)
                proj["overview"][issue_map[issue_label]] = " / ".join(vals)

        # 수금현황 (col N~)
        if len(row) > 14:
            col_n = _safe_str(row[13]).strip()
            col_o = _safe_str(row[14]).strip()
            if col_n == "총 계약금" and col_o:
                proj["overview"]["design_contract_amount"] = _parse_int(col_o)

    return proj


def import_from_pm_sheet(
    spreadsheet_id: str = None,
    owner_gw_id: str = "",
    mode: str = "upsert",
) -> dict:
    """
    PM팀 Official 시트에서 전체 프로젝트 기본정보를 읽어 DB에 반영.

    Args:
        spreadsheet_id: 스프레드시트 ID (기본: PM_OFFICIAL_SHEET_ID)
        owner_gw_id: 신규 프로젝트 소유자 GW ID
        mode: 'upsert' (기존 프로젝트 업데이트 + 신규 생성) 또는 'insert_only' (신규만)

    Returns:
        { success, created, updated, skipped, errors, projects: [...] }
    """
    from src.fund_table.db import (
        get_db, create_project, update_project, list_projects,
        save_project_overview, save_collections_bulk,
    )

    sid = spreadsheet_id or PM_OFFICIAL_SHEET_ID

    logger.info("PM Official 시트 임포트 시작: %s", sid)

    # Google Sheets 연결
    client = connect()
    spreadsheet = client.open_by_key(sid)
    logger.info("스프레드시트: %s (시트: %s)", spreadsheet.title,
                [ws.title for ws in spreadsheet.worksheets()])

    # 가장 최신 시트 찾기 (날짜가 포함된 시트명 또는 첫 번째 시트)
    worksheets = spreadsheet.worksheets()
    target_ws = None

    # 날짜 패턴(260316, 260312 등)이 포함된 시트 중 가장 큰 숫자
    import re
    date_sheets = []
    for ws in worksheets:
        match = re.search(r"(\d{6})", ws.title)
        if match:
            date_sheets.append((int(match.group(1)), ws))

    if date_sheets:
        date_sheets.sort(key=lambda x: x[0], reverse=True)
        target_ws = date_sheets[0][1]
        logger.info("최신 시트 선택: %s", target_ws.title)
    else:
        # 날짜 시트가 없으면 첫 번째 시트 사용
        target_ws = worksheets[0]
        logger.info("첫 번째 시트 사용: %s", target_ws.title)

    rows = target_ws.get_all_values()
    logger.info("전체 %d행 읽기 완료", len(rows))

    # 프로젝트 시작 행 찾기
    proj_starts = _find_project_starts(rows)
    if not proj_starts:
        return {
            "success": False, "error": "프로젝트를 찾을 수 없습니다.",
            "created": 0, "updated": 0, "skipped": 0, "errors": [],
        }

    logger.info("프로젝트 %d개 발견", len(proj_starts))

    # 기존 프로젝트 목록 (이름 → ID 매핑)
    existing_projects = {p["name"]: p for p in list_projects()}

    # 각 프로젝트 파싱 및 DB 저장
    created = 0
    updated = 0
    skipped = 0
    errors = []
    project_results = []
    seen_names = set()

    for idx, start in enumerate(proj_starts):
        end = proj_starts[idx + 1] if idx + 1 < len(proj_starts) else len(rows)
        raw_name = _safe_str(rows[start][2]).strip()

        # 중복 제거
        dedup_key = raw_name.replace(" ", "")
        if dedup_key in seen_names:
            continue
        seen_names.add(dedup_key)

        # 파싱
        try:
            proj = _parse_pm_project(rows, start, end, raw_name)
        except Exception as e:
            errors.append(f"{raw_name}: 파싱 실패 — {e}")
            logger.warning("프로젝트 파싱 실패: %s — %s", raw_name, e)
            continue

        # DB 저장
        try:
            existing = existing_projects.get(raw_name)

            if existing and mode == "insert_only":
                skipped += 1
                project_results.append({
                    "name": raw_name, "status": "skipped", "id": existing["id"],
                })
                continue

            if existing:
                # 기존 프로젝트 업데이트
                project_id = existing["id"]
                update_kwargs = {}
                if proj["grade"]:
                    update_kwargs["grade"] = proj["grade"]
                if proj["overview"].get("project_category"):
                    update_kwargs["description"] = proj["overview"]["project_category"]
                if proj["overview"].get("design_contract_amount"):
                    update_kwargs["design_amount"] = proj["overview"]["design_contract_amount"]
                if proj["overview"].get("construction_contract_amount"):
                    update_kwargs["construction_amount"] = proj["overview"]["construction_contract_amount"]

                if update_kwargs:
                    update_project(project_id, **update_kwargs)

                # 개요 업데이트
                if proj["overview"]:
                    ov_data = dict(proj["overview"])
                    if proj["members"]:
                        ov_data["members"] = proj["members"]
                    if proj["milestones"]:
                        ov_data["milestones"] = proj["milestones"]
                    save_project_overview(project_id, ov_data)

                updated += 1
                project_results.append({
                    "name": raw_name, "status": "updated", "id": project_id,
                })

            else:
                # 신규 프로젝트 생성
                create_kwargs = {
                    "grade": proj["grade"] or "4등급",
                }
                if owner_gw_id:
                    create_kwargs["owner_gw_id"] = owner_gw_id
                if proj["overview"].get("project_category"):
                    create_kwargs["description"] = proj["overview"]["project_category"]
                if proj["overview"].get("design_contract_amount"):
                    create_kwargs["design_amount"] = proj["overview"]["design_contract_amount"]
                if proj["overview"].get("construction_contract_amount"):
                    create_kwargs["construction_amount"] = proj["overview"]["construction_contract_amount"]

                result = create_project(raw_name, **create_kwargs)
                if not result.get("success"):
                    errors.append(f"{raw_name}: 생성 실패 — {result.get('message')}")
                    skipped += 1
                    continue

                project_id = result["id"]

                # 개요 저장
                if proj["overview"]:
                    ov_data = dict(proj["overview"])
                    if proj["members"]:
                        ov_data["members"] = proj["members"]
                    if proj["milestones"]:
                        ov_data["milestones"] = proj["milestones"]
                    save_project_overview(project_id, ov_data)

                # 수금현황 저장
                if proj["collections"]:
                    save_collections_bulk(project_id, proj["collections"])

                created += 1
                project_results.append({
                    "name": raw_name, "status": "created", "id": project_id,
                })

        except Exception as e:
            errors.append(f"{raw_name}: DB 저장 실패 — {e}")
            logger.error("프로젝트 DB 저장 실패: %s — %s", raw_name, e, exc_info=True)

    logger.info(
        "PM 시트 임포트 완료: 생성 %d, 업데이트 %d, 스킵 %d, 오류 %d",
        created, updated, skipped, len(errors),
    )

    return {
        "success": True,
        "sheet_title": target_ws.title,
        "total_found": len(proj_starts),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "projects": project_results,
    }


# ─── 실행 ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # 커맨드라인 인자로 모드 선택
    if len(sys.argv) > 1 and sys.argv[1] == "--pm":
        # PM Official 시트 임포트
        sid = sys.argv[2] if len(sys.argv) > 2 else PM_OFFICIAL_SHEET_ID
        print(f"PM Official 시트 임포트: {sid}")
        result = import_from_pm_sheet(sid)
        print(f"\n결과: 생성 {result['created']}, 업데이트 {result['updated']}, "
              f"스킵 {result['skipped']}, 오류 {len(result['errors'])}")
        if result["errors"]:
            for e in result["errors"]:
                print(f"  오류: {e}")
    else:
        # 기존 프로젝트 관리표 시트 임포트
        sid = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SPREADSHEET_ID
        print(f"스프레드시트 ID: {sid}")
        print()
        import_from_sheets(sid)
