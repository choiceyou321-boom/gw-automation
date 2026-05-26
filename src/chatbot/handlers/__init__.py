"""
chatbot.handlers — Gemini Function Calling 도구 핸들러 패키지

분리 계획 v4 P2: 도메인별 도구 dispatch 분류.

구성:
    pm.py        — PM(프로젝트 관리) 도구 14개
    gw.py        — GW(그룹웨어 자동화) 도구 15개
    shared.py    — 공통 도구 5개 (search/contract/transcribe 등)
    _impl.py     — 실제 핸들러 구현 (기존 handlers.py 통째 이동, 점진적 분할 예정)

호환성:
    기존 코드 `from src.chatbot.handlers import handle_xxx` 그대로 작동.
    신규 코드 권장: `from src.chatbot.handlers.pm import handle_xxx` (도메인 명시)
"""

# 기존 handlers의 모든 공개 심볼을 re-export (호환성 유지)
from src.chatbot.handlers._impl import *  # noqa: F401, F403

# 내부 심볼도 호환성을 위해 명시적 노출 (테스트에서 _user_locks 등 직접 접근)
from src.chatbot.handlers import _impl  # noqa: F401
from src.chatbot.handlers._impl import (  # noqa: F401
    _user_locks,
    _get_user_lock,
)

# 도메인별 분류 모듈도 함께 노출
from src.chatbot.handlers import pm, gw, shared, office  # noqa: F401

# Office 도메인 핸들러 직접 노출 (호환성을 위해 짧은 import 경로 지원)
from src.chatbot.handlers.office import (  # noqa: F401
    handle_save_contact_from_image,
    handle_list_contacts,
    handle_issue_tax_invoice,
    handle_list_tax_invoices,
    handle_cancel_tax_invoice,
)
