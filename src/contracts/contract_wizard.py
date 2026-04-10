"""
계약서 작성 단건 위저드 (챗봇 단계별 질문 플로우)

흐름:
  TYPE_SELECT → 자재납품 / 공사 선택
  [자재납품]
    MAT_SUB    → 협력사명, 대표자, 주소, 사업자번호
    MAT_DETAIL → 자재유형, 자재상세설명
    MAT_AMOUNT → 계약금액, 계약금비율, 중도금비율
    MAT_DATE   → 납품일자, 설치완료일, 계약일
    CONFIRM    → 전체 요약 + 확인
    EXECUTE    → DOCX 생성
  [공사]
    CON_SUB    → 협력사명, 대표자, 주소
    CON_DETAIL → 공사유형, 공급가액
    CON_DATE   → 착공일, 준공예정일, 중도금2차조건, 계약일
    CONFIRM    → 전체 요약 + 확인
    EXECUTE    → DOCX 생성
"""
from __future__ import annotations

import re
import logging
import pathlib
from datetime import datetime

logger = logging.getLogger(__name__)

OUTPUT_DIR = str(pathlib.Path(__file__).parent.parent.parent / "data" / "tmp")


def _is_affirm(text: str) -> bool:
    affirm = ["맞아", "맞아요", "확인", "좋아", "좋아요", "네", "예", "그래", "ok", "ㅇㅇ", "ㅇㅋ", "응"]
    return any(a in text.strip().lower() for a in affirm)


def _is_deny(text: str) -> bool:
    deny = ["아니", "아니요", "다시", "취소", "no", "틀려", "ㄴ"]
    return any(d in text.strip().lower() for d in deny)


def _parse_amount(text: str) -> int | None:
    t = text.replace(",", "").replace(" ", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*억", t)
    if m:
        return int(float(m.group(1)) * 1_0000_0000)
    m = re.search(r"(\d+(?:\.\d+)?)\s*만", t)
    if m:
        return int(float(m.group(1)) * 10000)
    m = re.search(r"(\d{4,})", t)
    if m:
        return int(m.group(1))
    return None


def _parse_date(text: str) -> str | None:
    """다양한 날짜 형식 → 'YYYY-MM-DD'"""
    t = text.strip()
    # YYYY-MM-DD or YYYY/MM/DD
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", t)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # YYYY년 MM월 DD일
    m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", t)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def _parse_pct(text: str) -> int | None:
    m = re.search(r"(\d+)\s*%?", text.strip())
    if m:
        return int(m.group(1))
    return None


# ── 위저드 클래스 ─────────────────────────────────────────────────────────────

class ContractWizard:
    """
    계약서 단건 작성 위저드.
    user_context["contract_wizard"] = wizard 인스턴스로 저장.
    """

    TYPE_MENU = (
        "어떤 계약서를 작성할까요?\n\n"
        "1. 자재납품 계약서 (조명, 커튼, 위생기구 등)\n"
        "2. 공사 계약서 (전기, 음향, 위생배관 등)\n\n"
        "번호 또는 이름으로 답해주세요."
    )

    def __init__(self, user_context: dict):
        self.user_context = user_context
        self.data: dict = {}
        self._type: str = ""   # "material" | "construction"
        self._step: str = "type_select"

    def start(self) -> tuple[str, bool]:
        return self.TYPE_MENU, False

    def process(self, user_input: str) -> tuple[str, bool]:
        handler = getattr(self, f"_handle_{self._step}", None)
        if handler is None:
            return "오류: 알 수 없는 단계입니다. 대화를 초기화해주세요.", True
        return handler(user_input)

    # ── type_select ──────────────────────────────────────────────────────────

    def _handle_type_select(self, text: str) -> tuple[str, bool]:
        t = text.strip().lower()
        if t in ("1", "자재", "자재납품", "자재납품계약서"):
            self._type = "material"
            self._step = "mat_sub"
            return self._ask_mat_sub(), False
        elif t in ("2", "공사", "공사계약서"):
            self._type = "construction"
            self._step = "con_sub"
            return self._ask_con_sub(), False
        else:
            if "자재" in t or "납품" in t or "조명" in t or "커튼" in t:
                self._type = "material"
                self._step = "mat_sub"
                return self._ask_mat_sub(), False
            if "공사" in t or "전기" in t or "음향" in t or "배관" in t:
                self._type = "construction"
                self._step = "con_sub"
                return self._ask_con_sub(), False
        return f"잘 이해하지 못했어요.\n\n{self.TYPE_MENU}", False

    # ── 자재납품 단계들 ──────────────────────────────────────────────────────

    def _ask_mat_sub(self) -> str:
        return (
            "협력사 정보를 알려주세요.\n\n"
            "다음 내용을 함께 입력해주시면 됩니다:\n"
            "• 협력사명 (예: 오티엘)\n"
            "• 대표자 (예: 이 봉 식)\n"
            "• 주소\n"
            "• 사업자등록번호 (예: 390-86-03578)\n\n"
            "예) 오티엘 / 이봉식 / 서울 도봉구 도봉산3길 46 / 390-86-03578"
        )

    def _handle_mat_sub(self, text: str) -> tuple[str, bool]:
        parts = [p.strip() for p in re.split(r"[/,\n]", text) if p.strip()]
        if len(parts) >= 4:
            self.data["sub_name"] = parts[0]
            self.data["sub_rep"] = parts[1]
            self.data["sub_addr"] = parts[2]
            self.data["sub_biz_no"] = parts[3]
        elif len(parts) == 3:
            self.data["sub_name"] = parts[0]
            self.data["sub_rep"] = parts[1]
            self.data["sub_addr"] = parts[2]
            self.data["sub_biz_no"] = ""
        elif len(parts) >= 1:
            self.data["sub_name"] = parts[0]
        # 사업자번호 패턴 탐색
        biz_m = re.search(r"\d{3}-\d{2}-\d{5}", text)
        if biz_m:
            self.data["sub_biz_no"] = biz_m.group()
        self._step = "mat_detail"
        return self._ask_mat_detail(), False

    def _ask_mat_detail(self) -> str:
        return (
            "납품할 자재 정보를 알려주세요.\n\n"
            "• 자재 유형 (예: 조명, 커튼, 위생기구, 도어락)\n"
            "• 자재 상세 설명 (계약서에 들어갈 물품 내용)\n\n"
            "예) 조명 / 조명(등기구) 제작 및 납품 (견적서 참조)"
        )

    def _handle_mat_detail(self, text: str) -> tuple[str, bool]:
        parts = [p.strip() for p in re.split(r"[/\n]", text, maxsplit=1) if p.strip()]
        if len(parts) >= 2:
            self.data["material_type"] = parts[0]
            self.data["material_desc"] = parts[1]
        elif len(parts) == 1:
            self.data["material_type"] = parts[0]
            self.data["material_desc"] = f"{parts[0]} 납품 (견적서 참조)"
        self._step = "mat_amount"
        return self._ask_mat_amount(), False

    def _ask_mat_amount(self) -> str:
        return (
            "계약 금액을 알려주세요.\n\n"
            "• 계약금액 (VAT 별도, 예: 47,500,000 또는 4750만)\n"
            "• 계약금 비율 (예: 40%) ← 기본 40%\n"
            "• 중도금 비율 (예: 50%) ← 기본 50%, 잔금은 자동 10%\n\n"
            "예) 4750만 / 40% / 50%\n"
            "금액만 입력하면 기본 40-50-10으로 처리합니다."
        )

    def _handle_mat_amount(self, text: str) -> tuple[str, bool]:
        amt = _parse_amount(text)
        if amt:
            self.data["total_amount"] = amt
        # 비율 파싱
        pcts = re.findall(r"(\d+)\s*%", text)
        if len(pcts) >= 2:
            self.data["deposit_pct"] = int(pcts[0])
            self.data["progress_pct"] = int(pcts[1])
        elif len(pcts) == 1:
            self.data["deposit_pct"] = int(pcts[0])
            self.data["progress_pct"] = 90 - int(pcts[0])
        else:
            self.data.setdefault("deposit_pct", 40)
            self.data.setdefault("progress_pct", 50)
        self._step = "mat_date"
        return self._ask_mat_date(), False

    def _ask_mat_date(self) -> str:
        return (
            "날짜 정보를 알려주세요.\n\n"
            "• 납품일자 (예: 2026-02-28)\n"
            "• 설치완료일 (예: 2026-03-16) ← 없으면 납품일자와 동일\n"
            "• 계약일 (예: 2026-02-03) ← 없으면 오늘\n\n"
            "예) 2026-02-28 / 2026-03-16 / 2026-02-03"
        )

    def _handle_mat_date(self, text: str) -> tuple[str, bool]:
        dates = [_parse_date(p) for p in re.split(r"[/,\n]", text) if p.strip()]
        dates = [d for d in dates if d]
        if len(dates) >= 3:
            self.data["delivery_date"] = dates[0]
            self.data["install_date"] = dates[1]
            self.data["contract_date"] = dates[2]
        elif len(dates) == 2:
            self.data["delivery_date"] = dates[0]
            self.data["install_date"] = dates[1]
            self.data.setdefault("contract_date", datetime.today().strftime("%Y-%m-%d"))
        elif len(dates) == 1:
            self.data["delivery_date"] = dates[0]
            self.data.setdefault("install_date", dates[0])
            self.data.setdefault("contract_date", datetime.today().strftime("%Y-%m-%d"))
        self._step = "confirm"
        return self._ask_confirm(), False

    # ── 공사 단계들 ──────────────────────────────────────────────────────────

    def _ask_con_sub(self) -> str:
        return (
            "협력사 정보를 알려주세요.\n\n"
            "• 협력사명 (예: 호림ENG, 아트음향)\n"
            "• 대표자 (예: 이 만 식)\n"
            "• 주소\n\n"
            "예) 호림ENG / 이만식 / 서울 강동구 구천면로 361, 102동 601호"
        )

    def _handle_con_sub(self, text: str) -> tuple[str, bool]:
        parts = [p.strip() for p in re.split(r"[/,\n]", text) if p.strip()]
        if len(parts) >= 3:
            self.data["sub_name"] = parts[0]
            self.data["sub_rep"] = parts[1]
            self.data["sub_addr"] = " ".join(parts[2:])
        elif len(parts) == 2:
            self.data["sub_name"] = parts[0]
            self.data["sub_rep"] = parts[1]
            self.data["sub_addr"] = ""
        elif len(parts) == 1:
            self.data["sub_name"] = parts[0]
        self._step = "con_detail"
        return self._ask_con_detail(), False

    def _ask_con_detail(self) -> str:
        return (
            "공사 정보를 알려주세요.\n\n"
            "• 공사 유형 (예: 위생배관공사, 음향공사, 전기공사, 도장공사)\n"
            "• 공급가액 VAT 제외 (예: 48,000,000 또는 4800만)\n\n"
            "예) 위생배관공사 / 48,000,000"
        )

    def _handle_con_detail(self, text: str) -> tuple[str, bool]:
        parts = [p.strip() for p in re.split(r"[/\n]", text, maxsplit=1) if p.strip()]
        if len(parts) >= 2:
            self.data["construction_type"] = parts[0]
            amt = _parse_amount(parts[1])
            if amt:
                self.data["supply_amount"] = amt
        elif len(parts) == 1:
            # 공사명인지 금액인지 판별
            amt = _parse_amount(parts[0])
            if amt:
                self.data["supply_amount"] = amt
            else:
                self.data["construction_type"] = parts[0]
        self._step = "con_date"
        return self._ask_con_date(), False

    def _ask_con_date(self) -> str:
        return (
            "날짜 및 대금 조건을 알려주세요.\n\n"
            "• 착공일 (예: 2026-02-05)\n"
            "• 준공예정일 (예: 2026-03-16)\n"
            "• 중도금 2차 조건 (예: 시운전 완료 이후, 공종 작업 완료 이후)\n"
            "• 계약일 (없으면 오늘)\n\n"
            "예) 2026-02-05 / 2026-03-16 / 시운전 완료 이후"
        )

    def _handle_con_date(self, text: str) -> tuple[str, bool]:
        parts = [p.strip() for p in re.split(r"[/\n]", text) if p.strip()]
        dates = []
        conditions = []
        for part in parts:
            d = _parse_date(part)
            if d:
                dates.append(d)
            elif "완료" in part or "이후" in part or "후" in part:
                conditions.append(part)

        if len(dates) >= 2:
            self.data["start_date"] = dates[0]
            self.data["end_date"] = dates[1]
        if len(dates) >= 3:
            self.data["contract_date"] = dates[2]
        else:
            self.data.setdefault("contract_date", datetime.today().strftime("%Y-%m-%d"))
        if conditions:
            self.data["progress2_cond"] = conditions[0]
        else:
            self.data.setdefault("progress2_cond", "공종 작업 완료 이후")

        self._step = "confirm"
        return self._ask_confirm(), False

    # ── 확인 ─────────────────────────────────────────────────────────────────

    def _ask_confirm(self) -> str:
        d = self.data
        lines = ["다음 내용으로 계약서를 생성할게요. 확인해주세요!\n"]
        if self._type == "material":
            lines.append("📋 **자재납품 계약서**")
            lines.append(f"🏢 협력사: {d.get('sub_name', '')} / 대표: {d.get('sub_rep', '')}")
            lines.append(f"📦 자재: {d.get('material_type', '')} — {d.get('material_desc', '')}")
            amt = d.get("total_amount", 0)
            dep = d.get("deposit_pct", 40)
            prg = d.get("progress_pct", 50)
            bal = 100 - dep - prg
            lines.append(f"💰 계약금액: {amt:,}원 (계약금{dep}%-중도금{prg}%-잔금{bal}%)")
            lines.append(f"📅 납품일: {d.get('delivery_date', '')} / 설치완료: {d.get('install_date', '')}")
            lines.append(f"📝 계약일: {d.get('contract_date', '')}")
        else:
            lines.append("🏗️ **공사 계약서**")
            lines.append(f"🏢 협력사: {d.get('sub_name', '')} / 대표: {d.get('sub_rep', '')}")
            lines.append(f"🔨 공사: {d.get('construction_type', '')}")
            sup = d.get("supply_amount", 0)
            vat = round(sup * 0.1)
            lines.append(f"💰 공급가액: {sup:,}원 (VAT {vat:,}원 포함 총 {sup+vat:,}원)")
            lines.append(f"📅 착공: {d.get('start_date', '')} ~ 준공: {d.get('end_date', '')}")
            lines.append(f"💳 중도금2차 조건: {d.get('progress2_cond', '')}")
            lines.append(f"📝 계약일: {d.get('contract_date', '')}")
        lines.append("\n'확인'이라고 하시면 DOCX 파일을 생성합니다.")
        lines.append("수정이 필요하면 말씀해주세요.")
        return "\n".join(lines)

    def _handle_confirm(self, text: str) -> tuple[str, bool]:
        if _is_deny(text):
            return (
                "어떤 부분을 수정할까요?\n"
                "협력사 정보 / 금액 / 날짜 / 자재(공사) 정보\n"
                "수정할 항목을 말씀해주세요.",
                False,
            )
        t = text.strip()
        # 수정 요청
        if "협력사" in t or "대표" in t or "주소" in t:
            if self._type == "material":
                self._step = "mat_sub"
                return self._ask_mat_sub(), False
            else:
                self._step = "con_sub"
                return self._ask_con_sub(), False
        if "자재" in t or "공사" in t:
            if self._type == "material":
                self._step = "mat_detail"
                return self._ask_mat_detail(), False
            else:
                self._step = "con_detail"
                return self._ask_con_detail(), False
        if "금액" in t or "비율" in t:
            if self._type == "material":
                self._step = "mat_amount"
                return self._ask_mat_amount(), False
            else:
                self._step = "con_detail"
                return self._ask_con_detail(), False
        if "날짜" in t or "기간" in t or "착공" in t or "납품" in t:
            if self._type == "material":
                self._step = "mat_date"
                return self._ask_mat_date(), False
            else:
                self._step = "con_date"
                return self._ask_con_date(), False
        # 확인
        return self._execute()

    # ── 실행 ─────────────────────────────────────────────────────────────────

    def _execute(self) -> tuple[str, bool]:
        from src.contracts.contract_generator import (
            generate_material_contract,
            generate_construction_contract,
        )
        import pathlib

        d = self.data
        sub = d.get("sub_name", "협력사")
        today = datetime.today().strftime("%Y%m%d")

        try:
            if self._type == "material":
                mat = d.get("material_type", "자재")
                fname = f"{today}_자재납품_{mat}_{sub}.docx"
                out_path = str(pathlib.Path(OUTPUT_DIR) / fname)
                generate_material_contract(d, out_path)
            else:
                con = d.get("construction_type", "공사")
                fname = f"{today}_공사_{con}_{sub}.docx"
                out_path = str(pathlib.Path(OUTPUT_DIR) / fname)
                generate_construction_contract(d, out_path)

            # 다운로드 토큰 발급 (소유권 추적)
            try:
                from src.chatbot._download_registry import register as register_download
                gw_id = self.user_context.get("gw_id", "")
                token = register_download(out_path, gw_id)
                download_url = f"/download/{token}"
            except Exception:
                download_url = f"/download/{fname}"

            return (
                f"✅ 계약서가 생성되었습니다!\n\n"
                f"📥 아래 링크를 클릭해서 다운로드하세요:\n\n"
                f"[📄 {fname}]({download_url})\n\n"
                f"파일을 열어 내용을 확인하고, 날인 후 보관해주세요.",
                True,
            )
        except Exception as e:
            logger.error(f"계약서 생성 오류: {e}")
            return f"❌ 계약서 생성 중 오류가 발생했습니다: {e}", True
