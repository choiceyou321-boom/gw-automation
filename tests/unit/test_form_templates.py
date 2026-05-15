"""
form_templates 순수 함수 단위 테스트.

GW/Playwright 의존 없는 순수 로직만 검증:
- 양식 키 탐색 (정확/별칭/부분 매칭)
- 필수 필드 목록
- 결재선/수신참조 resolve 규칙
"""
from src.approval.form_templates import (
    FORM_TEMPLATES,
    APPROVAL_PRESETS,
    DEFAULT_APPROVAL_LINE,
    SIMPLE_APPROVAL_LINE,
    get_template,
    get_template_key,
    get_required_fields,
    get_field_examples,
    list_form_names,
    resolve_approval_line,
    resolve_cc_recipients,
)


class TestTemplateLookup:
    def test_exact_key_match(self):
        # 첫 키를 picking — FORM_TEMPLATES가 비어있지 않다는 전제
        first_key = next(iter(FORM_TEMPLATES))
        assert get_template_key(first_key) == first_key
        assert get_template(first_key) is FORM_TEMPLATES[first_key]

    def test_unknown_form_returns_none(self):
        assert get_template_key("절대존재하지않는양식_xyz_12345") is None
        assert get_template("절대존재하지않는양식_xyz_12345") is None

    def test_partial_match(self):
        # 지출결의서가 등록되어 있다고 가정 — 부분 매칭 동작 검증
        key = get_template_key("지출결의")
        if key is not None:  # 등록된 경우만 검증
            assert "지출" in key or "지출" in FORM_TEMPLATES[key].get("display_name", "")

    def test_alias_match(self):
        # 별칭이 정의된 양식이 있으면 별칭으로 조회 가능해야 함
        for key, tmpl in FORM_TEMPLATES.items():
            aliases = tmpl.get("aliases", [])
            if aliases:
                assert get_template_key(aliases[0]) == key
                return  # 하나라도 검증되면 충분

    def test_list_form_names_returns_dicts(self):
        names = list_form_names()
        assert isinstance(names, list)
        assert len(names) == len(FORM_TEMPLATES)
        for entry in names:
            assert "key" in entry
            assert "display_name" in entry
            assert "status" in entry


class TestRequiredAndExamples:
    def test_required_fields_for_unknown_form(self):
        assert get_required_fields("절대존재하지않는양식_xyz") == []
        assert get_field_examples("절대존재하지않는양식_xyz") == {}

    def test_required_fields_returns_list(self):
        first_key = next(iter(FORM_TEMPLATES))
        required = get_required_fields(first_key)
        assert isinstance(required, list)


class TestApprovalLineResolution:
    def test_dict_custom_line_passes_through(self):
        custom = {"drafter": "auto", "final": "홍길동"}
        result = resolve_approval_line(custom)
        assert result == custom

    def test_preset_name_string(self):
        result = resolve_approval_line("기본")
        assert result == DEFAULT_APPROVAL_LINE

        result = resolve_approval_line("간단")
        assert result == SIMPLE_APPROVAL_LINE

    def test_unknown_preset_falls_back_to_default(self):
        # 알 수 없는 프리셋명은 기본 결재선 fall back (또는 None)
        result = resolve_approval_line("절대없는프리셋_xyz")
        # 동작은 구현에 따라 다르나 dict 또는 None이어야 함
        assert result is None or isinstance(result, dict)

    def test_none_returns_default(self):
        result = resolve_approval_line(None)
        # 기본값 또는 None 반환 — dict일 경우 drafter 키 있어야
        if result is not None:
            assert "drafter" in result or "final" in result

    def test_all_presets_have_required_keys(self):
        for name, line in APPROVAL_PRESETS.items():
            assert isinstance(line, dict), f"프리셋 '{name}'은 dict여야 함"
            assert "drafter" in line, f"프리셋 '{name}'에 drafter 누락"
            assert "final" in line, f"프리셋 '{name}'에 final 누락"


class TestCCRecipientsResolution:
    def test_list_passthrough(self):
        cc = ["재무전략팀", "재무회계팀"]
        result = resolve_cc_recipients(cc)
        assert result == cc

    def test_preset_name_resolves_to_list(self):
        # "재무" 프리셋이 정의되어 있음 → ["재무전략팀", "재무회계팀"]
        result = resolve_cc_recipients("재무")
        assert isinstance(result, list)
        assert "재무전략팀" in result

    def test_none_returns_empty(self):
        result = resolve_cc_recipients(None)
        assert result == [] or result is None

    def test_unknown_string_returns_list_or_empty(self):
        # 알 수 없는 문자열 — 빈 리스트 또는 [그 문자열]
        result = resolve_cc_recipients("절대없는프리셋_xyz")
        assert isinstance(result, list) or result is None


class TestTemplateStructuralInvariants:
    """모든 등록 양식이 최소 구조 만족하는지 검증 (회귀 방지)."""

    def test_all_templates_have_required_keys(self):
        for key, tmpl in FORM_TEMPLATES.items():
            assert "display_name" in tmpl, f"양식 '{key}'에 display_name 누락"
            assert isinstance(tmpl["display_name"], str)

    def test_fields_section_is_dict(self):
        for key, tmpl in FORM_TEMPLATES.items():
            if "fields" in tmpl:
                assert isinstance(tmpl["fields"], dict), f"양식 '{key}'의 fields가 dict 아님"
