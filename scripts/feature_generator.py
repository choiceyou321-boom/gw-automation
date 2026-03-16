#!/usr/bin/env python3
"""
기능 생성기 — 새로운 자동화 기능 스캐폴딩 도구

사용법:
    python scripts/feature_generator.py --name "출장신청서" --fields "출발지:text,도착지:text,출발일:date,귀환일:date,목적:text"
    python scripts/feature_generator.py --name "연장근무신청서" --fields "날짜:date,시간:number,사유:textarea" --dry-run

생성 파일:
    1. src/approval/forms/{snake_name}.py        — Playwright 자동화 스켈레톤
    2. src/chatbot/tools/{snake_name}_tool.py    — Gemini FunctionDeclaration
    3. docs/{snake_name}_howto.md               — 구현 가이드
"""

import argparse
import re
import sys
from pathlib import Path

# ── 한국어 → snake_case 변환 사전 ──────────────────────────────────────────
# 양식명
FORM_NAME_MAP = {
    "출장신청서":       "travel_request",
    "연장근무신청서":   "overtime_request",
    "휴가신청서":       "leave_request",
    "연차신청서":       "annual_leave_request",
    "구매요청서":       "purchase_request",
    "지출결의서":       "expense_approval",
    "법인카드신청서":   "corporate_card_request",
    "거래처등록":       "vendor_registration",
    "계약서":           "contract",
    "품의서":           "approval_request",
    "보고서":           "report",
    "협조전":           "cooperation_request",
    "업무보고서":       "work_report",
    "시말서":           "explanation_report",
    "인사발령":         "personnel_order",
    "채용요청":         "recruitment_request",
    "예산신청":         "budget_request",
    "물품구매":         "item_purchase",
    "교육신청":         "training_request",
    "해외출장":         "overseas_travel",
    "국내출장":         "domestic_travel",
}

# 필드명
FIELD_NAME_MAP = {
    "출발지":     "departure",
    "도착지":     "destination",
    "출발일":     "departure_date",
    "귀환일":     "return_date",
    "목적":       "purpose",
    "사유":       "reason",
    "날짜":       "date",
    "시간":       "time",
    "시작일":     "start_date",
    "종료일":     "end_date",
    "기간":       "period",
    "금액":       "amount",
    "총금액":     "total_amount",
    "내용":       "content",
    "설명":       "description",
    "제목":       "title",
    "프로젝트":   "project",
    "거래처":     "vendor",
    "담당자":     "manager",
    "부서":       "department",
    "팀":         "team",
    "승인자":     "approver",
    "결재선":     "approval_line",
    "수량":       "quantity",
    "단가":       "unit_price",
    "품목":       "item_name",
    "규격":       "specification",
    "비고":       "note",
    "첨부파일":   "attachment",
    "서명":       "signature",
}

# 필드 타입별 Playwright 액션 + Gemini Schema
FIELD_TYPE_CONFIG = {
    "text": {
        "playwright": 'await page.fill("{selector}", data["{field}"])',
        "gemini_type": "STRING",
        "gemini_desc": "{label} 텍스트",
    },
    "date": {
        "playwright": 'await page.fill("{selector}", data["{field}"])  # YYYY-MM-DD',
        "gemini_type": "STRING",
        "gemini_desc": "{label} (YYYY-MM-DD 형식)",
    },
    "number": {
        "playwright": 'await page.fill("{selector}", str(data["{field}"]))',
        "gemini_type": "NUMBER",
        "gemini_desc": "{label} (숫자)",
    },
    "select": {
        "playwright": 'await page.select_option("{selector}", data["{field}"])',
        "gemini_type": "STRING",
        "gemini_desc": "{label} 선택값",
    },
    "textarea": {
        "playwright": 'await page.fill("{selector}", data["{field}"])',
        "gemini_type": "STRING",
        "gemini_desc": "{label} (여러 줄 텍스트)",
    },
    "user_search": {
        "playwright": (
            '# 사용자 검색 팝업 — 이름 입력 후 검색\n'
            '        await page.fill("{selector}", data["{field}"])\n'
            '        await page.keyboard.press("Enter")  # 검색 실행\n'
            '        await page.click("tr:first-child")  # 첫 번째 결과 선택'
        ),
        "gemini_type": "STRING",
        "gemini_desc": "{label} (사용자 이름)",
    },
    "code_help": {
        "playwright": (
            '# 코드도움 팝업 — 검색어 입력 후 첫 결과 선택\n'
            '        await page.fill("{selector}", data["{field}"])\n'
            '        await page.keyboard.press("F2")   # 코드도움 팝업 열기\n'
            '        # TODO: OBTDataGrid API로 첫 행 선택'
        ),
        "gemini_type": "STRING",
        "gemini_desc": "{label} (코드 또는 키워드)",
    },
    "boolean": {
        "playwright": (
            'if data.get("{field}"):\n'
            '            await page.check("{selector}")\n'
            '        else:\n'
            '            await page.uncheck("{selector}")'
        ),
        "gemini_type": "BOOLEAN",
        "gemini_desc": "{label} (true/false)",
    },
}


def to_snake_case(korean: str) -> str:
    """한국어 양식명/필드명을 snake_case로 변환"""
    # 사전 우선
    if korean in FORM_NAME_MAP:
        return FORM_NAME_MAP[korean]
    # 로마자/숫자 혼합인 경우 직접 snake_case 변환
    s = re.sub(r'[\s\-]+', '_', korean.lower())
    s = re.sub(r'[^a-z0-9_]', '', s)
    return s or "form"


def to_class_name(snake: str) -> str:
    """snake_case → PascalCase"""
    return ''.join(w.capitalize() for w in snake.split('_'))


def parse_fields(fields_str: str) -> list[dict]:
    """
    'label:type,label:type,...' 형식 파싱
    타입 생략 시 'text' 기본값
    """
    fields = []
    for part in fields_str.split(','):
        part = part.strip()
        if not part:
            continue
        if ':' in part:
            label, ftype = part.split(':', 1)
        else:
            label, ftype = part, 'text'
        label = label.strip()
        ftype = ftype.strip().lower()
        if ftype not in FIELD_TYPE_CONFIG:
            print(f"  [경고] 알 수 없는 타입 '{ftype}' → 'text'로 대체")
            ftype = 'text'
        snake = FIELD_NAME_MAP.get(label, re.sub(r'[^a-z0-9_]', '', label.lower()) or label)
        fields.append({"label": label, "snake": snake, "type": ftype})
    return fields


# ── 코드 생성기 ──────────────────────────────────────────────────────────────

def generate_automation_module(form_name_ko: str, form_snake: str, class_name: str, fields: list[dict]) -> str:
    """src/approval/forms/{form_snake}.py 내용 생성"""
    field_fills = []
    for f in fields:
        cfg = FIELD_TYPE_CONFIG[f["type"]]
        action = cfg["playwright"].format(
            selector=f"th:has-text('{f['label']}') + td input",
            field=f["snake"],
        )
        field_fills.append(f'        # {f["label"]} ({f["type"]})\n        {action}')

    fields_block = "\n\n".join(field_fills)

    return f'''"""
{form_name_ko} 자동화 모듈
자동생성: scripts/feature_generator.py
"""
import time
import logging
from playwright.sync_api import Page

logger = logging.getLogger(__name__)


class {class_name}Automation:
    """
    {form_name_ko} 자동화 엔진.

    사용법:
        auto = {class_name}Automation(page, context)
        result = auto.run(data)
    """

    FORM_NAME = "{form_name_ko}"

    def __init__(self, page: Page, context):
        self.page = page
        self.context = context

    # ── 공개 메서드 ──────────────────────────────────────────────────────────

    def run(self, data: dict, action: str = "confirm") -> dict:
        """
        Args:
            data: 필드 데이터 딕셔너리
            action: 'confirm'(확인 후 대기) | 'draft'(임시저장) | 'submit'(결재상신)
        Returns:
            {{"success": bool, "message": str}}
        """
        try:
            self._navigate_to_form()
            self.fill_form(data)
            return self._finalize(action)
        except Exception as e:
            logger.error(f"{form_name_ko} 자동화 실패: {{e}}")
            return {{"success": False, "message": str(e)}}

    def fill_form(self, data: dict):
        """양식 필드 입력"""
        page = self.page
        logger.info(f"{form_name_ko} 입력 시작: {{list(data.keys())}}")

{fields_block}

        logger.info("{form_name_ko} 입력 완료")

    # ── 내부 메서드 ──────────────────────────────────────────────────────────

    def _navigate_to_form(self):
        """전자결재 양식으로 이동"""
        page = self.page
        # 전자결재 모듈 클릭
        page.locator("span.module-link.EA").click()
        page.wait_for_load_state("networkidle", timeout=10000)
        # 추천양식에서 해당 양식 클릭
        page.locator(f"text={{self.FORM_NAME}}").first.click()
        page.wait_for_load_state("networkidle", timeout=15000)
        logger.info(f"양식 이동 완료: {{self.FORM_NAME}}")

    def _finalize(self, action: str) -> dict:
        """결재 상신 / 임시저장 / 확인"""
        page = self.page
        if action == "submit":
            # TODO: 상신 버튼 셀렉터 확인 필요
            page.locator("button:has-text('상신')").click()
            logger.info("{form_name_ko} 결재 상신 완료")
            return {{"success": True, "message": "{form_name_ko} 결재 상신 완료"}}
        elif action == "draft":
            page.locator("button:has-text('보관'), button:has-text('임시저장')").first.click()
            logger.info("{form_name_ko} 임시저장 완료")
            return {{"success": True, "message": "{form_name_ko} 임시저장 완료"}}
        else:  # confirm
            logger.info("{form_name_ko} 입력 완료 — 사용자 확인 대기")
            return {{"success": True, "message": "{form_name_ko} 입력 완료. 화면을 확인해 주세요."}}
'''


def generate_tool_module(form_name_ko: str, form_snake: str, class_name: str, fields: list[dict]) -> str:
    """src/chatbot/tools/{form_snake}_tool.py 내용 생성"""
    # Gemini properties 생성
    prop_lines = []
    required_fields = []
    for f in fields:
        cfg = FIELD_TYPE_CONFIG[f["type"]]
        desc = cfg["gemini_desc"].format(label=f["label"])
        prop_lines.append(
            f'            "{f["snake"]}": types.Schema(type="{cfg["gemini_type"]}", description="{desc}"),'
        )
        # text, textarea, date 타입의 첫 2개는 required
        if f["type"] in ("text", "date") and len(required_fields) < 2:
            required_fields.append(f'"{f["snake"]}"')

    props_block = "\n".join(prop_lines)
    required_block = ", ".join(required_fields) if required_fields else f'"{fields[0]["snake"]}"'

    return f'''"""
{form_name_ko} Gemini Function Declaration
자동생성: scripts/feature_generator.py
"""
from google.genai import types
from src.approval.forms.{form_snake} import {class_name}Automation


# ── Gemini FunctionDeclaration ───────────────────────────────────────────────

FUNCTION_DECLARATION = types.FunctionDeclaration(
    name="submit_{form_snake}",
    description="{form_name_ko}을 작성합니다. 사용자가 '{form_name_ko}' 작성을 요청할 때 사용합니다.",
    parameters=types.Schema(
        type="OBJECT",
        properties={{
{props_block}
            "action": types.Schema(
                type="STRING",
                description="실행 액션: 'confirm'(입력 후 대기), 'draft'(임시저장), 'submit'(결재상신). 기본값 'confirm'",
            ),
        }},
        required=[{required_block}],
    ),
)


# ── 핸들러 ──────────────────────────────────────────────────────────────────

async def handle_{form_snake}(args: dict, page, context) -> str:
    """Gemini function call 핸들러"""
    automation = {class_name}Automation(page, context)
    result = automation.run(
        data={{k: v for k, v in args.items() if k != "action"}},
        action=args.get("action", "confirm"),
    )
    if result["success"]:
        return f"✅ {{result['message']}}"
    else:
        return f"❌ {form_name_ko} 처리 실패: {{result['message']}}"
'''


def generate_howto(form_name_ko: str, form_snake: str, class_name: str, fields: list[dict]) -> str:
    """docs/{form_snake}_howto.md 내용 생성"""
    field_table = "\n".join(
        f"| {f['label']} | `{f['snake']}` | {f['type']} | TODO: 실제 셀렉터 확인 |"
        for f in fields
    )
    checklist = "\n".join(
        f"- [ ] `{f['label']}` 셀렉터 확인: `th:has-text('{f['label']}') + td input`"
        for f in fields
    )

    return f'''# {form_name_ko} 자동화 구현 가이드

> 자동생성: `scripts/feature_generator.py`

## 파일 구조

```
src/approval/forms/{form_snake}.py        ← Playwright 자동화 (여기에 로직 구현)
src/chatbot/tools/{form_snake}_tool.py   ← Gemini Function Declaration
docs/{form_snake}_howto.md              ← 이 파일
```

## 구현 순서

### 1. 셀렉터 확인 (필수)

크롬 개발자 도구로 각 필드 셀렉터 확인:

| 필드 | 변수명 | 타입 | 셀렉터 |
|------|--------|------|--------|
{field_table}

### 2. 셀렉터 체크리스트

{checklist}

### 3. 자동화 테스트

```python
# 빠른 테스트 방법
from playwright.sync_api import sync_playwright
from src.approval.forms.{form_snake} import {class_name}Automation

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    # TODO: 로그인 처리

    auto = {class_name}Automation(page, context)
    result = auto.run({{
{chr(10).join(f"        '{f['snake']}': '테스트값'," for f in fields)}
    }})
    print(result)
```

### 4. agent.py 등록

`src/chatbot/agent.py`의 `AUTOMATION_TOOLS` 리스트에 추가:

```python
from src.chatbot.tools.{form_snake}_tool import FUNCTION_DECLARATION, handle_{form_snake}

# AUTOMATION_TOOLS 리스트에 추가
AUTOMATION_TOOLS = [
    types.Tool(function_declarations=[
        ...,
        FUNCTION_DECLARATION,  # ← 여기에 추가
    ])
]

# TOOL_HANDLERS 딕셔너리에 추가
TOOL_HANDLERS = {{
    ...,
    "submit_{form_snake}": handle_{form_snake},  # ← 여기에 추가
}}
```

## 주의사항

- 셀렉터는 그룹웨어 버전에 따라 달라질 수 있음
- OBTDataGrid 그리드 필드는 `_fill_grid_cell_via_realgrid_api()` 참고
- 코드도움 팝업은 `_select_project_modal()` 패턴 참고
'''


# ── 메인 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="자동화 기능 스캐폴딩 생성기")
    parser.add_argument("--name", required=True, help="양식명 (한국어, 예: '출장신청서')")
    parser.add_argument(
        "--fields", required=True,
        help="필드 정의 (예: '출발지:text,출발일:date,목적:textarea')"
    )
    parser.add_argument("--dry-run", action="store_true", help="파일 생성 없이 미리보기")
    args = parser.parse_args()

    form_name_ko = args.name
    form_snake = to_snake_case(form_name_ko)
    class_name = to_class_name(form_snake)
    fields = parse_fields(args.fields)

    if not fields:
        print("오류: 필드가 없습니다.")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  기능 생성기 — {form_name_ko}")
    print(f"{'='*60}")
    print(f"  파일명 prefix : {form_snake}")
    print(f"  클래스명      : {class_name}Automation")
    print(f"  필드 ({len(fields)}개)   : {', '.join(f['label'] for f in fields)}")
    print(f"{'='*60}\n")

    # 생성할 파일 목록
    root = Path(__file__).parent.parent
    files = {
        root / "src" / "approval" / "forms" / f"{form_snake}.py": generate_automation_module(form_name_ko, form_snake, class_name, fields),
        root / "src" / "chatbot" / "tools" / f"{form_snake}_tool.py": generate_tool_module(form_name_ko, form_snake, class_name, fields),
        root / "docs" / f"{form_snake}_howto.md": generate_howto(form_name_ko, form_snake, class_name, fields),
    }

    if args.dry_run:
        print("[dry-run 모드] 아래 파일이 생성됩니다:\n")
        for path in files:
            print(f"  📄 {path.relative_to(root)}")
        print("\n파일 내용은 --dry-run 없이 실행하면 생성됩니다.")
        return

    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"  ✅ 생성: {path.relative_to(root)}")

    print(f"\n완료! 다음 단계:")
    print(f"  1. docs/{form_snake}_howto.md 를 읽고 셀렉터 확인")
    print(f"  2. src/approval/forms/{form_snake}.py 에서 TODO 채우기")
    print(f"  3. src/chatbot/agent.py 에 등록")


if __name__ == "__main__":
    main()
