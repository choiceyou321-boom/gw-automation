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
- GET  /fund          : 프로젝트 관리 웹 페이지
- /api/fund/*         : 프로젝트 관리 API
"""

import os
import json
import base64
import uuid
import secrets
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

# 업로드 파일 토큰 매핑 (서버 경로를 클라이언트에 노출하지 않기 위한 인메모리 저장소)
# {token: {"path": str, "gw_id": str, "created": datetime}}
_upload_tokens: dict[str, dict] = {}

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


@asynccontextmanager
async def lifespan(app):
    """FastAPI lifespan — 스케줄러 시작/종료 관리"""
    from src.fund_table.scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="GW 자동화 챗봇 (웹)", version="2.0.0", lifespan=lifespan)

# CORS 설정 (allow_origins 환경변수로 설정, 기본값 localhost)
_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:51749").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSRF 미들웨어 (Double-Submit Cookie 패턴)
from starlette.middleware.base import BaseHTTPMiddleware

class CSRFMiddleware(BaseHTTPMiddleware):
    """state-changing 요청에 X-CSRF-Token 헤더 검증"""
    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    EXEMPT_PATHS = {"/auth/login", "/auth/register", "/auth/logout"}

    async def dispatch(self, request: Request, call_next):
        if request.method not in self.SAFE_METHODS and request.url.path not in self.EXEMPT_PATHS:
            cookie_token = request.cookies.get("csrf_token")
            header_token = request.headers.get("x-csrf-token")
            if not cookie_token or not header_token or cookie_token != header_token:
                return JSONResponse(
                    {"detail": "CSRF 토큰이 유효하지 않습니다."},
                    status_code=403
                )
        return await call_next(request)

app.add_middleware(CSRFMiddleware)

# 정적 파일 서빙
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# 프로젝트 관리 라우터 등록
from src.fund_table.routes import router as fund_router
app.include_router(fund_router)

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
    attachment_token: Optional[str] = None  # 업로드 토큰 (파일 경로 대신)
    attachment_path: Optional[str] = None  # 하위 호환 (deprecated, 무시됨)


class ChatResponse(BaseModel):
    response: str
    session_id: str
    action: Optional[str] = None
    action_result: Optional[str] = None
    timestamp: str


# ─────────────────────────────────────────
# 인증 유틸 (공용 미들웨어 사용)
# ─────────────────────────────────────────
from src.auth.middleware import get_current_user, require_auth

# 관리자 GW ID (환경변수 필수, 미설정 시 관리자 기능 비활성화)
ADMIN_GW_ID = os.environ.get("ADMIN_GW_ID", "")


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
    # CSRF 토큰 쿠키 (JS 읽기 가능, httpOnly=False)
    csrf_token = secrets.token_hex(32)
    resp.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
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
    resp.delete_cookie("csrf_token", path="/")
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
    resp = JSONResponse({"user": safe_user})
    # CSRF 쿠키가 없으면 재설정 (이전 세션에서 로그인한 경우 대비)
    if not request.cookies.get("csrf_token"):
        is_https = os.environ.get("HTTPS", "false").lower() == "true"
        csrf_token = secrets.token_hex(32)
        resp.set_cookie(
            key="csrf_token",
            value=csrf_token,
            httponly=False,
            samesite="lax",
            max_age=24 * 60 * 60,
            path="/",
            secure=is_https,
        )
    return resp


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


@app.get("/admin/unsupported-requests")
async def admin_list_unsupported(request: Request):
    """미지원 요청 목록 (관리자 전용)"""
    require_admin(request)
    from src.chatbot.chat_db import list_unsupported_requests
    items = list_unsupported_requests()
    return JSONResponse({"items": items, "total": len(items)})


@app.delete("/admin/unsupported-requests/{request_id}")
async def admin_delete_unsupported(request_id: int, request: Request):
    """미지원 요청 단건 삭제 (관리자 전용)"""
    require_admin(request)
    from src.chatbot.chat_db import delete_unsupported_request
    ok = delete_unsupported_request(request_id)
    if not ok:
        raise HTTPException(status_code=404, detail="존재하지 않는 요청입니다.")
    return JSONResponse({"message": "삭제 완료"})


@app.get("/admin/ngrok-traffic")
async def admin_ngrok_traffic(request: Request):
    """ngrok 트래픽 현황 조회 (관리자 전용)"""
    require_admin(request)
    import httpx as _httpx
    ngrok_base = "http://localhost:4040"
    try:
        async with _httpx.AsyncClient(timeout=3.0) as client:
            tunnels_res = await client.get(f"{ngrok_base}/api/tunnels")
            requests_res = await client.get(f"{ngrok_base}/api/requests/http?limit=100")
        tunnels = tunnels_res.json().get("tunnels", [])
        reqs = requests_res.json().get("requests", [])

        # 요청 목록 정리
        req_list = []
        total_bytes = 0
        for r in reqs:
            resp = r.get("response", {})
            req_obj = r.get("request", {})
            status = resp.get("status_code", 0)
            resp_headers = resp.get("headers", {})
            content_len = 0
            for k, v in resp_headers.items():
                if k.lower() == "content-length":
                    try:
                        content_len = int(v[0]) if isinstance(v, list) else int(v)
                    except Exception:
                        pass
            total_bytes += content_len
            req_list.append({
                "id": r.get("id"),
                "start": r.get("start"),
                "method": req_obj.get("method", "-"),
                "uri": req_obj.get("uri", "-"),
                "status": status,
                "duration_ms": round(r.get("duration", 0) / 1_000_000, 1),
                "remote_addr": r.get("remote_addr", "-"),
                "bytes": content_len,
            })

        # 터널 요약
        tunnel_info = []
        for t in tunnels:
            m = t.get("metrics", {})
            tunnel_info.append({
                "name": t.get("name"),
                "public_url": t.get("public_url"),
                "proto": t.get("proto"),
                "addr": t.get("config", {}).get("addr"),
                "conn_count": m.get("conns", {}).get("count", 0),
                "http_count": m.get("http", {}).get("count", 0),
            })

        return JSONResponse({
            "tunnels": tunnel_info,
            "requests": req_list,
            "total_requests": len(req_list),
            "total_bytes": total_bytes,
        })
    except Exception as e:
        return JSONResponse({"error": str(e), "tunnels": [], "requests": [], "total_requests": 0, "total_bytes": 0})


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

    # 첨부파일 경로 — 토큰 기반 조회 (서버 경로 미노출)
    attachment_path = None
    if request_body.attachment_token:
        token_info = _upload_tokens.get(request_body.attachment_token)
        if token_info and token_info["gw_id"] == gw_id:
            candidate = Path(token_info["path"])
            if candidate.is_file():
                attachment_path = str(candidate)
            else:
                logger.warning("attachment_token의 파일이 존재하지 않음: %s", request_body.attachment_token)
        else:
            logger.warning("유효하지 않은 attachment_token: %s", request_body.attachment_token)

    try:
        # Gemini 에이전트로 처리 (user_context 전달)
        result = await analyze_and_route(
            user_message=request_body.message,
            files=files,
            conversation_history=history,
            user_context=user_context,
            attachment_path=attachment_path,
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

        # 결재 도구 실행 후 임시 첨부파일 삭제 (성공/실패 무관)
        if attachment_path and result.get("action") in ("submit_expense_approval", "submit_approval_form"):
            try:
                Path(attachment_path).unlink(missing_ok=True)
            except Exception:
                pass
            # 토큰 정리
            if request_body.attachment_token:
                _upload_tokens.pop(request_body.attachment_token, None)

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
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")


@app.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    """
    파일 업로드 처리
    - 이미지/PDF: base64 인코딩 후 반환 + data/tmp/ 에 저장 (GW 결재 첨부용)
    - XLSX/DOCX: data/tmp/ 에 저장 (GW 결재 첨부 전용, base64 미반환)
    반환값에 attachment_path 포함 — 이후 /chat 요청 시 전달하면 결재 첨부파일로 자동 업로드
    """
    user = require_auth(request)
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일 이름이 없습니다.")

    # 파일 크기 제한 (20MB)
    MAX_SIZE = 20 * 1024 * 1024
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="파일 크기가 20MB를 초과합니다.")

    content_type = file.content_type or "application/octet-stream"
    # Gemini 분석 가능 타입
    gemini_types = ["image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf"]
    # 음성 파일 타입 (Speech-to-Text 변환용)
    audio_types = [
        "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
        "audio/mp4", "audio/x-m4a", "audio/m4a",
        "audio/ogg", "audio/flac", "audio/x-flac", "audio/webm",
    ]
    # GW 첨부만 가능한 타입 (확장자 기준)
    safe_name = Path(file.filename).name
    ext = Path(safe_name).suffix.lower()
    attachment_only_exts = {".xlsx", ".docx"}
    audio_exts = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm", ".mp4"}

    if (content_type not in gemini_types
            and content_type not in audio_types
            and ext not in attachment_only_exts
            and ext not in audio_exts):
        raise HTTPException(
            status_code=415,
            detail="지원하지 않는 파일 형식입니다. (지원: JPG, PNG, GIF, WebP, PDF, XLSX, DOCX, MP3, WAV, M4A, OGG, FLAC)"
        )

    # data/tmp/ 에 저장 (GW 결재 첨부파일 경로로 반환)
    # data/tmp/ 에 단일 저장 (GW 결재 첨부 + Gemini 분석 공용)
    tmp_dir = Path(__file__).parent.parent.parent / "data" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{user['gw_id']}_{uuid.uuid4()}_{safe_name}"
    tmp_path.write_bytes(contents)
    # 토큰 기반 파일 참조 (서버 경로를 클라이언트에 노출하지 않음)
    file_token = secrets.token_urlsafe(32)
    _upload_tokens[file_token] = {
        "path": str(tmp_path),
        "gw_id": user["gw_id"],
        "created": datetime.now(),
    }

    response_data: dict = {
        "name": file.filename,
        "type": content_type,
        "size": len(contents),
        "attachment_token": file_token,  # /chat 요청 시 이 값을 attachment_token으로 전달
    }

    # Gemini 분석 가능 타입이면 base64도 반환
    if content_type in gemini_types:
        response_data["data"] = base64.b64encode(contents).decode("utf-8")

    # 음성 파일이면 STT 변환 결과 포함
    if content_type in audio_types or ext in audio_exts:
        response_data["is_audio"] = True
        response_data["audio_token"] = file_token  # 서버 내부 참조용 (토큰)

    return JSONResponse(response_data)


@app.get("/download/{filename}")
async def download_file(filename: str, request: Request):
    """
    생성된 파일 다운로드 (계약서 DOCX 등)
    data/tmp/ 하위 파일만 제공 (경로 트래버설 방지)
    """
    require_auth(request)
    # 파일 이름만 허용 (/ 포함 불가)
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail="잘못된 파일 이름입니다.")

    tmp_dir = Path(__file__).parent.parent.parent / "data" / "tmp"
    file_path = tmp_dir / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

    # 파일 확장자에 따라 content-type 설정
    ext = file_path.suffix.lower()
    media_types = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pdf": "application/pdf",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    return FileResponse(
        path=str(file_path),
        filename=safe_name,
        media_type=media_type,
    )


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
