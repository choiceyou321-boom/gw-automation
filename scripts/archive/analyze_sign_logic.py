"""
wehago-sign 서명 알고리즘 분석 및 검증 스크립트

[이미 해독된 알고리즘]
JS 소스 (1.95189df6.chunk.js)에서 발견:
  wehago-sign = Base64(HmacSHA256(oAuthToken + transactionId + timestamp + pathname, signKey))

변수 매핑:
  l = oAuthToken    (쿠키, URL 디코딩 후)
  S = transactionId  (uuid4().hex 형태 32자 hex)
  d = timestamp     (Math.floor(Date.now()/1000) = Unix 초)
  pathname = URL 경로  (/schres/rs121A11 등)
  b = signKey       (쿠키값)

검증: 13개 실제 캡처 샘플 13/13 완전 일치 확인됨
"""
import sys, os
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import hmac, hashlib, base64, uuid, time, urllib.parse, json, re
import urllib.request, ssl
from pathlib import Path

DATA = Path(__file__).parent.parent / 'data' / 'gw_analysis'

# ─────────────────────────────────────────────
# 1. 서명 생성 함수
# ─────────────────────────────────────────────

def generate_wehago_sign(oauth_token_raw: str, sign_key: str, url_pathname: str):
    """
    wehago-sign 헤더 생성

    Args:
        oauth_token_raw: oAuthToken 쿠키값 (URL 인코딩 포함 가능)
        sign_key: signKey 쿠키값 (= BIZCUBE_HK 쿠키와 동일)
        url_pathname: 요청 URL 경로 (예: /schres/rs121A11)

    Returns:
        dict: authorization, transaction-id, timestamp, wehago-sign 포함
    """
    oauth_token = urllib.parse.unquote(oauth_token_raw)
    transaction_id = uuid.uuid4().hex          # 32자 소문자 hex
    timestamp = str(int(time.time()))           # Unix 초 단위

    # JS 원본: CryptoJS.HmacSHA256(l + S + d + pathname, b)
    message = oauth_token + transaction_id + timestamp + url_pathname
    signature = base64.b64encode(
        hmac.new(sign_key.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()
    ).decode()

    return {
        'authorization': 'Bearer ' + oauth_token,
        'transaction-id': transaction_id,
        'timestamp': timestamp,
        'wehago-sign': signature,
        'content-type': 'application/json',
    }


# ─────────────────────────────────────────────
# 2. 13개 실제 캡처 샘플로 알고리즘 검증
# ─────────────────────────────────────────────

def verify_algorithm():
    sign_key = '95233990162914950487395159959680005262700721'
    oauth_token = 'gcmsAmaranth36068|2922|wAgC3PYkqN3SlTVCqijvEkXYCh02uD'

    samples = [
        ('1772362525', '332e41135c4b9fd1e26c9cbb463ba4b6', 'U5s38exyxNjD8akM+CxBNRtUMY7NFoXDmXCqyHlfQEg=', '/schres/sc112A44'),
        ('1772362527', 'a04c1d423f942ca21ee27b6d4462312f', '/ueGbk64tLRN3c3DOzQaLF5G3/lt2IjkQhgJ3RW96dM=', '/schres/rs121A38'),
        ('1772362527', '2ede87ed7607d69f12f2237bfbd357bc', '22CTY7DahB57zkS38CwSA2FXQv0B+TAwpTU7Var6+7k=', '/schres/rs121A24'),
        ('1772362527', '1b0d59da36d8b327eed324c61bd555d2', 'LKGNEv8NcQZlhyWWmhNUdALTLF2gONc5eGLVNC9vPqU=', '/schres/rs121A28'),
        ('1772362527', 'aa75e26e928a11db7622e77048413d32', 'igUtAdwsypIY5xWmbXxYizPaZvP6rK32uU771rutZ2k=', '/schres/rs121A29'),
        ('1772362527', '0e3e4bb330e3a4bafffbdbbd3b3c7444', 'Dn6NtRkCex4qZdOks7TRWns+psuo37P2FS4jeGKLgKM=', '/schres/rs121A45'),
        ('1772362527', '9e29dbd852ac863aa1748435c5c8b9d0', 'WjQryAdyg+FF6lV6rKoIjlxF64KGAHmFZj7YrVRaNa0=', '/schres/rs121A46'),
        ('1772362527', '3a5a522cbfcd96818c5bf40ac4d6d239', 'O/691O2iiSDptwpPoRxYgRmM2ByxAn7ibDgGPG87rog=', '/schres/sc111A48'),
        ('1772362527', '90bfeb5e58434ffa8d9b6e1fc4e4f634', 'zCWokN5DbyzjiQCeWOw0xBfXLSL5yu6hxP1cjDDm83E=', '/schres/rs121A49'),
        ('1772362527', 'e233a51dc773c4f2b047b149d4952846', 'iLv3Dkeq3sm2YaKIT9iwL7oKqWVVKf+s99G9B6ecohU=', '/schres/rs121A01'),
        ('1772362527', '9617d5b55ce114dcdc27d55abdfd7230', 'NnmAi6HldWGk7GvSocEqDNgmU5q2kzbP+hRVIjSVT4s=', '/schres/rs121A01'),
        ('1772362527', '971650d6d20dfe5e35c24d0464325549', '4uLUVhBtfpG/lAbZUMOIydSUf6Fg3DlWgQR5IDNUutI=', '/schres/rs121A05'),
        ('1772362527', 'cce3754dc2bf32cba14a464fc3dbe4ec', 'rGszaACrAJ4FmIv4im+uxeYzDWUFX1f5N3Eg2Nu+yZI=', '/schres/rs121A05'),
    ]

    print('=== wehago-sign 알고리즘 검증 ===')
    print('공식: HMAC-SHA256(signKey, oAuthToken + transactionId + timestamp + pathname)')
    print()

    matches = 0
    for ts, tid, expected, pathname in samples:
        message = oauth_token + tid + ts + pathname
        result = base64.b64encode(
            hmac.new(sign_key.encode(), message.encode(), hashlib.sha256).digest()
        ).decode()
        ok = result == expected
        if ok:
            matches += 1
        print(f'  {"MATCH" if ok else "FAIL "} {pathname} tid={tid[:8]}...')

    print()
    print(f'결과: {matches}/{len(samples)} 일치')
    return matches == len(samples)


# ─────────────────────────────────────────────
# 3. JS 소스에서 서명 로직 추출 (참고용)
# ─────────────────────────────────────────────

def extract_sign_logic_from_js():
    """
    실제 JS 소스(1.95189df6.chunk.js)에서 서명 생성 코드를 추출하여 출력
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    url = 'https://gw.glowseoul.co.kr/modules/schres/static/js/1.95189df6.chunk.js'
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0',
        'Referer': 'https://gw.glowseoul.co.kr/'
    })

    print('\n=== JS 소스에서 서명 로직 추출 ===')
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
            js = resp.read().decode('utf-8', errors='replace')

        # HmacSHA256 주변 코드 추출
        idx = js.find('HmacSHA256')
        if idx >= 0:
            context_code = js[max(0, idx - 400):idx + 400]
            print('HmacSHA256 주변 코드:')
            print(context_code)
        else:
            print('HmacSHA256를 찾을 수 없음')

        # scheduleApiCommon 정의
        idx2 = js.find('scheduleApiCommon=function')
        if idx2 >= 0:
            context_code2 = js[max(0, idx2):idx2 + 300]
            print('\nscheduleApiCommon 정의:')
            print(context_code2)

        # signKey, oAuthToken 쿠키 읽는 부분
        for kw in ['signKey', 'oAuthToken', 'getTransactionId']:
            idx3 = js.find(kw)
            if idx3 >= 0:
                snippet = js[max(0, idx3 - 50):idx3 + 200]
                print(f'\n[{kw}] 참조:')
                print(snippet[:250])

    except Exception as e:
        print(f'JS 다운로드 실패: {e}')


# ─────────────────────────────────────────────
# 4. transaction-id 생성 규칙 분석
# ─────────────────────────────────────────────

def analyze_transaction_id():
    """
    transaction-id 패턴 분석
    JS 원본: getTransactionId() → uuid4().hex 형태 32자 hex
    """
    tids = [
        '332e41135c4b9fd1e26c9cbb463ba4b6',
        'a04c1d423f942ca21ee27b6d4462312f',
        '2ede87ed7607d69f12f2237bfbd357bc',
        '1b0d59da36d8b327eed324c61bd555d2',
        'aa75e26e928a11db7622e77048413d32',
        '0e3e4bb330e3a4bafffbdbbd3b3c7444',
        '9e29dbd852ac863aa1748435c5c8b9d0',
        '3a5a522cbfcd96818c5bf40ac4d6d239',
        '90bfeb5e58434ffa8d9b6e1fc4e4f634',
        'e233a51dc773c4f2b047b149d4952846',
    ]

    print('\n=== transaction-id 패턴 분석 ===')
    print(f'길이: {set(len(t) for t in tids)} (32자 = MD5/UUID hex)')
    print(f'모두 소문자 hex: {all(re.match(r"^[0-9a-f]+$", t) for t in tids)}')
    print('결론: uuid4().hex 형태 (Python uuid.uuid4().hex로 재현 가능)')
    print()
    print('Python 생성 예시:')
    import uuid as _uuid
    for _ in range(3):
        print(f'  uuid4().hex = {_uuid.uuid4().hex}')


# ─────────────────────────────────────────────
# 메인 실행
# ─────────────────────────────────────────────

if __name__ == '__main__':
    print('=' * 60)
    print('wehago-sign 서명 알고리즘 분석')
    print('=' * 60)

    # 검증
    verified = verify_algorithm()

    if verified:
        print('\n[완전 해독 완료] 알고리즘:')
        print('  wehago-sign = Base64(HMAC-SHA256(')
        print('    key   = signKey 쿠키,')
        print('    message = oAuthToken + transactionId + timestamp + url_pathname')
        print('  ))')
        print()
        print('  authorization = "Bearer " + oAuthToken 쿠키 (URL 디코딩)')
        print('  timestamp     = str(int(time.time()))')
        print('  transactionId = uuid.uuid4().hex')
    else:
        print('\n알고리즘 검증 실패. JS 소스 재분석 시작...')
        extract_sign_logic_from_js()

    # JS 소스 분석 (참고용)
    extract_sign_logic_from_js()

    # transaction-id 분석
    analyze_transaction_id()

    # 결과 저장
    result = {
        'algorithm': 'HMAC-SHA256',
        'formula': 'Base64(HMAC-SHA256(signKey, oAuthToken + transactionId + timestamp + url_pathname))',
        'headers': {
            'authorization': 'Bearer {oAuthToken_decoded}',
            'transaction-id': 'uuid4().hex (32자 소문자 hex)',
            'timestamp': 'str(int(time.time()))',
            'wehago-sign': '생성된 서명값',
            'content-type': 'application/json',
        },
        'cookie_sources': {
            'oAuthToken': 'oAuthToken 쿠키 (URL 디코딩 필요)',
            'signKey': 'signKey 쿠키 (= BIZCUBE_HK 쿠키와 동일)',
        },
        'verified_samples': 13,
        'verified': verified,
        'js_source': '1.95189df6.chunk.js (scheduleApiCommon 내부 ajaxEbp.post)',
    }

    out_path = DATA / 'sign_algorithm_analysis.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f'\n결과 저장: {out_path}')
