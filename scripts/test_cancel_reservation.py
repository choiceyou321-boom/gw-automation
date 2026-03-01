"""테스트 예약 취소 + 통합 테스트"""
import os, sys, json, datetime
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv('config/.env')

from src.meeting.reservation_api import create_api_with_session

api, cleanup = create_api_with_session(headless=True)

try:
    tomorrow = '2026-03-02'
    print(f"=== {tomorrow} 예약 현황 ===")
    reservations = api.get_reservations(tomorrow)
    for r in reservations:
        print(f"  [{r['resName']}] {r['start_time']}~{r['end_time']} - {r['reqText']} ({r['booker']}) seqNum={r['seqNum']} schmSeq={r['schmSeq']}")

    # "API자동화테스트" 예약 찾아서 취소
    test_res = [r for r in reservations if 'API자동화테스트' in r.get('reqText', '')]
    if test_res:
        r = test_res[0]
        print(f"\n=== 테스트 예약 취소: {r['reqText']} ===")

        # raw 데이터에서 필요한 필드 추출
        raw = r.get('raw', {})
        result = api.cancel_reservation(
            schm_seq=r['schmSeq'],
            seq_num=r['seqNum'],
            res_seq=r['resSeq'],
            res_idx=str(raw.get('resIdx', '1')),
            req_text=r['reqText'],
            start_date=r['startDate'],
            end_date=r['endDate'],
            create_date=str(raw.get('createDate', '')),
            res_name=r['resName'],
        )
        print(f"취소 결과: {result['success']}, {result['message']}")
        if result.get('data'):
            print(f"응답 데이터: {json.dumps(result['data'], ensure_ascii=False)[:500]}")

        # 취소 후 현황 확인
        print(f"\n=== 취소 후 {tomorrow} 예약 현황 ===")
        reservations2 = api.get_reservations(tomorrow)
        for r in reservations2:
            print(f"  [{r['resName']}] {r['start_time']}~{r['end_time']} - {r['reqText']} ({r['booker']})")
    else:
        print("\n테스트 예약 없음")

finally:
    cleanup()
    print("\n완료")
