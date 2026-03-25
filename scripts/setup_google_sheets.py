#!/usr/bin/env python3
"""
Google Sheets API 연동 — 프로젝트 관리표 분석 및 정리
사용법: python scripts/setup_google_sheets.py [--analyze | --beautify | --all]

--analyze  : 시트 구조 및 수식 분석만 수행
--beautify : 시트 서식 정리 + 수식 적용
--all      : 분석 + 정리 모두 (기본값)
"""

import json
import sys
import os
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDENTIALS_PATH = os.path.join(PROJECT_ROOT, "config", "google_service_account.json")
SPREADSHEET_ID = "1m4vLJakrcd3g2LtiWBSTRoCdWM_6iObll1fO-DyZK6w"

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    print("필요한 패키지를 설치합니다...")
    os.system("pip install gspread google-auth google-api-python-client")
    import gspread
    from google.oauth2.service_account import Credentials


# ─── 유틸리티 ──────────────────────────────────────────────────

def _col_letter(n):
    """열 번호 → 알파벳 (1=A, 26=Z, 27=AA)"""
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _rgb(hex_color):
    """#RRGGBB → Google Sheets API 색상 dict"""
    h = hex_color.lstrip("#")
    return {
        "red": int(h[0:2], 16) / 255,
        "green": int(h[2:4], 16) / 255,
        "blue": int(h[4:6], 16) / 255,
    }


# ─── 색상 팔레트 ───────────────────────────────────────────────

COLORS = {
    "header_bg": _rgb("#1F4E79"),       # 진한 남색 (제목)
    "header_text": _rgb("#FFFFFF"),      # 흰색
    "label_bg": _rgb("#D6E4F0"),         # 연한 파랑 (라벨)
    "value_bg": _rgb("#FFFFFF"),         # 흰색 (값)
    "profit_bg": _rgb("#FFF2CC"),        # 연한 노랑 (수익금 강조)
    "profit_text": _rgb("#B45F06"),      # 진한 주황 (수익금 텍스트)
    "sub_header_bg": _rgb("#2E75B6"),    # 중간 파랑 (수금현황 헤더)
    "complete_bg": _rgb("#C6EFCE"),      # 연한 초록 (수금완료)
    "incomplete_bg": _rgb("#FFC7CE"),    # 연한 빨강 (미수금)
    "border": _rgb("#B4B4B4"),           # 회색 테두리
    "section_bg": _rgb("#F2F2F2"),       # 연한 회색 (구분행)
    "pct_positive": _rgb("#006100"),     # 초록 (양호 비율)
    "pct_warning": _rgb("#9C5700"),      # 주황 (주의 비율)
}


# ─── 인증 ──────────────────────────────────────────────────────

def check_credentials():
    """서비스 계정 키 파일 존재 여부 확인"""
    if os.path.exists(CREDENTIALS_PATH):
        with open(CREDENTIALS_PATH) as f:
            data = json.load(f)
        email = data.get("client_email", "알 수 없음")
        print(f"✅ 서비스 계정 키 발견")
        print(f"   이메일: {email}")
        return True

    print("=" * 60)
    print("❌ Google 서비스 계정 키가 없습니다.")
    print("=" * 60)
    print()
    print("설정 가이드를 확인해주세요:")
    print(f"   📄 {PROJECT_ROOT}/docs/google_sheets_setup_guide.md")
    print()
    print(f"키 파일 저장 위치:")
    print(f"   📁 {CREDENTIALS_PATH}")
    print("=" * 60)
    return False


def connect():
    """Google Sheets API 연결"""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    client = gspread.authorize(creds)
    return client


# ─── 분석 ──────────────────────────────────────────────────────

def analyze_formulas(client):
    """모든 시트의 수식 관계 분석"""
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    print("\n" + "=" * 60)
    print(f"📊 스프레드시트: {spreadsheet.title}")
    print("=" * 60)

    all_sheets_info = []

    for ws in spreadsheet.worksheets():
        print(f"\n{'─' * 50}")
        print(f"📄 시트: {ws.title} (gid={ws.id})")
        print(f"   크기: {ws.row_count}행 × {ws.col_count}열")
        print(f"{'─' * 50}")

        # 값과 수식 모두 가져오기
        values = ws.get_all_values()
        formulas = ws.get_all_values(
            value_render_option=gspread.utils.ValueRenderOption.formula
        )

        sheet_info = {
            "title": ws.title,
            "gid": ws.id,
            "rows": len(values),
            "cols": max(len(row) for row in values) if values else 0,
            "formulas": [],
            "values": values,
            "formula_data": formulas,
        }

        # 수식 셀 탐지
        formula_cells = []
        for r, (val_row, form_row) in enumerate(zip(values, formulas)):
            for c, (val, form) in enumerate(zip(val_row, form_row)):
                if form and isinstance(form, str) and form.startswith("="):
                    cell_ref = _col_letter(c + 1) + str(r + 1)
                    formula_cells.append({
                        "cell": cell_ref,
                        "formula": form,
                        "value": val,
                    })

        sheet_info["formulas"] = formula_cells
        all_sheets_info.append(sheet_info)

        # 데이터 출력 (비어있지 않은 행만)
        print("\n📋 데이터:")
        for r, row in enumerate(values):
            non_empty = [c for c in row if c.strip()]
            if non_empty:
                cells = []
                for c in row[:12]:
                    cells.append(c.strip() if c.strip() else "·")
                print(f"  행{r+1:>3}: {' | '.join(cells)}")

        # 수식 출력
        if formula_cells:
            print(f"\n📐 수식 ({len(formula_cells)}개):")
            for fc in formula_cells:
                print(f"  {fc['cell']:>5} = {fc['formula']}")
                print(f"         → 결과: {fc['value']}")
        else:
            print("\n  ⚠️  수식 없음 — 모든 값이 직접 입력된 상태")
            print("      beautify 모드에서 수식을 자동으로 넣어줍니다.")

    # 분석 결과 저장
    output_path = os.path.join(PROJECT_ROOT, "data", "fund_table_analysis.json")
    analysis = []
    for si in all_sheets_info:
        analysis.append({
            "title": si["title"],
            "gid": si["gid"],
            "rows": si["rows"],
            "cols": si["cols"],
            "formula_count": len(si["formulas"]),
            "formulas": si["formulas"],
        })
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    print(f"\n💾 분석 결과 저장: {output_path}")

    return all_sheets_info


# ─── 시트 정리 ─────────────────────────────────────────────────

def beautify_sheet(client, sheets_info=None):
    """
    시트 구조 재배치 + 수식 적용 + 서식 정리

    최종 레이아웃:
    행1:  [제목] 종로 메디빌더 오블리브 의원 — 프로젝트 관리표
    행2:  (빈 행)
    행3:  ┌─ 수주/예산 요약 ─────────┬─ 지급/집행 요약 ─────────┐
    행4:  │  설계 수주액   | 값      │  하도급 계약 한도액 | 값  │
    행5:  │  시공 수주액   | 값      │  기지급 비용       | 값  │
    행6:  │  총 수주가액   | =SUM    │  집행 잔액         | =차 │
    행7:  │  실행 예산     | 값      │  한도 대비 집행율  | =% │
    행8:  │  실행 예산율   | =비율   │  총 지급율         | =% │
    행9:  │  기성 수금액   | 값      │  수익금            | =차 │
    행10: │  수금 대금 회수율| =비율  │  이익율            | =% │
    행11: └──────────────────────────┴──────────────────────────┘
    행12: (빈 행)
    행13: ┌─ 수금 현황 ────────────────────────────────────────┐
    행14: │      │ 설계                    │ 시공               │
    행15: │      │ 계약금│1차중도│2차중도│잔금│계약금│1차│2차│잔금│
    행16: │ 금액 │ ...   │ ...   │ ...  │... │ ... │...│...│...│
    행17: │ 수금 │ O/X   │ O/X   │ O/X  │O/X │ O/X │O/X│O/X│O/X│
    행18: │ 수금율│ ...%  │ ...%  │ ...% │...%│ ...%│..%│..%│..%│
    행19: └────────────────────────────────────────────────────┘
    """
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    ws = spreadsheet.sheet1
    sheet_id = ws.id

    print("\n" + "=" * 60)
    print("🎨 시트 정리 시작")
    print("=" * 60)

    # ── 1단계: 현재 데이터 읽기 ──
    current = ws.get_all_values()
    current_formulas = ws.get_all_values(
        value_render_option=gspread.utils.ValueRenderOption.formula
    )
    print(f"  현재 데이터: {len(current)}행")

    # ── 2단계: 새 레이아웃 데이터 준비 ──
    # 현재 시트에서 직접 입력값 추출 (수식이 아닌 원본 값)
    # 행 인덱스는 0-based (CSV export 기준)
    # 현재 구조: 행0=빈행, 행1~7=요약, 행8=빈행, 행9=빈행, 행10~11=설계/시공헤더, 행12=서브헤더, 행13=금액, 행14=수금완료, 행15=수금율

    print("  데이터 재배치 중...")

    # 새 레이아웃 (19행 × 10열)
    new_data = [[""] * 10 for _ in range(19)]

    # 행1: 제목 (B1:I1 병합할 예정)
    new_data[0][1] = "종로 메디빌더 오블리브 의원 — 프로젝트 관리표"

    # 행3: 섹션 헤더
    new_data[2][1] = "수주 / 예산 요약"
    new_data[2][5] = "지급 / 집행 요약"

    # 행4~10: 좌측 (수주/예산)  |  우측 (지급/집행)
    labels_left = [
        ("설계 수주액", "", ""),
        ("시공 수주액", "2900000000", ""),
        ("총 수주가액", "=D5+D6", ""),
        ("실행 예산", "2375320240", ""),
        ("실행 예산율", "=D8/D7", ""),
        ("기성 수금액", "2000000000", ""),
        ("수금 대금 회수율", "=D10/D7", ""),
    ]
    labels_right = [
        ("하도급 계약 한도액", "1638151890", ""),
        ("기지급 비용", "778008415", ""),
        ("집행 잔액", "=G5-G6", ""),
        ("한도 대비 집행율", "=G6/G5", ""),
        ("총 지급율", "=G6/D7", ""),
        ("수익금", "=D7-D8", ""),
        ("이익율", "=G10/D7", ""),
    ]

    for i, ((lbl_l, val_l, _), (lbl_r, val_r, __)) in enumerate(zip(labels_left, labels_right)):
        row = 3 + i  # 행4~10 (0-based: 3~9)
        new_data[row][2] = lbl_l       # C열: 좌측 라벨
        new_data[row][3] = val_l       # D열: 좌측 값
        new_data[row][5] = lbl_r       # F열: 우측 라벨
        new_data[row][6] = val_r       # G열: 우측 값

    # 행12: 빈 행 (구분)

    # 행13: 수금현황 섹션 헤더
    new_data[12][1] = "수금 현황"

    # 행14: 대분류 (설계 / 시공)
    new_data[13][2] = ""
    new_data[13][3] = "설계"
    new_data[13][7] = "시공"

    # 행15: 소분류 헤더
    sub_headers = ["", "", "", "계약금", "1차 중도금", "2차 중도금", "잔금", "계약금", "1차 중도금", "2차 중도금"]
    for c, h in enumerate(sub_headers):
        new_data[14][c] = h
    # J열에 잔금 추가 (10열 확장 필요)

    # 행16: 금액
    new_data[15][1] = "금액"
    new_data[15][7] = "1000000000"   # 시공 계약금
    new_data[15][8] = "1000000000"   # 시공 1차 중도금

    # 행17: 수금완료
    new_data[16][1] = "수금완료"
    for c in range(3, 7):   # 설계 4칸
        new_data[16][c] = "FALSE"
    new_data[16][7] = "TRUE"    # 시공 계약금
    new_data[16][8] = "TRUE"    # 시공 1차 중도금
    new_data[16][9] = "FALSE"   # 시공 2차 중도금

    # 행18: 수금율 (누적)
    new_data[17][1] = "수금율"

    # 10열 → 11열로 확장 (잔금 열 추가)
    for row in new_data:
        row.append("")
    # K열(index 10): 잔금
    new_data[14][10] = "잔금"
    new_data[15][9] = ""          # 시공 2차 중도금 금액: 없음
    new_data[15][10] = "900000000"  # 시공 잔금
    new_data[16][10] = "FALSE"      # 시공 잔금 미수금

    # 수금율 수식 (누적 합계 / 총 수주가액)
    # 시공: G열=계약금, H열=1차중도금, I열=2차중도금, J열=잔금 → K열
    # 수금율은 해당 열까지 누적 TRUE인 금액 합 / D7
    new_data[17][7] = "=H16/D7"              # 시공 계약금까지
    new_data[17][8] = "=(H16+I16)/D7"        # 시공 1차 중도금까지
    new_data[17][9] = "=(H16+I16+J16)/D7"    # 시공 2차 중도금까지
    new_data[17][10] = "=(H16+I16+J16+K16)/D7"  # 잔금까지

    # ── 3단계: 시트에 쓰기 ──
    print("  데이터 입력 중...")

    # 시트 크기 확장
    ws.resize(rows=20, cols=11)
    time.sleep(0.5)

    # 전체 클리어 후 새 데이터 쓰기
    ws.clear()
    time.sleep(0.5)

    # 셀 범위 업데이트 (RAW 모드로 수식도 그대로 입력)
    ws.update("A1:K19", new_data, value_input_option="USER_ENTERED")
    time.sleep(1)
    print("  ✅ 데이터 입력 완료")

    # ── 4단계: 서식 적용 ──
    print("  서식 적용 중...")
    requests = _build_format_requests(sheet_id)

    # batch update (한 번에 전송)
    spreadsheet.batch_update({"requests": requests})
    print("  ✅ 서식 적용 완료")

    # ── 5단계: 조건부 서식 (수금완료 TRUE=초록, FALSE=빨강) ──
    print("  조건부 서식 적용 중...")
    _apply_conditional_formatting(spreadsheet, sheet_id)
    print("  ✅ 조건부 서식 완료")

    print("\n" + "=" * 60)
    print("🎉 시트 정리 완료!")
    print(f"   https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")
    print("=" * 60)


def _build_format_requests(sheet_id):
    """배치 서식 요청 목록 생성"""
    requests = []

    thin_border = {
        "style": "SOLID",
        "width": 1,
        "color": COLORS["border"],
    }
    medium_border = {
        "style": "SOLID_MEDIUM",
        "width": 2,
        "color": COLORS["header_bg"],
    }

    # ── 전체 기본 폰트 ──
    requests.append(_repeat_cell(sheet_id, 0, 20, 0, 11, {
        "textFormat": {"fontFamily": "맑은 고딕", "fontSize": 10},
        "verticalAlignment": "MIDDLE",
    }))

    # ── 행1: 제목 ──
    requests.append(_repeat_cell(sheet_id, 0, 1, 1, 11, {
        "backgroundColor": COLORS["header_bg"],
        "textFormat": {
            "fontFamily": "맑은 고딕", "fontSize": 14,
            "bold": True, "foregroundColor": COLORS["header_text"],
        },
        "horizontalAlignment": "CENTER",
        "verticalAlignment": "MIDDLE",
    }))
    # 제목 행 높이
    requests.append(_row_height(sheet_id, 0, 1, 50))

    # 제목 셀 병합 (B1:K1)
    requests.append({
        "mergeCells": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 1, "endColumnIndex": 11},
            "mergeType": "MERGE_ALL",
        }
    })

    # ── 행3: 섹션 헤더 ──
    for col_start, col_end in [(1, 5), (5, 8)]:
        requests.append(_repeat_cell(sheet_id, 2, 3, col_start, col_end, {
            "backgroundColor": COLORS["section_bg"],
            "textFormat": {"fontFamily": "맑은 고딕", "fontSize": 10, "bold": True},
            "horizontalAlignment": "LEFT" if col_start == 1 else "LEFT",
        }))
    # 병합: B3:E3, F3:H3
    requests.append(_merge(sheet_id, 2, 3, 1, 5))
    requests.append(_merge(sheet_id, 2, 3, 5, 8))

    # ── 행4~10: 요약 영역 라벨 (C열, F열) ──
    for col in [2, 5]:  # C, F
        requests.append(_repeat_cell(sheet_id, 3, 10, col, col + 1, {
            "backgroundColor": COLORS["label_bg"],
            "textFormat": {"fontFamily": "맑은 고딕", "fontSize": 10, "bold": True},
            "horizontalAlignment": "RIGHT",
            "verticalAlignment": "MIDDLE",
        }))

    # ── 행4~10: 금액 값 (D열, G열) ──
    for col in [3, 6]:  # D, G
        requests.append(_repeat_cell(sheet_id, 3, 10, col, col + 1, {
            "horizontalAlignment": "RIGHT",
            "numberFormat": {"type": "NUMBER", "pattern": "#,##0"},
            "textFormat": {"fontFamily": "맑은 고딕", "fontSize": 10},
        }))

    # ── 비율 셀 (D8, D10, G7~G8, G10) — 백분율 포맷 ──
    pct_cells = [(7, 3), (9, 3), (6, 6), (7, 6), (9, 6)]  # (row0, col0)
    for r, c in pct_cells:
        requests.append(_repeat_cell(sheet_id, r, r + 1, c, c + 1, {
            "horizontalAlignment": "CENTER",
            "numberFormat": {"type": "PERCENT", "pattern": "0.00%"},
            "textFormat": {"fontFamily": "맑은 고딕", "fontSize": 10, "bold": True},
        }))

    # ── 수익금 행 강조 (행10: F=수익금, G=값) ──
    requests.append(_repeat_cell(sheet_id, 8, 9, 5, 8, {
        "backgroundColor": COLORS["profit_bg"],
        "textFormat": {
            "fontFamily": "맑은 고딕", "fontSize": 11, "bold": True,
            "foregroundColor": COLORS["profit_text"],
        },
    }))

    # ── 이익율 행 강조 (행10) ──
    requests.append(_repeat_cell(sheet_id, 9, 10, 5, 8, {
        "backgroundColor": COLORS["profit_bg"],
    }))

    # ── 요약 영역 테두리 ──
    requests.append(_borders(sheet_id, 3, 10, 2, 4, thin_border))  # 좌측
    requests.append(_borders(sheet_id, 3, 10, 5, 8, thin_border))  # 우측
    requests.append(_outer_border(sheet_id, 3, 10, 2, 8, medium_border))  # 외곽

    # ── 행13: 수금현황 섹션 헤더 ──
    requests.append(_repeat_cell(sheet_id, 12, 13, 1, 11, {
        "backgroundColor": COLORS["section_bg"],
        "textFormat": {"fontFamily": "맑은 고딕", "fontSize": 10, "bold": True},
    }))
    requests.append(_merge(sheet_id, 12, 13, 1, 11))

    # ── 행14: 대분류 헤더 (설계/시공) ──
    requests.append(_repeat_cell(sheet_id, 13, 14, 3, 11, {
        "backgroundColor": COLORS["sub_header_bg"],
        "textFormat": {
            "fontFamily": "맑은 고딕", "fontSize": 10, "bold": True,
            "foregroundColor": COLORS["header_text"],
        },
        "horizontalAlignment": "CENTER",
    }))
    # 설계 병합 (D14:G14), 시공 병합 (H14:K14)
    requests.append(_merge(sheet_id, 13, 14, 3, 7))
    requests.append(_merge(sheet_id, 13, 14, 7, 11))

    # ── 행15: 소분류 헤더 ──
    requests.append(_repeat_cell(sheet_id, 14, 15, 1, 11, {
        "backgroundColor": COLORS["label_bg"],
        "textFormat": {"fontFamily": "맑은 고딕", "fontSize": 9, "bold": True},
        "horizontalAlignment": "CENTER",
    }))

    # ── 행16: 금액 행 ──
    requests.append(_repeat_cell(sheet_id, 15, 16, 1, 2, {
        "backgroundColor": COLORS["label_bg"],
        "textFormat": {"fontFamily": "맑은 고딕", "fontSize": 10, "bold": True},
        "horizontalAlignment": "CENTER",
    }))
    requests.append(_repeat_cell(sheet_id, 15, 16, 2, 11, {
        "horizontalAlignment": "RIGHT",
        "numberFormat": {"type": "NUMBER", "pattern": "#,##0"},
        "textFormat": {"fontFamily": "맑은 고딕", "fontSize": 9},
    }))

    # ── 행17: 수금완료 라벨 ──
    requests.append(_repeat_cell(sheet_id, 16, 17, 1, 2, {
        "backgroundColor": COLORS["label_bg"],
        "textFormat": {"fontFamily": "맑은 고딕", "fontSize": 10, "bold": True},
        "horizontalAlignment": "CENTER",
    }))
    requests.append(_repeat_cell(sheet_id, 16, 17, 2, 11, {
        "horizontalAlignment": "CENTER",
        "textFormat": {"fontFamily": "맑은 고딕", "fontSize": 10, "bold": True},
    }))

    # ── 행18: 수금율 라벨 ──
    requests.append(_repeat_cell(sheet_id, 17, 18, 1, 2, {
        "backgroundColor": COLORS["label_bg"],
        "textFormat": {"fontFamily": "맑은 고딕", "fontSize": 10, "bold": True},
        "horizontalAlignment": "CENTER",
    }))
    requests.append(_repeat_cell(sheet_id, 17, 18, 2, 11, {
        "horizontalAlignment": "CENTER",
        "numberFormat": {"type": "PERCENT", "pattern": "0.00%"},
        "textFormat": {"fontFamily": "맑은 고딕", "fontSize": 10},
    }))

    # ── 수금현황 테두리 ──
    requests.append(_borders(sheet_id, 13, 18, 1, 11, thin_border))
    requests.append(_outer_border(sheet_id, 12, 18, 1, 11, medium_border))

    # ── 열 너비 ──
    widths = {
        0: 10,    # A: 여백
        1: 90,    # B: 라벨
        2: 160,   # C: 항목명
        3: 155,   # D: 금액/계약금
        4: 115,   # E: 1차중도금
        5: 160,   # F: 항목명/2차중도금
        6: 155,   # G: 금액/잔금
        7: 130,   # H: 계약금
        8: 130,   # I: 1차중도금
        9: 115,   # J: 2차중도금
        10: 130,  # K: 잔금
    }
    for col, w in widths.items():
        requests.append(_col_width(sheet_id, col, w))

    # ── 행 높이 ──
    for r in range(1, 19):
        requests.append(_row_height(sheet_id, r, r + 1, 30))
    # 빈 행은 낮게
    for r in [1, 11]:
        requests.append(_row_height(sheet_id, r, r + 1, 15))

    # ── 그리드라인 숨기기 (깔끔한 외관) ──
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {"hideGridlines": True},
            },
            "fields": "gridProperties.hideGridlines",
        }
    })

    return requests


def _apply_conditional_formatting(spreadsheet, sheet_id):
    """수금완료 TRUE/FALSE 조건부 서식"""
    requests = [
        # TRUE → 초록 배경
        {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{"sheetId": sheet_id, "startRowIndex": 16, "endRowIndex": 17, "startColumnIndex": 3, "endColumnIndex": 11}],
                    "booleanRule": {
                        "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "TRUE"}]},
                        "format": {
                            "backgroundColor": COLORS["complete_bg"],
                            "textFormat": {"foregroundColor": _rgb("#006100")},
                        },
                    },
                },
                "index": 0,
            }
        },
        # FALSE → 빨강 배경
        {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{"sheetId": sheet_id, "startRowIndex": 16, "endRowIndex": 17, "startColumnIndex": 3, "endColumnIndex": 11}],
                    "booleanRule": {
                        "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "FALSE"}]},
                        "format": {
                            "backgroundColor": COLORS["incomplete_bg"],
                            "textFormat": {"foregroundColor": _rgb("#9C0006")},
                        },
                    },
                },
                "index": 1,
            }
        },
    ]
    spreadsheet.batch_update({"requests": requests})


# ─── 서식 헬퍼 ─────────────────────────────────────────────────

def _repeat_cell(sid, r1, r2, c1, c2, fmt):
    """repeatCell 요청 생성"""
    fields = []
    for key in fmt:
        if key == "textFormat":
            fields.append("userEnteredFormat.textFormat")
        elif key == "backgroundColor":
            fields.append("userEnteredFormat.backgroundColor")
        elif key == "horizontalAlignment":
            fields.append("userEnteredFormat.horizontalAlignment")
        elif key == "verticalAlignment":
            fields.append("userEnteredFormat.verticalAlignment")
        elif key == "numberFormat":
            fields.append("userEnteredFormat.numberFormat")

    return {
        "repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": r1, "endRowIndex": r2, "startColumnIndex": c1, "endColumnIndex": c2},
            "cell": {"userEnteredFormat": fmt},
            "fields": ",".join(fields),
        }
    }


def _borders(sid, r1, r2, c1, c2, style):
    return {
        "updateBorders": {
            "range": {"sheetId": sid, "startRowIndex": r1, "endRowIndex": r2, "startColumnIndex": c1, "endColumnIndex": c2},
            "top": style, "bottom": style, "left": style, "right": style,
            "innerHorizontal": style, "innerVertical": style,
        }
    }


def _outer_border(sid, r1, r2, c1, c2, style):
    return {
        "updateBorders": {
            "range": {"sheetId": sid, "startRowIndex": r1, "endRowIndex": r2, "startColumnIndex": c1, "endColumnIndex": c2},
            "top": style, "bottom": style, "left": style, "right": style,
        }
    }


def _merge(sid, r1, r2, c1, c2):
    return {
        "mergeCells": {
            "range": {"sheetId": sid, "startRowIndex": r1, "endRowIndex": r2, "startColumnIndex": c1, "endColumnIndex": c2},
            "mergeType": "MERGE_ALL",
        }
    }


def _col_width(sid, col, width):
    return {
        "updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": col, "endIndex": col + 1},
            "properties": {"pixelSize": width},
            "fields": "pixelSize",
        }
    }


def _row_height(sid, r1, r2, height):
    return {
        "updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": r1, "endIndex": r2},
            "properties": {"pixelSize": height},
            "fields": "pixelSize",
        }
    }


# ─── 메인 ──────────────────────────────────────────────────────

def main():
    mode = "all"
    if len(sys.argv) > 1:
        arg = sys.argv[1].lstrip("-")
        if arg in ("analyze", "a"):
            mode = "analyze"
        elif arg in ("beautify", "b"):
            mode = "beautify"

    # 인증 확인
    if not check_credentials():
        return

    # 연결
    print("\n🔗 Google Sheets API 연결 중...")
    client = connect()
    print("✅ 연결 성공!")

    if mode in ("all", "analyze"):
        sheets_info = analyze_formulas(client)

    if mode in ("all", "beautify"):
        beautify_sheet(client)

    print("\n🎉 모든 작업 완료!")


if __name__ == "__main__":
    main()
