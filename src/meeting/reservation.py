"""
Task #6: 회의실 예약 자동화
- 그룹웨어 회의실 예약 페이지 진입
- 회의실 목록 조회
- 날짜/시간대별 예약 현황 조회
- 빈 시간대 검색
- 회의실 예약 등록
- 네트워크 인터셉트로 API 패턴 캡처
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from playwright.sync_api import Page

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.auth.login import login_and_get_context, close_session, GW_URL, DATA_DIR

logger = logging.getLogger("meeting")

# 캡처된 API 응답 저장용
_captured_apis = []


def _setup_network_intercept(page: Page):
    """회의실 관련 네트워크 응답 캡처"""
    def handle_response(response):
        url = response.url.lower()
        # 회의실/예약 관련 API 응답 캡처
        keywords = [
            "room", "meeting", "reserve", "reservation",
            "facility", "schedule", "calendar", "booking",
            "resource", "space",
        ]
        if any(kw in url for kw in keywords):
            try:
                body = response.json()
                _captured_apis.append({
                    "url": response.url,
                    "status": response.status,
                    "data": body,
                    "timestamp": datetime.now().isoformat(),
                })
                logger.info(f"API 캡처: {response.url[:120]}")
            except Exception:
                pass

    page.on("response", handle_response)


def _save_captured_apis():
    """캡처된 API 데이터를 파일로 저장"""
    if _captured_apis:
        DATA_DIR.mkdir(exist_ok=True)
        api_file = DATA_DIR / "meeting_apis.json"
        api_file.write_text(
            json.dumps(_captured_apis, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"캡처된 회의실 API {len(_captured_apis)}개 저장: {api_file}")


def navigate_to_meeting_room(page: Page):
    """회의실 예약 페이지로 이동"""
    logger.info("회의실 예약 메뉴 진입 중...")

    # 메뉴 클릭 시도
    menu_selectors = [
        'a:has-text("회의실")',
        'span:has-text("회의실")',
        'a:has-text("자원예약")',
        'span:has-text("자원예약")',
        'a:has-text("시설예약")',
        'span:has-text("시설예약")',
        '[data-menu*="room"]',
        '[data-menu*="meeting"]',
        '[data-menu*="resource"]',
        '[data-menu*="facility"]',
        '[href*="room"]',
        '[href*="meeting"]',
        '[href*="resource"]',
        '[href*="facility"]',
        '.menu-item:has-text("회의실")',
        '.menu-item:has-text("자원예약")',
        'li:has-text("회의실")',
        'li:has-text("자원예약")',
    ]

    for sel in menu_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                page.wait_for_timeout(3000)
                logger.info(f"회의실 메뉴 클릭: {sel}")
                return True
        except Exception:
            continue

    # URL 직접 이동 시도
    room_urls = [
        f"{GW_URL}/#/resource",
        f"{GW_URL}/#/meeting",
        f"{GW_URL}/#/room",
        f"{GW_URL}/#/facility",
        f"{GW_URL}/#/app/resource",
        f"{GW_URL}/#/app/meeting",
        f"{GW_URL}/#/reservation",
    ]
    for url in room_urls:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(3000)
            current = page.url.lower()
            if any(kw in current for kw in ["resource", "meeting", "room", "facility", "reservation"]):
                logger.info(f"URL로 회의실 페이지 진입: {url}")
                return True
        except Exception:
            continue

    # 실패 시 스크린샷 저장
    DATA_DIR.mkdir(exist_ok=True)
    page.screenshot(path=str(DATA_DIR / "meeting_nav_failed.png"))
    logger.warning("회의실 메뉴 진입 실패 - 스크린샷 확인 필요: data/meeting_nav_failed.png")
    return False


def get_meeting_rooms(page: Page) -> list[dict]:
    """
    회의실 목록 조회.
    반환: [{"name": "3층 대회의실", "id": "...", "location": "...", ...}, ...]
    """
    rooms = []
    logger.info("회의실 목록 조회 중...")

    # 회의실 목록 요소 추출
    room_selectors = [
        ".room-item",
        ".resource-item",
        ".facility-item",
        "[class*='room'] li",
        "[class*='resource'] li",
        "table tbody tr",
        ".list-item",
        ".room-name",
        "[class*='meeting-room']",
        ".lnb li",  # 좌측 네비게이션 회의실 목록
        ".tree-node",
        "[role='treeitem']",
    ]

    for sel in room_selectors:
        try:
            elements = page.locator(sel).all()
            if not elements:
                continue

            for el in elements:
                try:
                    text = el.inner_text(timeout=2000).strip()
                    if not text or len(text) > 200:
                        continue

                    room_id = el.get_attribute("data-id") or el.get_attribute("data-key") or ""
                    room = {
                        "name": text.split("\n")[0].strip(),
                        "id": room_id,
                        "raw_text": text,
                    }
                    # 중복 방지
                    if room["name"] and not any(r["name"] == room["name"] for r in rooms):
                        rooms.append(room)
                except Exception:
                    continue

            if rooms:
                logger.info(f"회의실 {len(rooms)}개 발견 (셀렉터: {sel})")
                break
        except Exception:
            continue

    # API 캡처에서 회의실 목록 추출 시도
    if not rooms:
        rooms = _extract_rooms_from_api()

    if not rooms:
        page.screenshot(path=str(DATA_DIR / "meeting_rooms_empty.png"))
        logger.warning("회의실 목록을 찾지 못했습니다 - 스크린샷 확인 필요")

    # 결과 저장
    if rooms:
        DATA_DIR.mkdir(exist_ok=True)
        rooms_file = DATA_DIR / "meeting_rooms.json"
        rooms_file.write_text(
            json.dumps(rooms, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"회의실 목록 저장: {rooms_file}")

    return rooms


def _extract_rooms_from_api() -> list[dict]:
    """캡처된 API에서 회의실 목록 추출"""
    rooms = []
    for api in _captured_apis:
        data = api.get("data", {})
        # 다양한 API 구조 대응
        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for key in ["data", "list", "items", "rooms", "resources", "result"]:
                if key in data:
                    val = data[key]
                    if isinstance(val, list):
                        items = val
                        break

        for item in items:
            if isinstance(item, dict):
                name = (
                    item.get("name") or item.get("roomName") or
                    item.get("resourceName") or item.get("facilityName") or
                    item.get("title") or ""
                )
                if name:
                    rooms.append({
                        "name": name,
                        "id": str(item.get("id", item.get("roomId", item.get("resourceId", "")))),
                        "location": item.get("location", item.get("floor", "")),
                        "capacity": item.get("capacity", item.get("maxPeople", "")),
                        "raw": item,
                    })

    if rooms:
        logger.info(f"API에서 회의실 {len(rooms)}개 추출")
    return rooms


def get_reservations(page: Page, date: str = None) -> list[dict]:
    """
    특정 날짜의 예약 현황 조회.
    date: "YYYY-MM-DD" 형식. None이면 오늘.
    반환: [{"room": "...", "start": "09:00", "end": "10:00", "title": "...", "booker": "..."}, ...]
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    reservations = []
    logger.info(f"예약 현황 조회: {date}")

    # 날짜 선택
    _select_date(page, date)

    # 예약 현황 추출 - 테이블/캘린더/타임라인 등 다양한 UI 대응
    reservation_selectors = [
        ".reservation-item",
        ".schedule-item",
        ".event-item",
        ".booking-item",
        "[class*='event']",
        "[class*='schedule']",
        "[class*='reservation']",
        "table tbody tr",
        ".calendar-event",
        ".timeline-event",
    ]

    for sel in reservation_selectors:
        try:
            elements = page.locator(sel).all()
            if not elements:
                continue

            for el in elements:
                try:
                    text = el.inner_text(timeout=2000).strip()
                    if not text:
                        continue

                    reservation = _parse_reservation(text, el)
                    if reservation:
                        reservations.append(reservation)
                except Exception:
                    continue

            if reservations:
                logger.info(f"예약 {len(reservations)}건 발견 (셀렉터: {sel})")
                break
        except Exception:
            continue

    # API 캡처에서 예약 현황 추출
    if not reservations:
        reservations = _extract_reservations_from_api(date)

    # 결과 저장
    DATA_DIR.mkdir(exist_ok=True)
    res_file = DATA_DIR / f"reservations_{date}.json"
    res_file.write_text(
        json.dumps(reservations, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"예약 현황 저장: {res_file} ({len(reservations)}건)")

    return reservations


def _select_date(page: Page, date: str):
    """날짜 선택"""
    # 날짜 입력 필드 찾기
    date_selectors = [
        'input[type="date"]',
        'input[name*="date"]',
        'input[placeholder*="날짜"]',
        'input[placeholder*="YYYY"]',
        '.date-picker input',
        '.datepicker input',
        '[class*="date"] input',
    ]

    for sel in date_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.fill(date)
                el.press("Enter")
                page.wait_for_timeout(2000)
                logger.info(f"날짜 입력: {date} (셀렉터: {sel})")
                return
        except Exception:
            continue

    # 캘린더 네비게이션으로 날짜 이동
    try:
        target = datetime.strptime(date, "%Y-%m-%d")
        day_str = str(target.day)
        day_selectors = [
            f'td:has-text("{day_str}")',
            f'[data-date="{date}"]',
            f'button:has-text("{day_str}")',
            f'.day:has-text("{day_str}")',
        ]
        for sel in day_selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=1000):
                    el.click()
                    page.wait_for_timeout(2000)
                    logger.info(f"캘린더에서 날짜 클릭: {date}")
                    return
            except Exception:
                continue
    except Exception:
        pass

    logger.info(f"날짜 선택 UI를 찾지 못함 - 현재 날짜 기준으로 진행")


def _parse_reservation(text: str, element=None) -> dict | None:
    """예약 텍스트를 딕셔너리로 파싱"""
    if not text or len(text) < 3:
        return None

    parts = [p.strip() for p in text.replace("\t", "\n").split("\n") if p.strip()]
    if not parts:
        return None

    reservation = {"raw_text": text}

    for part in parts:
        # 시간 패턴: "09:00", "09:00~10:00", "09:00-10:00"
        if ":" in part and any(c.isdigit() for c in part):
            time_part = part
            if "~" in time_part or "-" in time_part:
                sep = "~" if "~" in time_part else "-"
                times = time_part.split(sep)
                if len(times) == 2:
                    reservation["start_time"] = times[0].strip()
                    reservation["end_time"] = times[1].strip()
            else:
                reservation.setdefault("start_time", part)
        # 긴 텍스트는 제목
        elif len(part) > 3 and "title" not in reservation:
            reservation["title"] = part
        # 짧은 텍스트는 예약자
        elif len(part) <= 10 and "booker" not in reservation and part != reservation.get("title"):
            reservation.setdefault("booker", part)

    return reservation if "title" in reservation or "start_time" in reservation else None


def _extract_reservations_from_api(date: str) -> list[dict]:
    """캡처된 API에서 예약 현황 추출"""
    reservations = []
    for api in _captured_apis:
        data = api.get("data", {})
        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for key in ["data", "list", "items", "schedules", "reservations", "events", "result"]:
                if key in data:
                    val = data[key]
                    if isinstance(val, list):
                        items = val
                        break

        for item in items:
            if isinstance(item, dict):
                # 날짜 필터
                item_date = (
                    item.get("date") or item.get("startDate") or
                    item.get("reserveDate") or ""
                )
                if date and item_date and date not in str(item_date):
                    continue

                title = (
                    item.get("title") or item.get("subject") or
                    item.get("meetingTitle") or item.get("name") or ""
                )
                reservations.append({
                    "room": item.get("roomName", item.get("resourceName", "")),
                    "title": title,
                    "start_time": item.get("startTime", item.get("beginTime", "")),
                    "end_time": item.get("endTime", item.get("finishTime", "")),
                    "booker": item.get("booker", item.get("userName", item.get("creator", ""))),
                    "date": str(item_date),
                    "raw": item,
                })

    if reservations:
        logger.info(f"API에서 예약 {len(reservations)}건 추출")
    return reservations


def find_available_slots(
    page: Page,
    date: str = None,
    room_name: str = None,
    duration_minutes: int = 60,
) -> list[dict]:
    """
    빈 시간대 검색.
    date: "YYYY-MM-DD" (None이면 오늘)
    room_name: 특정 회의실 (None이면 전체)
    duration_minutes: 필요한 시간 (분)
    반환: [{"room": "...", "start": "09:00", "end": "10:00"}, ...]
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"빈 시간대 검색: {date}, 회의실={room_name or '전체'}, {duration_minutes}분")

    # 예약 현황 조회
    reservations = get_reservations(page, date)

    # 회의실 목록
    rooms = get_meeting_rooms(page)
    if room_name:
        rooms = [r for r in rooms if room_name in r.get("name", "")]

    # 업무 시간 기준 (09:00 ~ 18:00)
    work_start = 9 * 60   # 분 단위
    work_end = 18 * 60

    available = []

    for room in rooms:
        rname = room.get("name", "")

        # 해당 회의실의 예약 시간대 수집
        room_reservations = [
            r for r in reservations
            if rname in r.get("room", "") or rname in r.get("raw_text", "")
        ]

        # 예약 시간대를 분 단위로 변환
        busy_slots = []
        for res in room_reservations:
            start = _time_to_minutes(res.get("start_time", ""))
            end = _time_to_minutes(res.get("end_time", ""))
            if start is not None and end is not None:
                busy_slots.append((start, end))

        busy_slots.sort()

        # 빈 시간대 찾기
        current = work_start
        for busy_start, busy_end in busy_slots:
            if current + duration_minutes <= busy_start:
                available.append({
                    "room": rname,
                    "date": date,
                    "start_time": _minutes_to_time(current),
                    "end_time": _minutes_to_time(current + duration_minutes),
                })
            current = max(current, busy_end)

        # 마지막 예약 이후 ~ 업무 종료
        if current + duration_minutes <= work_end:
            available.append({
                "room": rname,
                "date": date,
                "start_time": _minutes_to_time(current),
                "end_time": _minutes_to_time(current + duration_minutes),
            })

    logger.info(f"빈 시간대 {len(available)}건 발견")

    # 결과 저장
    DATA_DIR.mkdir(exist_ok=True)
    avail_file = DATA_DIR / f"available_slots_{date}.json"
    avail_file.write_text(
        json.dumps(available, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return available


def _time_to_minutes(time_str: str) -> int | None:
    """시간 문자열을 분 단위로 변환: "09:30" → 570"""
    if not time_str:
        return None
    try:
        parts = time_str.strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return None


def _minutes_to_time(minutes: int) -> str:
    """분 단위를 시간 문자열로 변환: 570 → "09:30" """
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def make_reservation(
    page: Page,
    room_name: str,
    date: str,
    start_time: str,
    end_time: str,
    title: str,
    description: str = "",
) -> bool:
    """
    회의실 예약 등록.
    room_name: 회의실 이름 (예: "3층 대회의실")
    date: "YYYY-MM-DD"
    start_time: "HH:MM"
    end_time: "HH:MM"
    title: 회의 제목
    description: 회의 설명 (선택)
    반환: 성공 여부
    """
    logger.info(f"예약 등록: {room_name} / {date} {start_time}~{end_time} / {title}")

    # 예약 등록 버튼 클릭
    register_selectors = [
        'button:has-text("예약")',
        'button:has-text("등록")',
        'button:has-text("신규")',
        'a:has-text("예약하기")',
        'a:has-text("예약 등록")',
        'button:has-text("+")',
        '[class*="add"]',
        '[class*="register"]',
        '[class*="create"]',
        'button:has-text("새 예약")',
    ]

    clicked = False
    for sel in register_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                page.wait_for_timeout(2000)
                logger.info(f"예약 등록 버튼 클릭: {sel}")
                clicked = True
                break
        except Exception:
            continue

    if not clicked:
        logger.warning("예약 등록 버튼을 찾지 못했습니다")
        page.screenshot(path=str(DATA_DIR / "meeting_register_btn_failed.png"))
        return False

    # 회의실 선택
    _select_room(page, room_name)

    # 날짜 입력
    _fill_date(page, date)

    # 시간 입력
    _fill_time(page, start_time, end_time)

    # 제목 입력
    _fill_title(page, title)

    # 설명 입력
    if description:
        _fill_description(page, description)

    # 예약 저장(제출)
    success = _submit_reservation(page)

    if success:
        logger.info("예약 등록 성공!")
    else:
        logger.warning("예약 등록 실패 - 스크린샷 확인 필요")
        page.screenshot(path=str(DATA_DIR / "meeting_submit_failed.png"))

    return success


def _select_room(page: Page, room_name: str):
    """예약 폼에서 회의실 선택"""
    # 회의실 선택 드롭다운/셀렉트
    select_selectors = [
        'select[name*="room"]',
        'select[name*="resource"]',
        'select[name*="facility"]',
        '[class*="room"] select',
        '[class*="resource"] select',
    ]

    for sel in select_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.select_option(label=room_name)
                page.wait_for_timeout(1000)
                logger.info(f"회의실 선택 (select): {room_name}")
                return
        except Exception:
            continue

    # 텍스트 입력 + 검색 방식
    input_selectors = [
        'input[name*="room"]',
        'input[name*="resource"]',
        'input[placeholder*="회의실"]',
        'input[placeholder*="자원"]',
        '[class*="room"] input',
    ]

    for sel in input_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.fill(room_name)
                page.wait_for_timeout(1000)
                # 자동완성 드롭다운에서 선택
                try:
                    option = page.locator(f'li:has-text("{room_name}"), .option:has-text("{room_name}")').first
                    if option.is_visible(timeout=2000):
                        option.click()
                        page.wait_for_timeout(500)
                except Exception:
                    pass
                logger.info(f"회의실 입력: {room_name}")
                return
        except Exception:
            continue

    # 목록에서 클릭 선택
    try:
        room_el = page.locator(f'text="{room_name}"').first
        if room_el.is_visible(timeout=2000):
            room_el.click()
            page.wait_for_timeout(1000)
            logger.info(f"회의실 클릭 선택: {room_name}")
            return
    except Exception:
        pass

    logger.warning(f"회의실 선택 실패: {room_name}")


def _fill_date(page: Page, date: str):
    """예약 폼에서 날짜 입력"""
    date_selectors = [
        'input[type="date"]',
        'input[name*="date"]',
        'input[name*="Date"]',
        'input[placeholder*="날짜"]',
        'input[placeholder*="YYYY"]',
        '.date-picker input',
        '.datepicker input',
    ]

    for sel in date_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.fill(date)
                page.wait_for_timeout(500)
                logger.info(f"날짜 입력: {date}")
                return
        except Exception:
            continue

    logger.info("날짜 입력 필드를 찾지 못함 - 기본값 사용")


def _fill_time(page: Page, start_time: str, end_time: str):
    """예약 폼에서 시간 입력"""
    # 시작 시간
    start_selectors = [
        'input[name*="start"]',
        'input[name*="Start"]',
        'input[name*="begin"]',
        'select[name*="start"]',
        'select[name*="Start"]',
        'input[type="time"]:first-of-type',
        '[class*="start"] input',
        '[class*="start"] select',
    ]

    for sel in start_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                tag = el.evaluate("el => el.tagName.toLowerCase()")
                if tag == "select":
                    el.select_option(label=start_time)
                else:
                    el.fill(start_time)
                page.wait_for_timeout(500)
                logger.info(f"시작 시간 입력: {start_time}")
                break
        except Exception:
            continue

    # 종료 시간
    end_selectors = [
        'input[name*="end"]',
        'input[name*="End"]',
        'input[name*="finish"]',
        'select[name*="end"]',
        'select[name*="End"]',
        'input[type="time"]:last-of-type',
        '[class*="end"] input',
        '[class*="end"] select',
    ]

    for sel in end_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                tag = el.evaluate("el => el.tagName.toLowerCase()")
                if tag == "select":
                    el.select_option(label=end_time)
                else:
                    el.fill(end_time)
                page.wait_for_timeout(500)
                logger.info(f"종료 시간 입력: {end_time}")
                break
        except Exception:
            continue


def _fill_title(page: Page, title: str):
    """예약 폼에서 제목 입력"""
    title_selectors = [
        'input[name*="title"]',
        'input[name*="Title"]',
        'input[name*="subject"]',
        'input[name*="Subject"]',
        'input[placeholder*="제목"]',
        'input[placeholder*="회의"]',
        'input[placeholder*="이름"]',
        '[class*="title"] input',
        '[class*="subject"] input',
    ]

    for sel in title_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.fill(title)
                page.wait_for_timeout(500)
                logger.info(f"제목 입력: {title}")
                return
        except Exception:
            continue

    logger.warning("제목 입력 필드를 찾지 못함")


def _fill_description(page: Page, description: str):
    """예약 폼에서 설명 입력"""
    desc_selectors = [
        'textarea[name*="desc"]',
        'textarea[name*="content"]',
        'textarea[name*="memo"]',
        'textarea[name*="note"]',
        'textarea',
        '[class*="desc"] textarea',
        '[class*="content"] textarea',
        '[contenteditable="true"]',
    ]

    for sel in desc_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.fill(description)
                page.wait_for_timeout(500)
                logger.info("설명 입력 완료")
                return
        except Exception:
            continue


def _submit_reservation(page: Page) -> bool:
    """예약 폼 제출(저장)"""
    submit_selectors = [
        'button:has-text("저장")',
        'button:has-text("확인")',
        'button:has-text("등록")',
        'button:has-text("예약")',
        'button[type="submit"]',
        'button:has-text("Save")',
        'button:has-text("OK")',
        'a:has-text("저장")',
        'a:has-text("확인")',
        '.btn-save',
        '.btn-submit',
        '.btn-confirm',
    ]

    for sel in submit_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                page.wait_for_timeout(3000)
                logger.info(f"예약 제출: {sel}")

                # 성공 확인 - 알림/토스트 메시지 확인
                success_indicators = [
                    'text="성공"',
                    'text="완료"',
                    'text="등록되었습니다"',
                    'text="예약되었습니다"',
                    '.toast-success',
                    '.alert-success',
                    '[class*="success"]',
                ]
                for indicator in success_indicators:
                    try:
                        if page.locator(indicator).first.is_visible(timeout=2000):
                            return True
                    except Exception:
                        continue

                # 에러 메시지 확인
                error_indicators = [
                    'text="실패"',
                    'text="오류"',
                    'text="중복"',
                    'text="이미 예약"',
                    '.toast-error',
                    '.alert-error',
                    '[class*="error"]',
                ]
                for indicator in error_indicators:
                    try:
                        if page.locator(indicator).first.is_visible(timeout=1000):
                            error_text = page.locator(indicator).first.inner_text(timeout=1000)
                            logger.error(f"예약 실패 메시지: {error_text}")
                            return False
                    except Exception:
                        continue

                # 명확한 성공/실패 신호 없으면 일단 성공으로 판단
                return True
        except Exception:
            continue

    logger.warning("제출 버튼을 찾지 못했습니다")
    return False


def run():
    """회의실 예약 자동화 메인 실행 (테스트용)"""
    logger.info("=" * 50)
    logger.info("Task #6: 회의실 예약 자동화 시작")
    logger.info("=" * 50)

    browser, context, page = login_and_get_context(headless=False)

    try:
        # 네트워크 인터셉트 설정
        _setup_network_intercept(page)

        # 1. 회의실 예약 페이지 이동
        if not navigate_to_meeting_room(page):
            logger.error("회의실 페이지 진입 실패")
            return

        # 2. 회의실 목록 조회
        rooms = get_meeting_rooms(page)
        logger.info(f"회의실 목록: {[r['name'] for r in rooms]}")

        # 3. 오늘 예약 현황 조회
        today = datetime.now().strftime("%Y-%m-%d")
        reservations = get_reservations(page, today)
        logger.info(f"오늘 예약: {len(reservations)}건")

        # 4. 빈 시간대 검색
        available = find_available_slots(page, today)
        logger.info(f"빈 시간대: {len(available)}건")
        for slot in available:
            logger.info(f"  - {slot['room']}: {slot['start_time']}~{slot['end_time']}")

        # API 캡처 저장
        _save_captured_apis()

    finally:
        close_session(browser)

    logger.info("Task #6 완료")


if __name__ == "__main__":
    run()
