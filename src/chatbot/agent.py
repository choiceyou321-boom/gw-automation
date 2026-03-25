"""
Google Gemini 연동 + 의도 분석 에이전트
- 사용자 메시지와 첨부파일을 분석해 자동화 작업 라우팅
- Function calling 패턴으로 자동화 함수 호출
"""

import os
import base64
import logging
from google import genai
from google.genai import types

from src.chatbot.tools_schema import AUTOMATION_TOOLS
from src.chatbot.prompts import SYSTEM_PROMPT
from src.chatbot.handlers import TOOL_HANDLERS

logger = logging.getLogger(__name__)

# Gemini 클라이언트 (lazy 초기화 — API 키 없는 환경에서도 import 가능)
_client = None
MODEL_ID = "gemini-2.5-flash"


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    return _client

def build_message_parts(text: str, files: list[dict]) -> list:
    """
    텍스트 + 첨부파일로 Gemini 메시지 parts 구성.
    파일 이름 힌트를 텍스트로 먼저 추가하여 Gemini가 문서 종류를 더 잘 파악하도록 함.
    """
    parts = []

    # 첨부 파일 처리
    for f in files:
        file_type = f.get("type", "")
        file_data = f.get("data", "")  # base64
        file_name = f.get("name", "file")

        # 파일명 힌트: 문서 종류 파악을 돕는다
        if file_name and file_name != "file":
            parts.append(types.Part.from_text(text=f"[첨부파일: {file_name}]"))

        if file_type.startswith("image/"):
            parts.append(types.Part.from_bytes(
                data=base64.b64decode(file_data),
                mime_type=file_type,
            ))
        elif file_type == "application/pdf":
            parts.append(types.Part.from_bytes(
                data=base64.b64decode(file_data),
                mime_type="application/pdf",
            ))
        elif file_type.startswith("audio/"):
            # 음성 파일은 Gemini에 직접 전달하지 않음 (STT 모듈로 라우팅)
            parts.append(types.Part.from_text(
                text=f"[음성 파일: {file_name} ({file_type})] — 음성→텍스트 변환이 필요합니다."
            ))
        # 지원하지 않는 타입은 경고 없이 무시 (텍스트 힌트만 추가됨)

    # 사용자 텍스트 추가
    if text:
        parts.append(types.Part.from_text(text=text))

    return parts if parts else [types.Part.from_text(text=text or "안녕하세요")]


def _convert_history(conversation_history: list[dict]) -> list[types.Content]:
    """대화 히스토리를 Gemini 형식으로 변환"""
    contents = []
    for msg in conversation_history:
        role = "user" if msg["role"] == "user" else "model"
        text = msg["content"] if isinstance(msg["content"], str) else str(msg["content"])
        contents.append(types.Content(
            role=role,
            parts=[types.Part.from_text(text=text)],
        ))
    return contents


async def analyze_and_route(
    user_message: str,
    files: list[dict] = None,
    conversation_history: list[dict] = None,
    user_context: dict = None,
    attachment_path: str = None,
) -> dict:
    """
    사용자 메시지 분석 후 적절한 자동화 모듈 라우팅

    Returns:
        {
            "response": str,
            "action": str | None,
            "action_result": str | None
        }
    """
    if files is None:
        files = []
    if conversation_history is None:
        conversation_history = []

    # ── 계약서 마법사 활성화 시 Gemini 대신 직접 라우팅 ──
    if user_context and user_context.get("contract_wizard"):
        wizard = user_context["contract_wizard"]
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            response_msg, done = await loop.run_in_executor(None, wizard.process, user_message)
        except Exception as e:
            logger.error(f"contract_wizard 처리 오류: {e}")
            response_msg = f"계약서 마법사 처리 중 오류가 발생했습니다: {e}"
            done = True
        if done:
            user_context.pop("contract_wizard", None)
        return {"response": response_msg, "action": "contract_wizard", "action_result": None}

    # ── 전자결재 마법사가 활성화된 경우 Gemini 대신 마법사로 직접 라우팅 ──
    if user_context and user_context.get("approval_wizard"):
        wizard = user_context["approval_wizard"]
        try:
            import asyncio
            # wizard.process()는 동기 함수지만 실행 단계(_execute)에서 Playwright 블로킹 발생 가능
            # → run_in_executor로 이벤트 루프 블로킹 방지
            loop = asyncio.get_event_loop()
            response_msg, done = await loop.run_in_executor(None, wizard.process, user_message)
        except Exception as e:
            logger.error(f"approval_wizard 처리 오류: {e}")
            response_msg = f"마법사 처리 중 오류가 발생했습니다: {e}\n'/clear'로 대화를 초기화해주세요."
            done = True
        if done:
            user_context.pop("approval_wizard", None)
        return {"response": response_msg, "action": "approval_wizard", "action_result": None}

    # 메시지 parts 구성 (파일 포함)
    user_parts = build_message_parts(user_message, files)

    # 대화 히스토리 변환 + 현재 메시지
    contents = _convert_history(conversation_history)
    contents.append(types.Content(role="user", parts=user_parts))

    # 오늘 날짜를 시스템 프롬프트에 삽입
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    system_with_date = SYSTEM_PROMPT.replace("{today}", today)

    # Gemini API 호출 (function calling) — 동기 SDK를 이벤트 루프 밖에서 실행
    import asyncio
    response = await asyncio.to_thread(
        _get_client().models.generate_content,
        model=MODEL_ID,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_with_date,
            tools=AUTOMATION_TOOLS,
            temperature=0.7,
        ),
    )

    # 응답 처리
    result = {
        "response": "",
        "action": None,
        "action_result": None
    }

    # function call 확인
    function_call = None
    text_parts = []

    if response.candidates and response.candidates[0].content:
        for part in (response.candidates[0].content.parts or []):
            if part.function_call:
                function_call = part.function_call
            elif part.text:
                text_parts.append(part.text)

    if function_call:
        # 도구 실행
        tool_name = function_call.name
        tool_input = dict(function_call.args) if function_call.args else {}

        # 첨부파일 경로가 있으면 해당 도구에 주입
        if attachment_path and tool_name in (
            "submit_expense_approval",
            "submit_approval_form",
            "generate_contracts_from_file",
        ):
            if tool_name == "generate_contracts_from_file":
                tool_input.setdefault("file_path", attachment_path)
            else:
                tool_input.setdefault("attachment_path", attachment_path)

        handler = TOOL_HANDLERS.get(tool_name)

        if handler:
            action_result = handler(tool_input, user_context=user_context)
        else:
            action_result = f"'{tool_name}' 모듈이 준비 중입니다."
            # 미지원 툴 요청 기록
            try:
                from src.chatbot.chat_db import save_unsupported_request
                gw_id = (user_context or {}).get("gw_id", "unknown")
                save_unsupported_request(
                    gw_id=gw_id,
                    request_type=tool_name,
                    user_message=user_message,
                    detail="미구현 툴 호출",
                )
            except Exception:
                pass

        result["action"] = tool_name
        result["action_result"] = action_result

        # 도구 결과로 최종 응답 생성
        contents.append(response.candidates[0].content)
        contents.append(types.Content(
            role="user",
            parts=[types.Part.from_function_response(
                name=tool_name,
                response={"result": action_result},
            )],
        ))

        final_response = await asyncio.to_thread(
            _get_client().models.generate_content,
            model=MODEL_ID,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_with_date,
                tools=AUTOMATION_TOOLS,
                temperature=0.7,
            ),
        )

        if final_response.candidates and final_response.candidates[0].content:
            final_texts = [
                p.text for p in (final_response.candidates[0].content.parts or []) if p.text
            ]
            result["response"] = "\n".join(final_texts)
        else:
            result["response"] = action_result
    else:
        # 일반 텍스트 응답
        result["response"] = "\n".join(text_parts) if text_parts else "죄송합니다, 응답을 생성하지 못했습니다."

    return result
