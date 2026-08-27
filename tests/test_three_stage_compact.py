"""3단비교 응답을 AI가 읽을 짧은 평문으로 줄인다."""

from utils.three_stage import compact_three_stage


def test_compact_three_stage_lists_delegated_articles() -> None:
    payload = {
        "LawService": {
            "위임조문삼단비교": {
                "법률조문": [
                    {
                        "조번호": "2",
                        "시행령조문": {
                            "법령명": "국토의 계획 및 이용에 관한 법률 시행령",
                            "조번호": "4",
                            "조제목": "도시·군관리계획",
                        },
                        "시행규칙조문": {
                            "법령명": "국토의 계획 및 이용에 관한 법률 시행규칙",
                            "조번호": "5",
                        },
                    }
                ]
            }
        }
    }
    text = compact_three_stage(payload)
    assert "[3단비교 위임]" in text
    assert "국토의 계획 및 이용에 관한 법률 시행령" in text
    assert "시행령 제4조(도시·군관리계획)" in text
    assert "시행규칙 제5조" in text
    assert "get_article" in text


def test_compact_three_stage_empty_payload() -> None:
    assert compact_three_stage({}) == ""
    assert compact_three_stage(None) == ""
