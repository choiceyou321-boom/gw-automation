"""
자동화 도구 핸들러 함수들
"""

import os
import json
import logging
import threading
import concurrent.futures
from pathlib import Path
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# 동시 Playwright 세션 수 제한 (무제한 스레드 생성 방지)
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

# 사용자별 Lock — 동일 사용자의 동시 전자결재 요청 방지
_user_locks: dict[str, threading.Lock] = {}
_user_locks_guard = threading.Lock()


def _get_user_lock(gw_id: str) -> threading.Lock:
    """사용자별 Lock 반환 (없으면 생성)"""
    with _user_locks_guard:
        if gw_id not in _user_locks:
            _user_locks[gw_id] = threading.Lock()
        return _user_locks[gw_id]


@contextmanager
def _playwright_session(gw_id: str, encrypted_pw: str):
    """Playwright 세션 생성/정리 컨텍스트 매니저"""
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session

    pw = None
    browser = None
    try:
        pw = sync_playwright().start()
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=True,
            user_id=gw_id,
            user_pw=encrypted_pw,
        )
        yield browser, context, page
    finally:
        if browser:
            try:
                close_session(browser)
            except Exception:
                pass
        if pw:
            try:
                pw.stop()
            except Exception:
                pass

# 자동화 모듈 실행 함수들

def _get_api_for_user(user_context: dict = None):
    """
    사용자 컨텍스트에 따라 적절한 API 인스턴스 생성.
    user_context 있으면 session_manager 사용, 없으면 기존 방식.
    두 경로 모두 재인증을 위해 api._gw_id 주입 시도.
    """
    if user_context and user_context.get("gw_id"):
        from src.auth.session_manager import create_api
        return create_api(user_context["gw_id"])  # session_manager가 _gw_id 주입
    else:
        from src.meeting.reservation_api import create_api_with_session
        api, cleanup = create_api_with_session(headless=True)
        # fallback 경로에서도 재인증 가능하도록 gw_id 주입 시도
        gw_id = (user_context or {}).get("gw_id")
        if gw_id:
            api._gw_id = gw_id
        return api, cleanup


def handle_reserve_meeting_room(params: dict, user_context: dict = None) -> str:
    """
    회의실 예약 처리 - MeetingRoomAPI (reservation_api.py) 연동.
    기존 UI 자동화(reservation.py) 대신 rs121A API 직접 호출 방식 사용.
    """
    date       = params.get("date", "미정")
    start_time = params.get("start_time", "미정")
    end_time   = params.get("end_time", "미정")
    title      = params.get("title", "회의")
    room       = params.get("room_name", "1번 회의실")  # 미지정 시 1번 회의실 기본
    participants = params.get("participants", "")

    room_info = f"'{room}' 회의실" if room else "1번 회의실"
    part_info = f"\n- 참석자: {participants}" if participants else ""

    try:


        def _run_reservation():
            """별도 스레드에서 sync Playwright + MeetingRoomAPI 실행"""
            api, cleanup = _get_api_for_user(user_context)
            try:
                result = api.make_reservation(
                    room_name=room,
                    date=date,
                    start_time=start_time,
                    end_time=end_time,
                    title=title,
                    description=f"참석자: {participants}" if participants else "",
                )
                return result  # {"success": bool, "message": str, "data": dict}
            finally:
                cleanup()

        # async 루프 밖에서 sync Playwright 실행 (ThreadPoolExecutor 사용)
        future = _executor.submit(_run_reservation)
        result = future.result(timeout=120)

        if result.get("success"):
            return (
                f"회의실 예약이 완료되었습니다!\n\n"
                f"예약 내용:\n"
                f"- 제목: {title}\n"
                f"- 일시: {date} {start_time}~{end_time}\n"
                f"- 장소: {room_info}"
                f"{part_info}"
            )
        else:
            reason = result.get("message", "알 수 없는 오류")
            return (
                f"회의실 예약에 실패했습니다.\n"
                f"사유: {reason}\n\n"
                f"요청 내용:\n"
                f"- 제목: {title}\n"
                f"- 일시: {date} {start_time}~{end_time}\n"
                f"- 장소: {room_info}"
            )

    except Exception as e:
        return (
            f"회의실 예약 중 오류가 발생했습니다: {str(e)}\n\n"
            f"요청 내용:\n"
            f"- 제목: {title}\n"
            f"- 일시: {date} {start_time}~{end_time}\n"
            f"- 장소: {room_info}"
            f"{part_info}"
        )


def handle_check_reservation_status(params: dict, user_context: dict = None) -> str:
    """예약 현황 조회 - MeetingRoomAPI.get_reservations() 연동"""
    date = params.get("date", "")
    room_name = params.get("room_name", "")

    try:


        def _run_check():
            api, cleanup = _get_api_for_user(user_context)
            try:
                reservations = api.get_reservations(date)
                return reservations
            finally:
                cleanup()

        future = _executor.submit(_run_check)
        reservations = future.result(timeout=120)

        # 특정 회의실 필터링
        if room_name:
            reservations = [
                r for r in reservations
                if room_name in r.get("resName", "") or r.get("resName", "") in room_name
            ]

        if not reservations:
            room_info = f" ({room_name})" if room_name else ""
            return f"{date}{room_info} 예약이 없습니다. 모든 회의실이 비어 있습니다."

        lines = [f"📋 {date} 예약 현황 ({len(reservations)}건):\n"]
        for r in reservations:
            lines.append(
                f"• [{r.get('resName', '?')}] {r.get('start_time', '?')}~{r.get('end_time', '?')} "
                f"- {r.get('reqText', '(제목 없음)')} ({r.get('booker', '?')})"
            )
        return "\n".join(lines)

    except Exception as e:
        return f"예약 현황 조회 중 오류가 발생했습니다: {str(e)}"


def handle_check_available_rooms(params: dict, user_context: dict = None) -> str:
    """빈 회의실/시간대 조회 - MeetingRoomAPI.find_available_slots() 연동"""
    date = params.get("date", "")
    room_name = params.get("room_name", "")
    duration = int(params.get("duration_minutes", 60))

    try:


        def _run_check():
            api, cleanup = _get_api_for_user(user_context)
            try:
                slots = api.find_available_slots(
                    date=date,
                    room_name=room_name or None,
                    duration_minutes=duration,
                )
                return slots
            finally:
                cleanup()

        future = _executor.submit(_run_check)
        slots = future.result(timeout=120)

        if not slots:
            room_info = f" ({room_name})" if room_name else ""
            return f"{date}{room_info}에 {duration}분 이상 사용 가능한 시간대가 없습니다."

        # 회의실별로 그룹핑
        from collections import defaultdict
        by_room = defaultdict(list)
        for s in slots:
            by_room[s["resName"]].append(s)

        lines = [f"🕐 {date} 빈 시간대 ({duration}분 기준):\n"]
        for rname, rslots in by_room.items():
            time_strs = [f"{s['start_time']}~{s['end_time']}" for s in rslots]
            lines.append(f"• {rname}: {', '.join(time_strs)}")

        return "\n".join(lines)

    except Exception as e:
        return f"빈 회의실 조회 중 오류가 발생했습니다: {str(e)}"


def handle_cancel_meeting_reservation(params: dict, user_context: dict = None) -> str:
    """
    예약 취소 - MeetingRoomAPI.cancel_reservation() 연동.
    예약한 본인만 취소 가능 (GW 서버 권한 체크 + 클라이언트 필터링).
    """
    date = params.get("date", "")
    title = params.get("title", "")
    room_name = params.get("room_name", "")
    start_time = params.get("start_time", "")

    # 현재 사용자 정보 (로그인된 사용자)
    current_name = (user_context or {}).get("name", "")
    current_gw_id = (user_context or {}).get("gw_id", "")

    try:


        def _run_cancel():
            api, cleanup = _get_api_for_user(user_context)
            try:
                # 1단계: 해당 날짜 예약 조회
                reservations = api.get_reservations(date)

                # 본인 예약만 필터 (로그인 사용자 기준)
                booker_names = {current_name, current_gw_id} - {""}
                if not booker_names:
                    booker_names = None

                if booker_names:
                    my_reservations = [
                        r for r in reservations
                        if r.get("booker", "") in booker_names
                    ]
                else:
                    my_reservations = reservations

                if not my_reservations:
                    return {"success": False, "message": f"{date}에 본인 예약이 없습니다."}

                # 2단계: 조건으로 필터링
                candidates = my_reservations
                if title:
                    filtered = [r for r in candidates if title in r.get("reqText", "")]
                    if filtered:
                        candidates = filtered
                if room_name:
                    filtered = [r for r in candidates if room_name in r.get("resName", "") or r.get("resName", "") in room_name]
                    if filtered:
                        candidates = filtered
                if start_time:
                    clean_time = start_time.replace(":", "")
                    filtered = [r for r in candidates if clean_time in r.get("start_time", "").replace(":", "")]
                    if filtered:
                        candidates = filtered

                if len(candidates) == 0:
                    return {"success": False, "message": f"{date}에 조건에 맞는 예약을 찾을 수 없습니다."}

                if len(candidates) > 1:
                    lines = [f"{date}에 조건에 맞는 예약이 {len(candidates)}건 있습니다:\n"]
                    for i, r in enumerate(candidates, 1):
                        lines.append(
                            f"{i}. [{r.get('resName', '?')}] {r.get('start_time', '?')}~{r.get('end_time', '?')} "
                            f"- {r.get('reqText', '(제목 없음)')}"
                        )
                    lines.append("\n더 구체적으로 알려주시면 취소해드리겠습니다. (예: 제목, 회의실, 시간)")
                    return {"success": False, "message": "\n".join(lines)}

                # 3단계: 취소 실행
                target = candidates[0]
                raw = target.get("raw", {})
                result = api.cancel_reservation(
                    schm_seq=target.get("schmSeq", ""),
                    seq_num=target.get("seqNum", ""),
                    res_seq=target.get("resSeq", ""),
                    res_idx=str(raw.get("resIdx", "1")),
                    req_text=target.get("reqText", ""),
                    start_date=target.get("startDate", ""),
                    end_date=target.get("endDate", ""),
                    create_date=str(raw.get("createDate", "")),
                    res_name=target.get("resName", ""),
                )
                if result.get("success"):
                    return {
                        "success": True,
                        "message": (
                            f"예약이 취소되었습니다.\n\n"
                            f"취소된 예약:\n"
                            f"- 제목: {target.get('reqText', '?')}\n"
                            f"- 일시: {date} {target.get('start_time', '?')}~{target.get('end_time', '?')}\n"
                            f"- 장소: {target.get('resName', '?')}"
                        )
                    }
                else:
                    return {"success": False, "message": result.get("message", "취소 실패")}
            finally:
                cleanup()

        future = _executor.submit(_run_cancel)
        result = future.result(timeout=120)

        return result.get("message", "처리 완료")

    except Exception as e:
        return f"예약 취소 중 오류가 발생했습니다: {str(e)}"


def handle_list_my_reservations(params: dict, user_context: dict = None) -> str:
    """
    향후 N일간 본인 예약 목록 조회.
    empSeq 기준으로 본인 예약만 필터링하여 번호 매긴 목록 반환.
    """
    import datetime as _dt
    days = int(params.get("days", 14))
    days = min(days, 30)  # 최대 30일

    gw_id = (user_context or {}).get("gw_id", "")

    try:
        # 본인 empSeq 조회 (company_info에서)
        my_emp_seq = ""
        if gw_id:
            from src.auth.user_db import get_company_info as _get_company_info
            company_info = _get_company_info(gw_id)
            my_emp_seq = str(company_info.get("empSeq", ""))

        def _run_list():
            api, cleanup = _get_api_for_user(user_context)
            try:
                today = _dt.date.today()
                my_reservations = []
                for d in range(days):
                    target_date = (today + _dt.timedelta(days=d)).strftime("%Y-%m-%d")
                    try:
                        reservations = api.get_reservations(target_date)
                    except Exception as e:
                        logger.warning(f"예약 목록 조회 중 {target_date} 오류 (건너뜀): {e}")
                        continue

                    for res in reservations:
                        # empSeq 기준 본인 필터 (empSeq가 없으면 booker 이름으로 fallback)
                        res_emp_seq = str(res.get("empSeq", ""))
                        if my_emp_seq:
                            if res_emp_seq and res_emp_seq != my_emp_seq:
                                continue  # 타인 예약 건너뜀
                        my_reservations.append(res)

                return my_reservations
            finally:
                cleanup()

        future = _executor.submit(_run_list)
        my_reservations = future.result(timeout=120)

        if not my_reservations:
            return f"향후 {days}일간 본인 예약이 없습니다."

        lines = [f"내 회의실 예약 목록 (향후 {days}일, 총 {len(my_reservations)}건):\n"]
        for i, res in enumerate(my_reservations, 1):
            date_str = res.get("date", "")
            lines.append(
                f"{i}. {res.get('resName', '?')} "
                f"{date_str} {res.get('start_time', '?')}~{res.get('end_time', '?')}"
                f" ({res.get('reqText', '(제목 없음)')})"
            )
        lines.append("\n취소할 예약 번호를 알려주시면 취소해드리겠습니다.")
        return "\n".join(lines)

    except Exception as e:
        return f"예약 목록 조회 중 오류가 발생했습니다: {str(e)}"


def handle_cleanup_test_reservations(params: dict, user_context: dict = None) -> str:
    """
    [TEST_ 또는 [TEST] 접두사 테스트 예약 일괄 취소.
    scripts/full_test.py의 _cleanup_stale_test_reservations와 동일한 로직.
    본인(empSeq 일치) 예약만 취소.
    """
    import datetime as _dt
    days = int(params.get("days", 14))
    days = min(days, 30)

    gw_id = (user_context or {}).get("gw_id", "")

    try:
        # 본인 empSeq 조회
        my_emp_seq = ""
        if gw_id:
            from src.auth.user_db import get_company_info as _get_company_info
            company_info = _get_company_info(gw_id)
            my_emp_seq = str(company_info.get("empSeq", ""))

        if not my_emp_seq:
            logger.warning("cleanup_test_reservations: empSeq 미확인 — 본인 필터 없이 진행")

        def _run_cleanup():
            api, cleanup = _get_api_for_user(user_context)
            try:
                today = _dt.date.today()
                cancelled_count = 0
                skipped_others = 0
                failed_count = 0
                cancelled_details = []

                for d in range(days):
                    target_date = (today + _dt.timedelta(days=d)).strftime("%Y-%m-%d")
                    try:
                        reservations = api.get_reservations(target_date)
                    except Exception as e:
                        logger.warning(f"테스트 예약 정리: {target_date} 조회 실패 (건너뜀) — {e}")
                        continue

                    for res in reservations:
                        req_text = res.get("reqText", "")
                        # [TEST_xxx] 또는 [TEST] xxx 형식 모두 처리
                        if not (req_text.startswith("[TEST_") or req_text.startswith("[TEST]")):
                            continue

                        # 본인 예약 여부 확인
                        res_emp_seq = str(res.get("empSeq", ""))
                        if my_emp_seq and res_emp_seq and res_emp_seq != my_emp_seq:
                            logger.debug(
                                f"테스트 예약 정리: 다른 사용자 예약 건너뜀 "
                                f"(reqText={req_text!r}, empSeq={res_emp_seq})"
                            )
                            skipped_others += 1
                            continue

                        seq_num = res.get("seqNum", "")
                        if not seq_num:
                            logger.warning(
                                f"테스트 예약 정리: seqNum 없는 예약 건너뜀 "
                                f"(reqText={req_text!r}, date={target_date})"
                            )
                            continue

                        schm_seq = res.get("schmSeq", "")
                        res_seq = res.get("resSeq", "")
                        raw = res.get("raw", {})

                        try:
                            cancel_result = api.cancel_reservation(
                                schm_seq=schm_seq,
                                seq_num=seq_num,
                                res_seq=res_seq,
                                res_idx=str(raw.get("resIdx", "1")),
                                req_text=req_text,
                                start_date=res.get("startDate", ""),
                                end_date=res.get("endDate", ""),
                                create_date=str(raw.get("createDate", "")),
                                res_name=res.get("resName", ""),
                            )
                            if cancel_result.get("success"):
                                logger.info(
                                    f"테스트 예약 정리: 취소 성공 — {req_text!r} "
                                    f"({res.get('resName', '')} {target_date})"
                                )
                                cancelled_count += 1
                                cancelled_details.append(
                                    f"- {res.get('resName', '?')} {target_date} "
                                    f"{res.get('start_time', '?')}~{res.get('end_time', '?')} "
                                    f"({req_text})"
                                )
                            else:
                                logger.warning(
                                    f"테스트 예약 정리: 취소 실패 — {req_text!r} "
                                    f"({cancel_result.get('message', '')})"
                                )
                                failed_count += 1
                        except Exception as e:
                            logger.warning(f"테스트 예약 정리: 취소 중 오류 — {req_text!r}: {e}")
                            failed_count += 1

                return {
                    "cancelled_count": cancelled_count,
                    "skipped_others": skipped_others,
                    "failed_count": failed_count,
                    "cancelled_details": cancelled_details,
                }
            finally:
                cleanup()

        future = _executor.submit(_run_cleanup)
        result = future.result(timeout=120)

        cancelled_count = result["cancelled_count"]
        skipped_others = result["skipped_others"]
        failed_count = result["failed_count"]
        cancelled_details = result["cancelled_details"]

        if cancelled_count == 0 and failed_count == 0:
            msg = f"향후 {days}일 내 본인의 테스트([TEST_/[TEST]) 예약이 없습니다."
            if skipped_others:
                msg += f" (타 사용자 테스트 예약 {skipped_others}건은 건너뜀)"
            return msg

        lines = [f"테스트 예약 정리 완료 (향후 {days}일 스캔):\n"]
        lines.append(f"- 취소 성공: {cancelled_count}건")
        if failed_count:
            lines.append(f"- 취소 실패: {failed_count}건")
        if skipped_others:
            lines.append(f"- 타 사용자 예약 건너뜀: {skipped_others}건")
        if cancelled_details:
            lines.append("\n취소된 예약:")
            lines.extend(cancelled_details)
        return "\n".join(lines)

    except Exception as e:
        return f"테스트 예약 정리 중 오류가 발생했습니다: {str(e)}"


def handle_submit_expense_approval(params: dict, user_context: dict = None) -> str:
    """
    지출결의서 작성 처리
    - action='confirm': 확인 메시지 반환 (사용자가 '확인' 후 실행)
    - action='draft': Playwright로 실제 폼 작성 + 임시저장
    """
    title = params.get("title", "")
    description = params.get("description", "")
    amount = params.get("amount")
    date = params.get("date", "")
    project = params.get("project", "")
    items = params.get("items", [])
    payee = params.get("payee", "")
    approval_line = params.get("approval_line")
    cc = params.get("cc")
    evidence_type = params.get("evidence_type", "")
    invoice_vendor = params.get("invoice_vendor", "")
    invoice_amount = params.get("invoice_amount")
    invoice_date = params.get("invoice_date", "")
    auto_capture_budget = params.get("auto_capture_budget", False)
    usage_code = params.get("usage_code", "5020")
    budget_keyword = params.get("budget_keyword", "")
    payment_request_date = params.get("payment_request_date", "")
    accounting_date = params.get("accounting_date", "")
    attachment_path = params.get("attachment_path", "")
    action = params.get("action", "confirm")

    # 항목 정보 포맷
    amount_str = f"{int(amount):,}원" if amount else "미정"
    items_str = ""
    if items:
        for i, item in enumerate(items, 1):
            item_amount = f"{int(item.get('amount', 0)):,}원" if item.get('amount') else ""
            items_str += f"\n  {i}. {item.get('item', '?')} {item_amount}"

    if action not in ("draft", "submit"):
        # 대화형 질문 플로우: 필수 정보가 빠진 경우 먼저 질문
        missing_q = []
        if not title:
            missing_q.append("title")
        has_content = bool(description) or bool(items)
        if not has_content:
            missing_q.append("content")
        has_amount = bool(amount) or any(item.get("amount") for item in items)
        if not has_amount:
            missing_q.append("amount")

        if missing_q:
            # 이미 파악된 정보 정리
            known_parts = []
            if title:
                known_parts.append(f"제목: {title}")
            if project:
                known_parts.append(f"프로젝트: {project}")
            if has_amount:
                known_parts.append(f"금액: {amount_str}")
            if has_content:
                content_summary = description if description else (items[0].get('item', '') if items else '')
                known_parts.append(f"내용: {content_summary}")
            if payee:
                known_parts.append(f"지급처: {payee}")

            known_str = ""
            if known_parts:
                known_str = "지금까지 파악된 내용:\n" + "\n".join(f"  - {k}" for k in known_parts) + "\n\n"

            # 빠진 정보 중 첫 번째만 질문 (한 번에 하나씩)
            first_missing = missing_q[0]
            if first_missing == "title":
                # 프로젝트가 확정된 경우 제목 자동 제안
                if project:
                    # "GS-25-0088. [종로] 메디빌더 음향공사" 형식에서 제목 후보 생성
                    # project 문자열에서 코드 부분(GS-XX-XXXX.) 추출
                    import re as _re
                    # "GS-25-0088. [종로] 메디빌더 음향공사" → code="GS-25-0088", proj_name="[종로] 메디빌더 음향공사"
                    code_match = _re.match(r'^([A-Z]{2}-\d{2}-\d{4})\.\s*(.*)', project)
                    if code_match:
                        code_prefix = code_match.group(1) + ". "
                        proj_name = code_match.group(2).strip()   # "[종로] 메디빌더 음향공사" 형태 그대로 유지
                    else:
                        code_prefix = ""
                        proj_name = project.strip()
                    # 내용/용도 기반 제목 제안 (사용자가 언급한 키워드 활용)
                    content_hint = description or (items[0].get('item', '') if items else '')
                    if content_hint:
                        suggested_title = f"{code_prefix}{proj_name} {content_hint} 대금 지급의 건"
                    else:
                        suggested_title = f"{code_prefix}{proj_name} 대금 지급의 건"
                    question = (
                        f"결재 문서 제목을 이렇게 하면 어떨까요?\n\n"
                        f"  \"{suggested_title}\"\n\n"
                        f"이대로 괜찮으시면 '확인', 수정하실 내용이 있으면 원하는 제목을 알려주세요."
                    )
                else:
                    question = "결재 문서 제목을 알려주세요. (예: 'GS-25-0088. [종로] 메디빌더 음향공사 대금 지급의 건')"
            elif first_missing == "content":
                question = "어떤 용도의 지출인지 알려주세요. (예: 음향설비 설치 공사비, 야근 식대 등)"
            else:  # amount
                question = "금액이 얼마인가요? (예: 2,750,000원)"

            return f"{known_str}{question}"

        # 필수 정보 모두 있으면 미리보기
        confirm_msg = (
            f"다음 내용으로 지출결의서를 작성합니다:\n\n"
            f"- 제목: {title}\n"
            f"- 프로젝트: {project or '미지정'}\n"
            f"- 지출일: {date or '미지정'}\n"
            f"- 금액: {amount_str}\n"
            f"- 내용: {description}"
        )
        if items_str:
            confirm_msg += f"\n- 항목:{items_str}"
        if payee:
            confirm_msg += f"\n- 지급처: {payee}"
        if evidence_type:
            confirm_msg += f"\n- 증빙유형: {evidence_type}"
            if evidence_type in ("세금계산서", "계산서", "계산서내역"):
                if invoice_vendor or invoice_amount or invoice_date:
                    invoice_str = []
                    if invoice_vendor:
                        invoice_str.append(f"거래처: {invoice_vendor}")
                    if invoice_amount:
                        invoice_str.append(f"금액: {int(invoice_amount):,}원")
                    if invoice_date:
                        invoice_str.append(f"발행일: {invoice_date}")
                    confirm_msg += f"\n  (세금계산서 팝업 검색: {', '.join(invoice_str)})"
                else:
                    confirm_msg += "\n  (세금계산서 팝업: 거래처/금액 지정 없으면 목록 첫 번째 선택)"
        if auto_capture_budget:
            confirm_msg += "\n- 예실대비현황 스크린샷 자동 첨부: 예"
        if usage_code and usage_code != "5020":
            confirm_msg += f"\n- 용도코드: {usage_code}"
        if budget_keyword:
            confirm_msg += f"\n- 예산과목: {budget_keyword}"
        if payment_request_date:
            confirm_msg += f"\n- 지급요청일: {payment_request_date}"
        if accounting_date:
            confirm_msg += f"\n- 회계처리일자: {accounting_date}"
        # action에 따라 안내 문구 분기
        if action == "submit":
            confirm_msg += "\n\n다음 내용으로 즉시 결재상신하시겠습니까? 확인하려면 '확인'이라고 해주세요.\n⚠️ 상신 후에는 결재선에서 직접 반려 전까지 수정이 어렵습니다."
        else:
            confirm_msg += "\n\n맞으면 '확인' 또는 '작성해줘'라고 말씀해주세요."
        return confirm_msg

    # 필수 정보 검증 (상신 전 누락 방지)
    missing = []
    if not title:
        missing.append("제목")
    if not description and not items:
        missing.append("지출 내용(항목 또는 설명)")
    if not amount and not any(item.get("amount") for item in items):
        missing.append("금액")

    if missing:
        missing_str = ", ".join(missing)
        hints = []
        if "제목" in missing:
            hints.append("제목: 예) 'GS-25-0088. 메디빌더 음향공사 대금 지급의 건'")
        if "지출 내용" in missing_str:
            hints.append("내용: 예) '음향설비 설치 공사비'")
        if "금액" in missing_str:
            hints.append("금액: 예) '2,750,000원'")
        hint_str = "\n".join(f"  - {h}" for h in hints)
        return (
            f"지출결의서 작성에 필요한 정보가 부족합니다.\n\n"
            f"누락된 항목: **{missing_str}**\n\n"
            f"다음 정보를 알려주세요:\n{hint_str}"
        )

    # 실제 작성 단계
    try:


        def _run_approval():
            # 사용자별 Lock — 동일 사용자의 동시 결재 요청 방지
            gw_id = (user_context or {}).get("gw_id")
            if not gw_id:
                return {"success": False, "message": "로그인 정보가 없습니다. 먼저 /login으로 로그인해주세요."}

            user_lock = _get_user_lock(gw_id)
            if not user_lock.acquire(blocking=False):
                return {"success": False, "message": "이전 전자결재 요청이 진행 중입니다. 완료 후 다시 시도해주세요."}
            try:
                from playwright.sync_api import sync_playwright
                from src.auth.login import login_and_get_context, close_session
                from src.auth.user_db import get_decrypted_password
                from src.approval.approval_automation import ApprovalAutomation

                gw_pw = get_decrypted_password(gw_id)
                if not gw_pw:
                    return {"success": False, "message": "비밀번호를 찾을 수 없습니다. /login으로 다시 로그인해주세요."}

                pw = sync_playwright().start()
                try:
                    browser, context, page = login_and_get_context(
                        playwright_instance=pw,
                        headless=True,
                        user_id=gw_id,
                        user_pw=gw_pw,
                    )
                    page.set_viewport_size({"width": 1920, "height": 1080})

                    automation = ApprovalAutomation(page, context)
                    # 사용자별 결재선 동적 해석
                    from src.approval.form_templates import resolve_approval_line, resolve_cc_recipients
                    resolved_line = resolve_approval_line(approval_line, "지출결의서", user_context)
                    resolved_cc = resolve_cc_recipients(cc, "지출결의서", user_context)

                    expense_data = {
                        "title": title,
                        "date": date,
                        "description": description,
                        "items": items,
                        "total_amount": amount,
                        "project": project,
                    }
                    expense_data["approval_line"] = resolved_line
                    if resolved_cc:
                        expense_data["cc"] = resolved_cc
                    if evidence_type:
                        expense_data["evidence_type"] = evidence_type
                    if invoice_vendor:
                        expense_data["invoice_vendor"] = invoice_vendor
                    if invoice_amount is not None:
                        expense_data["invoice_amount"] = invoice_amount
                    if invoice_date:
                        expense_data["invoice_date"] = invoice_date
                    if attachment_path:
                        expense_data["attachment_path"] = attachment_path
                    if auto_capture_budget:
                        expense_data["auto_capture_budget"] = True
                    if usage_code:
                        expense_data["usage_code"] = usage_code
                    if budget_keyword:
                        expense_data["budget_keyword"] = budget_keyword
                    if payment_request_date:
                        expense_data["payment_request_date"] = payment_request_date
                    if accounting_date:
                        expense_data["accounting_date"] = accounting_date
                    # action에 따라 save_mode 결정
                    if action == "submit":
                        expense_data["save_mode"] = "submit"
                    else:
                        expense_data["save_mode"] = "draft"  # 기본값 임시저장
                    result = automation.create_expense_report(expense_data)

                    close_session(browser)
                    return result
                except RuntimeError as e:
                    return {"success": False, "message": str(e)}
                except Exception as e:
                    return {"success": False, "message": f"브라우저 자동화 오류: {str(e)}"}
                finally:
                    try:
                        pw.stop()
                    except Exception:
                        pass
            finally:
                user_lock.release()

        future = _executor.submit(_run_approval)
        result = future.result(timeout=180)

        if result.get("success"):
            # action에 따라 성공 메시지 분기
            if action == "submit":
                msg = f"지출결의서가 결재상신되었습니다!\n\n제목: {title}\n금액: {amount_str}"
            else:
                msg = f"지출결의서가 임시보관되었습니다! (상신 전 상태)\n\n제목: {title}\n금액: {amount_str}"
            # 검증결과 표시
            validation = result.get("validation_result", "")
            if validation:
                msg += f"\n검증결과: {validation}"
            tooltip = result.get("validation_tooltip", "")
            if tooltip:
                msg += f"\n미비사항: {tooltip}"
            if action != "submit":
                msg += "\n\n그룹웨어 임시보관문서에서 확인 후 직접 상신해주세요."
            else:
                msg += "\n\n그룹웨어에서 결재 진행 상황을 확인하세요."
            return msg
        else:
            err_msg = f"지출결의서 작성에 실패했습니다.\n사유: {result.get('message', '알 수 없는 오류')}"
            tooltip = result.get("validation_tooltip", "")
            if tooltip:
                err_msg += f"\n미비사항: {tooltip}"
            return err_msg

    except concurrent.futures.TimeoutError:
        return "지출결의서 작성 시간이 초과되었습니다 (3분). 네트워크 상태를 확인하고 다시 시도해주세요."
    except Exception as e:
        return f"지출결의서 작성 중 오류가 발생했습니다: {str(e)}"


def handle_submit_draft_approval(params: dict, user_context: dict = None) -> str:
    """
    임시보관문서함에서 문서를 열고 결재상신.
    ApprovalAutomation.open_draft_and_submit() 연동.
    """
    doc_title = params.get("doc_title", "")

    try:

        def _run():
            # 사용자별 Lock — 동일 사용자의 동시 결재 요청 방지
            gw_id = (user_context or {}).get("gw_id")
            if not gw_id:
                return {"success": False, "message": "로그인 정보가 없습니다. 먼저 /login으로 로그인해주세요."}

            user_lock = _get_user_lock(gw_id)
            if not user_lock.acquire(blocking=False):
                return {"success": False, "message": "이전 전자결재 요청이 진행 중입니다. 완료 후 다시 시도해주세요."}
            try:
                from src.auth.user_db import get_decrypted_password
                from src.approval.approval_automation import ApprovalAutomation

                gw_pw = get_decrypted_password(gw_id)
                if not gw_pw:
                    return {"success": False, "message": "비밀번호를 찾을 수 없습니다. /login으로 다시 로그인해주세요."}

                try:
                    with _playwright_session(gw_id, gw_pw) as (browser, context, page):
                        page.set_viewport_size({"width": 1920, "height": 1080})
                        automation = ApprovalAutomation(page, context)
                        return automation.open_draft_and_submit(doc_title=doc_title or None)
                except RuntimeError as e:
                    return {"success": False, "message": str(e)}
                except Exception as e:
                    return {"success": False, "message": f"브라우저 자동화 오류: {str(e)}"}
            finally:
                user_lock.release()

        future = _executor.submit(_run)
        result = future.result(timeout=180)

        if result.get("success"):
            doc = result.get("doc_title", doc_title or "")
            return f"결재상신이 완료되었습니다!\n\n문서: {doc}\n\n그룹웨어에서 결재 진행 상황을 확인하세요."
        else:
            return f"결재상신에 실패했습니다.\n사유: {result.get('message', '알 수 없는 오류')}"

    except concurrent.futures.TimeoutError:
        return "결재상신 시간이 초과되었습니다 (3분). 네트워크 상태를 확인하고 다시 시도해주세요."
    except Exception as e:
        return f"결재상신 중 오류가 발생했습니다: {str(e)}"


def handle_submit_approval_form(params: dict, user_context: dict = None) -> str:
    """
    전자결재 양식 작성 처리 (지출결의서 외)
    - form_type: 거래처등록, 연장근무, 외근신청, 선급금요청, 선급금정산, 증빙발행, 사내추천비
    - action='confirm': 확인 메시지 반환
    - action='draft': Playwright로 실제 폼 작성
    """
    from src.approval.form_templates import get_template, get_template_key, get_required_fields

    form_type = params.get("form_type", "")
    title = params.get("title", "")
    fields = params.get("fields", {})
    approval_line = params.get("approval_line")
    cc = params.get("cc")
    attachment_path = params.get("attachment_path", "")
    action = params.get("action", "confirm")

    # 양식 키 확인
    form_key = get_template_key(form_type)
    if not form_key:
        # 미지원 양식 요청 기록
        try:
            from src.chatbot.chat_db import save_unsupported_request
            gw_id = (user_context or {}).get("gw_id", "unknown")
            save_unsupported_request(
                gw_id=gw_id,
                request_type="unsupported_form",
                user_message=title or form_type,
                detail=f"양식: {form_type}",
            )
        except Exception:
            pass
        SUPPORTED_FORMS = "거래처등록, 연장근무, 외근신청, 선급금요청, 선급금정산, 증빙발행, 사내추천비"
        WORKING_FORMS = "거래처등록, 선급금요청, 선급금정산"  # 실제 E2E 동작 검증된 양식
        return (
            f"'{form_type}'은(는) 현재 지원되지 않는 양식입니다.\n\n"
            f"**지원 양식 목록**: {SUPPORTED_FORMS}\n"
            f"**E2E 완성 양식**: {WORKING_FORMS}\n\n"
            f"지출결의서가 필요하시면 '지출결의서 작성해줘'라고 말씀해주세요."
        )

    template = get_template(form_type)
    display_name = template.get("display_name", form_type)
    status = template.get("status", "template_only")

    if action != "draft":
        # 필수 필드 누락 체크
        required = get_required_fields(form_type)
        filled_labels = set()
        for key, value in fields.items():
            if value:
                field_info = template.get("fields", {}).get(key, {})
                label = field_info.get("label", key) if isinstance(field_info, dict) else key
                filled_labels.add(label)
        if title:
            filled_labels.add("제목")

        missing = [r for r in required if r not in filled_labels]

        # 대화형 질문 플로우: 필수 정보가 빠진 경우 먼저 질문 (한 번에 하나씩)
        if missing:
            known_parts = []
            if title:
                known_parts.append(f"제목: {title}")
            for key, value in fields.items():
                if value:
                    field_info = template.get("fields", {}).get(key, {})
                    label = field_info.get("label", key) if isinstance(field_info, dict) else key
                    known_parts.append(f"{label}: {value}")

            known_str = ""
            if known_parts:
                known_str = "지금까지 파악된 내용:\n" + "\n".join(f"  - {k}" for k in known_parts) + "\n\n"

            first_missing_label = missing[0]
            field_example = ""
            for key, info in template.get("fields", {}).items():
                if isinstance(info, dict) and info.get("label") == first_missing_label:
                    ex = info.get("example", "")
                    fmt = info.get("format", "")
                    if fmt:
                        field_example = f" (형식: {fmt})"
                    if ex:
                        field_example += f" 예) '{ex}'"
                    break

            question = f"{first_missing_label}을(를) 알려주세요.{field_example}"
            remaining = missing[1:]
            if remaining:
                question += f"\n\n(추가로 필요한 정보: {', '.join(remaining)})"

            return f"{known_str}{question}"

        # 필수 정보 모두 있으면 미리보기 표시
        confirm_lines = [f"다음 내용으로 **{display_name}**를 작성합니다:\n"]
        confirm_lines.append(f"- 제목: {title}")

        for key, value in fields.items():
            if value:
                field_info = template.get("fields", {}).get(key, {})
                label = field_info.get("label", key) if isinstance(field_info, dict) else key
                confirm_lines.append(f"- {label}: {value}")

        if status != "verified":
            confirm_lines.append(f"\n이 양식은 아직 자동 작성이 준비 중입니다. (DOM 탐색 미완)")

        confirm_lines.append("\n맞으면 '확인' 또는 '작성해줘'라고 말씀해주세요.")
        return "\n".join(confirm_lines)

    # 실제 작성 단계
    if status != "verified":
        return f"{display_name}은(는) 아직 자동 작성이 준비 중입니다. 수동으로 작성해주세요."

    # 필수 필드 누락 검증 (상신 전 차단)
    required = get_required_fields(form_type)
    filled_labels = set()
    if title:
        filled_labels.add("제목")
    for key, value in fields.items():
        if value:
            field_info = template.get("fields", {}).get(key, {})
            label = field_info.get("label", key) if isinstance(field_info, dict) else key
            filled_labels.add(label)

    missing_required = [r for r in required if r not in filled_labels]
    if missing_required:
        missing_str = ", ".join(missing_required)
        hints = []
        for r in missing_required:
            for key, info in template.get("fields", {}).items():
                if isinstance(info, dict) and info.get("label") == r:
                    example = info.get("example", "")
                    fmt = info.get("format", "")
                    hint = f"  - {r}"
                    if fmt:
                        hint += f" ({fmt})"
                    if example:
                        hint += f" 예) '{example}'"
                    hints.append(hint)
                    break
            else:
                hints.append(f"  - {r}")
        hint_str = "\n".join(hints)
        return (
            f"{display_name} 작성에 필요한 정보가 부족합니다.\n\n"
            f"누락된 필수 항목: **{missing_str}**\n\n"
            f"다음 정보를 알려주세요:\n{hint_str}"
        )

    try:


        def _run_approval():
            # 사용자별 Lock — 동일 사용자의 동시 결재 요청 방지
            gw_id = (user_context or {}).get("gw_id")
            if not gw_id:
                return {"success": False, "message": "로그인 정보가 없습니다. 먼저 /login으로 로그인해주세요."}

            user_lock = _get_user_lock(gw_id)
            if not user_lock.acquire(blocking=False):
                return {"success": False, "message": "이전 전자결재 요청이 진행 중입니다. 완료 후 다시 시도해주세요."}
            try:
                from playwright.sync_api import sync_playwright
                from src.auth.login import login_and_get_context, close_session
                from src.auth.user_db import get_decrypted_password
                from src.approval.approval_automation import ApprovalAutomation

                gw_pw = get_decrypted_password(gw_id)
                if not gw_pw:
                    return {"success": False, "message": "비밀번호를 찾을 수 없습니다. /login으로 다시 로그인해주세요."}

                pw = sync_playwright().start()
                try:
                    browser, context, page = login_and_get_context(
                        playwright_instance=pw,
                        headless=True,
                        user_id=gw_id,
                        user_pw=gw_pw,
                    )
                    page.set_viewport_size({"width": 1920, "height": 1080})

                    automation = ApprovalAutomation(page, context)
                    # 사용자별 결재선 동적 해석
                    from src.approval.form_templates import resolve_approval_line, resolve_cc_recipients
                    resolved_line = resolve_approval_line(approval_line, form_key, user_context)
                    resolved_cc = resolve_cc_recipients(cc, form_key, user_context)

                    data = {"title": title, **fields}
                    data["approval_line"] = resolved_line
                    if resolved_cc:
                        data["cc"] = resolved_cc
                    if attachment_path:
                        data["attachment_path"] = attachment_path
                    result = automation.create_form(form_key, data)

                    close_session(browser)
                    return result
                except RuntimeError as e:
                    return {"success": False, "message": str(e)}
                except Exception as e:
                    return {"success": False, "message": f"브라우저 자동화 오류: {str(e)}"}
                finally:
                    try:
                        pw.stop()
                    except Exception:
                        pass
            finally:
                user_lock.release()

        future = _executor.submit(_run_approval)
        result = future.result(timeout=180)

        if result.get("success"):
            return f"{display_name}가 임시보관되었습니다! (상신 전 상태)\n\n제목: {title}\n\n그룹웨어 임시보관문서에서 확인 후 직접 상신해주세요."
        else:
            return f"{display_name} 작성에 실패했습니다.\n사유: {result.get('message', '알 수 없는 오류')}"

    except concurrent.futures.TimeoutError:
        return f"{display_name} 작성 시간이 초과되었습니다 (3분). 네트워크 상태를 확인하고 다시 시도해주세요."
    except Exception as e:
        return f"{display_name} 작성 중 오류가 발생했습니다: {str(e)}"


def handle_search_project_code(params: dict, user_context: dict = None) -> str:
    """
    GW 프로젝트 코드도움 자동완성 검색.
    Playwright로 지출결의서 폼을 열고 키워드 입력 후 드롭다운 목록 반환.

    Returns:
        결과 목록 또는 안내 메시지 (Gemini가 사용자에게 확인 요청에 사용)
    """
    keyword = params.get("keyword", "").strip()
    if not keyword:
        return "검색 키워드를 입력해주세요."

    try:


        def _run_search():
            # 사용자별 Lock — 동일 사용자의 동시 결재 요청 방지
            gw_id = (user_context or {}).get("gw_id")
            if not gw_id:
                return {"success": False, "results": [], "message": "로그인 정보가 없습니다. 먼저 /login으로 로그인해주세요."}

            user_lock = _get_user_lock(gw_id)
            if not user_lock.acquire(blocking=False):
                return {"success": False, "results": [], "message": "이전 전자결재 요청이 진행 중입니다. 완료 후 다시 시도해주세요."}
            try:
                from src.auth.user_db import get_decrypted_password
                from src.approval.approval_automation import ApprovalAutomation

                gw_pw = get_decrypted_password(gw_id)
                if not gw_pw:
                    return {"success": False, "results": [], "message": "비밀번호를 찾을 수 없습니다."}

                try:
                    with _playwright_session(gw_id, gw_pw) as (browser, context, page):
                        page.set_viewport_size({"width": 1920, "height": 1080})
                        automation = ApprovalAutomation(page, context)
                        results = automation.search_project_codes(keyword, max_results=8)
                        return {"success": True, "results": results}
                except Exception as e:
                    return {"success": False, "results": [], "message": f"검색 오류: {str(e)}"}
            finally:
                user_lock.release()

        future = _executor.submit(_run_search)
        result = future.result(timeout=60)

        if not result.get("success"):
            return result.get("message", "프로젝트 검색에 실패했습니다.")

        results = result.get("results", [])

        if not results:
            return (
                f"그룹웨어에서 '{keyword}' 프로젝트를 찾지 못했어요.\n"
                f"정확한 프로젝트 코드(예: GS-25-0088)나 이름을 알려주세요."
            )

        if len(results) == 1:
            r = results[0]
            return (
                f"SEARCH_RESULT:SINGLE\n"
                f"프로젝트: {r['full_text']}\n"
                f"---\n"
                f"프로젝트는 '{r['full_text']}'가 맞나요?"
            )

        # 여러 건: 선택지 제시
        lines = [f"'{keyword}'로 검색된 프로젝트가 {len(results)}건 있습니다. 어떤 프로젝트인가요?\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['full_text']}")
        lines.append("\n번호로 선택하거나 전체 코드를 입력해주세요.")
        return "SEARCH_RESULT:MULTIPLE\n" + "\n".join(lines)

    except concurrent.futures.TimeoutError:
        return f"프로젝트 검색 시간이 초과되었습니다 (1분). 직접 프로젝트 코드를 입력해주세요."
    except Exception as e:
        return f"프로젝트 검색 중 오류가 발생했습니다: {str(e)}"


def handle_start_approval_wizard_fn(params: dict, user_context: dict = None) -> str:
    """
    전자결재 마법사 시작.
    user_context["approval_wizard"]에 ApprovalWizard 인스턴스 저장.
    첫 질문(양식 선택)을 반환.
    """
    if user_context is None:
        return "로그인 후 이용해주세요."

    from src.chatbot.approval_wizard import ApprovalWizard
    wizard = ApprovalWizard(user_context=user_context)
    user_context["approval_wizard"] = wizard
    msg, done = wizard.start()
    if done:
        del user_context["approval_wizard"]
    return msg


def handle_start_contract_wizard_fn(params: dict, user_context: dict = None) -> str:
    """계약서 단건 작성 마법사 시작."""
    if user_context is None:
        return "로그인 후 이용해주세요."
    from src.contracts.contract_wizard import ContractWizard
    wizard = ContractWizard(user_context=user_context)
    user_context["contract_wizard"] = wizard
    msg, done = wizard.start()
    if done:
        user_context.pop("contract_wizard", None)
    return msg


def handle_generate_contracts_from_file(params: dict, user_context: dict = None) -> str:
    """Excel 파일에서 계약서 일괄 생성."""
    file_path = params.get("file_path", "")
    import pathlib
    if not file_path or not pathlib.Path(file_path).exists():
        return (
            "Excel 파일을 찾을 수 없습니다.\n"
            "파일을 첨부하거나 경로를 확인해주세요.\n"
            "입력양식은 `data/계약서_입력양식.xlsx`를 참고하세요."
        )
    try:
        from src.contracts.contract_generator import generate_from_excel
        # data/tmp/ 에 생성 → /download/ 엔드포인트로 제공
        tmp_dir = pathlib.Path(__file__).parent.parent.parent / "data" / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        gw_id = (user_context or {}).get("gw_id", "")
        from src.chatbot._download_registry import register as register_download
        results = generate_from_excel(file_path, str(tmp_dir))
        ok = [r for r in results if r["status"] == "ok"]
        err = [r for r in results if r["status"] == "error"]
        lines = [f"✅ 계약서 일괄 생성 완료! ({len(ok)}건 성공, {len(err)}건 실패)\n"]
        lines.append("📥 아래 링크를 클릭해서 다운로드하세요:\n")
        for r in ok:
            fname = pathlib.Path(r["file"]).name
            token = register_download(r["file"], gw_id)
            lines.append(f"[📄 {fname}](/download/{token})")
        for r in err:
            lines.append(f"  ❌ {r['file']}: {r['msg']}")
        return "\n".join(lines)
    except Exception as e:
        return f"계약서 생성 중 오류가 발생했습니다: {e}"


def handle_get_mail_summary(params: dict, user_context: dict = None) -> str:
    """
    안 읽은 메일 요약 처리.
    summarizer.run_for_chatbot() 호출 → 결과 반환.
    """
    try:


        def _run_summary():
            from src.mail.summarizer import run_for_chatbot
            return run_for_chatbot(user_context=user_context)

        future = _executor.submit(_run_summary)
        result = future.result(timeout=120)

        return result
    except concurrent.futures.TimeoutError:
        return "메일 요약 시간이 초과되었습니다 (2분). 네트워크 상태를 확인하고 다시 시도해주세요."
    except Exception as e:
        return f"메일 요약 중 오류가 발생했습니다: {str(e)}"


def handle_transcribe_audio(params: dict, user_context: dict = None) -> str:
    """
    음성 파일을 텍스트로 변환 (Google Cloud Speech-to-Text API).
    """
    file_path = params.get("file_path", "")
    language = params.get("language", "ko-KR")

    if not file_path:
        return "음성 파일 경로가 필요합니다."

    if not os.path.exists(file_path):
        return f"파일을 찾을 수 없습니다: {file_path}"

    try:
        from src.chatbot.stt import transcribe_audio
        result = transcribe_audio(file_path, language=language)

        if result["success"]:
            duration = result["duration_seconds"]
            confidence = result["confidence"]
            text = result["text"]

            # 분:초 형식으로 표시
            mins = int(duration // 60)
            secs = int(duration % 60)
            time_str = f"{mins}분 {secs}초" if mins > 0 else f"{secs}초"

            return (
                f"🎤 음성을 텍스트로 변환했습니다 ({time_str}, 정확도 {confidence:.0%}):\n\n"
                f"{text}"
            )
        else:
            return f"음성 변환에 실패했습니다: {result.get('error', '알 수 없는 오류')}"

    except Exception as e:
        logger.error(f"STT 처리 오류: {e}")
        return f"음성 변환 중 오류가 발생했습니다: {str(e)}"


def handle_get_fund_summary(params: dict, user_context: dict = None) -> str:
    """자금현황 요약 조회 핸들러"""
    from src.fund_table.db import list_projects, get_fund_summary, get_all_projects_summary

    project_name = params.get("project_name", "")

    if project_name:
        # 특정 프로젝트 검색
        projects = list_projects()
        matched = None
        for p in projects:
            if project_name in p["name"]:
                matched = p
                break

        if not matched:
            return f"'{project_name}'에 해당하는 프로젝트를 찾을 수 없습니다. 등록된 프로젝트 목록: " + ", ".join(p["name"] for p in projects) if projects else "등록된 프로젝트가 없습니다."

        summary = get_fund_summary(matched["id"])
        if "error" in summary:
            return summary["error"]

        def fmt(n):
            return f"{n:,}원" if n else "0원"

        # 데이터 미입력 프로젝트 안내
        has_data = (
            summary['total_order'] > 0
            or summary['execution_budget'] > 0
            or summary['total_contract'] > 0
        )
        if not has_data:
            return (
                f"📊 **{summary['project_name']}**\n\n"
                f"아직 금액 데이터가 입력되지 않은 프로젝트입니다.\n"
                f"프로젝트 관리 페이지(/fund)에서 수주액, 실행예산 등을 먼저 입력해주세요."
            )

        lines = [f"📊 **{summary['project_name']}** 자금현황 요약\n"]
        lines.append(f"• 수주액: {fmt(summary['total_order'])}")
        if summary['design_amount'] or summary['construction_amount']:
            lines[-1] += f" (설계 {fmt(summary['design_amount'])} + 시공 {fmt(summary['construction_amount'])})"
        lines.append(f"• 실행예산: {fmt(summary['execution_budget'])}")
        lines.append(f"• 수익금: {fmt(summary['profit_amount'])} / 이익률 {summary['profit_rate']:.1f}%")
        if summary['total_companies'] > 0:
            lines.append(f"\n• 하도급 업체: {summary['total_companies']}개사")
            lines.append(f"• 계약총액: {fmt(summary['total_contract'])}")
            lines.append(f"• 기지급액: {fmt(summary['total_paid'])}")
            lines.append(f"• 잔여금액: {fmt(summary['total_remaining'])}")
        lines.append(f"\n상세 내용은 프로젝트 관리 페이지(/fund)에서 확인하세요.")
        return "\n".join(lines)
    else:
        # 전체 프로젝트 요약
        summaries = get_all_projects_summary()
        if not summaries:
            return "등록된 프로젝트가 없습니다. 프로젝트 관리 페이지(/fund)에서 프로젝트를 먼저 등록해주세요."

        lines = ["📊 **전체 프로젝트 자금현황**\n"]
        for s in summaries:
            lines.append(
                f"• **{s['project_name']}**: 수주 {s['total_order']:,}원 / "
                f"실행예산 {s['execution_budget']:,}원 / "
                f"기지급 {s['total_paid']:,}원 / "
                f"잔여 {s['total_remaining']:,}원"
            )
        lines.append(f"\n총 {len(summaries)}개 프로젝트. 상세는 프로젝트 관리 페이지(/fund)에서 확인하세요.")
        return "\n".join(lines)


# ─────────────────────────────────────────
# 프로젝트 관리 핸들러들
# ─────────────────────────────────────────

def _find_project(project_name: str):
    """프로젝트명으로 프로젝트 검색 (별칭 + 스코어링 기반 매칭)

    검색 우선순위:
    1. 프로젝트명 정확 일치
    2. 별칭(alias) 정확 일치
    3. 프로젝트명 부분 일치 (데이터 있는 프로젝트 우선)
    4. 별칭 부분 일치
    5. project_code 일치
    """
    from src.fund_table.db import list_projects, find_project_by_alias
    projects = list_projects()
    if not project_name:
        return None, projects

    search = project_name.strip()
    search_lower = search.lower()

    # 1. 프로젝트명 정확 일치
    for p in projects:
        if p["name"] == search:
            return p, projects

    # 2. 별칭(alias) 정확/부분 일치
    alias_match = find_project_by_alias(search)
    if alias_match:
        return alias_match, projects

    # 3. 프로젝트명 부분 일치 — 데이터 있는 프로젝트를 우선
    import re as _re

    def _has_data(p):
        return (p.get("design_amount", 0) or 0) + (p.get("construction_amount", 0) or 0) + \
               (p.get("execution_budget", 0) or 0) > 0

    def _normalize(name):
        """대괄호/괄호 제거하여 순수 텍스트로 변환 (예: '[제천] 의림지 청수당' → '제천 의림지 청수당')"""
        n = _re.sub(r'[\[\]()]', ' ', name)
        n = _re.sub(r'-\s*해외\s*-', '', n)
        return _re.sub(r'\s+', ' ', n).strip().lower()

    search_norm = _normalize(search)

    candidates = []
    for p in projects:
        pname_lower = p["name"].lower()
        pname_norm = _normalize(p["name"])
        matched = (
            search_lower in pname_lower or pname_lower in search_lower
            or search_norm in pname_norm or pname_norm in search_norm
        )
        if matched:
            score = 0
            if _has_data(p):
                score += 10
            score += max(0, 5 - abs(len(search) - len(p["name"])) // 3)
            candidates.append((score, p))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1], projects

    # 4. 검색어의 각 단어가 모두 프로젝트명에 포함되는지 (토큰 매칭)
    search_tokens = [t for t in search_lower.split() if len(t) >= 2]
    if search_tokens:
        for p in projects:
            pname_norm = _normalize(p["name"])
            if all(t in pname_norm for t in search_tokens):
                candidates.append((10 if _has_data(p) else 0, p))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1], projects

    # 5. project_code 일치
    for p in projects:
        if p.get("project_code") and search_lower in p["project_code"].lower():
            return p, projects

    return None, projects


def handle_update_project_info(params: dict, user_context: dict = None) -> str:
    """프로젝트 정보 수정 핸들러"""
    from src.fund_table.db import save_project_overview, get_project_overview

    project_name = params.get("project_name", "")
    field = params.get("field", "")
    value = params.get("value", "")

    project, all_projects = _find_project(project_name)
    if not project:
        names = ", ".join(p["name"] for p in all_projects)
        return f"'{project_name}' 프로젝트를 찾을 수 없습니다. 등록된 프로젝트: {names}"

    # 개요 필드 매핑
    overview_fields = {
        "location", "usage", "scale", "area_pyeong",
        "design_start", "design_end", "construction_start", "construction_end",
        "open_date", "current_status",
        "issue_design", "issue_schedule", "issue_budget",
        "issue_operation", "issue_defect", "issue_other",
        "project_category",
    }

    if field in overview_fields:
        data = {field: value}
        if field == "area_pyeong":
            try:
                data[field] = float(value)
            except ValueError:
                return f"면적은 숫자로 입력해주세요: '{value}'"
        result = save_project_overview(project["id"], data)
        if result["success"]:
            field_labels = {
                "location": "위치", "usage": "용도", "scale": "규모",
                "area_pyeong": "연면적", "design_start": "디자인 시작일",
                "design_end": "디자인 종료일", "construction_start": "시공 시작일",
                "construction_end": "시공 종료일", "open_date": "오픈 예정일",
                "current_status": "현황", "issue_design": "디자인/인허가 이슈",
                "issue_schedule": "일정 이슈", "issue_budget": "예산 이슈",
                "issue_operation": "운영 이슈", "issue_defect": "하자 이슈",
                "issue_other": "기타 이슈", "project_category": "카테고리",
            }
            label = field_labels.get(field, field)
            return f"'{project['name']}' 프로젝트의 {label}을(를) '{value}'(으)로 수정했습니다."
        return f"수정 실패: {result.get('message', '')}"
    else:
        return f"지원되지 않는 필드입니다: '{field}'. 가능한 필드: {', '.join(overview_fields)}"


def handle_add_project_note(params: dict, user_context: dict = None) -> str:
    """프로젝트 메모 추가 핸들러"""
    from src.fund_table.db import add_material

    project_name = params.get("project_name", "")
    title = params.get("title", "메모")
    content = params.get("content", "")

    project, all_projects = _find_project(project_name)
    if not project:
        names = ", ".join(p["name"] for p in all_projects)
        return f"'{project_name}' 프로젝트를 찾을 수 없습니다. 등록된 프로젝트: {names}"

    result = add_material(
        project_id=project["id"],
        material_type="text",
        description=title,
        content_text=content,
    )
    if result["success"]:
        return f"'{project['name']}' 프로젝트에 메모를 추가했습니다.\n제목: {title}\n내용: {content[:100]}{'...' if len(content) > 100 else ''}"
    return f"메모 추가 실패: {result.get('message', '')}"


def handle_add_project_subcontract(params: dict, user_context: dict = None) -> str:
    """하도급 업체 추가 핸들러"""
    from src.fund_table.db import add_subcontract, list_trades, add_trade

    project_name = params.get("project_name", "")
    company_name = params.get("company_name", "")
    trade_name = params.get("trade_name", "")
    contract_amount = int(params.get("contract_amount", 0) or 0)

    project, all_projects = _find_project(project_name)
    if not project:
        names = ", ".join(p["name"] for p in all_projects)
        return f"'{project_name}' 프로젝트를 찾을 수 없습니다. 등록된 프로젝트: {names}"

    # 공종 찾기/생성
    trade_id = None
    if trade_name:
        trades = list_trades(project["id"])
        for t in trades:
            if trade_name in t["name"] or t["name"] in trade_name:
                trade_id = t["id"]
                break
        if not trade_id:
            result = add_trade(project["id"], name=trade_name)
            if result["success"]:
                trade_id = result["id"]

    kwargs = {}
    if trade_id:
        kwargs["trade_id"] = trade_id
    if contract_amount:
        kwargs["contract_amount"] = contract_amount

    result = add_subcontract(project["id"], company_name=company_name, **kwargs)
    if result["success"]:
        msg = f"'{project['name']}' 프로젝트에 하도급 업체 '{company_name}'을(를) 추가했습니다."
        if trade_name:
            msg += f"\n공종: {trade_name}"
        if contract_amount:
            msg += f"\n계약금액: {contract_amount:,}원"
        return msg
    return f"업체 추가 실패: {result.get('message', '')}"


def handle_update_collection_status(params: dict, user_context: dict = None) -> str:
    """수금현황 업데이트 핸들러"""
    from src.fund_table.db import list_collections, update_collection

    project_name = params.get("project_name", "")
    stage = params.get("stage", "")
    collected = params.get("collected", False)

    project, all_projects = _find_project(project_name)
    if not project:
        names = ", ".join(p["name"] for p in all_projects)
        return f"'{project_name}' 프로젝트를 찾을 수 없습니다. 등록된 프로젝트: {names}"

    collections = list_collections(project["id"])
    matched = None
    for c in collections:
        if stage in c.get("stage", ""):
            matched = c
            break

    if not matched:
        stages = ", ".join(c["stage"] for c in collections) if collections else "없음"
        return f"'{stage}' 단계를 찾을 수 없습니다. 등록된 수금 단계: {stages}"

    result = update_collection(matched["id"], collected=1 if collected else 0)
    status = "수금 완료" if collected else "미수금"
    if result["success"]:
        return f"'{project['name']}' - '{matched['stage']}' ({matched.get('amount', 0):,}원) → {status} 처리 완료"
    return f"수정 실패: {result.get('message', '')}"


def handle_add_project_todo(params: dict, user_context: dict = None) -> str:
    """TODO 추가 핸들러"""
    from src.fund_table.db import create_todo

    project_name = params.get("project_name", "")
    content = params.get("content", "")
    priority = params.get("priority", "medium")
    category = params.get("category", "")

    project_id = None
    if project_name:
        project, _ = _find_project(project_name)
        if project:
            project_id = project["id"]

    result = create_todo(
        project_id=project_id,
        content=content,
        priority=priority,
        category=category,
    )
    if result["success"]:
        priority_label = {"high": "높음", "medium": "보통", "low": "낮음"}.get(priority, priority)
        msg = f"TODO 추가 완료: '{content}' (우선순위: {priority_label})"
        if project_name:
            msg += f"\n프로젝트: {project_name}"
        return msg
    return f"TODO 추가 실패: {result.get('message', '')}"


def handle_get_project_detail(params: dict, user_context: dict = None) -> str:
    """프로젝트 상세 정보 조회 핸들러"""
    from src.fund_table.db import (
        get_project_overview, list_collections, list_subcontracts,
        list_todos, list_materials, list_contacts
    )

    project_name = params.get("project_name", "")
    project, all_projects = _find_project(project_name)
    if not project:
        names = ", ".join(p["name"] for p in all_projects)
        return f"'{project_name}' 프로젝트를 찾을 수 없습니다. 등록된 프로젝트: {names}"

    pid = project["id"]
    ov = get_project_overview(pid)
    colls = list_collections(pid)
    subs = list_subcontracts(pid)
    todos = list_todos(project_id=pid)
    materials = list_materials(pid)
    contacts = list_contacts(pid)

    total_order = (project.get("design_amount", 0) or 0) + (project.get("construction_amount", 0) or 0)
    coll_total = sum(c.get("amount", 0) for c in colls)
    coll_done = sum(c.get("amount", 0) for c in colls if c.get("collected"))

    lines = [f"📋 **{project['name']}** 상세 정보\n"]

    # 기본정보
    lines.append(f"• 등급: {project.get('grade', '-')} | 상태: {project.get('status', '-')}")
    lines.append(f"• 수주액: {total_order:,}원 | 실행예산: {(project.get('execution_budget', 0) or 0):,}원")
    lines.append(f"• 이익율: {project.get('profit_rate', 0):.1f}%\n")

    # 개요
    if ov:
        lines.append(f"📍 위치: {ov.get('location', '-')} | 용도: {ov.get('usage', '-')}")
        if ov.get('design_start'):
            lines.append(f"📅 설계: {ov.get('design_start', '-')} ~ {ov.get('design_end', '-')}")
        if ov.get('construction_start'):
            lines.append(f"🔨 시공: {ov.get('construction_start', '-')} ~ {ov.get('construction_end', '-')}")
        if ov.get('current_status'):
            lines.append(f"📝 현황: {ov['current_status']}")

    # 마일스톤
    milestones = ov.get("milestones", [])
    if milestones:
        done = sum(1 for m in milestones if m.get("completed"))
        lines.append(f"\n✅ 진행률: {done}/{len(milestones)} 단계 완료")

    # 수금
    if colls:
        lines.append(f"\n💰 수금: {coll_done:,}/{coll_total:,}원 ({(coll_done/coll_total*100 if coll_total else 0):.1f}%)")

    # 하도급
    if subs:
        total_contract = sum(s.get("contract_amount", 0) for s in subs)
        lines.append(f"🏗️ 하도급: {len(subs)}개사, 계약총액 {total_contract:,}원")

    # 이슈
    issues = []
    for key in ["issue_design", "issue_schedule", "issue_budget", "issue_operation", "issue_defect", "issue_other"]:
        if ov.get(key):
            issues.append(ov[key])
    if issues:
        lines.append(f"\n⚠️ 이슈: {'; '.join(issues)}")

    # TODO
    pending_todos = [t for t in todos if not t.get("completed")]
    if pending_todos:
        lines.append(f"\n📝 미완료 TODO: {len(pending_todos)}건")
        for t in pending_todos[:5]:
            lines.append(f"  - {t['content']}")

    # 자료
    if materials:
        lines.append(f"\n📎 등록 자료: {len(materials)}건")

    # 연락처
    if contacts:
        lines.append(f"\n📞 거래처 연락처: {len(contacts)}건")

    lines.append(f"\n상세 내용은 프로젝트 관리 페이지(/fund)에서 확인하세요.")
    return "\n".join(lines)


def handle_add_project_contact(params: dict, user_context: dict = None) -> str:
    """거래처 연락처 추가 핸들러"""
    from src.fund_table.db import add_contact

    project_name = params.get("project_name", "")
    company_name = params.get("company_name", "")
    contact_person = params.get("contact_person", "")
    phone = params.get("phone", "")
    email = params.get("email", "")
    trade_name = params.get("trade_name", "")

    project, all_projects = _find_project(project_name)
    if not project:
        names = ", ".join(p["name"] for p in all_projects)
        return f"'{project_name}' 프로젝트를 찾을 수 없습니다. 등록된 프로젝트: {names}"

    kwargs = {}
    if contact_person: kwargs["contact_person"] = contact_person
    if phone: kwargs["phone"] = phone
    if email: kwargs["email"] = email
    if trade_name: kwargs["trade_name"] = trade_name

    result = add_contact(project["id"], company_name=company_name, **kwargs)
    if result["success"]:
        msg = f"'{project['name']}' 프로젝트에 연락처 추가 완료\n업체: {company_name}"
        if contact_person: msg += f"\n담당자: {contact_person}"
        if phone: msg += f"\n연락처: {phone}"
        return msg
    return f"연락처 추가 실패: {result.get('message', '')}"


def handle_get_overdue_items(params: dict, user_context: dict = None) -> str:
    """기한 초과/미수금/미완료 항목 조회 핸들러"""
    from src.fund_table.db import get_all_projects_full_data
    from datetime import datetime

    projects = get_all_projects_full_data()
    if not projects:
        return "등록된 프로젝트가 없습니다."

    today = datetime.now().strftime("%Y-%m-%d")
    lines = ["📊 **전체 프로젝트 밀린 항목 현황**\n"]

    total_overdue = 0
    total_uncollected = 0
    total_pending_todos = 0

    for p in projects:
        project_lines = []

        # 마일스톤 기한 초과
        for ms in p.get("milestones", []):
            if not ms.get("completed") and ms.get("date") and ms["date"] < today:
                project_lines.append(f"  ⏰ 마일스톤 기한 초과: '{ms['name']}' ({ms['date']})")
                total_overdue += 1

        # 미수금 (1000만원 이상)
        for c in p.get("collections", []):
            if not c.get("collected") and c.get("amount", 0) > 10000000:
                project_lines.append(f"  💰 미수금: '{c['stage']}' {c['amount']:,}원")
                total_uncollected += 1

        # 미완료 TODO (high 우선)
        for t in p.get("todos", []):
            if not t.get("completed") and t.get("priority") == "high":
                project_lines.append(f"  📝 긴급 TODO: {t['content']}")
                total_pending_todos += 1

        if project_lines:
            lines.append(f"**{p['name']}**")
            lines.extend(project_lines)
            lines.append("")

    if total_overdue + total_uncollected + total_pending_todos == 0:
        return "현재 기한 초과/미수금/긴급 TODO 항목이 없습니다. 잘 관리되고 있습니다!"

    lines.append(f"---\n총: 기한 초과 {total_overdue}건 | 미수금 {total_uncollected}건 | 긴급 TODO {total_pending_todos}건")
    return "\n".join(lines)


def handle_compare_projects(params: dict, user_context: dict = None) -> str:
    """프로젝트 포트폴리오 비교"""
    from src.fund_table import db as fund_db
    data = fund_db.get_portfolio_summary()
    if not data:
        return "등록된 프로젝트가 없습니다. 프로젝트 관리 페이지(/fund)에서 프로젝트를 추가해 주세요."

    lines = ["📊 **포트폴리오 비교 현황**\n"]

    total_order = sum(p["total_order"] for p in data)
    total_collected = sum(p["coll_collected"] for p in data)
    total_coll_total = sum(p["coll_total"] for p in data)
    total_uncollected = total_coll_total - total_collected
    lines.append(f"전체 {len(data)}개 프로젝트 | 총 수주액 {total_order:,.0f}원")
    lines.append(f"총 수금 {total_collected:,.0f}원 | 미수금 {total_uncollected:,.0f}원\n")

    # 프로젝트별 비교
    lines.append("| 프로젝트 | 등급 | 수주액 | 수금율 | 지급율 | 이익율 |")
    lines.append("|---------|------|--------|--------|--------|--------|")
    for p in data:
        lines.append(
            f"| {p['name']} | {p['grade']} | {p['total_order']:,.0f} | "
            f"{p['coll_rate']:.1f}% | {p['payment_rate']:.1f}% | {p['profit_rate']:.1f}% |"
        )

    # 수금율 순 추천
    sorted_by_coll = sorted(data, key=lambda x: x["coll_rate"])
    if sorted_by_coll and sorted_by_coll[0]["coll_rate"] < 50:
        worst = sorted_by_coll[0]
        lines.append(f"\n⚠️ **{worst['name']}** 수금율이 {worst['coll_rate']:.1f}%로 가장 낮습니다. 수금 독촉이 필요합니다.")

    lines.append("\n상세 정보는 프로젝트 관리 페이지(/fund)에서 확인하세요.")
    return "\n".join(lines)


def handle_generate_project_report(params: dict, user_context: dict = None) -> str:
    """프로젝트 종합 보고서 생성"""
    from src.fund_table import db as fund_db
    project_name = params.get("project_name", "")
    project, _ = _find_project(project_name)
    if not project:
        return f"'{project_name}' 프로젝트를 찾을 수 없습니다."

    pid = project["id"]
    detail = fund_db.get_project_detail(pid) if hasattr(fund_db, 'get_project_detail') else {}
    summary = fund_db.get_fund_summary(pid)
    overview_data = fund_db.get_project_overview(pid) or {}

    lines = [f"📋 **{project['name']} 프로젝트 보고서**\n"]

    # 기본 정보
    s = summary if "error" not in summary else {}
    total_order = (s.get("design_amount") or 0) + (s.get("construction_amount") or 0)
    lines.append("**1. 금액 현황**")
    lines.append(f"  - 수주액: {total_order:,.0f}원")
    lines.append(f"  - 실행예산: {s.get('execution_budget', 0):,.0f}원")
    lines.append(f"  - 수익금: {s.get('profit_amount', 0):,.0f}원 (이익율 {s.get('profit_rate', 0):.1f}%)")

    # 수금
    colls = fund_db.list_collections(pid) if hasattr(fund_db, 'list_collections') else []
    coll_total = sum(c.get("amount", 0) for c in colls)
    coll_done = sum(c.get("amount", 0) for c in colls if c.get("collected"))
    coll_rate = (coll_done / coll_total * 100) if coll_total else 0
    lines.append(f"\n**2. 수금 현황** ({coll_rate:.1f}%)")
    lines.append(f"  - 수금 완료: {coll_done:,.0f}원 / 전체: {coll_total:,.0f}원")
    if coll_total - coll_done > 0:
        lines.append(f"  - 미수금: {coll_total - coll_done:,.0f}원")

    # 하도급/지급
    subs = fund_db.list_subcontracts(pid) if hasattr(fund_db, 'list_subcontracts') else []
    sub_total = sum(sc.get("contract_amount", 0) for sc in subs)
    paid = 0
    for sc in subs:
        for i in range(1, 5):
            if sc.get(f"payment_{i}_confirmed"):
                paid += sc.get(f"payment_{i}", 0)
    pay_rate = (paid / sub_total * 100) if sub_total else 0
    lines.append(f"\n**3. 지급 현황** ({pay_rate:.1f}%)")
    lines.append(f"  - 기지급: {paid:,.0f}원 / 지급한도: {sub_total:,.0f}원")
    lines.append(f"  - 하도급사: {len(subs)}개사")

    # 개요
    ov = overview_data
    if ov.get("location"):
        lines.append(f"\n**4. 프로젝트 정보**")
        if ov.get("location"): lines.append(f"  - 위치: {ov['location']}")
        if ov.get("usage"): lines.append(f"  - 용도: {ov['usage']}")
        if ov.get("scale"): lines.append(f"  - 규모: {ov['scale']}")
        if ov.get("current_status"): lines.append(f"  - 현황: {ov['current_status']}")

    # 마일스톤
    milestones = ov.get("milestones") or []
    if milestones:
        done_count = sum(1 for m in milestones if m.get("completed"))
        lines.append(f"\n**5. 공정 진행률** ({done_count}/{len(milestones)})")
        for m in milestones:
            icon = "✅" if m.get("completed") else "⬜"
            lines.append(f"  {icon} {m.get('name', '-')} {m.get('date', '')}")

    # 이슈
    issue_keys = ["issue_design", "issue_schedule", "issue_budget", "issue_operation", "issue_defect", "issue_other"]
    issue_labels = {"issue_design": "디자인/인허가", "issue_schedule": "일정", "issue_budget": "예산",
                    "issue_operation": "운영", "issue_defect": "하자", "issue_other": "기타"}
    active_issues = [(issue_labels[k], ov[k]) for k in issue_keys if ov.get(k)]
    if active_issues:
        lines.append(f"\n**6. 이슈사항** ({len(active_issues)}건)")
        for label, val in active_issues:
            lines.append(f"  - [{label}] {val}")

    lines.append(f"\n---\n보고서 생성일: {__import__('datetime').date.today().isoformat()}")
    return "\n".join(lines)


def handle_update_project_milestone(params: dict, user_context: dict = None) -> str:
    """마일스톤 완료처리 또는 신규추가"""
    from src.fund_table import db as fund_db
    project_name = params.get("project_name", "")
    milestone_name = params.get("milestone_name", "")
    action = params.get("action", "complete")
    date_str = params.get("date", "")

    project, _ = _find_project(project_name)
    if not project:
        return f"'{project_name}' 프로젝트를 찾을 수 없습니다."

    pid = project["id"]
    ov = fund_db.get_project_overview(pid) or {}
    milestones = ov.get("milestones") or []

    if action == "add":
        new_ms = {"name": milestone_name, "completed": False}
        if date_str:
            new_ms["date"] = date_str
        milestones.append(new_ms)
        fund_db.save_project_overview(pid, {"milestones": milestones})
        return f"✅ **{project['name']}** 프로젝트에 '{milestone_name}' 단계를 추가했습니다."

    # complete
    found = False
    for m in milestones:
        if milestone_name.lower() in (m.get("name") or "").lower():
            m["completed"] = True
            if date_str:
                m["date"] = date_str
            found = True
            break

    if not found:
        return f"'{milestone_name}' 마일스톤을 찾을 수 없습니다. 등록된 마일스톤: {', '.join(m.get('name', '-') for m in milestones)}"

    fund_db.save_project_overview(pid, {"milestones": milestones})
    done_count = sum(1 for m in milestones if m.get("completed"))
    return f"✅ **{project['name']}** '{milestone_name}' 완료 처리! ({done_count}/{len(milestones)} 완료)"


def handle_request_annual_leave(params: dict, user_context: dict = None) -> str:
    """연차휴가신청서 작성 처리"""
    leave_type = params.get("leave_type", "연차")
    leave_start = params.get("leave_start", "")
    leave_end = params.get("leave_end", leave_start)
    save_mode = params.get("save_mode", "verify")

    if not leave_start:
        return "휴가 시작일을 알려주세요. (예: 2026-03-25)"

    try:
        def _run():
            from playwright.sync_api import sync_playwright
            from src.auth.login import login_and_get_context
            from src.auth.user_db import get_decrypted_password
            from src.approval.approval_automation import ApprovalAutomation

            gw_id = (user_context or {}).get("gw_id")
            if not gw_id:
                return {"success": False, "message": "로그인 정보가 없습니다. 먼저 /login으로 로그인해주세요."}

            gw_pw = get_decrypted_password(gw_id)
            if not gw_pw:
                return {"success": False, "message": "비밀번호를 찾을 수 없습니다. /login으로 다시 로그인해주세요."}

            pw = sync_playwright().start()
            try:
                browser, context, page = login_and_get_context(
                    playwright_instance=pw,
                    headless=True,
                    user_id=gw_id,
                    user_pw=gw_pw,
                )
                page.set_viewport_size({"width": 1920, "height": 1080})
                automation = ApprovalAutomation(page, context)
                data = {
                    "leave_type": leave_type,
                    "leave_start": leave_start,
                    "leave_end": leave_end,
                    "save_mode": save_mode,
                }
                return automation.create_annual_leave_request(data)
            finally:
                try:
                    pw.stop()
                except Exception:
                    pass

        future = _executor.submit(_run)
        result = future.result(timeout=180)

        if result.get("success"):
            mode_str = "신청이 완료되었습니다." if save_mode == "submit" else "내용을 확인해주세요."
            return (
                f"연차휴가신청서 {mode_str}\n\n"
                f"- 휴가 종류: {leave_type}\n"
                f"- 기간: {leave_start} ~ {leave_end}"
            )
        else:
            return f"연차휴가신청서 작성에 실패했습니다.\n사유: {result.get('message', '알 수 없는 오류')}"

    except concurrent.futures.TimeoutError:
        return "연차휴가신청서 처리 시간이 초과되었습니다 (3분). 다시 시도해주세요."
    except Exception as e:
        return f"연차휴가신청서 처리 중 오류가 발생했습니다: {str(e)}"


def handle_request_overtime(params: dict, user_context: dict = None) -> str:
    """연장근무신청서 작성 처리"""
    work_type = params.get("work_type", "연장근무")
    work_date = params.get("work_date", "")
    start_time = params.get("start_time", "")
    end_time = params.get("end_time", "")
    hours = params.get("hours")
    minutes = params.get("minutes")
    reason = params.get("reason", "")
    save_mode = params.get("save_mode", "verify")

    if not work_date:
        return "근무 날짜를 알려주세요. (예: 2026-03-25)"
    if not reason:
        return "연장근무 사유를 알려주세요."

    try:
        def _run():
            from playwright.sync_api import sync_playwright
            from src.auth.login import login_and_get_context
            from src.auth.user_db import get_decrypted_password
            from src.approval.approval_automation import ApprovalAutomation

            gw_id = (user_context or {}).get("gw_id")
            if not gw_id:
                return {"success": False, "message": "로그인 정보가 없습니다. 먼저 /login으로 로그인해주세요."}

            gw_pw = get_decrypted_password(gw_id)
            if not gw_pw:
                return {"success": False, "message": "비밀번호를 찾을 수 없습니다. /login으로 다시 로그인해주세요."}

            pw = sync_playwright().start()
            try:
                browser, context, page = login_and_get_context(
                    playwright_instance=pw,
                    headless=True,
                    user_id=gw_id,
                    user_pw=gw_pw,
                )
                page.set_viewport_size({"width": 1920, "height": 1080})
                automation = ApprovalAutomation(page, context)
                data = {
                    "work_type": work_type,
                    "work_date": work_date,
                    "start_time": start_time,
                    "end_time": end_time,
                    "hours": hours,
                    "minutes": minutes,
                    "reason": reason,
                    "save_mode": save_mode,
                }
                return automation.create_overtime_request(data)
            finally:
                try:
                    pw.stop()
                except Exception:
                    pass

        future = _executor.submit(_run)
        result = future.result(timeout=180)

        if result.get("success"):
            mode_str = "신청이 완료되었습니다." if save_mode == "submit" else "내용을 확인해주세요."
            time_str = f"\n- 시간: {start_time} ~ {end_time}" if start_time and end_time else ""
            return (
                f"연장근무신청서 {mode_str}\n\n"
                f"- 구분: {work_type}\n"
                f"- 날짜: {work_date}"
                f"{time_str}\n"
                f"- 사유: {reason}"
            )
        else:
            return f"연장근무신청서 작성에 실패했습니다.\n사유: {result.get('message', '알 수 없는 오류')}"

    except concurrent.futures.TimeoutError:
        return "연장근무신청서 처리 시간이 초과되었습니다 (3분). 다시 시도해주세요."
    except Exception as e:
        return f"연장근무신청서 처리 중 오류가 발생했습니다: {str(e)}"


def handle_request_outside_work(params: dict, user_context: dict = None) -> str:
    """외근신청서 작성 처리"""
    work_type = params.get("work_type", "종일외근")
    work_date = params.get("work_date", "")
    destination = params.get("destination", "")
    purpose = params.get("purpose", "")
    transportation = params.get("transportation", "")
    save_mode = params.get("save_mode", "verify")

    if not work_date:
        return "외근 날짜를 알려주세요. (예: 2026-03-25)"
    if not destination:
        return "방문처를 알려주세요."
    if not purpose:
        return "외근 사유(업무내용)를 알려주세요."

    try:
        def _run():
            from playwright.sync_api import sync_playwright
            from src.auth.login import login_and_get_context
            from src.auth.user_db import get_decrypted_password
            from src.approval.approval_automation import ApprovalAutomation

            gw_id = (user_context or {}).get("gw_id")
            if not gw_id:
                return {"success": False, "message": "로그인 정보가 없습니다. 먼저 /login으로 로그인해주세요."}

            gw_pw = get_decrypted_password(gw_id)
            if not gw_pw:
                return {"success": False, "message": "비밀번호를 찾을 수 없습니다. /login으로 다시 로그인해주세요."}

            pw = sync_playwright().start()
            try:
                browser, context, page = login_and_get_context(
                    playwright_instance=pw,
                    headless=True,
                    user_id=gw_id,
                    user_pw=gw_pw,
                )
                page.set_viewport_size({"width": 1920, "height": 1080})
                automation = ApprovalAutomation(page, context)
                data = {
                    "work_type": work_type,
                    "work_date": work_date,
                    "destination": destination,
                    "purpose": purpose,
                    "transportation": transportation,
                    "save_mode": save_mode,
                }
                return automation.create_outside_work_request(data)
            finally:
                try:
                    pw.stop()
                except Exception:
                    pass

        future = _executor.submit(_run)
        result = future.result(timeout=180)

        if result.get("success"):
            mode_str = "신청이 완료되었습니다." if save_mode == "submit" else "내용을 확인해주세요."
            trans_str = f"\n- 교통수단: {transportation}" if transportation else ""
            return (
                f"외근신청서 {mode_str}\n\n"
                f"- 구분: {work_type}\n"
                f"- 날짜: {work_date}\n"
                f"- 방문처: {destination}\n"
                f"- 업무내용: {purpose}"
                f"{trans_str}"
            )
        else:
            return f"외근신청서 작성에 실패했습니다.\n사유: {result.get('message', '알 수 없는 오류')}"

    except concurrent.futures.TimeoutError:
        return "외근신청서 처리 시간이 초과되었습니다 (3분). 다시 시도해주세요."
    except Exception as e:
        return f"외근신청서 처리 중 오류가 발생했습니다: {str(e)}"


# 도구 이름 → 핸들러 매핑

def handle_add_cc_to_approval_doc(params: dict, user_context: dict = None) -> str:
    """
    기결재 문서에 수신참조 추가.
    - doc_ids 제공 시: CcManagerMixin.batch_add_cc() 호출
    - doc_title 제공 시: CcManagerMixin.add_cc_by_title() 호출 (기안문서함에서 제목 검색)

    params:
        doc_ids:   문서 ID 목록 (str 또는 int). doc_title 미제공 시 필수.
        doc_title: 문서 제목 키워드. doc_ids 모를 때 사용.
        cc_name:   추가할 이름
        confirm:   True이면 즉시 실행, 생략/False이면 확인 요청
    """
    doc_ids    = params.get("doc_ids", [])
    doc_title  = params.get("doc_title", "").strip()
    cc_name    = params.get("cc_name", "").strip()
    confirm    = params.get("confirm", False)

    # 필수값 검증: cc_name 필수, doc_ids 또는 doc_title 중 하나 필수
    if not cc_name:
        return "❌ cc_name(추가할 사람 이름)을 입력해주세요."
    if not doc_ids and not doc_title:
        return (
            "❌ 문서를 특정해주세요.\n"
            "- doc_ids: 문서 번호를 알고 있으면 목록으로 입력 (예: [55700, 55654])\n"
            "- doc_title: 문서 제목 키워드로 검색 (예: 'GS-24-0025', '청수당 12월')"
        )

    # ── 확인 메시지 단계 (confirm=False) ──────────────────────────────────────
    if not confirm:
        if doc_title:
            target_desc = f"제목 키워드 '{doc_title}'로 검색된 문서"
        else:
            ids_str = ", ".join(str(d) for d in doc_ids)
            target_desc = f"문서 {ids_str} ({len(doc_ids)}건)"

        return (
            f"📋 **수신참조 추가 확인**\n\n"
            f"- 대상: {target_desc}\n"
            f"- 추가할 사람: **{cc_name}**\n\n"
            f"실행하려면 confirm: true로 다시 요청해주세요."
        )

    # ── 실제 실행 ─────────────────────────────────────────────────────────────
    use_title_search = bool(doc_title) and not doc_ids

    try:
        def _run():
            gw_id = (user_context or {}).get("gw_id")
            if not gw_id:
                return {"success": False, "message": "로그인 정보가 없습니다. 먼저 /login으로 로그인해주세요."}

            user_lock = _get_user_lock(gw_id)
            if not user_lock.acquire(blocking=False):
                return {"success": False, "message": "이전 전자결재 요청이 진행 중입니다. 완료 후 다시 시도해주세요."}
            try:
                from playwright.sync_api import sync_playwright
                from src.auth.login import login_and_get_context, close_session
                from src.auth.user_db import get_decrypted_password
                from src.approval.approval_automation import ApprovalAutomation

                gw_pw = get_decrypted_password(gw_id)
                if not gw_pw:
                    return {"success": False, "message": "비밀번호를 찾을 수 없습니다. /login으로 다시 로그인해주세요."}

                pw = sync_playwright().start()
                try:
                    browser, ctx, page = login_and_get_context(pw, gw_id, gw_pw)
                    auto = ApprovalAutomation(page, ctx)

                    if use_title_search:
                        # 제목 키워드로 검색 후 수신참조 추가
                        result = auto.add_cc_by_title(doc_title, cc_name, context=ctx)
                        return {"success": True, "mode": "title", "result": result}
                    else:
                        # 문서 ID 목록으로 일괄 추가
                        results = auto.batch_add_cc(doc_ids, cc_name, context=ctx)
                        return {"success": True, "mode": "ids", "results": results}
                finally:
                    try:
                        close_session(browser, ctx)
                    except Exception:
                        pass
                    pw.stop()
            finally:
                user_lock.release()

        future = _executor.submit(_run)
        outcome = future.result(timeout=180)  # 제목 검색은 시간이 더 걸릴 수 있음

        if not outcome.get("success"):
            return f"❌ 수신참조 추가 실패: {outcome.get('message', '알 수 없는 오류')}"

        mode = outcome.get("mode")

        # ── 제목 검색 결과 포맷 ────────────────────────────────────────────
        if mode == "title":
            res = outcome.get("result", {})
            if not res.get("success"):
                return f"❌ 제목 검색 실패: {res.get('message', '알 수 없는 오류')}"

            found = res.get("found_count", 0)
            ok_count = res.get("success_count", 0)
            details = res.get("details", [])

            lines = [
                f"✅ 수신참조 추가 완료 — **{cc_name}**",
                f"   검색 키워드: '{doc_title}' | 매칭 {found}건 | 성공 {ok_count}건",
            ]
            for d in details:
                icon = "✓" if d.get("success") else "✗"
                doc_id_str = f"docID {d.get('doc_id', '?')}"
                lines.append(f"  {icon} {doc_id_str}: {d.get('message', '')}")
            return "\n".join(lines)

        # ── doc_ids 결과 포맷 ─────────────────────────────────────────────
        results = outcome.get("results", [])
        ok   = [r for r in results if r["success"]]
        fail = [r for r in results if not r["success"]]

        lines = [f"✅ 수신참조 추가 완료 — **{cc_name}** ({len(ok)}/{len(results)}건 성공)"]
        for r in ok:
            lines.append(f"  • 문서 {r['doc_id']}: {r['message']}")
        if fail:
            lines.append(f"\n⚠️ 실패 {len(fail)}건:")
            for r in fail:
                lines.append(f"  • 문서 {r['doc_id']}: {r['message']}")

        return "\n".join(lines)

    except concurrent.futures.TimeoutError:
        return "⏱️ 수신참조 추가 시간 초과 (180초). 문서 수가 많으면 나눠서 요청해주세요."
    except Exception as e:
        logger.exception("handle_add_cc_to_approval_doc 오류")
        return f"❌ 수신참조 추가 중 오류: {e}"

def handle_analyze_youtube(params: dict, user_context: dict = None) -> str:
    """
    YouTube 영상 또는 재생목록 URL을 Gemini로 분석.
    자막 추출 + Gemini 요약/분석.
    """
    from src.chatbot.youtube_analyzer import (
        analyze_youtube_video, analyze_youtube_playlist, get_video_transcript
    )

    url = params.get("url", "")
    mode = params.get("mode", "summary")       # summary | transcript | playlist
    instruction = params.get("instruction", "")
    limit = int(params.get("limit", 5))

    if not url:
        return "❌ YouTube URL을 입력해주세요."

    # 재생목록인지 단일 영상인지 판단
    is_playlist = 'list=' in url and 'v=' not in url

    try:
        if mode == "transcript":
            future = _executor.submit(get_video_transcript, url)
            return future.result(timeout=60)

        elif is_playlist or mode == "playlist":
            analyze_each = params.get("analyze_each", False)
            instr = instruction or "이 재생목록의 영상들을 주제별로 분류하고 핵심 내용을 한국어로 요약해줘."
            future = _executor.submit(
                analyze_youtube_playlist, url, instr, limit, analyze_each
            )
            return future.result(timeout=120)

        else:
            instr = instruction or "이 유튜브 영상의 핵심 내용을 한국어로 요약해줘. \n주요 포인트를 항목별로 정리하고 실용적인 인사이트를 강조해줘."
            future = _executor.submit(
                analyze_youtube_video, url, instr, True
            )
            return future.result(timeout=90)

    except concurrent.futures.TimeoutError:
        return "⏱️ YouTube 분석 시간 초과. 영상이 너무 길거나 자막이 없을 수 있어요."
    except Exception as e:
        logger.exception("handle_analyze_youtube 오류")
        return f"❌ YouTube 분석 중 오류: {e}"


def handle_get_project_schedule(params: dict, user_context: dict = None) -> str:
    """
    특정 프로젝트의 공정 일정표를 조회하여 스릴 있게 설명합니다.
    group_name 별로 뭔어서, 진행상태와 날짜를 함께 보여줍니다.
    """
    import datetime as _dt
    from src.fund_table.db import list_schedule_items, get_project_overview

    project_name = params.get("project_name", "")
    project, all_projects = _find_project(project_name)
    if not project:
        names = ", ".join(p["name"] for p in all_projects[:10])
        return f"'{project_name}' 프로젝트를 찾을 수 없습니다.\n등록된 프로젝트: {names}"

    pid = project["id"]
    items = list_schedule_items(pid)
    ov = get_project_overview(pid)

    if not items:
        # 기본 일정정보(설계/시공 기간)만이라도 보여줍니다
        lines = [f"📅 **{project['name']}** 일정 요약\n"]
        if ov:
            if ov.get('design_start') or ov.get('design_end'):
                lines.append(f"✏️ 설계 기간: {ov.get('design_start','-')} ~ {ov.get('design_end','-')}")
            if ov.get('construction_start') or ov.get('construction_end'):
                lines.append(f"🔨 시공 기간: {ov.get('construction_start','-')} ~ {ov.get('construction_end','-')}")
            if ov.get('open_date'):
                lines.append(f"🎉 오픈일: {ov['open_date']}")
        if len(lines) == 1:
            return f"'{project['name']}' 프로젝트에 등록된 공정 일정표가 없습니다.\n프로젝트 관리 탭에서 일정표를 먼저 등록해주세요."
        return "\n".join(lines)

    # 상태 한글화
    status_map = {
        "done":     ("✅", "완료"),
        "ongoing":  ("🟡", "진행 중"),
        "planned":  ("⏳", "예정"),
        "delayed":  ("🔴", "지연"),
        "hold":     ("⏸️", "보류"),
    }

    today = _dt.date.today()

    # group_name 별 묶기
    from collections import defaultdict, OrderedDict
    groups: dict[str, list] = OrderedDict()
    no_group: list = []
    for item in items:
        g = item.get("group_name") or ""
        if g:
            groups.setdefault(g, [])
            groups[g].append(item)
        else:
            no_group.append(item)

    lines = [f"📊 **{project['name']}** 공정 일정표"]

    # 기본 일정정보
    if ov:
        parts = []
        if ov.get('design_start'):
            parts.append(f"설계: {ov.get('design_start','')}~{ov.get('design_end','')}")
        if ov.get('construction_start'):
            parts.append(f"시공: {ov.get('construction_start','')}~{ov.get('construction_end','')}")
        if ov.get('open_date'):
            parts.append(f"오픈: {ov['open_date']}")
        if parts:
            lines.append("📆 " + " | ".join(parts))
    lines.append("")

    # 진행중 항목 먼저 하이라이트
    ongoing_items = [it for it in items if it.get("status") == "ongoing"]
    if ongoing_items:
        lines.append("🟡 **현재 진행 중**")
        for it in ongoing_items:
            lines.append(f"  • {it['item_name']}  ({it.get('start_date','')} ~ {it.get('end_date','')})")
        lines.append("")

    # 그룹별 표시
    def _fmt_item(it: dict) -> str:
        icon, label = status_map.get(it.get("status", "planned"), ("□", it.get("status", "")))
        s = it.get("start_date", "")
        e = it.get("end_date", "")
        name = it.get("item_name", "")
        subtitle = it.get("subtitle", "")
        sub_str = f" ({subtitle})" if subtitle else ""
        notes = it.get("notes", "")
        note_str = f" — {notes}" if notes else ""
        # 남은 일수 계산 (planned/ongoing)
        remaining = ""
        if it.get("status") in ("planned", "ongoing") and e:
            try:
                end_d = _dt.date.fromisoformat(e)
                diff = (end_d - today).days
                if diff < 0:
                    remaining = f" [토{abs(diff)}일 지연]"
                elif diff == 0:
                    remaining = " [D-Day]"
                else:
                    remaining = f" [D-{diff}]"
            except Exception:
                pass
        return f"  {icon} {name}{sub_str}  {s}~{e}{remaining}{note_str}"

    for g_name, g_items in groups.items():
        done_cnt = sum(1 for it in g_items if it.get("status") == "done")
        lines.append(f"📁 **{g_name}** ({done_cnt}/{len(g_items)} 완료)")
        for it in g_items:
            lines.append(_fmt_item(it))
        lines.append("")

    if no_group:
        lines.append("**기타**")
        for it in no_group:
            lines.append(_fmt_item(it))
        lines.append("")

    # 완료율 요약
    done_total = sum(1 for it in items if it.get("status") == "done")
    delayed = sum(1 for it in items if it.get("status") == "delayed")
    lines.append(f"---")
    lines.append(f"📊 전체 진행률: {done_total}/{len(items)}건 완료 ({done_total/len(items)*100:.0f}%)")
    if delayed:
        lines.append(f"🔴 지연 항목 {delayed}건 주의 필요")

    return "\n".join(lines)


def handle_get_my_schedule(params: dict, user_context: dict = None) -> str:
    """
    GW 개인 일정 조회.
    오늘부터 N일치 일정을 조회해서 날짜별로 정리.
    (_executor 사용 — asyncio/테레그램 환경에서도 안전)
    """
    import datetime as _dt

    days = int(params.get("days", 7))
    days = min(days, 30)
    start_date = params.get("start_date") or _dt.date.today().strftime("%Y-%m-%d")
    try:
        start = _dt.date.fromisoformat(start_date)
    except Exception:
        start = _dt.date.today()

    try:
        def _run_schedule():
            api, cleanup = _get_api_for_user(user_context)
            try:
                from_dt = start.strftime("%Y%m%d")
                to_dt   = (start + _dt.timedelta(days=days - 1)).strftime("%Y%m%d")

                # GW 개인 일정 API
                result = api.call_api("/schd/api/schd001A01", {
                    "fromYmd": from_dt,
                    "toYmd":   to_dt,
                })
                if not result.get("ok"):
                    result = api.call_api("/schedule/api/schd001A01", {
                        "fromYmd": from_dt,
                        "toYmd":   to_dt,
                    })
                return result
            finally:
                cleanup()

        result = _executor.submit(_run_schedule).result(timeout=60)

        data = result.get("data", {})
        items = (
            data.get("list")
            or data.get("result", {}).get("list")
            or data.get("scheduleList")
            or data.get("data", {}).get("list")
            or []
        )

        if not items:
            return (
                f"{start.strftime('%Y-%m-%d')} ~ "
                f"{(start + _dt.timedelta(days=days-1)).strftime('%Y-%m-%d')} "
                f"기간 동안 등록된 개인 일정이 없습니다.\n"
                "\n💡 GW 캘린더에서 직접 확인하시거나, 회의실 예약 현황은 '회의실 예약 확인해줘'로 물어보세요."
            )

        # 날짜별 그룹화
        from collections import defaultdict
        grouped: dict[str, list] = defaultdict(list)
        for item in items:
            ymd = (
                item.get("startYmd")
                or item.get("schdDt")
                or item.get("fromYmd")
                or ""
            )
            if len(ymd) == 8:
                key = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
            else:
                key = ymd or "날짜 미상"
            grouped[key].append(item)

        lines = [f"📅 개인 일정 ({start.strftime('%Y-%m-%d')} ~ {(start + _dt.timedelta(days=days-1)).strftime('%Y-%m-%d')}, 총 {len(items)}건)\n"]
        weekdays = ["(월)", "(화)", "(수)", "(목)", "(금)", "(토)", "(일)"]
        for date_key in sorted(grouped.keys()):
            try:
                d = _dt.date.fromisoformat(date_key)
                wd = weekdays[d.weekday()]
                date_label = f"{date_key} {wd}"
            except Exception:
                date_label = date_key
            lines.append(f"▸ {date_label}")
            for ev in grouped[date_key]:
                title = (
                    ev.get("title")
                    or ev.get("schdNm")
                    or ev.get("subject")
                    or ev.get("name")
                    or "(제목 없음)"
                )
                s_time = ev.get("startTime") or ev.get("fromTime") or ""
                e_time = ev.get("endTime")   or ev.get("toTime")   or ""
                time_str = f" {s_time}~{e_time}" if s_time else ""
                all_day = ev.get("allDayYn") or ev.get("allDay") or ""
                if str(all_day).upper() in ("Y", "1", "TRUE"):
                    time_str = " [종일]"
                location = ev.get("place") or ev.get("location") or ""
                loc_str = f" 📍{location}" if location else ""
                lines.append(f"  • {title}{time_str}{loc_str}")
            lines.append("")

        return "\n".join(lines).rstrip()

    except Exception as e:
        logger.exception("handle_get_my_schedule 오류")
        return f"일정 조회 중 오류가 발생했습니다: {e}"


TOOL_HANDLERS = {
    "reserve_meeting_room": handle_reserve_meeting_room,
    "check_reservation_status": handle_check_reservation_status,
    "check_available_rooms": handle_check_available_rooms,
    "cancel_meeting_reservation": handle_cancel_meeting_reservation,
    "list_my_reservations": handle_list_my_reservations,
    "cleanup_test_reservations": handle_cleanup_test_reservations,
    "submit_expense_approval": handle_submit_expense_approval,
    "submit_draft_approval": handle_submit_draft_approval,
    "submit_approval_form": handle_submit_approval_form,
    "search_project_code": handle_search_project_code,
    "start_approval_wizard": handle_start_approval_wizard_fn,
    "start_contract_wizard": handle_start_contract_wizard_fn,
    "generate_contracts_from_file": handle_generate_contracts_from_file,
    "get_mail_summary": handle_get_mail_summary,
    "transcribe_audio": handle_transcribe_audio,
    "get_fund_summary": handle_get_fund_summary,
    "update_project_info": handle_update_project_info,
    "add_project_note": handle_add_project_note,
    "add_project_subcontract": handle_add_project_subcontract,
    "update_collection_status": handle_update_collection_status,
    "add_project_todo": handle_add_project_todo,
    "get_project_detail": handle_get_project_detail,
    "add_project_contact": handle_add_project_contact,
    "get_overdue_items": handle_get_overdue_items,
    "compare_projects": handle_compare_projects,
    "generate_project_report": handle_generate_project_report,
    "update_project_milestone": handle_update_project_milestone,
    "add_cc_to_approval_doc": handle_add_cc_to_approval_doc,
    "get_my_schedule": handle_get_my_schedule,
    "get_project_schedule": handle_get_project_schedule,
    "analyze_youtube": handle_analyze_youtube,
    "request_annual_leave": handle_request_annual_leave,
    "request_overtime": handle_request_overtime,
    "request_outside_work": handle_request_outside_work,
}
