"""행정규칙 본문 안의 법제처 표 이미지 회귀 테스트."""

from __future__ import annotations

import base64
from types import SimpleNamespace

import molit_cgm_expc_api as api
from PySide6.QtWidgets import QApplication
from utils.formatting import body_to_html
from utils.parsing import (
    admin_rule_plain_text,
    admin_rule_text,
    normalize_admin_rule_text,
)


def test_admin_rule_image_tags_keep_their_document_positions() -> None:
    source = (
        '1. 사업별 요율표<img id="158685505"></img>'
        '<img id="158685507"></img>* 공사계약 주석'
    )

    normalized = normalize_admin_rule_text(admin_rule_text(source))

    assert normalized.splitlines() == [
        "1. 사업별 요율표",
        "[[LAW_IMAGE:158685505]]",
        "[[LAW_IMAGE:158685507]]",
        "* 공사계약 주석",
    ]


def test_admin_rule_text_reads_structured_articles_and_appendix() -> None:
    assert admin_rule_text(
        {"조문내용": ["제1조(목적) 첫 조문", "제2조(적용) 둘째 조문"]}
    ) == "제1조(목적) 첫 조문\n제2조(적용) 둘째 조문"
    assert admin_rule_text(
        {"부칙내용": ["부칙 제1호", "이 규정은 발령한 날부터 시행한다."]}
    ) == "부칙 제1호\n이 규정은 발령한 날부터 시행한다."


def test_admin_rule_images_render_and_missing_image_has_official_link() -> None:
    _app = QApplication.instance() or QApplication([])
    value = "\n".join(
        (
            "1. 사업별 요율표",
            "[[LAW_IMAGE:158685505]]",
            "[[LAW_IMAGE:158685507]]",
        )
    )
    image_uri = "data:image/gif;base64,R0lGODlhAQABAAAAACw="

    html = body_to_html(
        value,
        administrative_rule=True,
        administrative_rule_normalized=True,
        embedded_images={"158685505": image_uri},
    )

    assert f'src="{image_uri}"' in html
    assert "flDownload.do?flSeq=158685507" in html
    assert "[[LAW_IMAGE:" not in html
    assert "[[LAW_IMAGE:" not in admin_rule_plain_text(value)
    assert admin_rule_plain_text(value).count("[원문 표 이미지]") == 2


def test_attach_admin_rule_images_downloads_each_id_once(monkeypatch) -> None:
    calls: list[str] = []

    def fake_request(_url, params, **_kwargs):
        image_id = str(params["flSeq"])
        calls.append(image_id)
        return SimpleNamespace(
            content=f"gif-{image_id}".encode(),
            headers={"Content-Type": "image/gif;;charset=UTF-8"},
        )

    monkeypatch.setattr(api, "_request", fake_request)
    payload = {
        "AdmRulService": {
            "조문": {
                "조문내용": [
                    '표<img id="10"></img><img id="10"></img>',
                    '<img id="20"></img>',
                ]
            }
        }
    }

    returned = api.attach_admin_rule_images(payload)

    assert returned is payload
    assert sorted(calls) == ["10", "20"]
    embedded = payload[api.ADMIN_RULE_IMAGES_KEY]
    assert base64.b64decode(embedded["10"].split(",", 1)[1]) == b"gif-10"
    assert base64.b64decode(embedded["20"].split(",", 1)[1]) == b"gif-20"


def test_attach_admin_rule_images_ignores_non_image_response(monkeypatch) -> None:
    monkeypatch.setattr(
        api,
        "_request",
        lambda *_args, **_kwargs: SimpleNamespace(
            content=b"<html>error</html>",
            headers={"Content-Type": "text/html"},
        ),
    )
    payload = {
        "AdmRulService": {"조문내용": '<img id="30"></img>'}
    }

    api.attach_admin_rule_images(payload)

    assert api.ADMIN_RULE_IMAGES_KEY not in payload
