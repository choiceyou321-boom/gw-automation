"""
Shared 도구 핸들러 — PM/GW 양쪽에서 공통 사용.

분리 계획 v4: C 도메인 (src/shared/).
연결 모듈: src/contracts/, src/chatbot/stt.py, src/chatbot/youtube_analyzer.py.
"""

from src.chatbot.handlers._impl import (
    handle_search_project_code,
    handle_start_contract_wizard_fn,
    handle_generate_contracts_from_file,
    handle_transcribe_audio,
    handle_analyze_youtube,
)

TOOLS: dict[str, callable] = {
    "search_project_code": handle_search_project_code,
    "start_contract_wizard": handle_start_contract_wizard_fn,
    "generate_contracts_from_file": handle_generate_contracts_from_file,
    "transcribe_audio": handle_transcribe_audio,
    "analyze_youtube": handle_analyze_youtube,
}

__all__ = list(TOOLS.keys()) + ["TOOLS"]
