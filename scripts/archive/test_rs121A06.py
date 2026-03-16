"""rs121A06 신규 단건 예약 생성 테스트"""
import os, sys, json, datetime
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv('config/.env')

from src.meeting.reservation_api import create_api_with_session, MeetingRoomAPI

api, cleanup = create_api_with_session(headless=True)

try:
    # 내일(월요일) 날짜
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    date_str = tomorrow.replace('-', '')
    print(f"테스트 날짜: {tomorrow} ({date_str})")

    CI = MeetingRoomAPI.COMPANY_INFO

    # rs121A06 — 신규 단건 예약 (JS 원본과 동일한 구조)
    body = {
        "companyInfo": CI,
        "langCode": "kr",
        "resSeq": "46",        # 2번 회의실
        "reqText": "API자동화테스트",
        "apprYn": "N",
        "alldayYn": "N",
        "startDate": date_str + "1500",
        "endDate": date_str + "1600",
        "descText": "",
        "resSubscriberList": [{
            "groupSeq": "gcmsAmaranth36068",
            "compSeq": "1000",
            "deptSeq": "2017",
            "empSeq": "2922"
        }],
        "uidList": "",
        "repeatType": "10",
        "repeatEndDay": ""
    }

    print('\n=== rs121A06 테스트 (신규 단건 예약) ===')
    print(f"Body: {json.dumps(body, ensure_ascii=False, indent=2)}")

    result = api.call_api('/schres/rs121A06', body)
    data = result.get('data', {})
    rc = data.get('resultCode', '?')
    rm = data.get('resultMsg', '')
    rd = data.get('resultData', '')
    print(f"\nHTTP status: {result.get('status')}")
    print(f"resultCode: {rc}")
    print(f"resultMsg: {rm}")
    if rd:
        rd_str = json.dumps(rd, ensure_ascii=False)[:500]
        print(f"resultData: {rd_str}")

    # 성공하면 예약 현황 확인
    if str(rc) in ('0', '200'):
        print('\n=== 예약 성공! 현황 확인 ===')
        reservations = api.get_reservations(tomorrow)
        for r in reservations:
            print(f"  [{r['resName']}] {r['start_time']}~{r['end_time']} - {r['reqText']} ({r['booker']})")

finally:
    cleanup()
    print("\n테스트 완료")
