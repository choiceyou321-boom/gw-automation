"""
프로젝트 관리표 API 라우터
- /api/fund/* : 프로젝트, 공종, 하도급, 연락처, GW 데이터 CRUD
- /fund       : 프로젝트 관리 웹 페이지 서빙
"""

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# .env 로드 (ANTHROPIC_API_KEY 등)
load_dotenv(Path(__file__).parent.parent.parent / "config" / ".env")

from src.fund_table import db

logger = logging.getLogger("fund_routes")

# 정적 파일 경로 (src/chatbot/static/fund.html)
STATIC_DIR = Path(__file__).parent.parent / "chatbot" / "static"

router = APIRouter()


# 공용 인증 미들웨어 (중복 제거)
from src.auth.middleware import require_auth

# 관리자 GW ID (소유자 검증 우회용)
ADMIN_GW_ID = os.environ.get("ADMIN_GW_ID", "")


def _check_owner(project_id: int, user: dict):
    """프로젝트 소유자 검증. 관리자는 통과."""
    if ADMIN_GW_ID and user["gw_id"] == ADMIN_GW_ID:
        return
    if not db.check_project_owner(project_id, user["gw_id"]):
        raise HTTPException(status_code=403, detail="이 프로젝트의 소유자만 수정할 수 있습니다.")


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
    project_code: Optional[str] = None  # GW 사업코드 (예: GS-25-0088)


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
    project_code: Optional[str] = None  # GW 사업코드


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
    vendor_name: Optional[str] = None  # 프론트엔드 필드명
    company_name: Optional[str] = None  # 레거시 호환
    trade_name: Optional[str] = None
    trade_id: Optional[int] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    note: Optional[str] = None

    @property
    def resolved_company_name(self) -> str:
        return self.vendor_name or self.company_name or ""


class ContactUpdate(BaseModel):
    """연락처 수정 요청"""
    vendor_name: Optional[str] = None
    company_name: Optional[str] = None
    trade_name: Optional[str] = None
    trade_id: Optional[int] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    note: Optional[str] = None

    @property
    def resolved_company_name(self) -> Optional[str]:
        return self.vendor_name or self.company_name


class ReorderItem(BaseModel):
    """순서 변경 항목"""
    id: int

class ReorderRequest(BaseModel):
    """프로젝트 순서 일괄 변경"""
    order: list[ReorderItem]


class CollectionItem(BaseModel):
    """수금현황 항목"""
    id: Optional[int] = None
    category: Optional[str] = ""
    stage: Optional[str] = ""
    amount: Optional[int] = 0
    collected: Optional[int] = 0

class CollectionsBulkSave(BaseModel):
    """수금현황 일괄 저장"""
    collections: list[CollectionItem]


class MemberItem(BaseModel):
    role: str = ""
    name: str = ""

class MilestoneItem(BaseModel):
    id: Optional[int] = None
    name: str = ""
    completed: int = 0
    date: str = ""

class OverviewSave(BaseModel):
    """프로젝트 개요 저장"""
    project_category: Optional[str] = None
    location: Optional[str] = None
    usage: Optional[str] = None
    scale: Optional[str] = None
    area_pyeong: Optional[float] = None
    design_start: Optional[str] = None
    design_end: Optional[str] = None
    construction_start: Optional[str] = None
    construction_end: Optional[str] = None
    open_date: Optional[str] = None
    current_status: Optional[str] = None
    design_contract_date: Optional[str] = None
    design_contract_amount: Optional[int] = None
    construction_contract_date: Optional[str] = None
    construction_contract_amount: Optional[int] = None
    issue_design: Optional[str] = None
    issue_schedule: Optional[str] = None
    issue_budget: Optional[str] = None
    issue_operation: Optional[str] = None
    issue_defect: Optional[str] = None
    issue_other: Optional[str] = None
    members: Optional[list[MemberItem]] = None
    milestones: Optional[list[MilestoneItem]] = None


# ─────────────────────────────────────────
# 프로젝트 CRUD 엔드포인트
# ─────────────────────────────────────────

@router.get("/api/fund/projects")
async def list_projects(request: Request):
    """전체 프로젝트 목록 조회"""
    require_auth(request)
    projects = db.list_projects()
    return JSONResponse({"projects": projects})


@router.get("/api/fund/portfolio-summary")
async def get_portfolio_summary(request: Request):
    """포트폴리오 전체 요약 (프로젝트 비교 뷰용)"""
    require_auth(request)
    data = db.get_portfolio_summary()
    return JSONResponse({"projects": data})


@router.post("/api/fund/projects")
async def create_project(req: ProjectCreate, request: Request):
    """프로젝트 생성. project_code가 있으면 백그라운드에서 GW 크롤링 자동 실행."""
    import threading
    user = require_auth(request)
    kwargs = req.model_dump(exclude={"name"}, exclude_none=True)
    kwargs["owner_gw_id"] = user["gw_id"]
    result = db.create_project(name=req.name, **kwargs)
    if not result["success"]:
        logger.warning("프로젝트 생성 실패: %s", result["message"])
        raise HTTPException(status_code=409, detail=result["message"])

    # project_code가 있으면 백그라운드에서 GW 크롤링 자동 시작
    new_id = result.get("id")
    project_code = req.project_code
    if project_code and new_id:
        gw_id = user["gw_id"]
        def _auto_crawl():
            try:
                from src.fund_table.project_crawler import crawl_project_info
                crawl_project_info(gw_id, project_code, new_id)
                logger.info("자동 크롤링 완료 (project_info): project_id=%d, code=%s", new_id, project_code)
            except Exception as e:
                logger.warning("자동 크롤링 실패 (project_info): %s", e)
            # 사업별 크롤러 (메인 — 전기+당기)
            try:
                from src.fund_table.budget_crawler_by_project import crawl_budget_by_project
                crawl_budget_by_project(gw_id, new_id, project_code)
                logger.info("자동 크롤링 완료 (budget_by_project): project_id=%d, code=%s", new_id, project_code)
            except Exception as e:
                logger.warning("자동 크롤링 실패 (budget_by_project): %s", e)
            # 상세 합계 크롤러 (보충 — 수입/지출 합계)
            try:
                from src.fund_table.budget_crawler import crawl_budget_summary
                crawl_budget_summary(gw_id, new_id, project_code)
                logger.info("자동 크롤링 완료 (budget_summary): project_id=%d, code=%s", new_id, project_code)
            except Exception as e:
                logger.warning("자동 크롤링 실패 (budget_summary): %s", e)
        threading.Thread(target=_auto_crawl, daemon=True).start()
        result["crawling"] = True  # 프론트엔드에 크롤링 진행 중임을 알림

    return JSONResponse(result, status_code=201)


@router.put("/api/fund/projects/reorder")
async def reorder_projects(req: ReorderRequest, request: Request):
    """프로젝트 순서 일괄 업데이트"""
    require_auth(request)
    order = [{"id": item.id} for item in req.order]
    result = db.reorder_projects(order)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(result)


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
        "total_contract": sum((s.get("contract_amount") or 0) for s in subcontracts),
        "total_paid": sum(
            (s.get("payment_1") or 0) + (s.get("payment_2") or 0)
            + (s.get("payment_3") or 0) + (s.get("payment_4") or 0)
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
    user = require_auth(request)
    # 프로젝트 존재 확인
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")

    _check_owner(project_id, user)

    kwargs = req.model_dump(exclude_none=True)
    if not kwargs:
        raise HTTPException(status_code=400, detail="수정할 항목이 없습니다.")

    result = db.update_project(project_id, **kwargs)
    if not result["success"]:
        logger.warning("프로젝트 수정 실패 (id=%d): %s", project_id, result["message"])
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(result)


@router.delete("/api/fund/projects/{project_id}")
async def delete_project(project_id: int, request: Request):
    """프로젝트 삭제 (하위 데이터 포함)"""
    user = require_auth(request)
    _check_owner(project_id, user)
    result = db.delete_project(project_id)
    if not result["success"]:
        logger.warning("프로젝트 삭제 실패 (id=%d): %s", project_id, result["message"])
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
    user = require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    _check_owner(project_id, user)
    result = db.add_trade(project_id, name=req.name, sort_order=req.sort_order or 0)
    if not result["success"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return JSONResponse(result, status_code=201)


@router.put("/api/fund/projects/{project_id}/trades/{trade_id}")
async def update_trade(project_id: int, trade_id: int, req: TradeUpdate, request: Request):
    """공종 수정"""
    require_auth(request)
    kwargs = req.model_dump(exclude_none=True)
    if not kwargs:
        raise HTTPException(status_code=400, detail="수정할 항목이 없습니다.")
    result = db.update_trade(trade_id, **kwargs)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(result)


@router.delete("/api/fund/projects/{project_id}/trades/{trade_id}")
async def delete_trade(project_id: int, trade_id: int, request: Request):
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
    user = require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    _check_owner(project_id, user)
    kwargs = req.model_dump(exclude={"company_name"}, exclude_none=True)
    result = db.add_subcontract(project_id, company_name=req.company_name, **kwargs)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(result, status_code=201)


@router.put("/api/fund/projects/{project_id}/subcontracts")
async def save_subcontracts_bulk(project_id: int, request: Request):
    """하도급 일괄 저장 (프론트엔드 saveSubcontracts)"""
    user = require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    _check_owner(project_id, user)
    body = await request.json()
    rows = body.get("subcontracts", [])

    # 기존 하도급 목록 조회
    existing = {s["id"]: s for s in db.list_subcontracts(project_id)}
    incoming_ids = set()

    for i, row in enumerate(rows):
        row_id = row.get("id")
        row["sort_order"] = i
        # 불필요한 키 제거
        clean = {k: v for k, v in row.items() if k not in ("id",)}

        if row_id and row_id in existing:
            # 기존 항목 수정
            db.update_subcontract(row_id, **clean)
            incoming_ids.add(row_id)
        else:
            # 새 항목 추가
            company = clean.pop("company_name", "")
            result = db.add_subcontract(project_id, company_name=company or "미정", **clean)
            if result.get("id"):
                incoming_ids.add(result["id"])

    # 삭제된 항목 처리
    for eid in existing:
        if eid not in incoming_ids:
            db.delete_subcontract(eid)

    return JSONResponse({"success": True, "message": f"하도급 {len(rows)}건 저장 완료"})


@router.put("/api/fund/subcontracts/{sub_id}")
async def update_subcontract(sub_id: int, req: SubcontractUpdate, request: Request):
    """하도급 업체 정보 수정 (개별)"""
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
    user = require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    _check_owner(project_id, user)
    company = req.resolved_company_name
    if not company:
        raise HTTPException(status_code=400, detail="업체명을 입력하세요.")
    kwargs = req.model_dump(exclude={"company_name", "vendor_name"}, exclude_none=True)
    result = db.add_contact(project_id, company_name=company, **kwargs)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(result, status_code=201)


@router.put("/api/fund/projects/{project_id}/contacts/{contact_id}")
async def update_contact(project_id: int, contact_id: int, req: ContactUpdate, request: Request):
    """연락처 수정"""
    require_auth(request)
    # vendor_name → company_name으로 변환
    kwargs = req.model_dump(exclude={"vendor_name"}, exclude_none=True)
    resolved = req.resolved_company_name
    if resolved:
        kwargs["company_name"] = resolved
    if not kwargs:
        raise HTTPException(status_code=400, detail="수정할 항목이 없습니다.")
    result = db.update_contact(contact_id, **kwargs)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(result)


@router.delete("/api/fund/projects/{project_id}/contacts/{contact_id}")
async def delete_contact(project_id: int, contact_id: int, request: Request):
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
async def save_overview(project_id: int, req: OverviewSave, request: Request):
    """프로젝트 개요 저장"""
    user = require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    _check_owner(project_id, user)
    data = req.model_dump(exclude_none=True)
    # members/milestones는 dict 리스트로 변환
    if "members" in data:
        data["members"] = [m.model_dump() if hasattr(m, "model_dump") else m for m in req.members]
    if "milestones" in data:
        data["milestones"] = [m.model_dump() if hasattr(m, "model_dump") else m for m in req.milestones]
    result = db.save_project_overview(project_id, data)
    if not result["success"]:
        logger.error("개요 저장 실패 (project_id=%d): %s", project_id, result["message"])
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(result)


# ─────────────────────────────────────────
# GW 크롤링 엔드포인트
# ─────────────────────────────────────────

@router.post("/api/fund/projects/{project_id}/crawl-gw")
async def crawl_gw_project(project_id: int, request: Request):
    """
    GW에서 프로젝트 등록정보 + 예실대비 크롤링.
    순서: 프로젝트정보 → 사업별(메인) → 상세 합계(보충)
    각 단계 독립 try/except (한쪽 실패해도 계속)
    """
    import threading
    user = require_auth(request)
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    _check_owner(project_id, user)

    pcode = project.get("project_code")
    if not pcode:
        raise HTTPException(status_code=400, detail="프로젝트 코드가 설정되지 않았습니다. 개요 탭에서 GW 사업코드를 먼저 입력해주세요.")

    gw_id = user["gw_id"]
    results = {"project_info": None, "budget_by_project": None, "budget_summary": None}

    def _crawl():
        # 1단계: 프로젝트 등록정보
        try:
            from src.fund_table.project_crawler import crawl_project_info
            results["project_info"] = crawl_project_info(gw_id, pcode, project_id)
        except Exception as e:
            results["project_info"] = {"success": False, "error": f"프로젝트정보: {e}"}

        # 2단계: 예실대비현황(사업별) — 메인 크롤러 (전기+당기)
        try:
            from src.fund_table.budget_crawler_by_project import crawl_budget_by_project
            results["budget_by_project"] = crawl_budget_by_project(gw_id, project_id, pcode)
        except Exception as e:
            results["budget_by_project"] = {"success": False, "error": f"예실대비(사업별): {e}"}

        # 3단계: 예실대비현황(상세) — 합계 보충 (수입합계/지출합계/총잔액)
        try:
            from src.fund_table.budget_crawler import crawl_budget_summary
            results["budget_summary"] = crawl_budget_summary(gw_id, project_id, pcode)
        except Exception as e:
            results["budget_summary"] = {"success": False, "error": f"예실대비(합계): {e}"}

    # 동기 실행 (Playwright는 동기 API)
    thread = threading.Thread(target=_crawl)
    thread.start()
    thread.join(timeout=300)  # 최대 5분 (3개 크롤러 순차: 프로젝트정보 + 사업별 + 상세합계)

    if thread.is_alive():
        return JSONResponse({"success": False, "error": "크롤링 시간 초과 (5분)"}, status_code=504)

    # 항목별 성공/실패 집계
    label_map = {
        "project_info": "프로젝트정보",
        "budget_by_project": "예실대비(사업별)",
        "budget_summary": "예실대비(합계)",
    }
    detail_list = []
    synced = 0
    failed = 0
    for key, r in results.items():
        label = label_map.get(key, key)
        if r and r.get("success"):
            synced += 1
            msg = "완료"
            if key == "budget_by_project" and r.get("record_count"):
                msg = f"{r['record_count']}건 저장"
            elif key == "budget_summary" and r.get("summary"):
                s = r["summary"]
                msg = f"수입합계={s.get('income_total',0):,}, 지출합계={s.get('expense_total',0):,}"
            detail_list.append({"item": label, "status": "success", "message": msg})
        else:
            failed += 1
            detail_list.append({"item": label, "status": "fail", "message": r.get("error", "실패") if r else "실행되지 않음"})

    total = synced + failed
    success = synced > 0
    return JSONResponse({
        "success": success,
        "message": f"{total}개 중 {synced}개 동기화 완료" if success else "크롤링 실패",
        "synced": synced,
        "failed": failed,
        "total": total,
        "details": detail_list,
    })


@router.post("/api/fund/crawl-gw-all")
async def crawl_gw_all(request: Request):
    """
    등록된 모든 프로젝트의 GW 정보 일괄 크롤링.
    순서: 프로젝트정보 → 사업별(메인) → 상세합계(보충)
    각 단계 독립 try/except (한쪽 실패해도 계속)
    """
    import threading
    from src.fund_table.scheduler import sync_running

    # 스케줄러 또는 다른 수동 트리거가 이미 실행 중이면 거부
    if sync_running.is_set():
        return JSONResponse(
            {"success": False, "error": "동기화가 이미 진행 중입니다."},
            status_code=409,
        )

    user = require_auth(request)
    gw_id = user["gw_id"]

    result = {}

    def _crawl():
        errors = []
        stage_results = {}

        # 1단계: 프로젝트 등록정보 크롤링
        try:
            from src.fund_table.project_crawler import crawl_all_project_info
            proj_result = crawl_all_project_info(gw_id)
            stage_results["project_info"] = proj_result
            proj_success = 0
            if proj_result.get("success") and proj_result.get("results"):
                proj_success = sum(
                    1 for r in proj_result["results"] if r.get("status") == "success"
                )
            elif not proj_result.get("success"):
                errors.append(f"프로젝트정보: {proj_result.get('error', '실패')}")
        except Exception as e:
            proj_result = {"success": False, "error": str(e)}
            stage_results["project_info"] = proj_result
            proj_success = 0
            errors.append(f"프로젝트정보: {e}")

        # 2단계: 예실대비현황(사업별) 크롤링 — 메인 (전기+당기)
        try:
            from src.fund_table.budget_crawler_by_project import crawl_all_by_project
            byprj_result = crawl_all_by_project(gw_id)
            stage_results["budget_by_project"] = byprj_result
            byprj_success = 0
            if byprj_result.get("success") and byprj_result.get("results"):
                byprj_success = sum(
                    1 for r in byprj_result["results"] if r.get("status") == "success"
                )
            elif not byprj_result.get("success"):
                errors.append(f"예실대비(사업별): {byprj_result.get('error', '실패')}")
        except Exception as e:
            byprj_result = {"success": False, "error": str(e)}
            stage_results["budget_by_project"] = byprj_result
            byprj_success = 0
            errors.append(f"예실대비(사업별): {e}")

        # 3단계: 예실대비현황(상세) 합계 크롤링 — 보충 (수입합계/지출합계/총잔액)
        try:
            from src.fund_table.budget_crawler import crawl_all_summary
            summary_result = crawl_all_summary(gw_id)
            stage_results["budget_summary"] = summary_result
            summary_success = 0
            if summary_result.get("success") and summary_result.get("results"):
                summary_success = sum(
                    1 for r in summary_result["results"] if r.get("status") == "success"
                )
            elif not summary_result.get("success"):
                errors.append(f"예실대비(합계): {summary_result.get('error', '실패')}")
        except Exception as e:
            summary_result = {"success": False, "error": str(e)}
            stage_results["budget_summary"] = summary_result
            summary_success = 0
            errors.append(f"예실대비(합계): {e}")

        # 3개 크롤러 중 가장 많이 성공한 수 기준
        synced = max(proj_success, byprj_success, summary_success)
        overall_success = synced > 0

        # 대상 프로젝트 수
        total_targets = (
            len(proj_result.get("results", []))
            or len(byprj_result.get("results", []))
            or len(summary_result.get("results", []))
        )
        failed_count = total_targets - synced if total_targets > synced else 0

        # 프로젝트별 상세 결과 (사업별 결과 우선, 없으면 프로젝트정보 결과)
        detail_list = []
        all_results = (
            byprj_result.get("results", [])
            or proj_result.get("results", [])
            or summary_result.get("results", [])
        )
        for item in all_results:
            detail_list.append({
                "project_id": item.get("project_id"),
                "project_name": item.get("project_name", item.get("project_code", "")),
                "status": item.get("status", "unknown"),
                "message": item.get("message", item.get("error", "")),
            })

        # 단계별 요약
        stages = []
        stage_labels = {
            "project_info": "프로젝트정보",
            "budget_by_project": "예실대비(사업별)",
            "budget_summary": "예실대비(합계)",
        }
        stage_counts = {
            "project_info": proj_success,
            "budget_by_project": byprj_success,
            "budget_summary": summary_success,
        }
        for key, label in stage_labels.items():
            sr = stage_results.get(key, {})
            stages.append({
                "stage": label,
                "success": sr.get("success", False),
                "count": stage_counts.get(key, 0),
                "message": sr.get("message", sr.get("error", "")),
            })

        result["data"] = {
            "success": overall_success,
            "synced": synced,
            "failed": failed_count,
            "total": total_targets,
            "message": f"{total_targets}개 중 {synced}개 동기화 완료"
                       + (f" (오류: {'; '.join(errors)})" if errors and overall_success else ""),
            "error": "; ".join(errors) if not overall_success and errors else None,
            "details": detail_list,
            "stages": stages,
        }

    thread = threading.Thread(target=_crawl)
    thread.start()
    thread.join(timeout=900)  # 최대 15분 (3개 크롤러 순차 실행)

    if thread.is_alive():
        return JSONResponse({"success": False, "error": "크롤링 시간 초과 (15분)"}, status_code=504)

    return JSONResponse(result.get("data", {"success": False, "error": "알 수 없는 오류"}))


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
async def save_collections(project_id: int, req: CollectionsBulkSave, request: Request):
    """수금현황 일괄 저장"""
    user = require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    _check_owner(project_id, user)
    items = [item.model_dump() for item in req.collections]
    result = db.save_collections_bulk(project_id, items)
    if not result["success"]:
        logger.error("수금현황 저장 실패 (project_id=%d): %s", project_id, result["message"])
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(result)


# ─────────────────────────────────────────
# GW 프로젝트 검색 (사업코드 자동 조회)
# ─────────────────────────────────────────

@router.post("/api/fund/gw/search-projects")
async def search_gw_projects_api(request: Request):
    """GW 프로젝트 키워드 검색 (캐시 우선, 없으면 안내)"""
    user = require_auth(request)
    body = await request.json()
    keyword = body.get("search_name", "").strip()

    cache_info = db.get_gw_cache_info()
    if cache_info["count"] > 0:
        results = db.search_gw_projects_cache(keyword)
        return JSONResponse({
            "success": True,
            "projects": results,
            "total": len(results),
            "source": "cache",
            "cache_count": cache_info["count"],
            "cache_updated": cache_info["last_update"],
        })

    return JSONResponse({
        "success": False,
        "error": "GW 프로젝트 목록이 아직 없습니다.",
        "need_fetch": True,
    })


@router.post("/api/fund/gw/fetch-project-list")
async def fetch_gw_project_list(request: Request):
    """GW에서 전체 프로젝트 목록 크롤링 → 캐시 저장"""
    import threading
    import traceback
    user = require_auth(request)
    gw_id = user["gw_id"]
    result = {"data": None, "error": None}

    def _fetch():
        try:
            from src.fund_table.project_crawler import search_gw_projects as _search_fn
            result["data"] = _search_fn(gw_id, "")
        except Exception as e:
            logger.error(f"GW 프로젝트 목록 크롤링 스레드 오류: {e}\n{traceback.format_exc()}")
            result["error"] = str(e)

    thread = threading.Thread(target=_fetch)
    thread.start()
    thread.join(timeout=180)

    if thread.is_alive():
        return JSONResponse({"success": False, "error": "GW 접속 시간 초과 (3분)"}, status_code=504)

    if result["error"]:
        return JSONResponse({"success": False, "error": f"GW 크롤링 오류: {result['error']}"})

    data = result["data"]
    if not data or not data.get("success"):
        return JSONResponse({"success": False, "error": data.get("error", "GW 프로젝트 목록 가져오기 실패") if data else "알 수 없는 오류"})

    projects = data.get("projects", [])
    if projects:
        db.save_gw_projects_cache(projects)

    return JSONResponse({
        "success": True,
        "total": len(projects),
        "message": f"GW에서 {len(projects)}개 프로젝트를 가져왔습니다.",
    })


# ─────────────────────────────────────────
# PM 시트 임포트 엔드포인트
# ─────────────────────────────────────────

@router.post("/api/fund/import-pm-sheet")
async def import_pm_sheet(request: Request):
    """
    PM팀 Official 시트에서 전체 프로젝트 기본정보를 읽어 DB에 반영.
    mode: 'upsert' (기존 업데이트 + 신규 생성) 또는 'insert_only' (신규만)
    """
    import threading
    user = require_auth(request)
    gw_id = user["gw_id"]

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    spreadsheet_id = body.get("spreadsheet_id", None)
    mode = body.get("mode", "upsert")

    result = {"data": None, "error": None}

    def _import():
        try:
            from src.fund_table.sheets_import import import_from_pm_sheet
            result["data"] = import_from_pm_sheet(
                spreadsheet_id=spreadsheet_id,
                owner_gw_id=gw_id,
                mode=mode,
            )
        except Exception as e:
            logger.error("PM 시트 임포트 오류: %s", e, exc_info=True)
            result["error"] = str(e)

    thread = threading.Thread(target=_import)
    thread.start()
    thread.join(timeout=120)

    if thread.is_alive():
        return JSONResponse(
            {"success": False, "error": "Google Sheets 접속 시간 초과 (2분)"},
            status_code=504,
        )

    if result["error"]:
        return JSONResponse(
            {"success": False, "error": f"PM 시트 임포트 오류: {result['error']}"},
            status_code=500,
        )

    data = result["data"]
    if not data:
        return JSONResponse(
            {"success": False, "error": "알 수 없는 오류"},
            status_code=500,
        )

    return JSONResponse(data)


# ─────────────────────────────────────────
# GW 데이터 조회 엔드포인트 (읽기 전용)
# ─────────────────────────────────────────

@router.get("/api/fund/projects/{project_id}/payments")
async def list_payments(project_id: int, request: Request, limit: int = 100):
    """이체완료 내역 조회"""
    require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    # 보안: limit 상한 제한 (DoS 방지)
    limit = min(max(1, limit), 500)
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
# TODO CRUD
# ─────────────────────────────────────────

@router.get("/api/fund/todos")
async def list_all_todos(request: Request):
    """전체 TODO 조회"""
    require_auth(request)
    todos = db.list_todos()
    return JSONResponse({"todos": todos})


@router.get("/api/fund/projects/{project_id}/todos")
async def list_project_todos(project_id: int, request: Request):
    """프로젝트별 TODO 조회"""
    require_auth(request)
    todos = db.list_todos(project_id=project_id)
    return JSONResponse({"todos": todos})


class TodoCreate(BaseModel):
    content: str
    priority: str = "medium"
    category: str = ""
    project_id: Optional[int] = None


@router.post("/api/fund/todos")
async def create_todo(request: Request, body: TodoCreate):
    """TODO 생성"""
    require_auth(request)
    result = db.create_todo(
        project_id=body.project_id,
        content=body.content,
        priority=body.priority,
        category=body.category,
    )
    return JSONResponse(result)


class TodoUpdate(BaseModel):
    content: Optional[str] = None
    completed: Optional[int] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    project_id: Optional[int] = None


@router.put("/api/fund/todos/{todo_id}")
async def update_todo(todo_id: int, request: Request, body: TodoUpdate):
    """TODO 수정"""
    require_auth(request)
    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    result = db.update_todo(todo_id, **kwargs)
    return JSONResponse(result)


@router.delete("/api/fund/todos/{todo_id}")
async def delete_todo(todo_id: int, request: Request):
    """TODO 삭제"""
    require_auth(request)
    result = db.delete_todo(todo_id)
    return JSONResponse(result)


# ─────────────────────────────────────────
# AI 인사이트 생성
# ─────────────────────────────────────────

@router.get("/api/fund/insights")
async def get_insights(request: Request):
    """저장된 인사이트 조회"""
    require_auth(request)
    insights = db.get_insights()
    return JSONResponse({"insights": insights})


@router.get("/api/fund/portfolio-analysis")
async def get_portfolio_analysis(request: Request):
    """포트폴리오 분석 결과 조회 (캐시된 인사이트)"""
    require_auth(request)
    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM project_insights WHERE project_id IS NULL ORDER BY generated_at DESC"
        ).fetchall()
        insights = [dict(r) for r in rows]
        # 프로젝트별 인사이트도 가져와서 요약 카드 구성
        proj_rows = conn.execute(
            "SELECT i.*, p.name as project_name FROM project_insights i "
            "JOIN projects p ON i.project_id = p.id "
            "ORDER BY p.sort_order ASC, i.generated_at DESC"
        ).fetchall()
        project_insights = {}
        for r in proj_rows:
            pid = r["project_id"]
            if pid not in project_insights:
                project_insights[pid] = {"project_name": r["project_name"], "items": []}
            project_insights[pid]["items"].append({
                "type": r["insight_type"],
                "content": r["content"],
                "generated_at": r["generated_at"]
            })
        return JSONResponse({
            "portfolio": insights,
            "projects": project_insights
        })
    finally:
        conn.close()


@router.post("/api/fund/insights/generate")
async def generate_insights(request: Request):
    """Claude Opus로 전체 프로젝트 인사이트 생성"""
    require_auth(request)

    import asyncio
    projects = db.get_all_projects_full_data()
    if not projects:
        return JSONResponse({"success": False, "error": "프로젝트가 없습니다."})

    try:
        result = await asyncio.to_thread(_call_claude_for_insights, projects)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"인사이트 생성 실패: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


def _format_materials_for_prompt(materials: list[dict]) -> str:
    """자료 목록을 프롬프트용 텍스트로 변환"""
    if not materials:
        return ""
    lines = []
    for m in materials[:10]:  # 최대 10개
        if m.get("material_type") == "text" and m.get("content_text"):
            lines.append(f"\n  - [메모] {m.get('description', '')}: {m['content_text'][:200]}")
        elif m.get("material_type") == "file":
            lines.append(f"\n  - [파일] {m.get('file_name', m.get('description', ''))}")
    return "".join(lines)


def _build_insights_prompt(projects: list[dict]) -> tuple[str, list[dict]]:
    """프로젝트 데이터를 인사이트 프롬프트로 변환"""
    from datetime import date
    project_summaries = []
    for p in projects:
        ov = p.get("overview", {})
        milestones = p.get("milestones", [])
        subs = p.get("subcontracts", [])
        colls = p.get("collections", [])
        issues = p.get("issues", [])
        todos = p.get("todos", [])

        total_order = (p.get("design_amount", 0) or 0) + (p.get("construction_amount", 0) or 0)
        ms_total = len(milestones)
        ms_done = sum(1 for m in milestones if m.get("completed"))

        coll_total = sum(c.get("amount", 0) for c in colls)
        coll_done = sum(c.get("amount", 0) for c in colls if c.get("collected"))

        sub_total_contract = sum(s.get("contract_amount", 0) for s in subs)
        sub_total_paid = 0
        for s in subs:
            for n in range(1, 5):
                if s.get(f"payment_{n}_confirmed"):
                    sub_total_paid += s.get(f"payment_{n}", 0) or 0

        summary = f"""
## [프로젝트 ID: {p['id']}] {p['name']} (등급: {p.get('grade', '-')}, 상태: {p.get('status', '-')})
- 수주액: {total_order:,}원 | 실행예산: {(p.get('execution_budget', 0) or 0):,}원 | 이익율: {p.get('profit_rate', 0)}%
- 위치: {ov.get('location', '-')} | 용도: {ov.get('usage', '-')} | 면적: {ov.get('area_pyeong', '-')}평
- 설계기간: {ov.get('design_start', '-')} ~ {ov.get('design_end', '-')}
- 시공기간: {ov.get('construction_start', '-')} ~ {ov.get('construction_end', '-')}
- 진행률: {ms_done}/{ms_total} 단계 완료
- 수금현황: {coll_done:,}/{coll_total:,}원 ({(coll_done/coll_total*100 if coll_total else 0):.1f}%)
- 하도급: {len(subs)}개 업체, 계약 {sub_total_contract:,}원, 기지급 {sub_total_paid:,}원
- 배정인원: {', '.join(f"{m.get('role', '')}:{m.get('name', '')}" for m in p.get('members', []))}
- 이슈: {'; '.join(issues) if issues else '없음'}
- 기존 TODO: {len(todos)}건 ({sum(1 for t in todos if t.get('completed'))}건 완료)
- 사용자 제공 자료: {len(p.get('materials', []))}건{_format_materials_for_prompt(p.get('materials', []))}
"""
        project_summaries.append({"id": p["id"], "name": p["name"], "text": summary})

    all_text = "\n".join(s["text"] for s in project_summaries)

    prompt = f"""당신은 건설/인테리어 프로젝트 관리에 20년 경력의 전문 컨설턴트입니다.
글로우서울(음향/인테리어 시공 전문)의 프로젝트 현황을 분석해주세요.

## 분석 관점 — 사람들이 쉽게 놓치는 것 위주로
당신의 역할은 일반적인 요약이 아니라, **담당자가 바쁘게 일하면서 미처 챙기지 못하는 포인트**를 짚어주는 것입니다:

- 수금 일정과 하도급 지급 일정의 **타이밍 불일치** (돈이 나가는데 들어오는 건 늦는 구간)
- 이익률이 양호해 보여도 **실집행 기준으로 이미 초과**된 항목
- 진행률 대비 수금이 늦거나, 반대로 선수금을 받았는데 착공이 안 된 경우
- 하도급 계약은 했지만 **지급 확인이 안 된 건** (분쟁 소지)
- 여러 프로젝트가 동시에 자금이 필요한 **자금 병목 시점**
- 데이터가 비어있어서 **판단 자체가 불가능한 항목** (이것이 가장 위험)

## 현재 프로젝트 현황
{all_text}

## 요청사항
각 프로젝트별로 아래 JSON 형식으로 반환해주세요:

1. **현황 점검** (strategy): 현재 프로젝트 상태를 3~5줄로 요약. 잘 가고 있는 점과 우려되는 점을 균형있게. 숫자 근거를 반드시 포함.

2. **놓치기 쉬운 리스크** (risk): 담당자가 바쁘면 지나치기 쉬운 리스크 위주. 예시:
   - "수금 계약금 0원 미수령 상태에서 하도급 지급이 진행 중"
   - "시공 종료일이 다가오는데 수금 잔금 일정이 미확정"
   - "하도급 3차 지급 미확인 — 업체와 확인 필요"
   뻔한 리스크("예산 초과 주의")보다는 구체적 상황을 지적해주세요.

3. **자금 흐름 분석** (profitability): 이익률뿐 아니라 실제 현금 흐름 관점에서 분석.
   - 수금된 금액 vs 기지급 금액 → 순현금 포지션
   - 향후 수금 예정 vs 지급 예정 → 자금 여유/부족 예측
   - 하도급 비율이 수주액 대비 몇 %인지, 직영 마진은 적정한지

4. **지금 해야 할 일** (action): 즉시 실행 가능한 구체적 액션. "~를 검토하세요" 같은 애매한 표현 대신:
   - "A업체 3차 지급 50,000,000원 확인서 수령 필요"
   - "발주처에 2차 중도금 500,000,000원 수금 요청 발송"
   - "시공 종료일 확정 후 잔금 수금 일정 협의"
   처럼 금액, 대상, 행동을 명시해주세요.

5. **필요한 정보 & TODO** (missing_data_todos): 정확한 분석을 위해 시스템에 입력이 필요한 항목.
   값이 '-', 0, 빈칸인 필드를 찾아서 TODO로 작성. 형식: "할 일 (이유)"
   예시:
   - "시공 시작일/종료일 입력 (일정 지연 여부 판단 불가)"
   - "계약서 PDF를 자료실에 업로드 (계약 조건 검토 필요)"
   - "수금 계약금 금액 입력 (현금흐름 분석 누락)"
   - "하도급 잔여 지급 스케줄 등록 (자금 계획 수립에 필요)"

6. **전체 포트폴리오 인사이트** (portfolio):
   - 전체 프로젝트를 동시에 보았을 때 발견되는 패턴
   - 어떤 프로젝트에 자금/인력을 우선 집중해야 하는지
   - 자금 병목 시점 예측 (수금 일정 vs 지급 일정 겹침)
   - 회사 전체의 현금 포지션 (총 수금액 vs 총 기지급 vs 미지급)

오늘 날짜: {date.today().isoformat()}

**규칙**:
- project_id는 현황에 표시된 실제 프로젝트 ID를 그대로 사용. project_name도 정확히 일치.
- 한국어로 작성. 금액은 원 단위 + 천단위 콤마.
- 숫자 근거 없는 추상적 조언은 금지. 반드시 데이터에서 근거를 찾아 인용.
- missing_data_todos가 있으면 해당 인사이트 본문에도 "⚠ 일부 정보가 미입력 상태입니다. TODO 리스트를 확인해주세요." 포함.
- **간결하게 작성**: 각 항목(strategy/risk/profitability/action)은 2~4문장 이내. 데이터가 부족한 프로젝트는 1~2문장으로 축소.
- 데이터가 거의 없는 프로젝트(수주액 0, 하도급 0, 수금 0)는 missing_data_todos만 작성하고 나머지는 "데이터 부족으로 분석 불가"로 통일.

반환 형식 (JSON만 반환):
```json
{{
  "projects": [
    {{
      "project_id": 실제_프로젝트_ID,
      "project_name": "정확한 프로젝트명",
      "strategy": "현황 점검 내용...",
      "risk": "놓치기 쉬운 리스크...",
      "profitability": "자금 흐름 분석...",
      "action": "지금 해야 할 일...",
      "missing_data_todos": ["할 일 (이유)", "..."]
    }}
  ],
  "portfolio": "전체 포트폴리오 인사이트..."
}}
```"""
    return prompt, project_summaries


def _parse_and_save_insights(raw_text: str, project_summaries: list[dict] = None) -> dict:
    """AI 응답 텍스트를 파싱하고 DB에 저장
    project_summaries: [{"id": 실제DB_ID, "name": "프로젝트명"}, ...] — 이름→ID 매핑용
    """
    import json, re
    # JSON 블록 추출 (다양한 형식 대응)
    if "```json" in raw_text:
        raw_text = raw_text.split("```json")[1].split("```")[0].strip()
    elif "```" in raw_text:
        raw_text = raw_text.split("```")[1].split("```")[0].strip()

    # JSON 객체 경계 탐지 (앞뒤 불필요한 텍스트 제거)
    match = re.search(r'\{[\s\S]*\}', raw_text)
    if match:
        raw_text = match.group(0)

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.warning("인사이트 JSON 파싱 실패. raw_text 앞 500자: %s", raw_text[:500])
        db.save_insight(project_id=0, content=raw_text, insight_type="portfolio")
        return {"success": True, "raw": raw_text[:1000], "parsed": False}

    # 실제 DB ID 매핑 (이름 기반 + 순서 기반 fallback)
    name_to_id = {}
    idx_to_id = {}
    valid_ids = set()
    if project_summaries:
        for i, ps in enumerate(project_summaries):
            name_to_id[ps["name"]] = ps["id"]
            idx_to_id[i + 1] = ps["id"]  # Gemini가 1부터 순번 매기는 경우 대비
            valid_ids.add(ps["id"])

    # 프로젝트별 인사이트 저장
    for pi in data.get("projects", []):
        raw_pid = pi.get("project_id")
        pname = pi.get("project_name", "")
        # 1) 이름으로 매핑 시도
        pid = name_to_id.get(pname)
        # 2) 이름 부분 매칭
        if not pid and pname:
            for db_name, db_id in name_to_id.items():
                if pname in db_name or db_name in pname:
                    pid = db_id
                    break
        # 3) raw_pid가 실제 DB에 존재하면 사용
        if not pid and raw_pid in valid_ids:
            pid = raw_pid
        # 4) raw_pid를 순번으로 간주하여 매핑
        if not pid and raw_pid:
            pid = idx_to_id.get(raw_pid)
        if not pid:
            continue
        for itype in ["strategy", "risk", "profitability", "action"]:
            content = pi.get(itype, "")
            if content:
                db.save_insight(project_id=pid, content=content, insight_type=itype)

        # 누락 정보 TODO 자동 생성
        missing_todos = pi.get("missing_data_todos", [])
        if missing_todos and pid:
            for todo_text in missing_todos:
                if not todo_text or not isinstance(todo_text, str):
                    continue
                # 이미 동일한 TODO가 있는지 확인 (중복 방지)
                existing = db.list_todos(project_id=pid)
                already_exists = any(
                    todo_text.strip() in t.get("content", "") or t.get("content", "") in todo_text.strip()
                    for t in existing if not t.get("completed")
                )
                if not already_exists:
                    db.create_todo(
                        project_id=pid,
                        content=f"[AI 권고] {todo_text.strip()}",
                        priority="medium",
                        category="누락정보"
                    )

    # 포트폴리오 인사이트 저장 (project_id=0)
    portfolio = data.get("portfolio", "")
    if portfolio:
        db.save_insight(project_id=0, content=portfolio, insight_type="portfolio")

    return {"success": True, "data": data, "parsed": True}


def _call_claude_for_insights(projects: list[dict]) -> dict:
    """Gemini API로 인사이트 생성 (Anthropic API 대안)"""
    from google import genai

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다.")

    client = genai.Client(api_key=gemini_key)

    # 활성 프로젝트만 필터 (완료/취소 제외 — 응답 토큰 초과 방지)
    active_projects = [p for p in projects if p.get("status", "") not in ("완료", "취소", "중단")]
    if not active_projects:
        active_projects = projects[:10]  # fallback
    prompt, project_summaries = _build_insights_prompt(active_projects)

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "temperature": 0.7,
            "max_output_tokens": 65536,
        },
    )

    raw_text = response.text.strip()
    return _parse_and_save_insights(raw_text, project_summaries)


# ─────────────────────────────────────────
# 프로젝트 관리 웹 페이지 서빙
# ─────────────────────────────────────────

@router.get("/fund")
async def serve_fund_page(request: Request):
    """프로젝트 관리표 웹 페이지 서빙"""
    require_auth(request)
    fund_html = STATIC_DIR / "fund.html"
    if not fund_html.exists():
        raise HTTPException(status_code=404, detail="fund.html을 찾을 수 없습니다.")
    return FileResponse(str(fund_html))


@router.get("/insights")
async def serve_insights_page(request: Request):
    """인사이트 페이지 → fund 페이지로 리다이렉트"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/fund")


# ─────────────────────────────────────────
# 자료실 (Materials) 엔드포인트
# ─────────────────────────────────────────

@router.get("/api/fund/projects/{project_id}/materials")
async def list_materials(project_id: int, request: Request):
    """프로젝트 자료 목록"""
    require_auth(request)
    materials = db.list_materials(project_id)
    return JSONResponse({"materials": materials})


class MaterialCreate(BaseModel):
    material_type: str = "text"
    description: str = ""
    content_text: str = ""

@router.post("/api/fund/projects/{project_id}/materials")
async def add_material_text(project_id: int, request: Request, body: MaterialCreate):
    """텍스트/메모 자료 추가"""
    require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    result = db.add_material(
        project_id=project_id,
        material_type=body.material_type,
        description=body.description,
        content_text=body.content_text,
    )
    return JSONResponse(result)


@router.post("/api/fund/projects/{project_id}/materials/upload")
async def upload_material_file(project_id: int, request: Request):
    """파일 업로드 자료 추가"""
    require_auth(request)
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")

    form = await request.form()
    file = form.get("file")
    if not file:
        raise HTTPException(status_code=400, detail="파일이 없습니다.")

    # 저장 디렉토리
    materials_dir = Path(__file__).parent.parent.parent / "data" / "materials" / str(project_id)
    materials_dir.mkdir(parents=True, exist_ok=True)

    # 안전한 파일명
    import re
    safe_name = re.sub(r'[^\w\-_\. ]', '_', file.filename)
    file_path = materials_dir / safe_name
    content = await file.read()
    file_path.write_bytes(content)

    relative_path = f"data/materials/{project_id}/{safe_name}"
    description = form.get("description", file.filename)

    result = db.add_material(
        project_id=project_id,
        material_type="file",
        file_name=file.filename,
        file_path=relative_path,
        mime_type=file.content_type or "",
        description=description,
    )
    return JSONResponse(result)


@router.delete("/api/fund/materials/{material_id}")
async def delete_material(material_id: int, request: Request):
    """자료 삭제"""
    require_auth(request)
    result = db.delete_material(material_id)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return JSONResponse(result)


# ─────────────────────────────────────────
# 알림 엔드포인트
# ─────────────────────────────────────────

@router.get("/api/fund/notifications")
async def get_notifications(request: Request):
    """알림 목록"""
    require_auth(request)
    # 자동 알림 생성 체크
    db.check_and_generate_notifications()
    notifications = db.list_notifications()
    return JSONResponse({"notifications": notifications})


@router.post("/api/fund/notifications/read-all")
async def mark_all_read(request: Request):
    """모든 알림 읽음"""
    require_auth(request)
    result = db.mark_notifications_read()
    return JSONResponse(result)


# ─────────────────────────────────────────
# 프로젝트 별칭 (alias) 관리 API
# ─────────────────────────────────────────

@router.get("/api/fund/projects/{project_id}/aliases")
async def get_aliases(project_id: int, request: Request):
    """프로젝트 별칭 목록"""
    require_auth(request)
    aliases = db.get_project_aliases(project_id)
    return JSONResponse({"aliases": aliases})


@router.post("/api/fund/projects/{project_id}/aliases")
async def add_alias(project_id: int, request: Request):
    """프로젝트 별칭 추가"""
    require_auth(request)
    body = await request.json()
    alias = body.get("alias", "").strip()
    if not alias:
        return JSONResponse({"error": "별칭을 입력해주세요"}, status_code=400)
    result = db.add_project_alias(project_id, alias, alias_type="manual")
    return JSONResponse(result)


@router.delete("/api/fund/projects/{project_id}/aliases")
async def delete_alias(project_id: int, request: Request):
    """프로젝트 별칭 삭제"""
    require_auth(request)
    body = await request.json()
    alias = body.get("alias", "").strip()
    if not alias:
        return JSONResponse({"error": "삭제할 별칭을 지정해주세요"}, status_code=400)
    result = db.remove_project_alias(project_id, alias)
    return JSONResponse(result)


@router.get("/api/fund/aliases")
async def get_all_project_aliases(request: Request):
    """전체 프로젝트 별칭 목록"""
    require_auth(request)
    aliases = db.get_all_aliases()
    return JSONResponse({"aliases": aliases})
