"""
회의실 예약 모듈 (API 기반) - MeetingRoomAPI 클래스
- httpx + wehago-sign HMAC-SHA256 직접 서명 방식
- Playwright는 로그인 + 쿠키 추출에만 사용, API 호출은 httpx
- wehago-sign = Base64(HMAC-SHA256(signKey, oAuthToken + transactionId + timestamp + pathname))
"""

import hmac
import hashlib
import base64
import json
import logging
import datetime
import time
import urllib.parse
from uuid import uuid4
from pathlib import Path

import httpx

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.auth.login import GW_URL, DATA_DIR

logger = logging.getLogger("meeting_api")

# API 기본 URL
API_BASE_URL = GW_URL  # https://gw.glowseoul.co.kr


class MeetingRoomAPI:
    """
    그룹웨어 회의실 예약 API 클래스.
    httpx로 rs121A API 직접 호출 + wehago-sign HMAC 서명 생성.
    """

    # 기본 companyInfo (하위 호환용 - 기존 단일 사용자)
    DEFAULT_COMPANY_INFO = {
        "compSeq": "1000",
        "groupSeq": "gcmsAmaranth36068",
        "deptSeq": "2017",
        "emailAddr": "tgjeon",
        "emailDomain": "glowseoul.co.kr",
        "empSeq": "2922",
    }

    # 하위 호환: 기존 코드에서 COMPANY_INFO 참조하는 경우
    COMPANY_INFO = DEFAULT_COMPANY_INFO

    # 회의실 resSeq 매핑 (rs121A01로 확인된 값)
    ROOM_MAP = {
        "1번 회의실": {"resSeq": "45", "resName": "1번 회의실"},
        "2번 회의실": {"resSeq": "46", "resName": "2번 회의실"},
        "3번 회의실": {"resSeq": "47", "resName": "3번 회의실"},
        "4번 회의실": {"resSeq": "48", "resName": "4번 회의실"},
        "5번 회의실": {"resSeq": "49", "resName": "5번 회의실"},
    }

    # 업무 시간 (분 단위)
    WORK_START = 9 * 60   # 09:00
    WORK_END   = 18 * 60  # 18:00

    def __init__(self, oauth_token: str, sign_key: str, cookies: dict = None, company_info: dict = None):
        """
        oauth_token: oAuthToken 쿠키값 (URL 인코딩 포함 가능)
        sign_key: signKey 쿠키값
        cookies: 전체 쿠키 딕셔너리 (httpx 요청에 포함)
        company_info: 사용자별 회사정보 (None이면 DEFAULT_COMPANY_INFO 사용)
        """
        self.oauth_token = urllib.parse.unquote(oauth_token)
        self.sign_key = sign_key
        self.cookies = cookies or {}
        # 사용자별 companyInfo (다중 사용자 지원)
        if company_info:
            self.company_info = company_info
        else:
            self.company_info = self.DEFAULT_COMPANY_INFO.copy()
        self.client = httpx.Client(
            base_url=API_BASE_URL,
            cookies=self.cookies,
            timeout=30.0,
            verify=False,  # 사내 SSL 인증서 이슈 대비
        )

    def close(self):
        """httpx 클라이언트 종료"""
        self.client.close()

    # ─────────────────────────────────────────
    # wehago-sign 서명 생성
    # ─────────────────────────────────────────

    def _generate_sign_headers(self, pathname: str) -> dict:
        """
        wehago-sign 인증 헤더 생성.
        공식: Base64(HMAC-SHA256(signKey, oAuthToken + transactionId + timestamp + pathname))
        13/13 실제 캡처 샘플 검증 완료.
        """
        transaction_id = uuid4().hex  # 32자 소문자 hex
        timestamp = str(int(time.time()))  # Unix 초

        message = self.oauth_token + transaction_id + timestamp + pathname
        signature = base64.b64encode(
            hmac.new(
                self.sign_key.encode("utf-8"),
                message.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode()

        return {
            "authorization": f"Bearer {self.oauth_token}",
            "transaction-id": transaction_id,
            "timestamp": timestamp,
            "wehago-sign": signature,
            "Content-Type": "application/json;charset=UTF-8",
        }

    # ─────────────────────────────────────────
    # 내부 유틸 메서드
    # ─────────────────────────────────────────

    def call_api(self, endpoint: str, body: dict) -> dict:
        """
        httpx로 rs121A API 직접 호출.
        wehago-sign 헤더를 자동 생성하여 첨부.

        반환: {"status": int, "ok": bool, "data": dict} 또는 {"error": str}
        """
        headers = self._generate_sign_headers(endpoint)

        try:
            response = self.client.post(endpoint, json=body, headers=headers)
            try:
                data = response.json()
            except Exception:
                data = {"raw_text": response.text[:500]}

            result = {
                "status": response.status_code,
                "ok": response.is_success,
                "data": data,
            }
        except Exception as e:
            logger.error(f"API 호출 실패 [{endpoint}]: {e}")
            return {"status": 0, "ok": False, "error": str(e)}

        if not result["ok"]:
            rc = data.get("resultCode", "N/A") if isinstance(data, dict) else "N/A"
            msg = data.get("resultMsg", "") if isinstance(data, dict) else ""
            logger.warning(
                f"API 응답 실패 [{endpoint}]: HTTP {result['status']}, "
                f"resultCode={rc}, msg={msg}"
            )
        else:
            rc = data.get("resultCode", "N/A") if isinstance(data, dict) else "N/A"
            logger.info(f"API 성공 [{endpoint}]: resultCode={rc}")

        return result

    def _find_room(self, room_name: str) -> dict | None:
        """
        회의실 이름으로 {resSeq, resName} 조회. 부분 일치 허용.
        숫자만 입력해도 인식 (예: "1" → 1번 회의실).
        """
        for key, info in self.ROOM_MAP.items():
            if room_name == key or room_name in key or key in room_name:
                return info
        if room_name.strip().isdigit():
            num = int(room_name.strip())
            if 1 <= num <= 5:
                key = f"{num}번 회의실"
                return self.ROOM_MAP[key]
        return None

    @staticmethod
    def _to_yyyymmdd(date_str: str) -> str:
        """날짜를 YYYYMMDD 형식으로 변환."""
        return date_str.replace("-", "")

    @staticmethod
    def _to_hhmm(time_str: str) -> str:
        """시간을 HHmm 형식으로 변환."""
        return time_str.replace(":", "")

    @staticmethod
    def _to_minutes(time_str: str) -> int | None:
        """시간 문자열을 분 단위로 변환. "09:30" → 570."""
        if not time_str:
            return None
        try:
            cleaned = time_str.replace(":", "").strip()
            if len(cleaned) >= 4:
                return int(cleaned[:2]) * 60 + int(cleaned[2:4])
        except (ValueError, IndexError):
            pass
        return None

    @staticmethod
    def _from_minutes(minutes: int) -> str:
        """분 단위를 시간 문자열로 변환. 570 → "09:30"."""
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    # ─────────────────────────────────────────
    # 공개 메서드
    # ─────────────────────────────────────────

    def get_rooms(self) -> list[dict]:
        """
        회의실 목록 조회 (rs121A01).
        반환: [{"resSeq": "45", "resName": "1번 회의실", "attrSeq": "2", ...}, ...]
        """
        logger.info("회의실 목록 조회 (rs121A01)...")
        body = {
            "companyInfo": self.company_info,
            "langCode": "kr",
            "searchText": "",
            "attrUseYn": "",
            "attrList": ["2", "4", "3", "8", "5", "ETC"],
            "propList": []
        }
        result = self.call_api("/schres/rs121A01", body)

        rooms = []
        raw_data = result.get("data", {})
        result_data = (
            raw_data.get("resultData", {}).get("resultList", [])
            if isinstance(raw_data.get("resultData"), dict)
            else raw_data.get("resultData", [])
        )

        if isinstance(result_data, list) and result_data:
            for item in result_data:
                if str(item.get("attrSeq", "")) == "2":
                    rooms.append({
                        "resSeq": str(item.get("resSeq", "")),
                        "resName": item.get("resName", item.get("resNm", "")),
                        "attrSeq": str(item.get("attrSeq", "")),
                        "location": item.get("dpropNm", item.get("location", "")),
                        "color": item.get("color", ""),
                        "raw": item
                    })
        else:
            logger.warning("rs121A01 결과 없음 - 로컬 매핑 사용")
            rooms = [
                {"resSeq": v["resSeq"], "resName": v["resName"], "attrSeq": "2"}
                for v in self.ROOM_MAP.values()
            ]

        logger.info(f"회의실 {len(rooms)}개 조회 완료")

        DATA_DIR.mkdir(exist_ok=True)
        (DATA_DIR / "meeting_rooms_api.json").write_text(
            json.dumps(rooms, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return rooms

    def get_reservations(self, date: str = None) -> list[dict]:
        """
        특정 날짜의 예약 현황 조회 (rs121A05).
        date: "YYYY-MM-DD" 또는 "YYYYMMDD". None이면 오늘.
        """
        if date is None:
            date = datetime.date.today().strftime("%Y-%m-%d")

        date_str = self._to_yyyymmdd(date)
        logger.info(f"예약 현황 조회 (rs121A05): {date_str}")

        body = {
            "companyInfo": self.company_info,
            "langCode": "kr",
            "startDate": date_str,
            "endDate": date_str,
            "statusType": ["10", "20"],
            "statusCode": "",
            "menuAuth": "USER",
            "resList": [{"resSeq": v["resSeq"]} for v in self.ROOM_MAP.values()]
        }
        result = self.call_api("/schres/rs121A05", body)

        reservations = []
        raw_data = result.get("data", {})
        rd = raw_data.get("resultData", [])
        if isinstance(rd, dict):
            result_data = rd.get("resultList", [])
        else:
            result_data = rd if isinstance(rd, list) else []

        if isinstance(result_data, list):
            for item in result_data:
                s_raw = str(item.get("resStartDate", item.get("startDate", "")))
                e_raw = str(item.get("resEndDate",   item.get("endDate",   "")))
                if len(s_raw) >= 12 and s_raw[:4].isdigit() and "-" not in s_raw:
                    start_time = f"{s_raw[8:10]}:{s_raw[10:12]}"
                elif " " in s_raw:
                    start_time = s_raw[11:16]
                else:
                    start_time = ""
                if len(e_raw) >= 12 and e_raw[:4].isdigit() and "-" not in e_raw:
                    end_time = f"{e_raw[8:10]}:{e_raw[10:12]}"
                elif " " in e_raw:
                    end_time = e_raw[11:16]
                else:
                    end_time = ""

                reservations.append({
                    "resSeq":     str(item.get("resSeq", "")),
                    "resName":    item.get("resName", item.get("resNm", "")),
                    "reqText":    item.get("reqText", ""),
                    "startDate":  s_raw,
                    "endDate":    e_raw,
                    "start_time": start_time,
                    "end_time":   end_time,
                    "date":       date,
                    "booker":     item.get("empName", item.get("empNm", item.get("userName", ""))),
                    "schmSeq":    str(item.get("schmSeq", "")),
                    "seqNum":     str(item.get("seqNum", "")),
                    "raw":        item
                })

        logger.info(f"예약 {len(reservations)}건 조회 완료")

        DATA_DIR.mkdir(exist_ok=True)
        (DATA_DIR / f"reservations_{date_str}.json").write_text(
            json.dumps(reservations, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return reservations

    def check_availability(
        self,
        date: str,
        start_time: str,
        end_time: str,
        room_name: str = None,
        res_seq: str = None,
    ) -> bool:
        """
        중복 예약 체크 (rs121A14).
        반환: True = 예약 가능, False = 중복/불가
        """
        if res_seq is None:
            room = self._find_room(room_name or "1번 회의실")
            if room is None:
                logger.warning(f"회의실 resSeq 불명: {room_name}")
                return False
            res_seq = room["resSeq"]

        date_str = self._to_yyyymmdd(date)
        start_dt = date_str + self._to_hhmm(start_time)
        end_dt   = date_str + self._to_hhmm(end_time)

        logger.info(f"중복 체크 (rs121A14): resSeq={res_seq}, {start_dt}~{end_dt}")

        body = {
            "companyInfo": self.company_info,
            "langCode": "kr",
            "resSeq":    res_seq,
            "startDate": start_dt,
            "endDate":   end_dt,
            "seqNum":    "",
            "resIdx":    ""
        }
        result = self.call_api("/schres/rs121A14", body)

        rd = result.get("data", {}).get("resultData", [])
        # resultData.resultList 구조 또는 직접 리스트 모두 처리
        if isinstance(rd, dict):
            result_data = rd.get("resultList", [])
        else:
            result_data = rd if isinstance(rd, list) else []

        if len(result_data) == 0:
            logger.info("중복 없음 - 예약 가능")
            return True
        else:
            logger.info(f"중복 예약 {len(result_data)}건 존재 - 예약 불가")
            return False

    def find_available_slots(
        self,
        date: str = None,
        room_name: str = None,
        duration_minutes: int = 60,
    ) -> list[dict]:
        """
        빈 시간대 검색 (rs121A05 결과 기반 계산).
        """
        if date is None:
            date = datetime.date.today().strftime("%Y-%m-%d")

        logger.info(f"빈 시간대 검색: {date}, 회의실={room_name or '전체'}, {duration_minutes}분")

        reservations = self.get_reservations(date)

        if room_name:
            room_info = self._find_room(room_name)
            target_rooms = [room_info] if room_info else []
        else:
            target_rooms = list(self.ROOM_MAP.values())

        available = []

        for room in target_rooms:
            r_seq  = room["resSeq"]
            r_name = room["resName"]

            busy_slots = []
            for res in reservations:
                if str(res.get("resSeq", "")) == r_seq:
                    s = self._to_minutes(res.get("start_time", ""))
                    e = self._to_minutes(res.get("end_time", ""))
                    if s is not None and e is not None and s < e:
                        busy_slots.append((s, e))

            busy_slots.sort()

            current = self.WORK_START
            for busy_start, busy_end in busy_slots:
                gap = busy_start - current
                if gap >= duration_minutes:
                    available.append({
                        "resSeq":     r_seq,
                        "resName":    r_name,
                        "date":       date,
                        "start_time": self._from_minutes(current),
                        "end_time":   self._from_minutes(busy_start),
                    })
                current = max(current, busy_end)

            if self.WORK_END - current >= duration_minutes:
                available.append({
                    "resSeq":     r_seq,
                    "resName":    r_name,
                    "date":       date,
                    "start_time": self._from_minutes(current),
                    "end_time":   self._from_minutes(self.WORK_END),
                })

        logger.info(f"빈 시간대 {len(available)}건 발견")

        date_str = self._to_yyyymmdd(date)
        DATA_DIR.mkdir(exist_ok=True)
        (DATA_DIR / f"available_slots_{date_str}.json").write_text(
            json.dumps(available, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return available

    def make_reservation(
        self,
        room_name: str,
        date: str,
        start_time: str,
        end_time: str,
        title: str,
        description: str = "",
        res_seq: str = None,
    ) -> dict:
        """
        회의실 예약 생성 (rs121A06 = 신규 단건 예약).
        반환: {"success": bool, "message": str, "data": dict}
        """
        if res_seq is None:
            room_info = self._find_room(room_name)
            if room_info is None:
                msg = f"회의실을 찾을 수 없습니다: {room_name}"
                logger.error(msg)
                return {"success": False, "message": msg, "data": {}}
            res_seq  = room_info["resSeq"]
            res_name = room_info["resName"]
        else:
            res_name = next(
                (v["resName"] for v in self.ROOM_MAP.values() if v["resSeq"] == res_seq),
                room_name
            )

        date_str = self._to_yyyymmdd(date)
        start_dt = date_str + self._to_hhmm(start_time)
        end_dt   = date_str + self._to_hhmm(end_time)

        logger.info(
            f"예약 생성 시도 (rs121A06): resSeq={res_seq}, "
            f"{start_dt}~{end_dt}, title={title}"
        )

        # 1단계: 중복 체크
        if not self.check_availability(date, start_time, end_time, res_seq=res_seq):
            msg = f"해당 시간대에 이미 예약이 있습니다: {date} {start_time}~{end_time} ({res_name})"
            logger.warning(msg)
            return {"success": False, "message": msg, "data": {}}

        # 2단계: 예약 생성 (rs121A06 = 신규 단건 예약)
        # JS 원본: b.a.rs121A06({resSeq, reqText, apprYn, alldayYn,
        #   startDate, endDate, descText, resSubscriberList, uidList,
        #   repeatType:"10", repeatEndDay:""})
        # 참고: rs121A12는 기존 예약 수정용, rs121A15는 반복 예약용
        # empSeq 필수 확인
        emp_seq = self.company_info.get("empSeq", "")
        if not emp_seq:
            msg = "프로필 설정이 필요합니다. empSeq가 설정되지 않았습니다. 관리자에게 문의하거나 프로필을 업데이트해주세요."
            logger.error(msg)
            return {"success": False, "message": msg, "data": {}}

        body = {
            "resSeq":             res_seq,
            "reqText":            title,
            "apprYn":             "N",
            "alldayYn":           "N",
            "startDate":          start_dt,    # YYYYMMDDHHmm
            "endDate":            end_dt,
            "descText":           description,
            "resSubscriberList":  [{
                "groupSeq": self.company_info["groupSeq"],
                "compSeq":  self.company_info["compSeq"],
                "deptSeq":  self.company_info["deptSeq"],
                "empSeq":   emp_seq,
            }],
            "uidList":            "",
            "repeatType":         "10",        # "10" = 반복 없음
            "repeatEndDay":       "",
        }

        result = self.call_api("/schres/rs121A06", body)

        data        = result.get("data", {})
        result_code = str(data.get("resultCode", ""))
        result_msg  = data.get("resultMsg", "")
        result_data = data.get("resultData", {})

        if result_code in ("0", "200") and isinstance(result_data, dict) and result_data.get("successTf"):
            msg = f"예약 성공: {title} ({date} {start_time}~{end_time}, {res_name})"
            logger.info(msg)
            return {"success": True, "message": msg, "data": data}
        else:
            msg = f"예약 실패: resultCode={result_code}, msg={result_msg}"
            logger.error(msg)
            return {"success": False, "message": msg, "data": data}

    def cancel_reservation(
        self,
        schm_seq: str,
        seq_num: str,
        res_seq: str,
        res_idx: str = "1",
        req_text: str = "",
        start_date: str = "",
        end_date: str = "",
        create_date: str = "",
        res_name: str = "",
    ) -> dict:
        """
        예약 취소 (rs121A11 statusCode=CA).
        JS 원본: {statusCode:"CA", resSeqList:[{resSeq, seqNum, resIdx, reqText, ...}]}
        반환: {"success": bool, "message": str, "data": dict}
        """
        logger.info(f"예약 취소 (rs121A11/CA): schmSeq={schm_seq}, seqNum={seq_num}, resSeq={res_seq}")

        body = {
            "statusCode": "CA",
            "resSeqList": [{
                "resSeq":     res_seq,
                "seqNum":     seq_num,
                "resIdx":     res_idx,
                "reqText":    req_text,
                "startDate":  start_date,
                "endDate":    end_date,
                "createDate": create_date,
                "schmSeq":    schm_seq,
                "schSeq":     "",
                "resName":    res_name,
                "alldayYn":   "N",
            }],
        }
        result = self.call_api("/schres/rs121A11", body)

        data        = result.get("data", {})
        result_code = str(data.get("resultCode", ""))
        result_msg  = data.get("resultMsg", "")

        if result_code in ("0", "200") or result.get("ok"):
            msg = f"예약 취소 성공: schmSeq={schm_seq}"
            logger.info(msg)
            return {"success": True, "message": msg, "data": data}
        else:
            msg = f"예약 취소 실패: resultCode={result_code}, msg={result_msg}"
            logger.error(msg)
            return {"success": False, "message": msg, "data": data}


# ─────────────────────────────────────────
# 편의 함수: Playwright 로그인 → 쿠키 추출 → httpx API
# ─────────────────────────────────────────

def _extract_auth_cookies(context) -> tuple[str, str, dict]:
    """
    Playwright BrowserContext에서 인증 쿠키 추출.
    반환: (oauth_token, sign_key, all_cookies_dict)
    """
    cookies = context.cookies()
    cookie_dict = {}
    oauth_token = ""
    sign_key = ""

    for c in cookies:
        cookie_dict[c["name"]] = c["value"]
        if c["name"] == "oAuthToken":
            oauth_token = c["value"]
        elif c["name"] == "signKey":
            sign_key = c["value"]

    if not oauth_token:
        # BIZCUBE_AT는 oAuthToken과 동일
        oauth_token = cookie_dict.get("BIZCUBE_AT", "")
    if not sign_key:
        # BIZCUBE_HK는 signKey와 동일
        sign_key = cookie_dict.get("BIZCUBE_HK", "")

    if not oauth_token or not sign_key:
        raise RuntimeError(
            f"인증 쿠키 누락: oAuthToken={'있음' if oauth_token else '없음'}, "
            f"signKey={'있음' if sign_key else '없음'}"
        )

    logger.info(f"인증 쿠키 추출 완료: oAuthToken={oauth_token[:20]}..., signKey={sign_key[:10]}...")
    return oauth_token, sign_key, cookie_dict


def create_api_with_session(
    headless: bool = True,
    user_id: str = None,
    user_pw: str = None,
    company_info: dict = None,
):
    """
    Playwright 로그인 → 쿠키 추출 → MeetingRoomAPI(httpx) 인스턴스 반환.

    user_id, user_pw: 지정 시 해당 사용자로 로그인. None이면 .env 기본값.
    company_info: 사용자별 회사정보. None이면 DEFAULT_COMPANY_INFO 사용.

    사용 예:
        api, cleanup = create_api_with_session()
        try:
            result = api.make_reservation(...)
        finally:
            cleanup()
    """
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session

    pw = sync_playwright().start()
    browser, context, page = login_and_get_context(
        playwright_instance=pw, headless=headless,
        user_id=user_id, user_pw=user_pw,
    )

    # 쿠키 추출
    oauth_token, sign_key, cookie_dict = _extract_auth_cookies(context)

    # Playwright 브라우저 종료 (더 이상 불필요)
    close_session(browser)
    pw.stop()

    # httpx 기반 API 인스턴스 생성
    api = MeetingRoomAPI(
        oauth_token=oauth_token,
        sign_key=sign_key,
        cookies=cookie_dict,
        company_info=company_info,
    )

    def cleanup():
        api.close()

    return api, cleanup


# ─────────────────────────────────────────
# 테스트 실행
# ─────────────────────────────────────────

def run():
    """MeetingRoomAPI 모듈 테스트 실행"""
    import os
    os.environ['PYTHONIOENCODING'] = 'utf-8'

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    logger.info("=" * 50)
    logger.info("MeetingRoomAPI 테스트 시작 (httpx + wehago-sign)")
    logger.info("=" * 50)

    api, cleanup = create_api_with_session(headless=True)

    try:
        today    = datetime.date.today().strftime("%Y-%m-%d")
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

        # 1. 회의실 목록
        logger.info("\n[1] 회의실 목록 조회")
        rooms = api.get_rooms()
        for r in rooms:
            logger.info(f"  resSeq={r['resSeq']}, resName={r['resName']}")

        # 2. 오늘 예약 현황
        logger.info(f"\n[2] 예약 현황: {today}")
        reservations = api.get_reservations(today)
        logger.info(f"  총 {len(reservations)}건")
        for res in reservations[:5]:
            logger.info(
                f"  [{res['resName']}] {res['reqText']} "
                f"{res['start_time']}~{res['end_time']}"
            )

        # 3. 빈 시간대 검색
        logger.info(f"\n[3] 빈 시간대: {today}, 60분")
        slots = api.find_available_slots(today, duration_minutes=60)
        for slot in slots[:5]:
            logger.info(f"  [{slot['resName']}] {slot['start_time']}~{slot['end_time']}")

        # 4. 중복 체크
        logger.info(f"\n[4] 중복 체크: {tomorrow} 10:00~11:00 (1번 회의실)")
        ok = api.check_availability(tomorrow, "10:00", "11:00", room_name="1번 회의실")
        logger.info(f"  예약 가능: {ok}")

        # 5. 예약 생성 (필요할 때 주석 해제)
        # logger.info(f"\n[5] 예약 생성: {tomorrow} 10:00~11:00")
        # result = api.make_reservation(
        #     room_name="1번 회의실",
        #     date=tomorrow,
        #     start_time="10:00",
        #     end_time="11:00",
        #     title="API 테스트 예약",
        #     description="자동화 모듈 테스트"
        # )
        # logger.info(f"  결과: {result['success']}, {result['message']}")

    finally:
        cleanup()

    logger.info("\n테스트 완료")


if __name__ == "__main__":
    run()
