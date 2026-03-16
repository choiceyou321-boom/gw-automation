"""rs121A12 예약 생성 파라미터 테스트 - companyInfo + langCode 포함"""
import os, sys, json, datetime
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv('config/.env')

from src.meeting.reservation_api import create_api_with_session, MeetingRoomAPI

api, cleanup = create_api_with_session(headless=True)

try:
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    date_str = tomorrow.replace('-', '')
    print(f"테스트 날짜: {tomorrow} ({date_str})")

    CI = MeetingRoomAPI.COMPANY_INFO  # companyInfo

    def test(label, body):
        print(f"\n{'='*50}")
        print(f"=== {label} ===")
        r = api.call_api('/schres/rs121A12', body)
        d = r.get('data', {})
        rc = d.get('resultCode', '?')
        rm = d.get('resultMsg', '')
        rd = d.get('resultData', '')
        print(f"resultCode={rc}, msg={rm}")
        if rd:
            rd_str = json.dumps(rd, ensure_ascii=False)[:500]
            print(f"resultData={rd_str}")
        return rc

    # JS 원본: scheduleApiCommon("rs121A12", {companyInfo: companyInfo(), ...params, langCode: langCode()})
    # companyInfo와 langCode가 자동으로 래핑됨

    # 테스트 1: companyInfo + langCode + resIdx 빈값
    rc1 = test("companyInfo 포함, resIdx 빈값", {
        "companyInfo": CI,
        "langCode": "kr",
        "resSeq": "45",
        "seqNum": "",
        "resIdx": "",
        "reqText": "API테스트1",
        "apprYn": "N",
        "alldayYn": "N",
        "startDatePk": date_str,
        "createDatePk": "",
        "startDate": date_str + "1500",
        "endDate": date_str + "1600",
        "descText": "",
        "resSubscriberList": [{"groupSeq": "gcmsAmaranth36068", "compSeq": "1000", "deptSeq": "2017", "empSeq": "2922"}],
        "uidList": "",
        "repeatType": "10",
        "repeatEndDay": "",
        "repeatByDay": "",
        "resName": "1번 회의실",
    })

    # 테스트 2: companyInfo + langCode + resIdx="1"
    rc2 = test("companyInfo 포함, resIdx=1", {
        "companyInfo": CI,
        "langCode": "kr",
        "resSeq": "45",
        "seqNum": "",
        "resIdx": "1",
        "reqText": "API테스트2",
        "apprYn": "N",
        "alldayYn": "N",
        "startDatePk": date_str,
        "createDatePk": "",
        "startDate": date_str + "1500",
        "endDate": date_str + "1600",
        "descText": "",
        "resSubscriberList": [{"groupSeq": "gcmsAmaranth36068", "compSeq": "1000", "deptSeq": "2017", "empSeq": "2922"}],
        "uidList": "",
        "repeatType": "10",
        "repeatEndDay": "",
        "repeatByDay": "",
        "resName": "1번 회의실",
    })

    # 테스트 3: 다른 시간대
    rc3 = test("다른 시간 (09:00~10:00)", {
        "companyInfo": CI,
        "langCode": "kr",
        "resSeq": "46",
        "seqNum": "",
        "resIdx": "",
        "reqText": "API테스트3",
        "apprYn": "N",
        "alldayYn": "N",
        "startDatePk": date_str,
        "createDatePk": "",
        "startDate": date_str + "0900",
        "endDate": date_str + "1000",
        "descText": "",
        "resSubscriberList": [{"groupSeq": "gcmsAmaranth36068", "compSeq": "1000", "deptSeq": "2017", "empSeq": "2922"}],
        "uidList": "",
        "repeatType": "10",
        "repeatEndDay": "",
        "repeatByDay": "",
        "resName": "2번 회의실",
    })

    print(f"\n\n요약: 테스트1={rc1}, 테스트2={rc2}, 테스트3={rc3}")

finally:
    cleanup()
    print("\n테스트 완료")
