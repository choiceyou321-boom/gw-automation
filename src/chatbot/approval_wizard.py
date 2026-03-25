"""
전자결재 작성 위저드 (단계별 질문 플로우)

흐름:
  FORM_SELECT → 작성 가능한 양식 목록 보여주고 선택
  PROJECT → 프로젝트 검색 + 확인
  CONTENT → 지출 내용 + 금액 입력
  TITLE → 제목 자동 제안 + 확인
  BUDGET → 예산과목 키워드 입력
  INVOICE → 세금계산서 여부 → 업체 검색 → 확인
  FINAL_CONFIRM → 전체 요약 + 최종 확인
  EXECUTING → 자동화 실행

사용:
  wizard = ApprovalWizard(user_context=ctx)
  msg, done = wizard.start()          # 첫 질문
  msg, done = wizard.process(input)   # 이후 단계
  if done: del ctx["approval_wizard"]
"""

from __future__ import annotations

import re
import logging
import concurrent.futures

logger = logging.getLogger(__name__)

# ── 지원 양식 정의 ──────────────────────────────────────────────────────────

SUPPORTED_FORMS = {
    "1": {"key": "expense",   "label": "지출결의서",   "status": "완성"},
    "2": {"key": "vendor",    "label": "거래처등록",   "status": "완성"},
}

PREPARING_FORMS = ["연장근무신청", "외근신청", "선급금요청", "선급금정산"]


def _form_menu() -> str:
    lines = ["어떤 전자결재 양식을 작성할까요?\n"]
    lines.append("✅ 작성 가능한 양식:")
    for num, info in SUPPORTED_FORMS.items():
        lines.append(f"  {num}. {info['label']}")
    lines.append(f"\n📋 준비 중: {', '.join(PREPARING_FORMS)}")
    lines.append("\n번호 또는 이름으로 입력해주세요. (예: '1' 또는 '지출결의서')")
    return "\n".join(lines)


def _parse_form_choice(text: str) -> str | None:
    """사용자 입력 → form key (expense/vendor/None)"""
    t = text.strip()
    # 번호로 선택
    if t in SUPPORTED_FORMS:
        return SUPPORTED_FORMS[t]["key"]
    # 이름으로 선택
    for info in SUPPORTED_FORMS.values():
        if info["label"] in t or t in info["label"]:
            return info["key"]
    # 키워드 매핑
    expense_kw = ["지출", "경비", "결의서", "expense", "공사비", "식대", "교통"]
    vendor_kw = ["거래처", "협력사", "vendor", "업체 등록", "업체등록"]
    tl = t.lower()
    if any(k in tl for k in expense_kw):
        return "expense"
    if any(k in tl for k in vendor_kw):
        return "vendor"
    return None


def _is_affirm(text: str) -> bool:
    """'맞아', '확인', '좋아' 등 긍정 응답 감지"""
    affirm = ["맞아", "맞아요", "맞습니다", "확인", "좋아", "좋아요", "네", "예", "그래", "그거로", "ok", "ㅇㅇ", "ㅇㅋ"]
    t = text.strip().lower()
    return any(a in t for a in affirm)


def _is_deny(text: str) -> bool:
    """'아니', '취소' 등 부정/취소 응답 감지"""
    deny = ["아니", "아니요", "아니에요", "다시", "취소", "no", "틀려", "ㄴ"]
    t = text.strip().lower()
    return any(d in t for d in deny)


def _parse_amount(text: str) -> float | None:
    """'275만', '2,750,000', '275만원' → 2750000.0"""
    t = text.replace(",", "").replace(" ", "")
    # '억' 단위
    m = re.search(r'(\d+(?:\.\d+)?)\s*억', t)
    if m:
        return float(m.group(1)) * 1_0000_0000
    # '만' 단위 (소수점 포함)
    m = re.search(r'(\d+(?:\.\d+)?)\s*만', t)
    if m:
        return float(m.group(1)) * 10000
    # 순수 숫자
    m = re.search(r'(\d{4,})', t)
    if m:
        return float(m.group(1))
    return None


# ── 위저드 클래스 ────────────────────────────────────────────────────────────

class ApprovalWizard:
    """
    전자결재 작성 단계별 질문 상태머신.
    user_context["approval_wizard"] = wizard 인스턴스로 저장.
    """

    # expense 위저드 단계 순서
    EXPENSE_STEPS = [
        "project",
        "project_confirm",
        "content",
        "title",
        "budget",
        "invoice_ask",
        "invoice_vendor",
        "invoice_confirm",
        "final_confirm",
    ]

    def __init__(self, user_context: dict, initial_data: dict | None = None):
        self.user_context = user_context
        self.data: dict = initial_data or {}       # 수집된 결재 정보
        self._form_key: str = ""                   # "expense" | "vendor"
        self._step: str = "form_select"            # 현재 단계
        self._search_results: list = []            # 임시 프로젝트 검색 결과
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    # ── 공개 메서드 ──────────────────────────────────────────────────────────

    def start(self) -> tuple[str, bool]:
        """위저드 첫 메시지 반환 (form_select or project)"""
        if self._form_key == "expense" and self.data.get("project"):
            # 이미 프로젝트까지 알고 있으면 다음 단계부터
            self._step = "content"
            return self._ask_content(), False
        if self._form_key == "expense":
            self._step = "project"
            return self._ask_project(), False
        # 양식 선택부터
        self._step = "form_select"
        return _form_menu(), False

    def process(self, user_input: str) -> tuple[str, bool]:
        """
        사용자 입력을 받아 다음 단계로 진행.
        Returns: (bot_response, is_done)
        is_done=True → 위저드 종료 (caller가 session에서 제거)
        """
        handler = getattr(self, f"_handle_{self._step}", None)
        if handler is None:
            return "오류: 알 수 없는 단계입니다. '/clear'로 대화를 초기화해주세요.", True
        return handler(user_input)

    # ── 단계별 핸들러 ────────────────────────────────────────────────────────

    def _handle_form_select(self, text: str) -> tuple[str, bool]:
        form_key = _parse_form_choice(text)
        if not form_key:
            return (
                f"잘 이해하지 못했어요.\n\n{_form_menu()}",
                False,
            )
        self._form_key = form_key
        if form_key == "expense":
            self._step = "project"
            return self._ask_project(), False
        elif form_key == "vendor":
            # 거래처등록은 사업자등록증/통장사본이 필요
            return (
                "거래처등록 신청을 위해 **사업자등록증**과 **통장사본**을 첨부해주세요!\n"
                "이미지 또는 PDF로 올려주시면 자동으로 정보를 추출해드릴게요.",
                True,  # 위저드 종료 → Gemini가 이어받음
            )
        return _form_menu(), False

    # ── 지출결의서 단계들 ───────────────────────────────────────────────────

    def _ask_project(self) -> str:
        return (
            "어떤 프로젝트의 지출결의서인가요?\n"
            "프로젝트 이름 일부만 입력해도 검색해드릴게요. (예: '메디빌더', '종로')\n\n"
            "프로젝트가 없는 경우 '없음' 또는 '스킵'이라고 해주세요."
        )

    def _handle_project(self, text: str) -> tuple[str, bool]:
        t = text.strip()
        # 스킵
        if t in ("없음", "없어", "스킵", "skip", "빼줘", "나중에"):
            self.data["project"] = ""
            self._step = "content"
            return self._ask_content(), False

        # GW 프로젝트 검색
        results = self._search_projects(t)
        if results is None:
            return "프로젝트 검색 중 오류가 발생했어요. 다시 시도하거나 '스킵'으로 건너뛸 수 있어요.", False

        if not results:
            return (
                f"'{t}'로 검색된 프로젝트가 없어요.\n"
                "다른 키워드로 다시 검색하거나, 정확한 프로젝트 코드(예: GS-25-0088)를 입력해주세요.\n"
                "프로젝트가 없으면 '없음'이라고 해주세요.",
                False,
            )

        self._search_results = results
        if len(results) == 1:
            r = results[0]
            self._step = "project_confirm"
            return (
                f"프로젝트를 찾았어요!\n\n"
                f"  📁 **{r['full_text']}**\n\n"
                f"이 프로젝트가 맞나요? (맞아 / 아니오)",
                False,
            )

        # 여러 건
        lines = [f"'{t}'로 검색된 프로젝트 ({len(results)}건):"]
        for i, r in enumerate(results, 1):
            lines.append(f"  {i}. {r['full_text']}")
        lines.append("\n번호로 선택해주세요. 없으면 '없음'이라고 해주세요.")
        self._step = "project_confirm"
        return "\n".join(lines), False

    def _handle_project_confirm(self, text: str) -> tuple[str, bool]:
        t = text.strip()

        # 1건 결과에서 확인/부정
        if len(self._search_results) == 1:
            if _is_affirm(t):
                self.data["project"] = self._search_results[0]["full_text"]
                self._step = "content"
                return self._ask_content(), False
            elif _is_deny(t):
                self._step = "project"
                return "다른 키워드로 다시 검색해볼게요. 프로젝트 이름을 입력해주세요.", False

        # 여러 건에서 번호 선택
        m = re.search(r'\d+', t)
        if m:
            idx = int(m.group()) - 1
            if 0 <= idx < len(self._search_results):
                self.data["project"] = self._search_results[idx]["full_text"]
                self._step = "content"
                return self._ask_content(), False
            return f"1~{len(self._search_results)} 중에서 선택해주세요.", False

        # 없음
        if t in ("없음", "없어", "없는 거", "스킵"):
            self.data["project"] = ""
            self._step = "content"
            return self._ask_content(), False

        # 다시 검색
        if len(t) >= 2:
            return self._handle_project(t)

        return "번호를 입력하거나 '없음'으로 건너뛰어주세요.", False

    def _ask_content(self) -> str:
        project_hint = f" ({self.data.get('project', '')})" if self.data.get("project") else ""
        return (
            f"지출 내용{project_hint}을 알려주세요.\n"
            "어떤 용도의 지출인지, 금액은 얼마인지 함께 입력해주시면 좋아요.\n\n"
            "예) '음향공사 대금 275만원', '야근 식대 35,000원'"
        )

    def _handle_content(self, text: str) -> tuple[str, bool]:
        self.data["description"] = text.strip()
        # 금액 파싱 시도
        amt = _parse_amount(text)
        if amt:
            self.data["amount"] = amt

        # 제목 제안
        self._step = "title"
        return self._suggest_title(), False

    def _suggest_title(self) -> str:
        project = self.data.get("project", "")
        desc = self.data.get("description", "")

        if project:
            m = re.match(r'^([A-Z]{2}-\d{2}-\d{4})\.\s*(.*)', project)
            if m:
                code = m.group(1) + ". "
                proj_name = m.group(2).strip()
            else:
                code = ""
                proj_name = project.strip()
            # 내용에서 핵심 키워드 추출 (앞 10글자)
            content_hint = re.sub(r'\d[\d,]*만?원?', '', desc).strip()[:20]
            suggested = f"{code}{proj_name} {content_hint} 대금 지급의 건".strip()
        else:
            content_hint = re.sub(r'\d[\d,]*만?원?', '', desc).strip()[:20]
            suggested = f"{content_hint} 대금 지급의 건".strip()

        self._title_suggestion = suggested
        return (
            f"결재 제목을 이렇게 하면 어떨까요?\n\n"
            f"  📝 **\"{suggested}\"**\n\n"
            f"이대로 괜찮으시면 '확인', 다른 제목은 직접 입력해주세요."
        )

    def _handle_title(self, text: str) -> tuple[str, bool]:
        if _is_affirm(text):
            self.data["title"] = self._title_suggestion
        else:
            self.data["title"] = text.strip()

        self._step = "budget"
        return self._ask_budget(), False

    def _ask_budget(self) -> str:
        return (
            "예산과목은 무엇으로 할까요?\n\n"
            "예) 외주공사비, 시공재료비, 경비, 식대, 교통비\n\n"
            "잘 모르시면 '스킵'이라고 해주세요. (기본: 외주공사비)"
        )

    def _handle_budget(self, text: str) -> tuple[str, bool]:
        t = text.strip()
        if t in ("스킵", "skip", "모름", "기본", ""):
            self.data["budget_keyword"] = ""
        else:
            self.data["budget_keyword"] = t

        self._step = "invoice_ask"
        return self._ask_invoice(), False

    def _ask_invoice(self) -> str:
        return (
            "세금계산서나 영수증이 있나요?\n\n"
            "1. 세금계산서 있어요\n"
            "2. 카드 영수증 있어요\n"
            "3. 현금영수증 있어요\n"
            "4. 없어요 (증빙 없음)\n\n"
            "번호 또는 내용으로 답해주세요."
        )

    def _handle_invoice_ask(self, text: str) -> tuple[str, bool]:
        t = text.strip().lower()

        if "세금" in t or "계산서" in t or t == "1":
            self.data["evidence_type"] = "세금계산서"
            self._step = "invoice_vendor"
            return (
                "어떤 업체(공급자)의 세금계산서인가요?\n"
                "업체 상호를 입력해주시면 그룹웨어에서 조회해드릴게요.\n\n"
                "예) '주식회사 대한음향', '(주)현대정보'",
                False,
            )
        elif "카드" in t or t == "2":
            self.data["evidence_type"] = "카드사용내역"
            self._step = "final_confirm"
            return self._ask_final_confirm(), False
        elif "현금" in t or t == "3":
            self.data["evidence_type"] = "현금영수증"
            self._step = "final_confirm"
            return self._ask_final_confirm(), False
        else:
            # 없음 또는 4
            self.data["evidence_type"] = ""
            self._step = "final_confirm"
            return self._ask_final_confirm(), False

    def _handle_invoice_vendor(self, text: str) -> tuple[str, bool]:
        vendor = text.strip()
        self.data["invoice_vendor"] = vendor
        self._step = "invoice_confirm"

        return (
            f"'{vendor}' 세금계산서를 그룹웨어에서 찾겠습니다.\n\n"
            f"실제 작성 시 자동으로 검색해서 매칭할게요. "
            f"발행 금액이나 날짜를 알면 알려주세요. (몰라도 괜찮아요)\n\n"
            f"계속 진행할까요? (네 / 금액: OO원 / 날짜: YYYY-MM-DD)",
            False,
        )

    def _handle_invoice_confirm(self, text: str) -> tuple[str, bool]:
        t = text.strip()
        # 금액 파싱
        amt = _parse_amount(t)
        if amt and not self.data.get("invoice_amount"):
            self.data["invoice_amount"] = amt
        # 날짜 파싱
        dm = re.search(r'(\d{4}-\d{2}-\d{2})', t)
        if dm:
            self.data["invoice_date"] = dm.group(1)

        self._step = "final_confirm"
        return self._ask_final_confirm(), False

    def _ask_final_confirm(self) -> str:
        d = self.data
        lines = ["다음 내용으로 지출결의서를 작성할게요. 확인해주세요!\n"]
        lines.append(f"📌 **제목**: {d.get('title', '(미정)')}")
        if d.get("project"):
            lines.append(f"📁 **프로젝트**: {d['project']}")
        amt = d.get("amount")
        lines.append(f"💰 **금액**: {f'{int(amt):,}원' if amt else '(미정)'}")
        lines.append(f"📋 **내용**: {d.get('description', '(미정)')}")
        if d.get("budget_keyword"):
            lines.append(f"🏷️ **예산과목**: {d['budget_keyword']}")
        ev = d.get("evidence_type", "")
        if ev:
            lines.append(f"🧾 **증빙유형**: {ev}")
            if d.get("invoice_vendor"):
                lines.append(f"   └ 업체: {d['invoice_vendor']}")
                if d.get("invoice_amount"):
                    lines.append(f"   └ 공급가액: {int(d['invoice_amount']):,}원")
                if d.get("invoice_date"):
                    lines.append(f"   └ 발행일: {d['invoice_date']}")
        lines.append("\n'확인'이라고 하시면 바로 작성(임시저장)합니다.")
        lines.append("수정하실 내용이 있으면 말씀해주세요.")
        return "\n".join(lines)

    def _handle_final_confirm(self, text: str) -> tuple[str, bool]:
        if _is_deny(text):
            return (
                "어떤 부분을 수정할까요?\n"
                "• 프로젝트 변경\n• 제목 변경\n• 금액 변경\n• 내용 변경\n• 예산과목 변경\n• 계산서 변경\n"
                "수정할 항목을 말씀해주세요.",
                False,
            )

        # 중간 수정 요청 파싱
        t = text.strip()
        if "프로젝트" in t:
            self._step = "project"
            return self._ask_project(), False
        if "제목" in t:
            self._step = "title"
            return self._suggest_title(), False
        if "금액" in t:
            self._step = "content"
            return "금액이 얼마인가요?", False
        if "예산" in t or "과목" in t:
            self._step = "budget"
            return self._ask_budget(), False
        if "계산서" in t or "증빙" in t:
            self._step = "invoice_ask"
            return self._ask_invoice(), False

        # 확인 → 실제 작성
        return self._execute()

    # ── 자동화 실행 ──────────────────────────────────────────────────────────

    def _execute(self) -> tuple[str, bool]:
        """지출결의서 실제 작성 실행"""
        from src.chatbot.handlers import handle_submit_expense_approval
        params = {
            **self.data,
            "action": "draft",
        }
        result = handle_submit_expense_approval(params, user_context=self.user_context)
        return result, True

    # ── GW 조회 헬퍼 ────────────────────────────────────────────────────────

    def _search_projects(self, keyword: str) -> list | None:
        """GW 프로젝트 코드 검색 (동기, executor 사용)"""
        try:
            from src.chatbot.handlers import handle_search_project_code
            raw = handle_search_project_code(
                {"keyword": keyword},
                user_context=self.user_context,
            )
            # handle_search_project_code 반환값 파싱
            # "SEARCH_RESULT:SINGLE\n..." 또는 "SEARCH_RESULT:MULTIPLE\n..."
            return _parse_search_result(raw)
        except Exception as e:
            logger.warning(f"프로젝트 검색 오류: {e}")
            return None


def _parse_search_result(raw: str) -> list:
    """
    handle_search_project_code 결과 → [{full_text: str}] 파싱.

    SINGLE 포맷:
        SEARCH_RESULT:SINGLE
        프로젝트: GS-25-0088. [종로] 메디빌더
        ---
        ...
    MULTIPLE 포맷:
        SEARCH_RESULT:MULTIPLE
        '키워드'로 검색된 프로젝트가 N건 ...
        1. GS-25-0088. [종로] 메디빌더
        2. GS-25-0091. [서울] 메디빌더 2차
        ...
    """
    if not raw:
        return []
    if "프로젝트를 찾지 못했" in raw or "검색 오류" in raw:
        return []

    lines = raw.strip().split("\n")
    first = lines[0].strip()

    if first.startswith("SEARCH_RESULT:SINGLE"):
        # "프로젝트: GS-25-0088. ..." 줄에서 추출
        for line in lines[1:]:
            line = line.strip()
            if line.startswith("프로젝트:"):
                full_text = line[len("프로젝트:"):].strip()
                return [{"full_text": full_text}] if full_text else []
        return []

    if first.startswith("SEARCH_RESULT:MULTIPLE"):
        results = []
        for line in lines[1:]:
            line = line.strip()
            # "1. GS-25-0088. ..." 패턴
            m = re.match(r'^\d+\.\s+(.+)', line)
            if m:
                results.append({"full_text": m.group(1).strip()})
        return results

    return []
