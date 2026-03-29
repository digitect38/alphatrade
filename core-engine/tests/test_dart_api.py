"""Tests for DART API disclosure classification.

~80 test cases.
"""

import pytest
from app.services.dart_api import DARTClient


class TestIsMajorDisclosure:
    @pytest.mark.parametrize("report_name", [
        "주요사항보고서",
        "주요사항보고(자율공시)",
        "최대주주변경",
        "최대주주변경 공시",
        "합병 결정",
        "합병 관련 주요사항",
        "분할 결정",
        "회사 분할 공시",
        "유상증자 결정",
        "유상증자 관련",
        "무상증자 결정",
        "전환사채 발행",
        "전환사채권 발행결정",
        "자기주식 취득",
        "자기주식 처분",
        "영업양수 결정",
        "영업양도 결정",
        "임원변경 관련",
        "상장폐지 사유 발생",
        "회생절차 개시",
        "부도 발생",
        "감자 결정",
        "공개매수 신고",
    ])
    def test_major_disclosure_detected(self, report_name):
        assert DARTClient.is_major_disclosure(report_name) is True

    @pytest.mark.parametrize("report_name", [
        "분기보고서 (2026.03)",
        "사업보고서",
        "반기보고서",
        "증권신고서",
        "투자설명서",
        "주주총회소집공고",
        "의결권대리행사권유참고서류",
        "임원·주요주주특정증권등소유상황보고서",
        "타법인주식및출자증권취득결정",
        "연결재무제표기준영업실적등에관한전망",
        "기업설명회(IR)",
        "공정공시",
    ])
    def test_normal_disclosure_not_flagged(self, report_name):
        assert DARTClient.is_major_disclosure(report_name) is False

    def test_empty_string(self):
        assert DARTClient.is_major_disclosure("") is False

    @pytest.mark.parametrize("report_name", [
        "합병",           # exact keyword
        "대규모 합병 결정",  # keyword in middle
        "유상증자결정",     # no space
    ])
    def test_partial_match(self, report_name):
        assert DARTClient.is_major_disclosure(report_name) is True
