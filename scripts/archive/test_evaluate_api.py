"""
Playwright page.evaluate() 방식으로 rs121A API 호출 테스트
- 브라우저 컨텍스트에서 JS fetch()를 실행 → wehago-sign 인증 자동 포함
- httpx 직접 호출 불가 문제 우회
"""
import sys
import os
import json
import datetime

# 한국어 인코딩 설정
os.environ['PYTHONIOENCODING'] = 'utf-8'
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, 'config', '.env'))

from playwright.sync_api import sync_playwright
from src.auth.login import login_and_get_context, close_session
from pathlib import Path

# 결과 저장 경로
DATA_DIR = Path(PROJECT_ROOT) / 'data' / 'gw_analysis'
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 공통 companyInfo
COMPANY_INFO = {
    "compSeq": "1000",
    "groupSeq": "gcmsAmaranth36068",
    "deptSeq": "2017",
    "emailAddr": "tgjeon",
    "emailDomain": "glowseoul.co.kr"
}

# 오늘 날짜 (YYYYMMDD 형식)
TODAY = datetime.date.today().strftime("%Y%m%d")
TOMORROW = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y%m%d")


def call_api_via_evaluate(page, endpoint: str, body: dict) -> dict:
    """
    page.evaluate()를 통해 axios/XHR/fetch 순으로 rs121A API 호출.
    axios 인터셉터가 wehago-sign 헤더를 자동으로 첨부함.
    """
    body_json = json.dumps(body, ensure_ascii=False)

    js_code = f"""
    async () => {{
        const url = "{endpoint}";
        const bodyData = {body_json};

        // 방법 1: window.axios (인터셉터로 wehago-sign 자동 첨부)
        if (window.axios) {{
            try {{
                const resp = await window.axios.post(url, bodyData, {{
                    headers: {{ "Content-Type": "application/json;charset=UTF-8" }}
                }});
                return {{ status: resp.status, ok: resp.status >= 200 && resp.status < 300, data: resp.data, method: "axios" }};
            }} catch (e) {{
                if (e.response) {{
                    return {{ status: e.response.status, ok: false, data: e.response.data, error: e.message, method: "axios" }};
                }}
            }}
        }}

        // 방법 2: XMLHttpRequest
        try {{
            const result = await new Promise((resolve, reject) => {{
                const xhr = new XMLHttpRequest();
                xhr.open("POST", url, true);
                xhr.setRequestHeader("Content-Type", "application/json;charset=UTF-8");
                xhr.setRequestHeader("Accept", "application/json");
                xhr.withCredentials = true;
                xhr.onload = () => {{
                    try {{
                        const data = JSON.parse(xhr.responseText);
                        resolve({{ status: xhr.status, ok: xhr.status >= 200 && xhr.status < 300, data, method: "xhr" }});
                    }} catch(e) {{
                        resolve({{ status: xhr.status, ok: false, data: xhr.responseText, method: "xhr" }});
                    }}
                }};
                xhr.onerror = () => reject(new Error("XHR network error"));
                xhr.send(JSON.stringify(bodyData));
            }});
            return result;
        }} catch (e2) {{}}

        // 방법 3: fetch 폴백
        try {{
            const response = await fetch(url, {{
                method: "POST",
                headers: {{
                    "Content-Type": "application/json;charset=UTF-8",
                    "Accept": "application/json"
                }},
                credentials: "include",
                body: JSON.stringify(bodyData)
            }});
            const data = await response.json();
            return {{ status: response.status, ok: response.ok, data, method: "fetch" }};
        }} catch (e3) {{
            return {{ status: 0, ok: false, error: e3.toString(), method: "fetch" }};
        }}
    }}
    """
    result = page.evaluate(js_code)
    return result


def test_rs121A01(page) -> dict:
    """자원 목록 조회 - 회의실 목록과 resSeq 확인"""
    print("\n=== rs121A01: 자원 목록 조회 ===")
    # 브라우저 캡처 기준 실제 파라미터 패턴
    body = {
        "companyInfo": COMPANY_INFO,
        "langCode": "kr",
        "searchText": "",
        "attrUseYn": "",
        "attrList": ["2", "4", "3", "8", "5", "ETC"],
        "propList": []
    }
    result = call_api_via_evaluate(page, "/schres/rs121A01", body)

    status = result.get('status', 0)
    method = result.get('method', '?')
    data = result.get('data', {})
    print(f"  HTTP 상태: {status} (호출방식: {method})")
    print(f"  resultCode: {data.get('resultCode', 'N/A') if isinstance(data, dict) else 'N/A'}")
    print(f"  resultMsg: {data.get('resultMsg', 'N/A') if isinstance(data, dict) else 'N/A'}")

    # resultData.resultList 구조 처리
    rd = data.get('resultData', []) if isinstance(data, dict) else []
    if isinstance(rd, dict):
        result_list = rd.get('resultList', [])
    else:
        result_list = rd if isinstance(rd, list) else []

    print(f"  자원 수: {len(result_list)}개")
    for item in result_list[:15]:
        res_seq = item.get('resSeq', '?')
        res_name = item.get('resName', item.get('resNm', '?'))
        attr_seq = item.get('attrSeq', '?')
        attr_name = item.get('attrName', '?')
        print(f"    resSeq={res_seq}, resName={res_name}, attrSeq={attr_seq}, attrName={attr_name}")

    if result.get('error') and status == 0:
        print(f"  오류: {result['error']}")

    return {"api": "rs121A01", "status": status, "method": method, "response": data}


def test_rs121A05(page) -> dict:
    """예약 현황 조회 - 오늘의 예약 목록"""
    print("\n=== rs121A05: 예약 현황 조회 (오늘) ===")
    body = {
        "companyInfo": COMPANY_INFO,
        "langCode": "kr",
        "startDate": TODAY,
        "endDate": TODAY,
        "statusType": "A",  # A = 전체
        "resList": [
            {"resSeq": "45"},  # 1번 회의실
            {"resSeq": "46"},  # 2번 회의실
            {"resSeq": "47"},  # 3번 회의실
            {"resSeq": "48"},  # 4번 회의실
            {"resSeq": "49"},  # 5번 회의실
        ]
    }
    result = call_api_via_evaluate(page, "/schres/rs121A05", body)

    status = result.get('status', 0)
    data = result.get('data', {})
    print(f"  HTTP 상태: {status}")
    print(f"  resultCode: {data.get('resultCode', 'N/A')}")
    print(f"  resultMsg: {data.get('resultMsg', 'N/A')}")

    result_data = data.get('resultData', [])
    if isinstance(result_data, list):
        print(f"  예약 건수: {len(result_data)}건")
        for item in result_data[:5]:
            req_text = item.get('reqText', '?')
            start_dt = item.get('startDate', '?')
            end_dt = item.get('endDate', '?')
            res_seq = item.get('resSeq', '?')
            print(f"    [{res_seq}] {req_text} | {start_dt}~{end_dt}")
    elif result.get('error'):
        print(f"  오류: {result['error']}")

    return {"api": "rs121A05", "status": status, "response": data}


def test_rs121A14(page) -> dict:
    """중복 체크 - 특정 시간대 예약 가능 여부 확인"""
    print("\n=== rs121A14: 중복 체크 ===")
    # 내일 오전 10시~11시, 1번 회의실 (resSeq=45)
    start_dt = f"{TOMORROW}1000"
    end_dt = f"{TOMORROW}1100"
    body = {
        "companyInfo": COMPANY_INFO,
        "langCode": "kr",
        "resSeq": "45",
        "startDate": start_dt,
        "endDate": end_dt,
        "seqNum": "",
        "resIdx": ""
    }
    result = call_api_via_evaluate(page, "/schres/rs121A14", body)

    status = result.get('status', 0)
    data = result.get('data', {})
    print(f"  HTTP 상태: {status}")
    print(f"  resultCode: {data.get('resultCode', 'N/A')}")
    print(f"  resultMsg: {data.get('resultMsg', 'N/A')}")
    print(f"  검사 시간: {start_dt}~{end_dt} (1번 회의실)")

    result_data = data.get('resultData')
    if result_data is not None:
        if isinstance(result_data, list) and len(result_data) > 0:
            print(f"  중복 예약 있음: {len(result_data)}건")
            for item in result_data[:3]:
                print(f"    {json.dumps(item, ensure_ascii=False)[:200]}")
        elif isinstance(result_data, list) and len(result_data) == 0:
            print("  중복 없음 - 예약 가능!")
        else:
            print(f"  resultData: {json.dumps(result_data, ensure_ascii=False)[:300]}")
    elif result.get('error'):
        print(f"  오류: {result['error']}")

    return {"api": "rs121A14", "status": status, "response": data}


def test_rs121A49(page) -> dict:
    """설정 데이터 조회 - 예약 시스템 설정값 확인"""
    print("\n=== rs121A49: 설정 데이터 조회 ===")
    body = {
        "companyInfo": COMPANY_INFO,
        "langCode": "kr"
    }
    result = call_api_via_evaluate(page, "/schres/rs121A49", body)

    status = result.get('status', 0)
    data = result.get('data', {})
    print(f"  HTTP 상태: {status}")
    print(f"  resultCode: {data.get('resultCode', 'N/A')}")

    result_data = data.get('resultData')
    if result_data:
        if isinstance(result_data, dict):
            print(f"  resApprYn (승인필요): {result_data.get('resApprYn', '?')}")
            print(f"  confStartTime: {result_data.get('confStartTime', '?')}")
            print(f"  confEndTime: {result_data.get('confEndTime', '?')}")
        print(f"  전체: {json.dumps(result_data, ensure_ascii=False)[:500]}")
    elif result.get('error'):
        print(f"  오류: {result['error']}")

    return {"api": "rs121A49", "status": status, "response": data}


def prepare_rs121A11_params() -> dict:
    """
    rs121A11 예약 생성 파라미터 구조 준비
    ★ 실제 예약 생성은 주석 처리 - 파라미터 구조 확인용
    """
    # 내일 오전 10시~11시 예약 예시
    start_dt = f"{TOMORROW}1000"
    end_dt = f"{TOMORROW}1100"
    now_dt = datetime.datetime.now().strftime("%Y%m%d%H%M%S")

    return {
        "companyInfo": COMPANY_INFO,
        "langCode": "kr",
        "resSeq": "45",           # 1번 회의실
        "seqNum": "",             # 시퀀스 번호 (신규는 빈 값)
        "resIdx": "",             # 자원 인덱스 (신규는 빈 값)
        "reqText": "테스트 미팅",  # 예약명
        "startDate": start_dt,    # 시작일시 (YYYYMMDDHHmm)
        "endDate": end_dt,        # 종료일시
        "createDate": now_dt,     # 생성일시
        "schmSeq": "",            # 일정 시퀀스 (빈 값)
        "apprYn": "N",            # 승인 불필요 (N = 즉시 확정)
        "alldayYn": "N",          # 종일 예약 아님
        "useYn": "Y",             # 사용 여부
        "contents": "",           # 상세 내용 (선택)
        "attdList": []            # 참석자 목록 (선택)
    }


def main():
    print("=" * 60)
    print("Playwright evaluate() 방식 rs121A API 테스트")
    print(f"테스트 날짜: {TODAY}")
    print("=" * 60)

    # Playwright 로그인 (headless=False로 디버깅 용이)
    print("\n[1단계] 그룹웨어 로그인...")
    pw = sync_playwright().start()
    try:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=False  # 디버깅을 위해 브라우저 창 표시
        )
        print("  로그인 성공!")

        # 자원 예약 페이지로 이동 (schres 모듈 로드를 위해 필요할 수 있음)
        print("\n[2단계] 자원 예약 페이지로 이동...")
        page.goto(
            "https://gw.glowseoul.co.kr/#/UK/UKA/UKA0000",
            wait_until="domcontentloaded",
            timeout=30000
        )
        # schres JS 모듈이 완전히 로드될 때까지 대기
        page.wait_for_timeout(5000)
        print("  페이지 로드 완료")

        # API 테스트 실행
        print("\n[3단계] API 테스트 시작...")
        all_results = {}

        # 테스트 1: 자원 목록 조회
        try:
            r1 = test_rs121A01(page)
            all_results["rs121A01"] = r1
        except Exception as e:
            print(f"  rs121A01 예외: {e}")
            all_results["rs121A01"] = {"error": str(e)}

        # 테스트 2: 예약 현황 조회
        try:
            r2 = test_rs121A05(page)
            all_results["rs121A05"] = r2
        except Exception as e:
            print(f"  rs121A05 예외: {e}")
            all_results["rs121A05"] = {"error": str(e)}

        # 테스트 3: 중복 체크
        try:
            r3 = test_rs121A14(page)
            all_results["rs121A14"] = r3
        except Exception as e:
            print(f"  rs121A14 예외: {e}")
            all_results["rs121A14"] = {"error": str(e)}

        # 테스트 4: 설정 조회
        try:
            r4 = test_rs121A49(page)
            all_results["rs121A49"] = r4
        except Exception as e:
            print(f"  rs121A49 예외: {e}")
            all_results["rs121A49"] = {"error": str(e)}

        # ★ rs121A11 예약 생성 - 파라미터 준비만, 실행은 주석 처리
        print("\n=== rs121A11: 예약 생성 (파라미터 구조만 확인) ===")
        rs121A11_params = prepare_rs121A11_params()
        print("  준비된 예약 생성 파라미터:")
        print(f"  {json.dumps(rs121A11_params, ensure_ascii=False, indent=4)}")
        print("  [주의] 실제 예약 생성은 아래 코드를 활성화하세요:")
        print("  # result = call_api_via_evaluate(page, '/schres/rs121A11', rs121A11_params)")
        all_results["rs121A11_params"] = rs121A11_params

        # ▼▼▼ 실제 예약 생성 실행 코드 (필요할 때만 주석 해제) ▼▼▼
        # print("\n=== rs121A11: 예약 생성 실행 ===")
        # try:
        #     r5 = call_api_via_evaluate(page, "/schres/rs121A11", rs121A11_params)
        #     status = r5.get('status', 0)
        #     data = r5.get('data', {})
        #     print(f"  HTTP 상태: {status}")
        #     print(f"  resultCode: {data.get('resultCode', 'N/A')}")
        #     print(f"  resultMsg: {data.get('resultMsg', 'N/A')}")
        #     print(f"  결과: {json.dumps(data.get('resultData', {}), ensure_ascii=False)[:500]}")
        #     all_results["rs121A11"] = {"status": status, "response": data}
        # except Exception as e:
        #     print(f"  rs121A11 예외: {e}")
        #     all_results["rs121A11"] = {"error": str(e)}
        # ▲▲▲ 주석 끝 ▲▲▲

        # 결과 저장
        output_path = DATA_DIR / "evaluate_test_results.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
        print(f"\n[4단계] 결과 저장 완료: {output_path}")

        # 요약 출력
        print("\n" + "=" * 60)
        print("테스트 결과 요약")
        print("=" * 60)
        for api_name, result in all_results.items():
            if api_name == "rs121A11_params":
                print(f"  {api_name}: 파라미터 준비 완료")
                continue
            status = result.get('status', 'N/A')
            resp = result.get('response', {})
            result_code = resp.get('resultCode', 'N/A') if isinstance(resp, dict) else 'N/A'
            err = result.get('error', '')
            if err:
                print(f"  {api_name}: 오류 - {err[:80]}")
            else:
                print(f"  {api_name}: HTTP {status}, resultCode={result_code}")

    finally:
        close_session(browser)
        pw.stop()
        print("\n브라우저 종료 완료")


if __name__ == "__main__":
    main()
