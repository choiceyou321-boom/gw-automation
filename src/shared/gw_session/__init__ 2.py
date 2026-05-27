"""
shared/gw_session — 그룹웨어 세션 추상화 레이어

목적:
  - 더존 Amaranth10 외에 영림원/이카운트 등 다른 그룹웨어로 갈아끼울 수 있도록
    IGroupwareProvider Protocol 으로 GW 접근 코드를 추상화한다.

구성:
  - interface.py   : IGroupwareProvider Protocol + 데이터 클래스
  - selectors.py   : GW 페이지/셀렉터 자산 사전 (Track A에서 발견하는 대로 확장)
  - douzone.py     : DouzoneAmaranth10Provider (현재 구현)

사용:
    from src.shared.gw_session import get_provider, GW_PAGES, EXCEL_DOWNLOAD
    gw = get_provider().restore_session("tgjeon")
    result = gw.export_xlsx("예실대비현황_상세")
"""

from src.shared.gw_session.interface import (
    Module,
    GWPage,
    ExportResult,
    IGroupwareProvider,
)
from src.shared.gw_session.selectors import (
    EXCEL_DOWNLOAD,
    HOME_MODULE_LINK,
    OBT_DATA_GRID,
    HAMBURGER_COORDS,
    GW_MODULES,
    GW_PAGES,
    INQUIRY_BUTTONS,
    DOWNLOAD_MODAL_BUTTONS,
)


def get_provider() -> IGroupwareProvider:
    """현재 활성 GW Provider 반환.

    설정에 따라 다른 Provider를 반환할 수 있도록 구성하나,
    현재 단계에서는 DouzoneAmaranth10Provider 로 고정.
    """
    from src.shared.gw_session.douzone import DouzoneAmaranth10Provider
    return DouzoneAmaranth10Provider()


__all__ = [
    "get_provider",
    # interface
    "Module", "GWPage", "ExportResult", "IGroupwareProvider",
    # selectors
    "EXCEL_DOWNLOAD", "HOME_MODULE_LINK", "OBT_DATA_GRID", "HAMBURGER_COORDS",
    "GW_MODULES", "GW_PAGES", "INQUIRY_BUTTONS", "DOWNLOAD_MODAL_BUTTONS",
]
