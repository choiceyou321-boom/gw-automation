import os
import sys
import json
import logging
import datetime
from pathlib import Path

# 프로젝트 루트를 경로에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.meeting.reservation_api import create_api_with_session

# 로그 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("test_reserve")

def test_reservation():
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    
    logger.info("회의실 예약 생성 테스트 시작...")
    
    # 1. API 인스턴스 생성 (로그인 포함)
    api, cleanup = create_api_with_session(headless=True)
    
    try:
        # 내일 날짜 설정
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        start_time = "14:00"
        end_time = "15:00"
        room_name = "1번 회의실"
        title = f"API 단위 테스트 - {datetime.datetime.now().strftime('%H:%M:%S')}"
        
        logger.info(f"대상: {room_name}, 일시: {tomorrow} {start_time}~{end_time}")
        
        # 2. 직접 rs121A12 호출 시도 (다양한 페이로드 변형)
        room = api._find_room(room_name)
        res_seq = room["resSeq"]
        date_str = tomorrow.replace("-", "")
        start_dt = date_str + start_time.replace(":", "")
        end_dt = date_str + end_time.replace(":", "")
        
        results = []
        
        base_payload = {
            "resSeq": res_seq,
            "seqNum": "",
            "resIdx": "1",
            "reqText": title,
            "apprYn": "N",
            "alldayYn": "N",
            "startDatePk": date_str,
            "createDatePk": "",
            "startDate": start_dt,
            "endDate": end_dt,
            "descText": "자동화 테스트",
            "uidList": "",
            "repeatType": "10",
            "repeatEndDay": "",
            "repeatByDay": "",
            "resName": room["resName"]
        }
        
        # 시도 6: empSeq를 숫자로 (Integer)
        logger.info("시도 6: empSeq as Integer (2922)")
        payload6 = base_payload.copy()
        payload6["resSubscriberList"] = [{
            "groupSeq": api.COMPANY_INFO["groupSeq"],
            "compSeq": api.COMPANY_INFO["compSeq"],
            "deptSeq": api.COMPANY_INFO["deptSeq"],
            "empSeq": 2922
        }]
        result6 = api.call_api("/schres/rs121A12", payload6)
        results.append({"at": 6, "payload": payload6, "resp": result6})

        # 시도 7: resSubscriberList 내부에 더 많은 필드 추가 (JS 소스 기반)
        logger.info("시도 7: More fields in resSubscriberList")
        payload7 = base_payload.copy()
        payload7["resSubscriberList"] = [{
            "groupSeq": api.COMPANY_INFO["groupSeq"],
            "compSeq": api.COMPANY_INFO["compSeq"],
            "deptSeq": api.COMPANY_INFO["deptSeq"],
            "empSeq": "2922",
            "empName": "전태규",
            "deptName": "PM팀",
            "ownerYn": "Y",
            "viewYn": "Y"
        }]
        result7 = api.call_api("/schres/rs121A12", payload7)
        results.append({"at": 7, "payload": payload7, "resp": result7})

        # 파일로 결과 저장
        Path("data/test_results.json").parent.mkdir(exist_ok=True)
        Path("data/test_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"테스트 결과 저장 완료: data/test_results.json")

    except Exception as e:
        logger.error(f"테스트 중 오류 발생: {e}")
    finally:
        cleanup()

if __name__ == "__main__":
    test_reservation()
