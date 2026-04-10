#!/usr/bin/env python3
"""
Obsidian 업무 참고 정보 자동 동기화 스크립트
외부 소스에서 업무 관련 정보를 크롤링하여 Obsidian vault에 저장.

크롤링 대상:
  1. 환율 (USD/AED/PHP/CNY/JPY) — Frankfurter API (무료, 인증 불필요)
  2. 건설/인테리어 업계 뉴스 — RSS 피드 (건설경제, 대한경제 등)
  3. 건설 법령 개정 — 법제처 법령정보센터 RSS
  4. 건설공사비지수 — e-나라지표 HTML 파싱

실행:
    python scripts/obsidian_sync.py           # 전체 동기화
    python scripts/obsidian_sync.py --rates   # 환율만
    python scripts/obsidian_sync.py --news    # 뉴스만
    python scripts/obsidian_sync.py --law     # 법령만
    python scripts/obsidian_sync.py --stats   # 공사비지수만

APScheduler에서 호출 시: run_obsidian_sync()
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ─────────────────────────── 경로 설정 ────────────────────────────

VAULT_PATH = Path.home() / "Documents" / "Obsidian" / "글로우서울_업무"
RESOURCES = VAULT_PATH / "3-Resources"

# 서브 폴더 매핑
FOLDER = {
    "finance":     RESOURCES / "금융_정보",
    "news":        RESOURCES / "업계_뉴스",
    "law":         RESOURCES / "법규_규정",
    "market":      RESOURCES / "건설시장_동향",
    "subcontract": RESOURCES / "협력업체_참고",
}

# ──────────────────────── 1. 환율 크롤러 ──────────────────────────

class ExchangeRateCrawler:
    """
    Frankfurter API (ECB 기반, 무료, 인증 불필요)
    https://www.frankfurter.app/
    """
    API_URL = "https://api.frankfurter.app/latest?from=KRW&to=USD,AED,PHP,CNY,JPY,EUR"

    # 프로젝트별 관련 통화 메모
    CURRENCY_INFO = {
        "USD": ("미국 달러", "카타르·미국 SB 프로젝트"),
        "AED": ("UAE 디르함", "카타르 SB, 리야드 레인 (AED/SAR 유사)"),
        "PHP": ("필리핀 페소", "필리핀 SB 프로젝트"),
        "CNY": ("중국 위안", "상하이 러브스타, 남경 SB"),
        "JPY": ("일본 엔",   "참고용"),
        "EUR": ("유럽 유로", "참고용"),
    }

    def fetch(self) -> Optional[dict]:
        try:
            r = requests.get(self.API_URL, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("[환율] 조회 실패: %s", e)
            return None

    def to_markdown(self, data: dict) -> str:
        date = data.get("date", datetime.now().strftime("%Y-%m-%d"))
        rates = data.get("rates", {})
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        lines = [
            "---",
            "type: reference",
            f"updated: {datetime.now().strftime('%Y-%m-%d')}",
            "source: Frankfurter API (ECB 기반)",
            "tags: [환율, 금융정보, 해외프로젝트]",
            "---",
            "",
            "# 환율 동향",
            "",
            f"> **기준일**: {date}  |  KRW(원화) 기준",
            "",
            "## 주요 통화 (1원 = 외화)",
            "",
            "| 통화명 | 코드 | 1원 → 외화 | 1외화 → 원 | 프로젝트 관련 |",
            "|--------|------|-----------|-----------|--------------|",
        ]

        for code, (name, project) in self.CURRENCY_INFO.items():
            if code in rates:
                rate = rates[code]          # 1 KRW → X 외화
                krw = 1 / rate              # 1 외화 → N 원
                lines.append(
                    f"| {name} | **{code}** | {rate:.6f} | **{krw:,.0f}원** | {project} |"
                )

        # 실용 환산표 (해외 프로젝트 계약금액 환산)
        lines += [
            "",
            "## 실용 환산 (KRW → USD)",
            "",
            "| 원화 | USD 환산 | 비고 |",
            "|------|---------|------|",
        ]
        usd_rate = rates.get("USD")
        if usd_rate:
            for krw_amt in [10_000_000, 50_000_000, 100_000_000, 500_000_000, 1_000_000_000]:
                usd_amt = krw_amt * usd_rate
                label = f"{krw_amt // 10_000:,}만원" if krw_amt < 100_000_000 else f"{krw_amt // 100_000_000:,}억원"
                lines.append(f"| {label} | ${usd_amt:,.0f} | |")

        lines += [
            "",
            "## 관련 노트",
            "",
            "- [[INDEX_건축법규전체]] — 건축행위 시 적용 법규 전체 목록",
            "- [[건설비용_지표]] — 공사비지수 / 기준금리 참고",
            "- [[협력업체_신용확인_가이드]] — 해외 협력업체 계약 전 체크리스트",
            "- [[건설뉴스_환율관련]] — 환율 영향 건설·부동산 최신 뉴스",
            "",
            "---",
            f"*마지막 업데이트: {now_str} | 출처: [Frankfurter API](https://www.frankfurter.app/)*",
        ]
        return "\n".join(lines)


# ──────────────────────── 2. 뉴스 크롤러 ─────────────────────────

class ConstructionNewsCrawler:
    """
    건설/인테리어 업계 뉴스 RSS 피드 수집.
    feedparser 라이브러리 사용 (없으면 requests + 기본 XML 파싱으로 폴백).
    """

    # 한국 건설/인테리어 뉴스 RSS 피드 목록 (작동 검증된 URL)
    RSS_FEEDS = [
        {
            "name": "한국경제 부동산건설",
            "url": "https://www.hankyung.com/feed/realestate",
            "tags": ["건설", "부동산"],
        },
        {
            "name": "연합뉴스 경제",
            "url": "https://www.yna.co.kr/rss/economy.xml",
            "tags": ["건설", "경제"],
        },
    ]

    MAX_ITEMS_PER_FEED = 5   # 피드당 최신 기사 수
    DAYS_BACK = 14           # 최근 N일 기사만

    def _parse_rss_with_feedparser(self, url: str) -> list[dict]:
        import feedparser
        feed = feedparser.parse(url)
        items = []
        cutoff = datetime.now() - timedelta(days=self.DAYS_BACK)
        for entry in feed.entries[: self.MAX_ITEMS_PER_FEED]:
            title = getattr(entry, "title", "제목 없음")
            link = getattr(entry, "link", "")
            summary = getattr(entry, "summary", "")[:200].replace("\n", " ")
            # 날짜 파싱
            pub_date = ""
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    dt = datetime(*entry.published_parsed[:6])
                    if dt < cutoff:
                        continue
                    pub_date = dt.strftime("%Y-%m-%d")
                except Exception:
                    pass
            items.append({"title": title, "link": link, "summary": summary, "date": pub_date})
        return items

    def _parse_rss_basic(self, url: str) -> list[dict]:
        """feedparser 없을 때 requests + 기본 정규식으로 title/link 추출"""
        import re
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        items = []
        titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", r.text) or \
                 re.findall(r"<title>(.*?)</title>", r.text)
        links  = re.findall(r"<link>(https?://[^<]+)</link>", r.text)
        # 첫 번째는 피드 제목이므로 건너뜀
        for i, title in enumerate(titles[1: self.MAX_ITEMS_PER_FEED + 1]):
            link = links[i] if i < len(links) else ""
            items.append({"title": title.strip(), "link": link.strip(), "summary": "", "date": ""})
        return items

    def fetch_all(self) -> list[dict]:
        """모든 RSS 피드에서 기사 수집"""
        all_items = []
        try:
            import feedparser
            use_feedparser = True
        except ImportError:
            use_feedparser = False
            logger.warning("[뉴스] feedparser 미설치 — 기본 파싱 사용. pip install feedparser")

        for feed_info in self.RSS_FEEDS:
            try:
                if use_feedparser:
                    items = self._parse_rss_with_feedparser(feed_info["url"])
                else:
                    items = self._parse_rss_basic(feed_info["url"])
                for item in items:
                    item["source"] = feed_info["name"]
                    item["feed_tags"] = feed_info["tags"]
                all_items.extend(items)
                logger.info("[뉴스] %s: %d건 수집", feed_info["name"], len(items))
            except Exception as e:
                logger.warning("[뉴스] %s 수집 실패: %s", feed_info["name"], e)

        return all_items

    def to_markdown(self, items: list[dict]) -> str:
        now = datetime.now()
        week_str = now.strftime("%Y-W%U")
        now_str = now.strftime("%Y-%m-%d %H:%M")

        # 소스별 그룹핑
        by_source: dict[str, list] = {}
        for item in items:
            src = item.get("source", "기타")
            by_source.setdefault(src, []).append(item)

        lines = [
            "---",
            "type: reference",
            f"week: \"{week_str}\"",
            f"updated: {now.strftime('%Y-%m-%d')}",
            "tags: [뉴스, 건설업계, 인테리어]",
            "---",
            "",
            f"# 건설/인테리어 업계 뉴스 ({now.strftime('%Y년 %m월 %d일')})",
            "",
            f"> 최근 {self.DAYS_BACK}일 내 주요 기사 | {len(items)}건 수집",
            "",
        ]

        if not items:
            lines += ["(수집된 기사 없음)", ""]
        else:
            for source, source_items in by_source.items():
                lines += [f"## {source}", ""]
                for item in source_items:
                    date_str = f" `{item['date']}`" if item.get("date") else ""
                    title = item.get("title", "").replace("|", "\\|")
                    link = item.get("link", "")
                    summary = item.get("summary", "")

                    if link:
                        lines.append(f"### [{title}]({link}){date_str}")
                    else:
                        lines.append(f"### {title}{date_str}")

                    if summary:
                        lines.append(f"> {summary[:150]}...")
                    lines.append("")

        lines += [
            "## 관련 노트",
            "",
            "- [[INDEX_건축법규전체]] — 건축 관련 28개 법령 전체 목록",
            "- [[건설법령_개정동향]] — 최신 건설 법령 개정 / 시행 현황",
            "- [[환율_동향]] — 해외 프로젝트 계약 시 환율 참고",
            "- [[건설비용_지표]] — 공사비지수 / 물가 변동 참고",
            "",
            "---",
            f"*마지막 업데이트: {now_str}*",
        ]
        return "\n".join(lines)


# ──────────────────────── 3. 법령 크롤러 ─────────────────────────

class ConstructionLawCrawler:
    """
    국가법령정보센터 / 법제처 RSS에서 건설 관련 법령 개정 정보 수집.
    건설산업기본법, 건축법, 주택법 등 최신 개정 공고를 모니터링.
    """

    # 법령/규제 관련 기사가 포함된 작동 확인 RSS 피드
    RSS_FEEDS = [
        {
            "name": "연합뉴스 경제",
            "url": "https://www.yna.co.kr/rss/economy.xml",
        },
        {
            "name": "한국경제 부동산건설",
            "url": "https://www.hankyung.com/feed/realestate",
        },
    ]

    # 법령/규제 관련 키워드 (일반 뉴스와 구분)
    KEYWORDS = [
        "법", "개정", "시행", "고시", "규정", "기준", "조례", "입법",
        "건설산업기본법", "건축법", "주택법", "하도급법", "안전관리",
        "허가", "인허가", "규제", "의무화",
    ]

    MAX_ITEMS = 10

    def fetch(self) -> list[dict]:
        """건설 관련 법령 개정 기사 수집"""
        try:
            import feedparser
            use_feedparser = True
        except ImportError:
            use_feedparser = False

        all_items = []
        for feed_info in self.RSS_FEEDS:
            try:
                if use_feedparser:
                    import feedparser as fp
                    feed = fp.parse(feed_info["url"])
                    entries = feed.entries[:20]
                    for entry in entries:
                        title = getattr(entry, "title", "")
                        # 건설 관련 키워드 필터링
                        if not any(kw in title for kw in self.KEYWORDS):
                            continue
                        link = getattr(entry, "link", "")
                        date = ""
                        if hasattr(entry, "published_parsed") and entry.published_parsed:
                            try:
                                date = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d")
                            except Exception:
                                pass
                        all_items.append({
                            "title": title,
                            "link": link,
                            "date": date,
                            "source": feed_info["name"],
                        })
                else:
                    import re
                    r = requests.get(feed_info["url"], timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                    r.raise_for_status()
                    titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", r.text) or \
                             re.findall(r"<title>(.*?)</title>", r.text)
                    links = re.findall(r"<link>(https?://[^<]+)</link>", r.text)
                    for i, title in enumerate(titles[1:]):
                        if any(kw in title for kw in self.KEYWORDS):
                            link = links[i] if i < len(links) else ""
                            all_items.append({
                                "title": title.strip(),
                                "link": link.strip(),
                                "date": "",
                                "source": feed_info["name"],
                            })
                    if len(all_items) >= self.MAX_ITEMS:
                        break

                logger.info("[법령] %s: 건설 관련 %d건 수집", feed_info["name"], len(all_items))
            except Exception as e:
                logger.warning("[법령] %s 수집 실패: %s", feed_info["name"], e)

        return all_items[:self.MAX_ITEMS]

    def to_markdown(self, items: list[dict]) -> str:
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M")

        lines = [
            "---",
            "type: reference",
            f"updated: {now.strftime('%Y-%m-%d')}",
            "source: 법제처 / 국토교통부",
            "tags: [법령, 건설법규, 규제동향]",
            "---",
            "",
            "# 건설 관련 법령 개정 동향",
            "",
            f"> 마지막 조회: {now.strftime('%Y년 %m월 %d일')}",
            "",
            "## 최신 입법예고 / 행정예고",
            "",
        ]

        if not items:
            lines += [
                "> RSS 수집 실패 또는 최근 건설 관련 개정 없음.",
                ">",
                "> 직접 확인: [국가법령정보센터](https://www.law.go.kr/) | [국토교통부](https://www.molit.go.kr/)",
                "",
            ]
        else:
            for item in items:
                date_str = f" `{item['date']}`" if item.get("date") else ""
                title = item.get("title", "").replace("|", "\\|")
                link = item.get("link", "")
                source = item.get("source", "")
                if link:
                    lines.append(f"- [{title}]({link}){date_str} — *{source}*")
                else:
                    lines.append(f"- {title}{date_str} — *{source}*")

        lines += [
            "",
            "## 상시 참고 법령 링크",
            "",
            "| 법령 | 링크 |",
            "|------|------|",
            "| 건설산업기본법 | [바로가기](https://www.law.go.kr/lsSc.do?query=건설산업기본법) |",
            "| 건축법 | [바로가기](https://www.law.go.kr/lsSc.do?query=건축법) |",
            "| 하도급거래 공정화에 관한 법률 | [바로가기](https://www.law.go.kr/lsSc.do?query=하도급거래) |",
            "| 주택법 | [바로가기](https://www.law.go.kr/lsSc.do?query=주택법) |",
            "| 실내건축의 구조·시공방법 등에 관한 기준 | [바로가기](https://www.law.go.kr/lsSc.do?query=실내건축) |",
            "",
            "## 관련 노트",
            "",
            "- [[INDEX_건축법규전체]] — 건축행위 관련 28개 법령 전체 목록",
            "- [[건축법]] — 허가·신고·건축기준 핵심 조항",
            "- [[건설산업기본법]] — 건설업 등록·하도급 규정",
            "- [[하도급법]] — 불공정 하도급 행위 규제",
            "- [[소방시설법]] — 소방시설 설치 기준",
            "- [[건설뉴스_주간]] — 최신 건설 업계 뉴스",
            "",
            "---",
            f"*마지막 업데이트: {now_str}*",
        ]
        return "\n".join(lines)


# ──────────────────────── 4. 건설비용 지표 크롤러 ─────────────────

class ConstructionCostCrawler:
    """
    건설 관련 비용 지표 수집.
    - e-나라지표: 건설업 생산지수, 공사비지수
    - 한국은행 경제통계: 건설투자 증감률
    실제 파싱이 어려운 경우 공식 링크와 조회 방법을 안내하는 노트 생성.
    """

    # 공개 API: 통계청 KOSIS API (API 키 없이 일부 접근 가능한 URL)
    KOSIS_URLS = {
        "건설공사비지수": "https://kosis.kr/statHtml/statHtml.do?orgId=116&tblId=DT_116N_4JO01",
        "건설업생산지수": "https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=INH_1C8016_012",
    }

    # 한국건설기술연구원 COCI 페이지
    KICT_URL = "https://www.kict.re.kr/sub03/sub0308.do"

    def fetch(self) -> dict:
        """공사비 관련 지표 페이지 접근 시도, 실패 시 링크 안내용 데이터 반환"""
        result = {
            "success": False,
            "data": [],
            "links": self.KOSIS_URLS,
        }

        # 한국은행 기준금리 조회 시도 (단순 HTML 파싱)
        try:
            r = requests.get(
                "https://www.bok.or.kr/portal/main/main.do",
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            # 기준금리는 HTML에서 직접 추출하기 어려우므로 한은 오픈API 대안 안내
            result["bok_url"] = "https://www.bok.or.kr/portal/main/contents.do?menuNo=200656"
        except Exception as e:
            logger.debug("[건설비용] 한은 페이지 접근 실패: %s", e)

        return result

    def to_markdown(self, data: dict) -> str:
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M")

        lines = [
            "---",
            "type: reference",
            f"updated: {now.strftime('%Y-%m-%d')}",
            "source: KICT, KOSIS, 한국은행",
            "tags: [건설시장, 공사비, 비용지표]",
            "---",
            "",
            "# 건설 비용 지표 참고",
            "",
            f"> 마지막 조회: {now.strftime('%Y년 %m월 %d일')}",
            "",
            "## 주요 지표 조회 링크",
            "",
            "| 지표 | 기관 | 바로가기 | 주기 |",
            "|------|------|---------|------|",
            "| 건설공사비지수 (COCI) | 한국건설기술연구원 (KICT) | [KICT 바로가기](https://www.kict.re.kr/sub03/sub0308.do) | 월간 |",
            "| 건설업 생산지수 | 통계청 KOSIS | [KOSIS 바로가기](https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=INH_1C8016_012) | 월간 |",
            "| 건설공사비지수 (KOSIS) | 통계청 | [KOSIS 바로가기](https://kosis.kr/statHtml/statHtml.do?orgId=116&tblId=DT_116N_4JO01) | 분기 |",
            "| 기준금리 | 한국은행 | [한은 바로가기](https://www.bok.or.kr/portal/main/contents.do?menuNo=200656) | 수시 |",
            "| e-나라지표 건설수주 | 국토교통부 | [바로가기](https://www.index.go.kr/potal/main/EachDtlPageDetail.do?idx_cd=1066) | 월간 |",
            "",
            "## 건설공사비지수 (COCI) 활용법",
            "",
            "- 설계 시점과 시공 시점의 물가 변동을 반영한 공사비 보정에 사용",
            "- 계약 단가 조정 협의 시 객관적 근거로 활용 가능",
            "- 계산식: `보정 공사비 = 최초 계약금액 × (시공 시점 COCI / 계약 시점 COCI)`",
            "",
            "## 실내건축 자재 가격 참고",
            "",
            "| 자재 | 참고 소스 | 비고 |",
            "|------|-----------|------|",
            "| 마감재 (타일, 마루 등) | 물가정보 월간지 | 유료 구독 필요 |",
            "| 철근, 시멘트 | [물가정보 포털](https://www.price.go.kr/) | 공공요금·원자재 |",
            "| 인건비 (품셈) | [건설표준품셈](https://www.molit.go.kr/) | 국토부 고시, 연 1회 |",
            "",
            "## 관련 노트",
            "",
            "- [[INDEX_건축법규전체]] — 건축행위 관련 법규 전체",
            "- [[건설산업기본법]] — 건설업 면허·도급 규정",
            "- [[하도급법]] — 공사비 관련 하도급 단가 기준",
            "- [[환율_동향]] — 해외 공사비 환산 참고",
            "- [[건설법령_개정동향]] — 최신 법령 개정 현황",
            "",
            "---",
            f"*마지막 업데이트: {now_str}*",
        ]
        return "\n".join(lines)


# ──────────────────────── 5. 협력업체 주의사항 ────────────────────

class SubcontractorReferenceWriter:
    """
    협력업체 신용/부도 정보 조회 방법 안내 노트.
    실시간 자동 크롤링보다는 정기 확인 가이드 형태로 제공.
    """

    def to_markdown(self) -> str:
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M")

        lines = [
            "---",
            "type: reference",
            f"updated: {now.strftime('%Y-%m-%d')}",
            "source: KISCON, 나이스평가정보, 건설공제조합",
            "tags: [협력업체, 신용조회, 부도주의]",
            "---",
            "",
            "# 협력업체 신용 확인 가이드",
            "",
            "계약 전 또는 지급 전 협력업체 신용 상태를 확인하는 방법.",
            "",
            "## 무료 조회 채널",
            "",
            "| 채널 | URL | 확인 내용 |",
            "|------|-----|-----------|",
            "| 건설산업지식정보시스템 (KISCON) | [kiscon.net](https://www.kiscon.net/) | 건설업 등록 현황, 말소 여부 |",
            "| 건설공제조합 | [cgc.or.kr](https://www.cgc.or.kr/) | 공제 가입 여부, 보증 한도 |",
            "| 국세청 사업자 진위확인 | [nts.go.kr](https://www.nts.go.kr/) | 사업자등록 유효 여부 |",
            "| 법원 경매정보 | [courtauction.go.kr](https://www.courtauction.go.kr/) | 재산 경매 여부 |",
            "| 기업신용평가 (무료 간편조회) | [dart.fss.or.kr](https://dart.fss.or.kr/) | 상장사 한정, 재무정보 |",
            "",
            "## 유료 조회 채널",
            "",
            "| 채널 | 용도 |",
            "|------|------|",
            "| 나이스평가정보 (NICE) | 기업 신용등급, 부채비율 |",
            "| 한국기업데이터 (KED) | 소상공인/중소기업 신용정보 |",
            "| 건설워크넷 | 건설사 시공 실적, 분쟁 이력 |",
            "",
            "## 계약 전 체크리스트",
            "",
            "- [ ] 사업자등록증 진위 확인 (국세청)",
            "- [ ] 건설업 면허 등록 여부 (KISCON)",
            "- [ ] 공제 가입 및 보증 가능액 확인",
            "- [ ] 건설공제조합 보증 발급 가능 여부",
            "- [ ] 최근 3개월 부도설/법정관리 뉴스 검색",
            "",
            "## 주의 업체 기록",
            "",
            "> 계약 시 주의가 필요했던 업체는 아래에 메모 (날짜 + 사유)",
            "",
            "| 업체명 | 확인일 | 사유 | 상태 |",
            "|--------|--------|------|------|",
            "| (직접 입력) | | | |",
            "",
            "## 관련 노트",
            "",
            "- [[INDEX_건축법규전체]] — 건축행위 관련 법규 전체",
            "- [[건설산업기본법]] — 건설업 면허·하도급 계약 규정",
            "- [[하도급법]] — 하도급 대금 지급 의무·지연이자",
            "- [[건설근로자법]] — 노무비 지급 보증 요건",
            "- [[건설법령_개정동향]] — 하도급 관련 최신 법령 개정",
            "",
            "---",
            f"*마지막 업데이트: {now_str}*",
        ]
        return "\n".join(lines)


# ──────────────────────── ObsidianWriter ─────────────────────────

class ObsidianWriter:
    """Obsidian vault에 마크다운 파일 저장"""

    def __init__(self):
        self._ensure_folders()

    def _ensure_folders(self):
        """필요한 폴더 생성"""
        for folder in FOLDER.values():
            folder.mkdir(parents=True, exist_ok=True)
        logger.debug("[ObsidianWriter] 폴더 구조 확인 완료")

    def write(self, folder_key: str, filename: str, content: str) -> Path:
        """파일 저장 (기존 파일 덮어쓰기)"""
        folder = FOLDER[folder_key]
        path = folder / filename
        path.write_text(content, encoding="utf-8")
        logger.info("[ObsidianWriter] 저장: %s", path.relative_to(VAULT_PATH))
        return path

    def write_index(self):
        """각 폴더 INDEX 파일 생성/갱신"""
        now_str = datetime.now().strftime("%Y-%m-%d")
        indices = {
            "finance": (
                "INDEX_금융정보.md",
                "# 금융 정보\n\n- [[환율_동향]]\n\n---\n*자동 생성*",
            ),
            "news": (
                "INDEX_업계뉴스.md",
                f"# 업계 뉴스\n\n## 최신 주간 뉴스\n\n```dataview\nLIST\nFROM \"3-Resources/업계_뉴스\"\nSORT updated DESC\nLIMIT 8\n```\n\n---\n*자동 생성*",
            ),
            "law": (
                "INDEX_법규규정.md",
                "# 법규 / 규정\n\n- [[건설법령_개정동향]]\n\n---\n*자동 생성*",
            ),
            "market": (
                "INDEX_건설시장.md",
                "# 건설시장 동향\n\n- [[건설비용_지표]]\n\n---\n*자동 생성*",
            ),
            "subcontract": (
                "INDEX_협력업체.md",
                "# 협력업체 참고\n\n- [[협력업체_신용확인_가이드]]\n\n---\n*자동 생성*",
            ),
        }
        for folder_key, (filename, content) in indices.items():
            path = FOLDER[folder_key] / filename
            if not path.exists():  # INDEX는 없을 때만 생성 (덮어쓰기 안 함)
                path.write_text(content, encoding="utf-8")
                logger.info("[ObsidianWriter] INDEX 생성: %s", filename)


# ──────────────────────── 메인 실행 함수 ─────────────────────────

def run_obsidian_sync(
    do_rates: bool = True,
    do_news: bool = True,
    do_law: bool = True,
    do_stats: bool = True,
    do_subcontract: bool = True,
) -> dict:
    """
    전체 Obsidian 동기화 실행.
    APScheduler에서 호출하거나 CLI에서 직접 실행 가능.

    Returns:
        {"success": bool, "results": {...}, "errors": [...]}
    """
    writer = ObsidianWriter()
    writer.write_index()

    results = {}
    errors = []
    now = datetime.now()

    # 1. 환율
    if do_rates:
        try:
            crawler = ExchangeRateCrawler()
            data = crawler.fetch()
            if data:
                content = crawler.to_markdown(data)
                writer.write("finance", "환율_동향.md", content)
                results["rates"] = "성공"
            else:
                results["rates"] = "데이터 없음"
                errors.append("환율: 데이터 조회 실패")
        except Exception as e:
            results["rates"] = f"실패: {e}"
            errors.append(f"환율: {e}")
            logger.error("[환율] 처리 중 오류: %s", e, exc_info=True)

    # 2. 건설 뉴스
    if do_news:
        try:
            crawler = ConstructionNewsCrawler()
            items = crawler.fetch_all()
            content = crawler.to_markdown(items)
            week_str = now.strftime("%Y-W%U")
            writer.write("news", f"건설뉴스_{week_str}.md", content)
            results["news"] = f"성공 ({len(items)}건)"
        except Exception as e:
            results["news"] = f"실패: {e}"
            errors.append(f"뉴스: {e}")
            logger.error("[뉴스] 처리 중 오류: %s", e, exc_info=True)

    # 3. 법령 개정
    if do_law:
        try:
            crawler = ConstructionLawCrawler()
            items = crawler.fetch()
            content = crawler.to_markdown(items)
            writer.write("law", "건설법령_개정동향.md", content)
            results["law"] = f"성공 ({len(items)}건)"
        except Exception as e:
            results["law"] = f"실패: {e}"
            errors.append(f"법령: {e}")
            logger.error("[법령] 처리 중 오류: %s", e, exc_info=True)

    # 4. 건설 비용 지표
    if do_stats:
        try:
            crawler = ConstructionCostCrawler()
            data = crawler.fetch()
            content = crawler.to_markdown(data)
            writer.write("market", "건설비용_지표.md", content)
            results["stats"] = "성공 (링크 안내 노트)"
        except Exception as e:
            results["stats"] = f"실패: {e}"
            errors.append(f"비용지표: {e}")
            logger.error("[비용지표] 처리 중 오류: %s", e, exc_info=True)

    # 5. 협력업체 가이드 (정적 노트 — 처음 한 번만 생성)
    if do_subcontract:
        try:
            target = FOLDER["subcontract"] / "협력업체_신용확인_가이드.md"
            if not target.exists():
                ref_writer = SubcontractorReferenceWriter()
                content = ref_writer.to_markdown()
                writer.write("subcontract", "협력업체_신용확인_가이드.md", content)
                results["subcontract"] = "성공 (신규 생성)"
            else:
                results["subcontract"] = "건너뜀 (기존 파일 유지)"
        except Exception as e:
            results["subcontract"] = f"실패: {e}"
            errors.append(f"협력업체: {e}")

    success = len(errors) == 0
    summary = "Obsidian 동기화 완료" if success else f"Obsidian 동기화 부분 완료 (오류 {len(errors)}건)"
    logger.info("=== %s ===", summary)
    for k, v in results.items():
        logger.info("  [%s] %s", k, v)

    return {"success": success, "results": results, "errors": errors, "summary": summary}


# ──────────────────────── CLI 진입점 ─────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Obsidian 업무 참고 정보 자동 동기화")
    parser.add_argument("--rates",      action="store_true", help="환율만 동기화")
    parser.add_argument("--news",       action="store_true", help="뉴스만 동기화")
    parser.add_argument("--law",        action="store_true", help="법령만 동기화")
    parser.add_argument("--stats",      action="store_true", help="건설비용지표만 동기화")
    parser.add_argument("--subcontract",action="store_true", help="협력업체 가이드만 생성")
    args = parser.parse_args()

    # 특정 옵션 없으면 전체 실행
    all_mode = not any([args.rates, args.news, args.law, args.stats, args.subcontract])

    result = run_obsidian_sync(
        do_rates=      all_mode or args.rates,
        do_news=       all_mode or args.news,
        do_law=        all_mode or args.law,
        do_stats=      all_mode or args.stats,
        do_subcontract=all_mode or args.subcontract,
    )

    print("\n=== 동기화 결과 ===")
    for k, v in result["results"].items():
        print(f"  {k:15s} : {v}")
    if result["errors"]:
        print("\n오류:")
        for e in result["errors"]:
            print(f"  ✗ {e}")
    print(f"\n{'✓' if result['success'] else '△'} {result['summary']}")
    print(f"  Obsidian vault: {VAULT_PATH}")

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
