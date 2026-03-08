"""
텔레그램 - 그룹웨어 업무 자동화 (텔레그램 채널)
- /start, /login, /register 명령어
- /clear - 대화 내역 지우기 (로그인 유지)
- /mailcheck - 안 읽은 메일 요약 수신 + Notion 저장
- 이미지/PDF 파일 첨부 지원
- 인메모리 대화 히스토리 (단순 유지)
"""

import os
import sys
import base64
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """봇 시작 시 인사"""
    welcome_text = (
        "안녕하세요! 그룹웨어 업무 자동화 봇입니다.\n\n"
        "사용하시려면 그룹웨어 계정 인증이 필요합니다.\n"
        "아직 가입하지 않으셨다면 회원가입을 먼저 진행해주세요:\n"
        "`/register [아이디] [비밀번호] [이름] [직급(선택)]`\n"
        "예시: `/register tgjeon mypass123 전태규 대리`\n\n"
        "이미 가입하셨다면 아래 명령어로 로그인해 주세요:\n"
        "`/login [아이디] [비밀번호]`\n"
        "예시: `/login tgjeon mypass123`\n\n"
        "기타 명령어:\n"
        "`/mail` (또는 `/mailcheck`) - 안 읽은 메일 AI 요약 + Notion 저장\n"
        "`/setline 검토:이름 승인:이름` - 결재선 설정\n"
        "`/myline` - 현재 결재선 확인\n"
        "`/clear` - 대화 내역 지우기 (로그인 유지)"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')


async def register_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """텔레그램에서 회원가입 처리"""
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "사용법: `/register [아이디] [비밀번호] [이름] [직급(선택)]`\n"
            "예시: `/register tgjeon 1234 홍길동 선임`",
            parse_mode='Markdown'
        )
        return

    gw_id, gw_pw, name = args[0], args[1], args[2]
    position = args[3] if len(args) > 3 else ""

    # 보안: 비밀번호 포함 메시지 삭제
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
            text=f"회원가입 성공!\n이제 `/login {gw_id} [비밀번호]`를 입력해 로그인해 주세요.",
            parse_mode='Markdown',
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"회원가입 실패: {result['message']}",
        )


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """텔레그램 채팅방에서 그룹웨어 계정 연동"""
    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "사용법: `/login [아이디] [비밀번호]`", parse_mode='Markdown'
        )
        return

    gw_id, gw_pw = args[0], args[1]

    # 보안: 비밀번호 포함 메시지 삭제
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=update.message.message_id,
        )
    except Exception as e:
        logger.warning(f"메시지 삭제 실패 (관리자 권한 필요): {e}")

    user = verify_login(gw_id, gw_pw)
    if user:
        tg_sessions[update.effective_user.id] = {
            "gw_id": user["gw_id"],
            "name": user["name"],
            "position": user.get("position", ""),
            "emp_seq": user.get("emp_seq", ""),
            "dept_seq": user.get("dept_seq", ""),
            "email_addr": user.get("email_addr", ""),
            "history": [],  # 인메모리 대화 히스토리
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
    session = _check_login(tg_user_id)

    if not session:
        await update.message.reply_text(
            "먼저 로그인을 해주세요.\n`/login [아이디] [비밀번호]`", parse_mode='Markdown'
        )
        return

    user_message = update.message.text

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action='typing'
    )

    try:
        result = await analyze_and_route(
            user_message=user_message,
            files=[],
            conversation_history=list(session["history"]),
            user_context=_get_user_context(session),
        )

        _append_history(session, "user", user_message)
        _append_history(session, "assistant", result["response"])

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
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()
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

        response_text = result["response"]
        if len(response_text) > 4000:
            response_text = response_text[:4000] + "\n\n(메시지가 길어 일부 생략되었습니다)"

        await update.message.reply_text(response_text)

    except Exception as e:
        logger.error(f"사진 처리 실패: {str(e)}", exc_info=True)
        await update.message.reply_text("사진 처리 중 오류가 발생했습니다.")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """문서(PDF 등) 첨부 메시지 처리"""
    tg_user_id = update.effective_user.id
    session = _check_login(tg_user_id)

    if not session:
        await update.message.reply_text(
            "먼저 로그인을 해주세요.\n`/login [아이디] [비밀번호]`", parse_mode='Markdown'
        )
        return

    doc = update.message.document
    mime = doc.mime_type or ""
    supported = ("image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf")

    if mime not in supported:
        await update.message.reply_text(
            "지원하지 않는 파일 형식입니다.\n지원: JPG, PNG, GIF, WebP, PDF"
        )
        return

    if doc.file_size and doc.file_size > 10 * 1024 * 1024:
        await update.message.reply_text("파일 크기가 10MB를 초과합니다.")
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action='typing'
    )

    try:
        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()
        encoded = base64.b64encode(bytes(file_bytes)).decode("utf-8")

        files = [{"name": doc.file_name or "file", "type": mime, "data": encoded}]
        user_message = update.message.caption or f"이 파일({doc.file_name})을 분석해주세요."

        result = await analyze_and_route(
            user_message=user_message,
            files=files,
            conversation_history=list(session["history"]),
            user_context=_get_user_context(session),
        )

        _append_history(session, "user", f"[파일: {doc.file_name}] {user_message}")
        _append_history(session, "assistant", result["response"])

        response_text = result["response"]
        if len(response_text) > 4000:
            response_text = response_text[:4000] + "\n\n(메시지가 길어 일부 생략되었습니다)"

        await update.message.reply_text(response_text)

    except Exception as e:
        logger.error(f"문서 처리 실패: {str(e)}", exc_info=True)
        await update.message.reply_text("파일 처리 중 오류가 발생했습니다.")


def main():
    """봇 실행"""
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

    # 메시지 핸들러
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    print("텔레그램 메시지 수신 대기 중... (종료: Ctrl+C)")
    app.run_polling()


if __name__ == "__main__":
    main()
