"""CRM 도메인 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class BusinessCard:
    """명함 OCR 결과 — 자동 추출된 구조화 정보."""
    name: str = ""
    company: str = ""
    department: str = ""
    title: str = ""           # 직책 (예: 과장, 대표)
    email: str = ""
    phone_mobile: str = ""    # 휴대폰
    phone_office: str = ""    # 사무실 전화
    fax: str = ""
    address: str = ""
    website: str = ""
    raw_text: str = ""        # OCR 원본 텍스트 (디버그용)
    confidence: float = 0.0   # 0.0~1.0 (OCR 신뢰도)
    image_path: str = ""      # 원본 이미지 파일 경로

    def as_dict(self) -> dict:
        return {
            "name": self.name, "company": self.company,
            "department": self.department, "title": self.title,
            "email": self.email,
            "phone_mobile": self.phone_mobile, "phone_office": self.phone_office,
            "fax": self.fax, "address": self.address, "website": self.website,
            "raw_text": self.raw_text, "confidence": self.confidence,
            "image_path": self.image_path,
        }


@dataclass
class Contact:
    """DB에 저장된 연락처 (BusinessCard + 메타데이터)."""
    id: Optional[int] = None
    name: str = ""
    company: str = ""
    department: str = ""
    title: str = ""
    email: str = ""
    phone_mobile: str = ""
    phone_office: str = ""
    fax: str = ""
    address: str = ""
    website: str = ""
    note: str = ""                    # 사용자 메모
    tags: list[str] = field(default_factory=list)
    owner_gw_id: str = ""             # 이 연락처를 등록한 사용자 GW ID
    google_resource_name: str = ""    # Google Contacts 리소스 ID (동기화 시)
    project_codes: list[str] = field(default_factory=list)  # 연결된 GS-YY-XXXX
    image_path: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
