"""
챗봇 - 그룹웨어 업무 자동화 (웹 채널)
FastAPI 백엔드
- POST /auth/register : 회원가입
- POST /auth/login    : 로그인
- POST /auth/logout   : 로그아웃
- GET  /auth/me       : 현재 사용자 정보
- PUT  /auth/profile  : 프로필 업데이트
- POST /chat          : 채팅 메시지 처리 (텍스트 + 파일)
- POST /upload        : 파일 업로드
- GET  /              : 프론트엔드 서빙
"""

import os
import json
import base64
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Response, Cookie
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .agent import analyze_and_route
from .chat_db import save_message, get_session_history, list_sessions, delete_session, get_or_create_session, update_session_title

logger = logging.getLogger("chatbot_app")

# 프로젝트 루트 경로
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path(__file__).parent.parent.parent / "data" / "chatbot"
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="GW 자동화 챗봇 (웹)", version="2.0.0")

# CORS 설정 (allow_origins 환경변수로 설정, 기본값 localhost)
_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:51749").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 서빙
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ─────────────────────────────────────────
# Pydantic 모델
# ─────────────────────────────────────────

class RegisterRequest(BaseModel):
    gw_id: str
    gw_pw: str
    name: str
    position: str = ""


class LoginRequest(BaseModel):
    gw_id: str
    gw_pw: str


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    position: Optional[str] = None
    emp_seq: Optional[str] = None
    dept_seq: Optional[str] = None
    email_addr: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    files: Optional[list[dict]] = None  # [{name, type, data(base64)}]


class ChatResponse(BaseModel):
    response: str
    session_id: str
    action: Optional[str] = None
    action_result: Optional[str] = None
    timestamp: str


# ─────────────────────────────────────────
# 인증 유틸
# ─────────────────────────────────────────

def get_current_user(request: Request) -> dict | None:
    """JWT 쿠키에서 현재 사용자 정보 추출. 미인증이면 None."""
    from src.auth.jwt_utils import verify_token
    from src.auth.user_db import get_user

    token = request.cookies.get("auth_token")
    if not token:
        return None

    payload = verify_token(token)
    if not payload:
        return None

    user = get_user(payload["gw_id"])
    return user


# 관리자 GW ID (환경변수 필수, 미설정 시 관리자 기능 비활성화)
ADMIN_GW_ID = os.environ.get("ADMIN_GW_ID", "")


def require_auth(request: Request) -> dict:
    """인증 필수. 미인증이면 401 에러."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user


def require_admin(request: Request) -> dict:
    """관리자 인증 필수."""
    user = require_auth(request)
    if user["gw_id"] != ADMIN_GW_ID:
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return user


# ─────────────────────────────────────────
# 인증 엔드포인트
# ─────────────────────────────────────────

@app.post("/auth/register")
async def register(req: RegisterRequest):
    """회원가입"""
    from src.auth.user_db import register as db_register

    if not req.gw_id or not req.gw_pw or not req.name:
        raise HTTPException(status_code=400, detail="아이디, 비밀번호, 이름은 필수입니다.")

    result = db_register(
        gw_id=req.gw_id,
        gw_pw=req.gw_pw,
        name=req.name,
        position=req.position,
    )

    if not result["success"]:
        raise HTTPException(status_code=409, detail=result["message"])

    return JSONResponse({"message": result["message"]})


@app.post("/auth/login")
async def login(req: LoginRequest, response: Response):
    """로그인 → JWT 쿠키 발급"""
    from src.auth.user_db import verify_login
    from src.auth.jwt_utils import create_token

    user = verify_login(req.gw_id, req.gw_pw)
    if not user:
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")

    token = create_token(user["gw_id"], user["name"])

    resp = JSONResponse({
        "message": "로그인 성공",
        "user": {
            "gw_id": user["gw_id"],
            "name": user["name"],
            "position": user["position"],
            "emp_seq": user["emp_seq"],
        }
    })
    # httpOnly 쿠키로 JWT 설정 (same-origin, 24시간)
    is_https = os.environ.get("HTTPS", "false").lower() == "true"
    resp.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=24 * 60 * 60,
        path="/",
        secure=is_https,
    )
    return resp


@app.post("/auth/logout")
async def logout():
    """로그아웃 → 쿠키 삭제"""
    resp = JSONResponse({"message": "로그아웃되었습니다."})
    resp.delete_cookie("auth_token", path="/")
    return resp


@app.get("/auth/me")
async def get_me(request: Request):
    """현재 로그인 사용자 정보 (민감 필드 제외)"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    safe_user = {
        "gw_id": user["gw_id"],
        "name": user.get("name"),
        "position": user.get("position"),
        "emp_seq": user.get("emp_seq"),
        "dept_seq": user.get("dept_seq"),
        "is_admin": bool(ADMIN_GW_ID and user["gw_id"] == ADMIN_GW_ID),
    }
    return JSONResponse({"user": safe_user})


@app.put("/auth/profile")
async def update_profile(req: ProfileUpdateRequest, request: Request):
    """프로필 업데이트 (emp_seq, dept_seq 등)"""
    user = require_auth(request)

    from src.auth.user_db import update_profile as db_update

    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="업데이트할 항목이 없습니다.")

    result = db_update(user["gw_id"], **updates)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return JSONResponse({"message": result["message"]})


# ─────────────────────────────────────────
# 관리자 엔드포인트
# ─────────────────────────────────────────

@app.get("/admin/users")
async def admin_list_users(request: Request):
    """사용자 목록 (관리자 전용)"""
    require_admin(request)
    from src.auth.user_db import list_users
    users = list_users()
    for u in users:
        u["is_admin"] = bool(ADMIN_GW_ID and u.get("gw_id") == ADMIN_GW_ID)
    return JSONResponse({"users": users})


@app.delete("/admin/users/{gw_id}")
async def admin_delete_user(gw_id: str, request: Request):
    """사용자 삭제 (관리자 전용). 본인은 삭제 불가."""
    admin = require_admin(request)
    if gw_id == admin["gw_id"]:
        raise HTTPException(status_code=400, detail="본인 계정은 삭제할 수 없습니다.")

    from src.auth.user_db import delete_user
    result = delete_user(gw_id)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])

    # 삭제된 사용자의 GW 세션 캐시도 제거
    from src.auth.session_manager import invalidate_cache
    invalidate_cache(gw_id)

    return JSONResponse({"message": result["message"]})


@app.put("/admin/users/{gw_id}/profile")
async def admin_update_user_profile(gw_id: str, req: ProfileUpdateRequest, request: Request):
    """다른 사용자의 프로필 업데이트 (관리자 전용)"""
    require_admin(request)

    from src.auth.user_db import update_profile as db_update, get_user
    if not get_user(gw_id):
        raise HTTPException(status_code=404, detail="존재하지 않는 사용자입니다.")

    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="업데이트할 항목이 없습니다.")

    result = db_update(gw_id, **updates)
    return JSONResponse({"message": result["message"]})


@app.get("/admin")
async def serve_admin_page(request: Request):
    """관리자 페이지 서빙"""
    require_admin(request)
    admin_path = STATIC_DIR / "admin.html"
    if not admin_path.exists():
        raise HTTPException(status_code=404, detail="admin.html not found")
    return FileResponse(str(admin_path))


# ─────────────────────────────────────────
# 프론트엔드
# ─────────────────────────────────────────

@app.get("/")
async def serve_frontend():
    """프론트엔드 HTML 서빙"""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(str(index_path))


# ─────────────────────────────────────────
# 채팅 엔드포인트
# ─────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
async def chat(request_body: ChatRequest, request: Request):
    """
    채팅 메시지 처리
    - 로그인 사용자: user_context 전달 (사용자별 API 호출)
    - 비로그인: 401 반환
    """
    user = require_auth(request)

    # user_context 구성
    user_context = {
        "gw_id": user["gw_id"],
        "name": user["name"],
        "position": user.get("position", ""),
        "emp_seq": user.get("emp_seq", ""),
        "dept_seq": user.get("dept_seq", ""),
        "email_addr": user.get("email_addr", ""),
    }

    # 세션 ID: 사용자별로 분리
    gw_id = user["gw_id"]
    session_id = request_body.session_id or str(uuid.uuid4())
    files = request_body.files or []

    # 세션 자동 생성
    session_info = get_or_create_session(gw_id, session_id)

    # DB에서 히스토리 로드
    history_rows = get_session_history(gw_id, session_id, limit=40)
    history = [{"role": row["role"], "content": row["content"]} for row in history_rows]

    try:
        # Gemini 에이전트로 처리 (user_context 전달)
        result = await analyze_and_route(
            user_message=request_body.message,
            files=files,
            conversation_history=history,
            user_context=user_context,
        )

        # 메시지 DB 저장 (user + assistant)
        save_message(gw_id, session_id, "user", request_body.message, file_count=len(files))
        save_message(
            gw_id, session_id, "assistant", result["response"],
            action=result.get("action"),
            action_result=result.get("action_result"),
        )

        # 첫 메시지이면 세션 제목 자동 설정
        if not session_info.get("title"):
            # 첫 메시지의 앞 50자를 제목으로 사용
            title = request_body.message[:50].strip()
            if len(request_body.message) > 50:
                title += "..."
            update_session_title(gw_id, session_id, title)

        # 결과를 로컬 파일로 저장 (이중 백업) — 파일 데이터(base64)는 제외
        timestamp = datetime.now().isoformat()
        files_meta = [{"name": f.get("name"), "type": f.get("type"), "size": len(f.get("data", ""))} for f in files]
        save_chat_log(session_id, request_body.message, result, timestamp, files_meta, gw_id)

        return ChatResponse(
            response=result["response"],
            session_id=session_id,
            action=result.get("action"),
            action_result=result.get("action_result"),
            timestamp=timestamp
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"채팅 처리 오류: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"처리 오류: {str(e)}")


@app.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    """
    파일 업로드 처리
    - 이미지: base64 인코딩 후 반환
    - PDF: 저장 후 경로 반환
    """
    require_auth(request)  # 인증 필수
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일 이름이 없습니다.")

    # 파일 크기 제한 (10MB)
    MAX_SIZE = 10 * 1024 * 1024
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="파일 크기가 10MB를 초과합니다.")

    content_type = file.content_type or "application/octet-stream"
    allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf"]

    if content_type not in allowed_types:
        raise HTTPException(
            status_code=415,
            detail=f"지원하지 않는 파일 형식입니다. (지원: JPG, PNG, GIF, WebP, PDF)"
        )

    # base64 인코딩
    encoded = base64.b64encode(contents).decode("utf-8")

    # 업로드 파일 저장
    upload_dir = DATA_DIR / "uploads"
    upload_dir.mkdir(exist_ok=True)
    safe_name = Path(file.filename).name  # 디렉토리 구분자 제거 (경로 트래버설 방지)
    save_path = upload_dir / f"{uuid.uuid4()}_{safe_name}"
    save_path.write_bytes(contents)

    return JSONResponse({
        "name": file.filename,
        "type": content_type,
        "data": encoded,
        "size": len(contents),
        "saved_path": str(save_path)
    })


@app.get("/history/{session_id}")
async def get_history(session_id: str, request: Request):
    """세션의 대화 히스토리 반환"""
    user = require_auth(request)
    history = get_session_history(user["gw_id"], session_id)
    return JSONResponse({"session_id": session_id, "history": history})


@app.delete("/history/{session_id}")
async def clear_history(session_id: str, request: Request):
    """세션의 대화 히스토리 삭제"""
    user = require_auth(request)
    delete_session(user["gw_id"], session_id)
    return JSONResponse({"message": "대화 기록이 삭제되었습니다."})


@app.get("/sessions")
async def get_sessions(request: Request):
    """현재 사용자의 세션 목록 반환"""
    user = require_auth(request)
    sessions = list_sessions(user["gw_id"])
    return JSONResponse({"sessions": sessions})


def save_chat_log(
    session_id: str,
    user_message: str,
    result: dict,
    timestamp: str,
    files: list,
    gw_id: str = "",
):
    """대화 로그를 로컬 파일에 저장"""
    log_dir = DATA_DIR / "logs"
    log_dir.mkdir(exist_ok=True)

    # 날짜별 로그 파일
    date_str = timestamp[:10]
    log_file = log_dir / f"chat_{date_str}.jsonl"

    log_entry = {
        "timestamp": timestamp,
        "session_id": session_id,
        "gw_id": gw_id,
        "user_message": user_message,
        "response": result["response"],
        "action": result.get("action"),
        "action_result": result.get("action_result"),
        "file_count": len(files)
    }

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
