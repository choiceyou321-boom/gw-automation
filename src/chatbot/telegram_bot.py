"""
텔레그램 - 그룹웨어 업무 자동화 (텔레그램 채널)
- /start, /login, /register 명령어
- /clear - 대화 내역 지우기 (로그인 유지)
- /mailcheck - 안 읽은 메일 요약 수신 + Notion 저장
- 이미지/PDF 파일 첨부 지원
- 인메모리 대화 히스토리 (단순 유지)
"""
from __future__ import annotations

import os
import sys
import base64
import logging
import time
import threading
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from dotenv import load_dotenv

# 루트 경로 설정 (자동화 work)
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

# 환경 변수 로드
load_dotenv(ROOT_DIR / "config" / ".env")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# 기존 로직 임포트
from src.chatbot.agent import analyze_and_route
from src.auth.user_db import verify_login, register as db_register, get_approval_config, set_approval_config

# 텔레그램 유저 ID → { user_context, history }
tg_sessions: dict[int, dict] = {}

# 비밀번호 대기 상태 (2-step 인증): {tg_user_id: {"type": "login"|"register", ...}}
_pending_auth: dict[int, dict] = {}

# 임시 파일 저장 경로
TMP_DIR = ROOT_DIR / "data" / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)

# 지원 확장자
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".xlsx", ".docx"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm"}
# 파일 크기 제한 (20MB)
MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """봇 시작 시 인사"""
    welcome_text = (
        "안녕하세요! 그룹웨어 업무 자동화 봇입니다.\n\n"
        "사용하시려면 그룹웨어 계정 인증이 필요합니다.\n"
        "아직 가입하지 않으셨다면 회원가입을 먼저 진행해주세요:\n"
        "`/register [아이디] [이름] [직급(선택)]`\n"
        "예시: `/register tgjeon 전태규 대리`\n"
        "(비밀번호는 다음 단계에서 별도 입력)\n\n"
        "이미 가입하셨다면 아래 명령어로 로그인해 주세요:\n"
        "`/login [아이디]`\n"
        "예시: `/login tgjeon`\n"
        "(비밀번호는 다음 단계에서 별도 입력)\n\n"
        "기타 명령어:\n"
        "`/mail` (또는 `/mailcheck`) - 안 읽은 메일 AI 요약 + Notion 저장\n"
        "`/setline 검토:이름 승인:이름` - 결재선 설정\n"
        "`/myline` - 현재 결재선 확인\n"
        "`/clear` - 대화 내역 지우기 (로그인 유지)"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')


async def register_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    텔레그램에서 회원가입 처리 (2-step 보안 플로우)
    Step 1: /register [아이디] [이름] [직급] → 비밀번호 요청
    Step 2: 사용자가 비밀번호만 별도 전송 → 즉시 삭제 후 가입 처리
    (하위호환: /register [아이디] [비밀번호] [이름] 도 지원하되 메시지 삭제)
    """
    args = context.args
    tg_user_id = update.effective_user.id

    if len(args) < 2:
        await update.message.reply_text(
            "사용법: `/register [아이디] [이름] [직급(선택)]`\n"
            "예시: `/register tgjeon 홍길동 선임`\n\n"
            "비밀번호는 다음 단계에서 별도로 입력합니다. (보안)",
            parse_mode='Markdown'
        )
        return

    # 하위호환: 3개 이상 인자 + 2번째가 한글이 아니면 기존 방식 (id pw name)
    if len(args) >= 3 and not any('\uac00' <= c <= '\ud7a3' for c in args[1]):
        # 기존 방식: /register id pw name [position]
        gw_id, gw_pw, name = args[0], args[1], args[2]
        position = args[3] if len(args) > 3 else ""
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=update.message.message_id,
            )
        except Exception as e:
            logger.warning(f"메시지 삭제 실패: {e}")
        result = db_register(gw_id=gw_id, gw_pw=gw_pw, name=name, position=position)
        if result["success"]:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"회원가입 성공!\n이제 `/login {gw_id}`를 입력해 로그인해 주세요.",
                parse_mode='Markdown',
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"회원가입 실패: {result['message']}",
            )
        return

    # 2-step 방식: /register id name [position]
    gw_id = args[0]
    name = args[1]
    position = args[2] if len(args) > 2 else ""
    _pending_auth[tg_user_id] = {
        "type": "register",
        "gw_id": gw_id,
        "name": name,
        "position": position,
    }
    await update.message.reply_text(
        f"아이디: `{gw_id}`, 이름: `{name}`\n\n"
        "비밀번호를 다음 메시지로 입력해주세요.\n"
        "(입력 즉시 메시지가 삭제됩니다)",
        parse_mode='Markdown',
    )


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    텔레그램 채팅방에서 그룹웨어 계정 연동 (2-step 보안 플로우)
    Step 1: /login [아이디] → 비밀번호 요청
    Step 2: 사용자가 비밀번호만 별도 전송 → 즉시 삭제 후 인증
    (하위호환: /login [아이디] [비밀번호] 도 지원하되 메시지 삭제)
    """
    args = context.args
    tg_user_id = update.effective_user.id

    if not args:
        await update.message.reply_text(
            "사용법: `/login [아이디]`\n"
            "예시: `/login tgjeon`\n\n"
            "비밀번호는 다음 단계에서 별도로 입력합니다. (보안)",
            parse_mode='Markdown',
        )
        return

    # 하위호환: /login id pw (2개 인자)
    if len(args) == 2:
        gw_id, gw_pw = args[0], args[1]
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=update.message.message_id,
            )
        except Exception as e:
            logger.warning(f"메시지 삭제 실패 (관리자 권한 필요): {e}")
        await _do_login(update, context, gw_id, gw_pw)
        return

    # 2-step 방식: /login id → 비밀번호 대기
    gw_id = args[0]
    _pending_auth[tg_user_id] = {"type": "login", "gw_id": gw_id}
    await update.message.reply_text(
        f"아이디: `{gw_id}`\n\n"
        "비밀번호를 다음 메시지로 입력해주세요.\n"
        "(입력 즉시 메시지가 삭제됩니다)",
        parse_mode='Markdown',
    )


async def _do_login(update: Update, context: ContextTypes.DEFAULT_TYPE, gw_id: str, gw_pw: str):
    """실제 로그인 처리 (공통)"""
    user = verify_login(gw_id, gw_pw)
    if user:
        tg_sessions[update.effective_user.id] = {
            "gw_id": user["gw_id"],
            "name": user["name"],
            "position": user.get("position", ""),
            "emp_seq": user.get("emp_seq", ""),
            "dept_seq": user.get("dept_seq", ""),
            "email_addr": user.get("email_addr", ""),
            "history": [],
        }
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"로그인 성공! 환영합니다, *{user['name']}*님.\n이제 자유롭게 업무를 요청해 주세요.",
            parse_mode='Markdown',
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="인증 실패: 아이디 또는 비밀번호가 올바르지 않거나 아직 회원가입을 하지 않으셨습니다.",
        )


async def clear_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """대화 내역 지우기 (로그인 유지)"""
    tg_user_id = update.effective_user.id
    if tg_user_id not in tg_sessions:
        await update.message.reply_text(
            "먼저 로그인을 해주세요.\n`/login [아이디] [비밀번호]`", parse_mode='Markdown'
        )
        return

    tg_sessions[tg_user_id]["history"] = []
    await update.message.reply_text("대화 내역이 지워졌습니다. 새로운 대화를 시작하세요.")


async def mailcheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /mailcheck — 안 읽은 메일 요약 → 텔레그램 응답 + Notion 저장.
    Playwright(동기)를 asyncio 블로킹 없이 executor에서 실행.
    """
    tg_user_id = update.effective_user.id
    session = _check_login(tg_user_id)

    if not session:
        await update.message.reply_text(
            "먼저 로그인을 해주세요.\n`/login [아이디] [비밀번호]`", parse_mode='Markdown'
        )
        return

    await update.message.reply_text("메일함을 확인하는 중입니다. 잠시 기다려주세요...")
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action='typing'
    )

    try:
        from src.mail.summarizer import run_mail_push_for_user
        gw_id = session.get("gw_id", "")
        chat_id = update.effective_chat.id

        result = await run_mail_push_for_user(
            gw_id=gw_id,
            bot_token=TELEGRAM_TOKEN,
            chat_id=chat_id,
            max_count=5,
        )

        if result["count"] == 0:
            # 새 메일 없음 - run_mail_push_for_user가 텔레그램으로 보내지 않으므로 직접 응답
            await update.message.reply_text("현재 안 읽은 새로운 메일이 없습니다.")
        elif not result["success"]:
            # 메일은 수집했지만 푸시 전송 실패 → 메시지는 이미 answer로 전송
            await update.message.reply_text(
                f"메일 {result['count']}건을 수집했으나 전송에 실패했습니다. ({result['message']})"
            )
        # 성공 시 run_mail_push_for_user 내부에서 텔레그램 전송 완료

    except Exception as e:
        logger.error(f"mailcheck 실패: {e}", exc_info=True)
        await update.message.reply_text(f"메일 확인 중 오류가 발생했습니다: {str(e)[:200]}")


async def setline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /setline — 사용자별 결재선 설정.
    사용법:
      /setline 검토:신동관 승인:최기영       → default 결재선 설정
      /setline 지출결의서 검토:신동관 승인:최기영  → 양식별 결재선 설정
      /setline 간단 승인:최기영              → "간단" 프리셋 결재선 설정
      /setline 거래처등록 승인:최기영          → 거래처등록 양식 결재선 설정
    """
    tg_user_id = update.effective_user.id
    session = _check_login(tg_user_id)
    if not session:
        await update.message.reply_text(
            "먼저 로그인을 해주세요.\n`/login [아이디] [비밀번호]`", parse_mode='Markdown'
        )
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "사용법:\n"
            "`/setline 검토:이름 승인:이름` — 기본 결재선 설정\n"
            "`/setline 지출결의서 검토:이름 승인:이름` — 양식별 설정\n"
            "`/setline 간단 승인:이름` — 간단 결재선 설정\n\n"
            "예시:\n"
            "`/setline 검토:신동관 승인:최기영`\n"
            "`/setline 거래처등록 승인:최기영`",
            parse_mode='Markdown',
        )
        return

    gw_id = session.get("gw_id")
    if not gw_id:
        await update.message.reply_text("로그인 정보를 확인할 수 없습니다.")
        return

    # 인자 파싱: 첫 번째 인자가 "검토:" 또는 "승인:"으로 시작하면 양식명 없음 (default)
    # 아니면 첫 번째 인자가 양식명/프리셋명
    line_args = list(args)
    target_key = "default"  # 기본 키

    # 첫 번째 인자가 "검토:" 또는 "승인:"이 아니면 양식명으로 간주
    if line_args and not line_args[0].startswith(("검토:", "승인:")):
        target_key = line_args.pop(0)

    if not line_args:
        await update.message.reply_text(
            "결재선 정보가 부족합니다. `검토:이름` 또는 `승인:이름`을 입력해주세요.",
            parse_mode='Markdown',
        )
        return

    # "검토:이름", "승인:이름" 파싱
    line = {}
    for arg in line_args:
        if arg.startswith("검토:"):
            line["agree"] = arg[3:]
        elif arg.startswith("승인:"):
            line["final"] = arg[3:]
        else:
            await update.message.reply_text(
                f"알 수 없는 형식: `{arg}`\n`검토:이름` 또는 `승인:이름` 형식으로 입력해주세요.",
                parse_mode='Markdown',
            )
            return

    if "final" not in line:
        await update.message.reply_text(
            "최종 승인자(`승인:이름`)는 필수입니다.",
            parse_mode='Markdown',
        )
        return

    # 기존 설정 불러와서 머지
    existing_config = get_approval_config(gw_id)
    existing_config[target_key] = line
    result = set_approval_config(gw_id, existing_config)

    if result["success"]:
        line_desc = ""
        if line.get("agree"):
            line_desc += f"검토: {line['agree']} → "
        line_desc += f"승인: {line['final']}"
        await update.message.reply_text(
            f"결재선이 설정되었습니다.\n\n"
            f"대상: **{target_key}**\n"
            f"결재선: {line_desc}",
            parse_mode='Markdown',
        )
    else:
        await update.message.reply_text(f"설정 실패: {result['message']}")


async def myline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/myline — 현재 설정된 결재선 확인"""
    tg_user_id = update.effective_user.id
    session = _check_login(tg_user_id)
    if not session:
        await update.message.reply_text(
            "먼저 로그인을 해주세요.\n`/login [아이디] [비밀번호]`", parse_mode='Markdown'
        )
        return

    gw_id = session.get("gw_id")
    if not gw_id:
        await update.message.reply_text("로그인 정보를 확인할 수 없습니다.")
        return

    config = get_approval_config(gw_id)
    if not config:
        await update.message.reply_text(
            "설정된 결재선이 없습니다. (양식 기본값 사용 중)\n\n"
            "설정하려면: `/setline 검토:이름 승인:이름`",
            parse_mode='Markdown',
        )
        return

    lines = ["현재 설정된 결재선:\n"]
    for key, line in config.items():
        desc = f"  **{key}**: "
        parts = []
        if line.get("agree"):
            parts.append(f"검토 → {line['agree']}")
        if line.get("final"):
            parts.append(f"승인 → {line['final']}")
        desc += " → ".join(parts) if parts else "(설정 없음)"
        lines.append(desc)

    lines.append("\n변경: `/setline [양식명] 검토:이름 승인:이름`")
    await update.message.reply_text("\n".join(lines), parse_mode='Markdown')


def _check_login(tg_user_id: int) -> dict | None:
    """로그인 세션 확인, 없으면 None"""
    return tg_sessions.get(tg_user_id)


def _get_user_context(session: dict) -> dict:
    """세션에서 user_context만 추출 (history 제외)"""
    return {k: v for k, v in session.items() if k != "history"}


def _append_history(session: dict, role: str, content: str):
    """히스토리에 메시지 추가 (최근 40개만 유지)"""
    session["history"].append({"role": role, "content": content})
    if len(session["history"]) > 40:
        session["history"] = session["history"][-40:]


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """일반 텍스트 메시지 처리"""
    tg_user_id = update.effective_user.id

    # ── 2-step 인증: 비밀번호 대기 중이면 여기서 처리 ──
    pending = _pending_auth.pop(tg_user_id, None)
    if pending:
        gw_pw = update.message.text.strip()
        # 비밀번호 메시지 즉시 삭제
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=update.message.message_id,
            )
        except Exception as e:
            logger.warning(f"비밀번호 메시지 삭제 실패: {e}")

        if pending["type"] == "login":
            await _do_login(update, context, pending["gw_id"], gw_pw)
        elif pending["type"] == "register":
            result = db_register(
                gw_id=pending["gw_id"], gw_pw=gw_pw,
                name=pending["name"], position=pending.get("position", ""),
            )
            if result["success"]:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"회원가입 성공!\n이제 `/login {pending['gw_id']}`를 입력해 로그인해 주세요.",
                    parse_mode='Markdown',
                )
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"회원가입 실패: {result['message']}",
                )
        return

    session = _check_login(tg_user_id)

    if not session:
        await update.message.reply_text(
            "먼저 로그인을 해주세요.\n`/login [아이디] [비밀번호]`", parse_mode='Markdown'
        )
        return

    # ── dispatch 수정 모드 처리 ──
    if session.get("dispatch_edit_mode") and session.get("pending_dispatch"):
        user_text = update.message.text.strip()
        if user_text == "확인":
            # 수정 완료 → confirm 처리 실행
            session.pop("dispatch_edit_mode", None)
            pending = session["pending_dispatch"]
            await update.message.reply_text("⏳ GW에 작성 중입니다...")
            form_type = pending["form_type"]
            extracted_data = pending["extracted_data"].copy()
            clean_data = {k: v for k, v in extracted_data.items() if not k.startswith("_")}
            user_ctx = _get_user_context(session)
            try:
                from src.chatbot.handlers import TOOL_HANDLERS
                if form_type == "지출결의서":
                    handler = TOOL_HANDLERS.get("submit_expense_approval")
                    result_str = handler(clean_data, user_context=user_ctx)
                else:
                    handler = TOOL_HANDLERS.get("submit_approval_form")
                    result_str = handler({"form_type": form_type, "data": clean_data}, user_context=user_ctx)
                session.pop("pending_dispatch", None)
                await update.message.reply_text(f"✅ 완료!\n\n{result_str}")
            except Exception as e:
                await update.message.reply_text(f"❌ GW 작성 중 오류가 발생했습니다.\n{str(e)}")
        else:
            # 필드 수정 파싱: "날짜 2026-03-25" 형식
            _parse_edit_command(session, user_text)
            await update.message.reply_text(
                "수정됐습니다. 계속 수정하거나 `확인`을 입력하세요.",
                parse_mode="Markdown",
            )
        return

    user_message = update.message.text

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action='typing'
    )

    # 세션에 보관된 임시 첨부파일 경로 확인 후 소비
    pending_attachment = session.pop("pending_attachment_path", None)

    try:
        result = await analyze_and_route(
            user_message=user_message,
            files=[],
            conversation_history=list(session["history"]),
            user_context=_get_user_context(session),
            attachment_path=pending_attachment or None,
        )

        _append_history(session, "user", user_message)
        _append_history(session, "assistant", result["response"])

        # 결재 도구가 실행됐으면 첨부파일 삭제 (성공/실패 무관)
        if pending_attachment and result.get("action") in ("submit_expense_approval", "submit_approval_form"):
            try:
                Path(pending_attachment).unlink(missing_ok=True)
            except Exception:
                pass

        response_text = result["response"]
        if len(response_text) > 4000:
            response_text = response_text[:4000] + "\n\n(메시지가 길어 일부 생략되었습니다)"

        await update.message.reply_text(response_text)

    except Exception as e:
        logger.error(f"메시지 처리 실패: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "오류가 발생하여 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."
        )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """사진 첨부 메시지 처리"""
    tg_user_id = update.effective_user.id
    session = _check_login(tg_user_id)

    if not session:
        await update.message.reply_text(
            "먼저 로그인을 해주세요.\n`/login [아이디] [비밀번호]`", parse_mode='Markdown'
        )
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action='typing'
    )

    try:
        photo = update.message.photo[-1]

        # 파일 크기 확인
        if photo.file_size and photo.file_size > MAX_ATTACHMENT_SIZE:
            await update.message.reply_text("파일 크기가 20MB를 초과합니다.")
            return

        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()

        # 지출결의서/결재 첨부용으로 임시 파일 저장
        gw_id = session.get("gw_id", "unknown")
        tmp_path = TMP_DIR / f"{gw_id}_{int(time.time())}_photo.jpg"
        tmp_path.write_bytes(bytes(photo_bytes))
        session["pending_attachment_path"] = str(tmp_path)

        # ── Vision Dispatch 우선 처리 ──
        try:
            from src.vision import dispatch_document
            parse_result = await dispatch_document(bytes(photo_bytes), "image/jpeg")

            if parse_result.form_type and parse_result.confidence >= 0.7:
                # 신뢰도 70% 이상 → 확인 메시지 + 인라인 버튼 전송
                await _send_dispatch_confirm(update, context, session, parse_result, tmp_path)
                return
            elif parse_result.confidence < 0.4:
                # 신뢰도 40% 미만 → 불명확 안내
                await update.message.reply_text(
                    "📷 사진이 불명확하거나 지원하지 않는 문서입니다.\n"
                    "더 선명하게 찍어서 다시 올려주세요."
                )
                return
            # 신뢰도 0.4~0.7: 일반 Gemini 대화로 폴백
        except ImportError:
            pass  # vision 모듈 없으면 기존 방식으로 폴백

        # ── 기존 Gemini 대화 방식 (폴백) ──
        encoded = base64.b64encode(bytes(photo_bytes)).decode("utf-8")
        files = [{"name": "photo.jpg", "type": "image/jpeg", "data": encoded}]
        user_message = update.message.caption or "이 이미지를 분석해주세요."

        result = await analyze_and_route(
            user_message=user_message,
            files=files,
            conversation_history=list(session["history"]),
            user_context=_get_user_context(session),
        )

        _append_history(session, "user", f"[사진 첨부] {user_message}")
        _append_history(session, "assistant", result["response"])

        # 결재 도구가 이번 메시지에서 바로 실행됐으면 첨부파일 삭제
        if result.get("action") in ("submit_expense_approval", "submit_approval_form"):
            try:
                tmp_path.unlink(missing_ok=True)
                session.pop("pending_attachment_path", None)
            except Exception:
                pass

        response_text = result["response"]
        if len(response_text) > 4000:
            response_text = response_text[:4000] + "\n\n(메시지가 길어 일부 생략되었습니다)"

        await update.message.reply_text(response_text)

    except Exception as e:
        logger.error(f"사진 처리 실패: {str(e)}", exc_info=True)
        await update.message.reply_text("사진 처리 중 오류가 발생했습니다.")


async def _send_dispatch_confirm(update, context, session, parse_result, image_path):
    """Vision Dispatch 확인 메시지 + 인라인 버튼 전송"""
    doc_type = parse_result.document_type
    form_type = parse_result.form_type
    data = parse_result.extracted_data
    confidence_pct = int(parse_result.confidence * 100)

    # 추출 데이터 요약 텍스트 생성
    lines = [f"📄 *{doc_type}* 감지됨 (신뢰도 {confidence_pct}%)\n"]
    lines.append(f"➡️ *{form_type}*으로 작성할게요:\n")

    # 문서 타입별 표시 필드
    field_display = {
        "지출결의서": [
            ("날짜", "date"),
            ("금액", "total_amount"),
            ("항목", "_merchant"),
            ("용도", "_category"),
            ("결제수단", "_payment_method"),
        ],
        "거래처등록신청서": [
            ("회사명", "company_name"),
            ("사업자번호", "business_number"),
            ("대표자", "representative"),
            ("업태/종목", None),  # 업태와 종목 합쳐서 표시
        ],
    }

    fields = field_display.get(form_type, [])
    for label, key in fields:
        if key is None:
            # 업태/종목 특수 처리
            val = f"{data.get('business_type', '?')} / {data.get('business_item', '?')}"
        else:
            val = data.get(key, "미확인")
        if val and val != "미확인":
            if key == "total_amount" and isinstance(val, int):
                val = f"{val:,}원"
            lines.append(f"  ├ {label}: {val}")

    if parse_result.missing_fields:
        lines.append(f"\n⚠️ 미확인 필드: {', '.join(parse_result.missing_fields)}")
    if parse_result.warnings:
        for w in parse_result.warnings:
            lines.append(f"⚠️ {w}")

    lines.append("\n어떻게 할까요?")

    # 인라인 버튼 구성
    keyboard = [
        [
            InlineKeyboardButton("✅ GW에 작성 (보관)", callback_data="dispatch_confirm"),
            InlineKeyboardButton("❌ 취소", callback_data="dispatch_cancel"),
        ],
        [InlineKeyboardButton("✏️ 내용 수정 후 작성", callback_data="dispatch_edit")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # 세션에 pending_dispatch 저장
    session["pending_dispatch"] = {
        "document_type": doc_type,
        "form_type": form_type,
        "extracted_data": data,
        "image_path": str(image_path),
        "confidence": parse_result.confidence,
        "missing_fields": parse_result.missing_fields,
        "warnings": parse_result.warnings,
    }

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


def _parse_edit_command(session: dict, user_text: str):
    """
    dispatch 수정 명령 파싱.
    형식: "날짜 2026-03-25", "금액 50000", "항목 점심식사" 등
    세션의 pending_dispatch.extracted_data를 직접 갱신한다.
    """
    # 한국어 레이블 → extracted_data 키 매핑
    label_to_key = {
        "날짜": "date",
        "금액": "total_amount",
        "항목": "_merchant",
        "용도": "_category",
        "결제수단": "_payment_method",
        "회사명": "company_name",
        "사업자번호": "business_number",
        "대표자": "representative",
        "업태": "business_type",
        "종목": "business_item",
    }
    parts = user_text.split(maxsplit=1)
    if len(parts) < 2:
        return  # 형식 불일치는 무시

    label, value = parts[0].strip(), parts[1].strip()
    key = label_to_key.get(label)
    if key and session.get("pending_dispatch"):
        # 금액 필드는 숫자로 변환 시도
        if key == "total_amount":
            try:
                value = int(value.replace(",", "").replace("원", ""))
            except ValueError:
                pass
        session["pending_dispatch"]["extracted_data"][key] = value


async def handle_dispatch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """인라인 버튼 클릭 처리 (Vision Dispatch 확인/수정/취소)"""
    query = update.callback_query
    await query.answer()  # 버튼 로딩 스피너 제거

    tg_user_id = update.effective_user.id
    session = _check_login(tg_user_id)
    if not session:
        await query.edit_message_text("세션이 만료되었습니다. 다시 로그인해주세요.")
        return

    pending = session.get("pending_dispatch")
    if not pending:
        await query.edit_message_text("처리할 문서가 없습니다.")
        return

    action = query.data  # "dispatch_confirm" | "dispatch_cancel" | "dispatch_edit"

    if action == "dispatch_cancel":
        # 취소 처리
        session.pop("pending_dispatch", None)
        session.pop("dispatch_edit_mode", None)
        await query.edit_message_text("❌ 취소되었습니다.")
        return

    if action == "dispatch_edit":
        # 수정 모드 진입: 다음 텍스트 메시지에서 필드 수정 입력 대기
        session["dispatch_edit_mode"] = True
        await query.edit_message_text(
            "✏️ 수정할 내용을 입력해주세요.\n"
            "형식: `레이블 값` (예: `날짜 2026-03-25`, `금액 50000`, `항목 점심식사`)\n\n"
            "수정 완료 후 `확인`을 입력하면 GW에 작성합니다.",
            parse_mode="Markdown",
        )
        return

    if action == "dispatch_confirm":
        # GW 자동 입력 실행
        await query.edit_message_text("⏳ GW에 작성 중입니다...")

        form_type = pending["form_type"]
        extracted_data = pending["extracted_data"].copy()
        # 내부 메타 필드(_로 시작) 제거
        clean_data = {k: v for k, v in extracted_data.items() if not k.startswith("_")}

        user_ctx = _get_user_context(session)

        try:
            from src.chatbot.handlers import TOOL_HANDLERS
            if form_type == "지출결의서":
                handler = TOOL_HANDLERS.get("submit_expense_approval")
                result_str = handler(clean_data, user_context=user_ctx)
            else:
                handler = TOOL_HANDLERS.get("submit_approval_form")
                result_str = handler(
                    {"form_type": form_type, "data": clean_data},
                    user_context=user_ctx,
                )
            session.pop("pending_dispatch", None)
            await query.edit_message_text(f"✅ 완료!\n\n{result_str}")
        except Exception as e:
            logger.error(f"dispatch_confirm GW 작성 실패: {e}", exc_info=True)
            await query.edit_message_text(f"❌ GW 작성 중 오류가 발생했습니다.\n{str(e)}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """문서(PDF, 이미지, xlsx, docx 등) 첨부 메시지 처리"""
    tg_user_id = update.effective_user.id
    session = _check_login(tg_user_id)

    if not session:
        await update.message.reply_text(
            "먼저 로그인을 해주세요.\n`/login [아이디] [비밀번호]`", parse_mode='Markdown'
        )
        return

    doc = update.message.document
    mime = doc.mime_type or ""
    file_name = doc.file_name or "file"
    ext = Path(file_name).suffix.lower()

    # 오디오 파일이 문서로 전송된 경우 → STT 처리
    is_audio = ext in AUDIO_EXTENSIONS or mime.startswith("audio/")
    if is_audio:
        # handle_audio와 동일한 로직으로 처리
        if doc.file_size and doc.file_size > MAX_ATTACHMENT_SIZE:
            await update.message.reply_text("파일 크기가 20MB를 초과합니다.")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
        try:
            file = await context.bot.get_file(doc.file_id)
            file_bytes = await file.download_as_bytearray()
            gw_id = session.get("gw_id", "unknown")
            tmp_path = TMP_DIR / f"{gw_id}_{int(time.time())}_{Path(file_name).name}"
            tmp_path.write_bytes(bytes(file_bytes))

            await update.message.reply_text(f"🎤 음성 파일({file_name}) 변환 중...")
            from src.chatbot.stt import transcribe_audio
            result = transcribe_audio(str(tmp_path))

            if result["success"] and result["text"]:
                text = result["text"]
                stt_msg = f"🎤 변환 완료 ({result['duration_seconds']}초, 신뢰도 {result['confidence']:.0%}):\n\"{text}\""
                user_msg = update.message.caption or text
                ai_result = await analyze_and_route(
                    user_message=user_msg, files=[],
                    conversation_history=list(session["history"]),
                    user_context=_get_user_context(session),
                )
                _append_history(session, "user", f"[오디오: {file_name}] {user_msg}")
                _append_history(session, "assistant", ai_result["response"])
                response_text = f"{stt_msg}\n\n{ai_result['response']}"
                if len(response_text) > 4000:
                    response_text = response_text[:4000] + "\n\n(메시지가 길어 일부 생략되었습니다)"
                await update.message.reply_text(response_text)
            else:
                await update.message.reply_text(f"음성 변환 실패: {result.get('error', '알 수 없는 오류')}")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        except Exception as e:
            logger.error(f"오디오(문서) 처리 실패: {str(e)}", exc_info=True)
            await update.message.reply_text("오디오 파일 처리 중 오류가 발생했습니다.")
        return

    # Gemini 분석 가능 타입 (이미지/PDF)
    gemini_supported = ("image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf")
    # 첨부파일 저장만 가능한 확장자 (xlsx, docx 등)
    attachment_only = ext in ALLOWED_EXTENSIONS and mime not in gemini_supported

    if mime not in gemini_supported and not attachment_only:
        await update.message.reply_text(
            "지원하지 않는 파일 형식입니다.\n"
            "지원: JPG, PNG, GIF, WebP, PDF (분석+첨부) / XLSX, DOCX (첨부만) / MP3, WAV, M4A, OGG (음성변환)"
        )
        return

    if doc.file_size and doc.file_size > MAX_ATTACHMENT_SIZE:
        await update.message.reply_text("파일 크기가 20MB를 초과합니다.")
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action='typing'
    )

    try:
        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()

        # 지출결의서/결재 첨부용으로 임시 파일 저장 (지원 확장자인 경우)
        gw_id = session.get("gw_id", "unknown")
        safe_name = Path(file_name).name
        tmp_path = TMP_DIR / f"{gw_id}_{int(time.time())}_{safe_name}"
        tmp_path.write_bytes(bytes(file_bytes))
        session["pending_attachment_path"] = str(tmp_path)

        # Gemini 분석이 가능한 타입이면 base64로 전달, 아니면 빈 files 리스트
        if mime in gemini_supported:
            encoded = base64.b64encode(bytes(file_bytes)).decode("utf-8")
            files = [{"name": file_name, "type": mime, "data": encoded}]
            user_message = update.message.caption or f"이 파일({file_name})을 분석해주세요."
        else:
            files = []
            user_message = (
                update.message.caption
                or f"파일({file_name})을 첨부했습니다. 이 파일을 결재 문서에 첨부해주세요."
            )

        result = await analyze_and_route(
            user_message=user_message,
            files=files,
            conversation_history=list(session["history"]),
            user_context=_get_user_context(session),
        )

        _append_history(session, "user", f"[파일: {file_name}] {user_message}")
        _append_history(session, "assistant", result["response"])

        # 결재 도구가 이번 메시지에서 바로 실행됐으면 첨부파일 삭제
        if result.get("action") in ("submit_expense_approval", "submit_approval_form"):
            try:
                tmp_path.unlink(missing_ok=True)
                session.pop("pending_attachment_path", None)
            except Exception:
                pass

        response_text = result["response"]
        if len(response_text) > 4000:
            response_text = response_text[:4000] + "\n\n(메시지가 길어 일부 생략되었습니다)"

        await update.message.reply_text(response_text)

    except Exception as e:
        logger.error(f"문서 처리 실패: {str(e)}", exc_info=True)
        await update.message.reply_text("파일 처리 중 오류가 발생했습니다.")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """텔레그램 음성 메시지 (녹음) 처리 → STT 변환"""
    tg_user_id = update.effective_user.id
    session = _check_login(tg_user_id)

    if not session:
        await update.message.reply_text(
            "먼저 로그인을 해주세요.\n`/login [아이디] [비밀번호]`", parse_mode='Markdown'
        )
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action='typing'
    )

    try:
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        file_bytes = await file.download_as_bytearray()

        # 음성 메시지는 OGG 형식
        gw_id = session.get("gw_id", "unknown")
        tmp_path = TMP_DIR / f"{gw_id}_{int(time.time())}_voice.ogg"
        tmp_path.write_bytes(bytes(file_bytes))

        # STT 변환
        from src.chatbot.stt import transcribe_audio
        result = transcribe_audio(str(tmp_path))

        if result["success"] and result["text"]:
            text = result["text"]
            confidence = result["confidence"]
            duration = result["duration_seconds"]

            # 변환 결과를 사용자에게 보여주고 챗봇에 전달
            stt_msg = f"🎤 음성 인식 ({duration}초, 신뢰도 {confidence:.0%}):\n\"{text}\""
            await update.message.reply_text(stt_msg)

            # 변환된 텍스트를 챗봇으로 라우팅
            ai_result = await analyze_and_route(
                user_message=text,
                files=[],
                conversation_history=list(session["history"]),
                user_context=_get_user_context(session),
            )

            _append_history(session, "user", f"[음성] {text}")
            _append_history(session, "assistant", ai_result["response"])

            response_text = ai_result["response"]
            if len(response_text) > 4000:
                response_text = response_text[:4000] + "\n\n(메시지가 길어 일부 생략되었습니다)"
            await update.message.reply_text(response_text)
        else:
            error = result.get("error", "알 수 없는 오류")
            await update.message.reply_text(f"음성 인식에 실패했습니다.\n오류: {error}")

        # 임시 파일 정리
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

    except Exception as e:
        logger.error(f"음성 처리 실패: {str(e)}", exc_info=True)
        await update.message.reply_text("음성 처리 중 오류가 발생했습니다.")


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """텔레그램 오디오 파일 (MP3 등) 처리 → STT 변환"""
    tg_user_id = update.effective_user.id
    session = _check_login(tg_user_id)

    if not session:
        await update.message.reply_text(
            "먼저 로그인을 해주세요.\n`/login [아이디] [비밀번호]`", parse_mode='Markdown'
        )
        return

    audio = update.message.audio
    file_name = audio.file_name or "audio.mp3"
    ext = Path(file_name).suffix.lower()

    if ext not in AUDIO_EXTENSIONS:
        await update.message.reply_text(
            "지원하지 않는 오디오 형식입니다.\n지원: MP3, WAV, M4A, OGG, FLAC, WebM"
        )
        return

    if audio.file_size and audio.file_size > MAX_ATTACHMENT_SIZE:
        await update.message.reply_text("파일 크기가 20MB를 초과합니다.")
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action='typing'
    )

    try:
        file = await context.bot.get_file(audio.file_id)
        file_bytes = await file.download_as_bytearray()

        gw_id = session.get("gw_id", "unknown")
        safe_name = Path(file_name).name
        tmp_path = TMP_DIR / f"{gw_id}_{int(time.time())}_{safe_name}"
        tmp_path.write_bytes(bytes(file_bytes))

        await update.message.reply_text(f"🎤 음성 파일({file_name}) 변환 중...")

        # STT 변환
        from src.chatbot.stt import transcribe_audio
        result = transcribe_audio(str(tmp_path))

        if result["success"] and result["text"]:
            text = result["text"]
            confidence = result["confidence"]
            duration = result["duration_seconds"]

            stt_msg = f"🎤 변환 완료 ({duration}초, 신뢰도 {confidence:.0%}):\n\"{text}\""

            # 변환된 텍스트를 챗봇으로 라우팅
            user_msg = update.message.caption or text
            ai_result = await analyze_and_route(
                user_message=user_msg,
                files=[],
                conversation_history=list(session["history"]),
                user_context=_get_user_context(session),
            )

            _append_history(session, "user", f"[오디오: {file_name}] {user_msg}")
            _append_history(session, "assistant", ai_result["response"])

            response_text = f"{stt_msg}\n\n{ai_result['response']}"
            if len(response_text) > 4000:
                response_text = response_text[:4000] + "\n\n(메시지가 길어 일부 생략되었습니다)"
            await update.message.reply_text(response_text)
        else:
            error = result.get("error", "알 수 없는 오류")
            await update.message.reply_text(f"음성 변환에 실패했습니다.\n오류: {error}")

        # 임시 파일 정리
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

    except Exception as e:
        logger.error(f"오디오 처리 실패: {str(e)}", exc_info=True)
        await update.message.reply_text("오디오 파일 처리 중 오류가 발생했습니다.")


def _build_application() -> Application:
    """봇 Application 인스턴스 생성 (핸들러 포함)"""
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # 명령어 핸들러
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("register", register_user))
    app.add_handler(CommandHandler("clear", clear_chat))
    app.add_handler(CommandHandler("mailcheck", mailcheck))
    app.add_handler(CommandHandler("mail", mailcheck))  # /mail 단축 별칭
    app.add_handler(CommandHandler("setline", setline))
    app.add_handler(CommandHandler("myline", myline))

    # 인라인 버튼 콜백 핸들러 (Vision Dispatch 확인/수정/취소)
    app.add_handler(CallbackQueryHandler(handle_dispatch_callback, pattern="^dispatch_"))

    # 메시지 핸들러
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    return app


# ── 백그라운드 실행용 전역 상태 ──────────────────────────
_tg_app: Application | None = None
_tg_thread: threading.Thread | None = None
_stop_event = threading.Event()


def start_telegram_bot() -> None:
    """챗봇 서버와 함께 텔레그램 봇을 백그라운드 스레드로 시작."""
    global _tg_app, _tg_thread

    if not TELEGRAM_TOKEN:
        logger.warning("TELEGRAM_TOKEN 없음 — 텔레그램 봇 비활성화")
        return

    if _tg_thread and _tg_thread.is_alive():
        logger.info("텔레그램 봇이 이미 실행 중")
        return

    _stop_event.clear()

    def _run():
        global _tg_app
        import asyncio

        async def _poll():
            global _tg_app
            _tg_app = _build_application()
            logger.info("텔레그램 봇 폴링 시작 (@GlowSeoul_PM_Team_bot)")
            async with _tg_app:
                await _tg_app.updater.start_polling(drop_pending_updates=True)
                await _tg_app.start()
                # 실행 중 대기 — stop_telegram_bot() 호출 시 _stop_event 세팅
                while not _stop_event.is_set():
                    await asyncio.sleep(0.5)
                await _tg_app.updater.stop()
                await _tg_app.stop()

        asyncio.run(_poll())

    _tg_thread = threading.Thread(target=_run, daemon=True, name="telegram-bot")
    _tg_thread.start()
    logger.info("텔레그램 봇 스레드 시작됨")


def stop_telegram_bot() -> None:
    """텔레그램 봇 종료 (서버 종료 시 호출)."""
    _stop_event.set()
    logger.info("텔레그램 봇 종료 요청 전송")


def main():
    """단독 실행용 엔트리포인트"""
    if not TELEGRAM_TOKEN:
        print("=" * 50)
        print("[오류] config/.env 파일에 TELEGRAM_TOKEN이 없습니다.")
        print("BotFather를 통해 발급받은 토큰을 다음과 같이 추가해주세요:")
        print("TELEGRAM_TOKEN=123456789:ABCdefGHI...")
        print("=" * 50)
        sys.exit(1)

    print("=" * 50)
    print("  텔레그램 서버 시작")
    print("=" * 50)
    print("텔레그램 메시지 수신 대기 중... (종료: Ctrl+C)")
    _build_application().run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
