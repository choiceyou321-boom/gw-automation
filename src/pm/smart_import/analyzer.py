"""
Smart Import AI 분석기
- 사용자가 입력한 텍스트를 분석해 도메인 타입 자동 분류
- Gemini/Claude로 구조화된 데이터 추출
- 부족한 필드 리스트 반환
"""
import json
import logging
import os
from typing import Optional
from datetime import datetime

logger = logging.getLogger("smart_import_analyzer")


# 인메모리 분석 결과 캐시 (30분 TTL)
_analysis_cache: dict[str, dict] = {}


def _get_ai_client():
    """AI 클라이언트 선택 (Gemini 우선, 폴백 Claude)"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        try:
            from google import genai
            return ("gemini", genai.Client(api_key=api_key))
        except ImportError:
            logger.warning("Gemini not available, falling back to Claude")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            from anthropic import Anthropic
            return ("claude", Anthropic(api_key=api_key))
        except ImportError:
            logger.warning("Claude not available")

    logger.warning("No AI client configured")
    return (None, None)


def analyze(text: str, hint_project_id: Optional[int] = None) -> dict:
    """
    입력 텍스트를 분석해 도메인 타입 자동 분류 + 필드 추출

    Args:
        text: 사용자 입력 텍스트
        hint_project_id: URL에서 파싱한 프로젝트 ID (선택)

    Returns:
        {
            "analysis_id": "ai-20250528-001",
            "detected_type": "estimate|meeting|schedule|milestone|contacts|collection|overview|unknown",
            "confidence": 0.95,
            "extracted_fields": {...},
            "missing_fields": [
                {"field": "company_name", "label": "업체명", "required": true}
            ],
            "preview": {
                "title": "견적서 분석",
                "items": [...]
            }
        }
    """
    client_type, client = _get_ai_client()
    if client is None:
        logger.warning("No AI client available, using fallback detection")
        return _fallback_detection(text)

    if client_type == "gemini":
        return _analyze_with_gemini(client, text, hint_project_id)
    else:
        return _analyze_with_claude(client, text, hint_project_id)


def _analyze_with_gemini(client, text: str, hint_project_id: Optional[int]) -> dict:
    """Gemini를 사용한 분석"""
    system_prompt = """당신은 프로젝트 관리 AI 어시스턴트입니다.
사용자가 제공한 텍스트를 분석해 다음 중 하나로 분류하세요:
- estimate: 견적서, 산출내역서, 공사비 내역
- meeting: 회의록, 의사록, 회의 기록
- schedule: 공정표, 일정, 스케줄, 타임라인
- milestone: 마일스톤, 체크리스트, 진행 단계
- contacts: 연락처, 거래처 정보, 담당자
- collection: 수금 정보, 수입 기록
- overview: 프로젝트 개요, 프로젝트 정보
- unknown: 분류 불가

JSON 형식으로 응답하세요:
{
  "detected_type": "...",
  "confidence": 0.0-1.0,
  "extracted_fields": {...},
  "missing_fields": [
    {"field": "name", "label": "이름", "required": true}
  ],
  "reasoning": "..."
}"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[{
                "role": "user",
                "parts": [{
                    "text": f"{system_prompt}\n\n사용자 입력:\n{text}"
                }]
            }],
            generation_config={
                "temperature": 0.3,
                "top_p": 0.9,
            }
        )

        result_text = response.text
        # JSON 추출 (마크다운 코드블록 처리)
        if "```json" in result_text:
            start = result_text.find("```json") + 7
            end = result_text.find("```", start)
            result_text = result_text[start:end].strip()
        elif "```" in result_text:
            start = result_text.find("```") + 3
            end = result_text.find("```", start)
            result_text = result_text[start:end].strip()

        analysis = json.loads(result_text)

    except Exception as e:
        logger.error(f"Gemini 분석 실패: {e}")
        return _fallback_detection(text)

    # 응답 포장
    analysis_id = f"ai-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    analysis["analysis_id"] = analysis_id
    analysis["preview"] = _generate_preview(analysis["detected_type"], analysis.get("extracted_fields", {}))

    # 캐시 저장
    _analysis_cache[analysis_id] = analysis

    return analysis


def _analyze_with_claude(client, text: str, hint_project_id: Optional[int]) -> dict:
    """Claude를 사용한 분석"""
    system_prompt = """당신은 프로젝트 관리 AI 어시스턴트입니다.
사용자가 제공한 텍스트를 분석해 다음 중 하나로 분류하세요:
- estimate: 견적서, 산출내역서, 공사비 내역
- meeting: 회의록, 의사록, 회의 기록
- schedule: 공정표, 일정, 스케줄, 타임라인
- milestone: 마일스톤, 체크리스트, 진행 단계
- contacts: 연락처, 거래처 정보, 담당자
- collection: 수금 정보, 수입 기록
- overview: 프로젝트 개요, 프로젝트 정보
- unknown: 분류 불가

JSON 형식으로 응답하세요:
{
  "detected_type": "...",
  "confidence": 0.0-1.0,
  "extracted_fields": {...},
  "missing_fields": [
    {"field": "name", "label": "이름", "required": true}
  ],
  "reasoning": "..."
}"""

    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": f"사용자 입력:\n{text}"
            }]
        )

        result_text = response.content[0].text
        # JSON 추출 (마크다운 코드블록 처리)
        if "```json" in result_text:
            start = result_text.find("```json") + 7
            end = result_text.find("```", start)
            result_text = result_text[start:end].strip()
        elif "```" in result_text:
            start = result_text.find("```") + 3
            end = result_text.find("```", start)
            result_text = result_text[start:end].strip()

        analysis = json.loads(result_text)

    except Exception as e:
        logger.error(f"Claude 분석 실패: {e}")
        return _fallback_detection(text)

    # 응답 포장
    analysis_id = f"ai-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    analysis["analysis_id"] = analysis_id
    analysis["preview"] = _generate_preview(analysis["detected_type"], analysis.get("extracted_fields", {}))

    # 캐시 저장
    _analysis_cache[analysis_id] = analysis

    return analysis


def _fallback_detection(text: str) -> dict:
    """AI 미사용 시 규칙 기반 검출"""
    text_lower = text.lower()
    detected_type = "unknown"
    confidence = 0.3

    # 간단한 키워드 매칭
    if any(kw in text_lower for kw in ["견적", "산출내역", "공사비", "단가", "공종"]):
        detected_type = "estimate"
        confidence = 0.6
    elif any(kw in text_lower for kw in ["회의", "의사록", "결론", "토의"]):
        detected_type = "meeting"
        confidence = 0.6
    elif any(kw in text_lower for kw in ["공정", "일정", "스케줄", "시작일", "준공"]):
        detected_type = "schedule"
        confidence = 0.6
    elif any(kw in text_lower for kw in ["마일스톤", "체크리스트", "진행", "단계"]):
        detected_type = "milestone"
        confidence = 0.6
    elif any(kw in text_lower for kw in ["연락처", "전화", "이메일", "담당자", "회사명"]):
        detected_type = "contacts"
        confidence = 0.6
    elif any(kw in text_lower for kw in ["수금", "수입", "수령", "대금"]):
        detected_type = "collection"
        confidence = 0.6
    elif any(kw in text_lower for kw in ["프로젝트", "개요", "위치", "용도", "면적"]):
        detected_type = "overview"
        confidence = 0.6

    analysis_id = f"ai-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    result = {
        "analysis_id": analysis_id,
        "detected_type": detected_type,
        "confidence": confidence,
        "extracted_fields": {},
        "missing_fields": _get_missing_fields_for_type(detected_type),
        "preview": _generate_preview(detected_type, {}),
        "reasoning": "규칙 기반 검출 (AI 미사용)"
    }

    _analysis_cache[analysis_id] = result
    return result


def _get_missing_fields_for_type(detected_type: str) -> list[dict]:
    """도메인 타입별 필수/선택 필드"""
    fields_map = {
        "estimate": [
            {"field": "company_name", "label": "업체명", "required": True},
            {"field": "trade_name", "label": "공종", "required": True},
            {"field": "estimate_amount", "label": "견적금액", "required": True},
            {"field": "description", "label": "설명", "required": False},
        ],
        "meeting": [
            {"field": "title", "label": "회의명", "required": True},
            {"field": "date", "label": "회의일시", "required": True},
            {"field": "attendees", "label": "참석자", "required": False},
            {"field": "summary", "label": "주요 결론", "required": False},
        ],
        "schedule": [
            {"field": "item_name", "label": "항목명", "required": True},
            {"field": "start_date", "label": "시작일", "required": True},
            {"field": "end_date", "label": "종료일", "required": True},
            {"field": "description", "label": "설명", "required": False},
        ],
        "milestone": [
            {"field": "name", "label": "마일스톤명", "required": True},
            {"field": "target_date", "label": "목표일", "required": True},
            {"field": "description", "label": "설명", "required": False},
        ],
        "contacts": [
            {"field": "company_name", "label": "업체명", "required": True},
            {"field": "contact_person", "label": "담당자", "required": False},
            {"field": "phone", "label": "전화", "required": False},
            {"field": "email", "label": "이메일", "required": False},
        ],
        "collection": [
            {"field": "amount", "label": "금액", "required": True},
            {"field": "category", "label": "구분 (설계/시공)", "required": True},
            {"field": "collection_date", "label": "수금일", "required": False},
        ],
        "overview": [
            {"field": "location", "label": "위치", "required": False},
            {"field": "usage", "label": "용도", "required": False},
            {"field": "area_pyeong", "label": "면적 (평)", "required": False},
            {"field": "current_status", "label": "진행 현황", "required": False},
        ],
        "unknown": [
            {"field": "description", "label": "설명", "required": True},
        ]
    }

    return fields_map.get(detected_type, fields_map["unknown"])


def _generate_preview(detected_type: str, fields: dict) -> dict:
    """분석 결과 미리보기"""
    type_labels = {
        "estimate": "견적서",
        "meeting": "회의록",
        "schedule": "일정",
        "milestone": "마일스톤",
        "contacts": "연락처",
        "collection": "수금",
        "overview": "프로젝트 개요",
        "unknown": "기타"
    }

    return {
        "title": f"{type_labels.get(detected_type, '분석 결과')} 분석",
        "type_label": type_labels.get(detected_type, "기타"),
        "extracted_count": len(fields),
        "items": [
            {"key": k, "value": str(v)[:100]}
            for k, v in list(fields.items())[:5]
        ]
    }


def get_analysis(analysis_id: str) -> Optional[dict]:
    """캐시에서 분석 결과 조회"""
    return _analysis_cache.get(analysis_id)


def clear_analysis(analysis_id: str) -> bool:
    """분석 결과 캐시에서 제거"""
    if analysis_id in _analysis_cache:
        del _analysis_cache[analysis_id]
        return True
    return False
