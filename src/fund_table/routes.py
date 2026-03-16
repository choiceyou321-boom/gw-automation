"""
자금관리표 API 라우터
- /api/fund/* : 프로젝트, 공종, 하도급, 연락처, GW 데이터 CRUD
- /fund       : 자금관리 웹 페이지 서빙
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from src.fund_table import db

logger = logging.getLogger("fund_routes")

# 정적 파일 경로 (src/chatbot/static/fund.html)
STATIC_DIR = Path(__file__).parent.parent / "chatbot" / "static"

router = APIRouter()


# ─────────────────────────────────────────
# 인증 유틸 (chatbot/app.py 와 동일한 JWT 쿠키 방식)
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


def require_auth(request: Request) -> dict:
    """인증 필수. 미인증이면 401 에러."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user


# ─────────────────────────────────────────
# Pydantic 요청 모델
# ─────────────────────────────────────────

class ProjectCreate(BaseModel):
    """프로젝트 생성 요청"""
    name: str
    description: Optional[str] = None
    design_amount: Optional[int] = None
    construction_amount: Optional[int] = None
    execution_budget: Optional[int] = None
    profit_amount: Optional[int] = None
    profit_rate: Optional[float] = None
    status: Optional[str] = None
    grade: Optional[str] = None


class ProjectUpdate(BaseModel):
    """프로젝트 수정 요청"""
    name: Optional[str] = None
    description: Optional[str] = None
    design_amount: Optional[int] = None
    construction_amount: Optional[int] = None
    execution_budget: Optional[int] = None
    profit_amount: Optional[int] = None
    profit_rate: Optional[float] = None
    status: Optional[str] = None
    grade: Optional[str] = None


class TradeCreate(BaseModel):
    """공종 생성 요청"""
    name: str
    sort_order: Optional[int] = 0


class TradeUpdate(BaseModel):
    """공종 수정 요청"""
    name: Optional[str] = None
    sort_order: Optional[int] = None


class SubcontractCreate(BaseModel):
    """하도급 업체 생성 요청"""
    company_name: str
    trade_id: Optional[int] = None
    account_category: Optional[str] = None
    has_estimate: Optional[int] = None
    has_contract: Optional[int] = None
    has_vendor_reg: Optional[int] = None
    estimate_amount: Optional[int] = None
    contract_amount: Optional[int] = None
    payment_1: Optional[int] = None
    payment_2: Optional[int] = None
    payment_3: Optional[int] = None
    payment_4: Optional[int] = None
    remaining_amount: Optional[int] = None
    payment_rate: Optional[float] = None
    payment_1_confirmed: Optional[int] = None
    payment_2_confirmed: Optional[int] = None
    payment_3_confirmed: Optional[int] = None
    payment_4_confirmed: Optional[int] = None
    sort_order: Optional[int] = None


class SubcontractUpdate(BaseModel):
    """하도급 업체 수정 요청"""
    company_name: Optional[str] = None
    trade_id: Optional[int] = None
    account_category: Optional[str] = None
    has_estimate: Optional[int] = None
    has_contract: Optional[int] = None
    has_vendor_reg: Optional[int] = None
    estimate_amount: Optional[int] = None
    contract_amount: Optional[int] = None
    payment_1: Optional[int] = None
    payment_2: Optional[int] = None
    payment_3: Optional[int] = None
    payment_4: Optional[int] = None
    remaining_amount: Optional[int] = None
    payment_rate: Optional[float] = None
    payment_1_confirmed: Optional[int] = None
    payment_2_confirmed: Optional[int] = None
    payment_3_confirmed: Optional[int] = None
    payment_4_confirmed: Optional[int] = None
    sort_order: Optional[int] = None


class ContactCreate(BaseModel):
    """연락처 생성 요청"""
    company_name: str
    trade_name: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class ContactUpdate(BaseModel):
    """연락처 수정 요청"""
    company_name: Optional[str] = None
    trade_name: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


# ─────────────────────────────────────────
# 프로젝트 CRUD 엔드포인트
# ─────────────────────────────────────────

@router.get("/api/fund/projects")
async def list_projects(request: Request):
    """전체 프로젝트 목록 조회"""
    require_auth(request)
    projects = db.list_projects()
    return JSONResponse({"projects": projects})


@router.post("/api/fund/projects")
async def create_project(req: ProjectCreate, request: Request):
    """프로젝트 생성"""
    require_auth(request)
    kwargs = req.model_dump(exclude={"name"}, exclude_none=True)
    result = db.create_project(name=req.name, **kwargs)
    if not result["success"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return JSONResponse(result, status_code=201)


@router.put("/api/fund/projects/reorder")
async def reorder_projects(request: Request):
    """프로젝트 순서 일괄 업데이트"""
    require_auth(request)
    body = await request.json()
    order = body.get("order", [])  # [{id: 1}, {id: 3}, ...]
    conn = db.get_db()
    try:
        for i, item in enumerate(order):
            conn.execute(
                "UPDATE projects SET sort_order = ? WHERE id = ?",
                (i, item["id"])
            )
        conn.commit()
        return JSONResponse({"success": True, "message": f"{len(order)}개 프로젝트 순서 저장"})
    finally:
        conn.close()


@router.get("/api/fund/projects/{project_id}")
async def get_project(project_id: int, request: Request):
    """프로젝트 상세 조회 (공종, 하도급 요약 포함)"""
    require_auth(request)
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")

    # 공종 목록
    trades = db.list_trades(project_id)
    # 하도급 요약 (업체 수, 계약총액)
    subcontracts = db.list_subcontracts(project_id)
    sub_summary = {
        "count": len(subcontracts),
        "total_contract": sum(s.get("contract_amount", 0) for s in subcontracts),
        "total_paid": sum(
            s.get("payment_1", 0) + s.get("payment_2", 0)
            + s.get("payment_3", 0) + s.get("payment_4", 0)
            for s in subcontracts
        ),
    }

    return JSONResponse({
        "project": project,
        "trades": trades,
        "subcontracts_summary": sub_summary,
    })


@router.put("/api/fund/projects/{project_id}")
async def update_project(project_id: int, req: ProjectUpdate, request: Request):
    """프로젝트 정보 수정"""
    require_auth(request)
    # 프로젝트 존재 확인
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")

    kwargs = req.model_dump(exclude_none=True)
    if not kwargs:
        raise HTTPException(status_code=400, detail="수정할 항목이 없습니다.")

    result = db.update_project(project_id, **kwargs)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(result)


@router.delete("/api/fund/projects/{project_id}")
async def delete_project(project_id: int, request: Request):
    """프로젝트 삭제 (하위 데이터 포함)"""
    require_auth(request)
    result = db.delete_project(project_id)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return JSONResponse(result)


# ─────────────────────────────────────────
# 공종 CRUD 엔드포인트
# ─────────────────────────────────────────

@router.get("/api/fund/projects/{project_id}/trades")
async def list_trades(project_id: int, request: Request):
    """프로젝트의 공종 목록 조회"""
    require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    trades = db.list_trades(project_id)
    return JSONResponse({"trades": trades})


@router.post("/api/fund/projects/{project_id}/trades")
async def add_trade(project_id: int, req: TradeCreate, request: Request):
    """공종 추가"""
    require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    result = db.add_trade(project_id, name=req.name, sort_order=req.sort_order or 0)
    if not result["success"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return JSONResponse(result, status_code=201)


@router.put("/api/fund/trades/{trade_id}")
async def update_trade(trade_id: int, req: TradeUpdate, request: Request):
    """공종 수정"""
    require_auth(request)
    kwargs = req.model_dump(exclude_none=True)
    if not kwargs:
        raise HTTPException(status_code=400, detail="수정할 항목이 없습니다.")
    result = db.update_trade(trade_id, **kwargs)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(result)


@router.delete("/api/fund/trades/{trade_id}")
async def delete_trade(trade_id: int, request: Request):
    """공종 삭제"""
    require_auth(request)
    result = db.delete_trade(trade_id)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return JSONResponse(result)


# ─────────────────────────────────────────
# 하도급 상세 CRUD 엔드포인트
# ─────────────────────────────────────────

@router.get("/api/fund/projects/{project_id}/subcontracts")
async def list_subcontracts(project_id: int, request: Request):
    """프로젝트의 하도급 목록 조회 (공종명 포함)"""
    require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    subcontracts = db.list_subcontracts(project_id)
    return JSONResponse({"subcontracts": subcontracts})


@router.post("/api/fund/projects/{project_id}/subcontracts")
async def add_subcontract(project_id: int, req: SubcontractCreate, request: Request):
    """하도급 업체 추가"""
    require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    kwargs = req.model_dump(exclude={"company_name"}, exclude_none=True)
    result = db.add_subcontract(project_id, company_name=req.company_name, **kwargs)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(result, status_code=201)


@router.put("/api/fund/subcontracts/{sub_id}")
async def update_subcontract(sub_id: int, req: SubcontractUpdate, request: Request):
    """하도급 업체 정보 수정"""
    require_auth(request)
    kwargs = req.model_dump(exclude_none=True)
    if not kwargs:
        raise HTTPException(status_code=400, detail="수정할 항목이 없습니다.")
    result = db.update_subcontract(sub_id, **kwargs)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(result)


@router.delete("/api/fund/subcontracts/{sub_id}")
async def delete_subcontract(sub_id: int, request: Request):
    """하도급 업체 삭제"""
    require_auth(request)
    result = db.delete_subcontract(sub_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(result)


# ─────────────────────────────────────────
# 연락처 CRUD 엔드포인트
# ─────────────────────────────────────────

@router.get("/api/fund/projects/{project_id}/contacts")
async def list_contacts(project_id: int, request: Request):
    """프로젝트의 연락처 목록 조회"""
    require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    contacts = db.list_contacts(project_id)
    return JSONResponse({"contacts": contacts})


@router.post("/api/fund/projects/{project_id}/contacts")
async def add_contact(project_id: int, req: ContactCreate, request: Request):
    """연락처 추가"""
    require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    kwargs = req.model_dump(exclude={"company_name"}, exclude_none=True)
    result = db.add_contact(project_id, company_name=req.company_name, **kwargs)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(result, status_code=201)


@router.put("/api/fund/contacts/{contact_id}")
async def update_contact(contact_id: int, req: ContactUpdate, request: Request):
    """연락처 수정"""
    require_auth(request)
    kwargs = req.model_dump(exclude_none=True)
    if not kwargs:
        raise HTTPException(status_code=400, detail="수정할 항목이 없습니다.")
    result = db.update_contact(contact_id, **kwargs)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(result)


@router.delete("/api/fund/contacts/{contact_id}")
async def delete_contact(contact_id: int, request: Request):
    """연락처 삭제"""
    require_auth(request)
    result = db.delete_contact(contact_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(result)


# ─────────────────────────────────────────
# 프로젝트 개요 엔드포인트
# ─────────────────────────────────────────

@router.get("/api/fund/projects/{project_id}/overview")
async def get_overview(project_id: int, request: Request):
    """프로젝트 개요 조회"""
    require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    overview = db.get_project_overview(project_id)
    return JSONResponse({"overview": overview})


@router.put("/api/fund/projects/{project_id}/overview")
async def save_overview(project_id: int, request: Request):
    """프로젝트 개요 저장"""
    require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    body = await request.json()
    result = db.save_project_overview(project_id, body)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(result)


# ─────────────────────────────────────────
# 수금현황 엔드포인트
# ─────────────────────────────────────────

@router.get("/api/fund/projects/{project_id}/collections")
async def list_collections(project_id: int, request: Request):
    """수금현황 조회"""
    require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    collections = db.list_collections(project_id)
    return JSONResponse({"collections": collections})


@router.put("/api/fund/projects/{project_id}/collections")
async def save_collections(project_id: int, request: Request):
    """수금현황 일괄 저장"""
    require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    body = await request.json()
    items = body.get("collections", [])
    result = db.save_collections_bulk(project_id, items)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(result)


# ─────────────────────────────────────────
# GW 데이터 조회 엔드포인트 (읽기 전용)
# ─────────────────────────────────────────

@router.get("/api/fund/projects/{project_id}/payments")
async def list_payments(project_id: int, request: Request, limit: int = 100):
    """이체완료 내역 조회"""
    require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    payments = db.list_payment_history(project_id=project_id, limit=limit)
    return JSONResponse({"payments": payments})


@router.get("/api/fund/projects/{project_id}/budget")
async def list_budget(project_id: int, request: Request, year: Optional[int] = None):
    """예실대비현황 조회"""
    require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    budget = db.list_budget_actual(project_id=project_id, year=year)
    return JSONResponse({"budget": budget})


@router.get("/api/fund/projects/{project_id}/summary")
async def get_fund_summary(project_id: int, request: Request):
    """프로젝트 자금현황 요약"""
    require_auth(request)
    summary = db.get_fund_summary(project_id)
    if "error" in summary:
        raise HTTPException(status_code=404, detail=summary["error"])
    return JSONResponse({"summary": summary})


# ─────────────────────────────────────────
# 자금관리 웹 페이지 서빙
# ─────────────────────────────────────────

@router.get("/fund")
async def serve_fund_page(request: Request):
    """자금관리표 웹 페이지 서빙"""
    require_auth(request)
    fund_html = STATIC_DIR / "fund.html"
    if not fund_html.exists():
        raise HTTPException(status_code=404, detail="fund.html을 찾을 수 없습니다.")
    return FileResponse(str(fund_html))
