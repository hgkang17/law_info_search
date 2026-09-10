"""구버전 저장본 이미지 복구와 번호 본문에 맞춘 이미지 배치."""

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextDocument, QImage
from utils.images import _to_data_uri
from utils.formatting import body_to_html, DETAIL_DOCUMENT_STYLE
from ui.tabs.resource_search import ResourceSearchTab


def test_original_payload_restores_images_missing_from_cached_sections():
    uri = "data:image/png;base64,test"
    record = {
        "administrative_rule_parse_version": 30,
        "administrative_rule_sections": [{"label": "조문", "value": "1-1-1. 이미지가 사라진 저장본"}],
        "detail_payload": {"AdmRulService": {"조문내용": '1-1-1. 원문<img id="123"></img>'}, "_law_go_kr_images": {"123": uri}},
    }
    assert "[[LAW_IMAGE:123]]" in ResourceSearchTab._cached_admrul_sections(record)[0][1]
    assert ResourceSearchTab._admin_rule_images(record)["123"] == uri


def test_image_uses_preceding_numbered_body_indent_and_no_extra_line_height():
    app = QApplication.instance() or QApplication([])
    image = QImage(100, 200, QImage.Format.Format_RGB32)
    image.fill(0xff000000)
    html = body_to_html("1-1-1. 본문\n(1) 하위항목\n[[LAW_IMAGE:123]]\n(2) 다음 항목",
        administrative_rule=True, embedded_images={"123": _to_data_uri(image)})
    document = QTextDocument()
    document.setHtml(DETAIL_DOCUMENT_STYLE + '<div class="content">' + html + '</div>')
    number = document.find("하위항목").block().blockFormat().leftMargin()
    picture = document.find("\ufffc").block()
    assert picture.blockFormat().leftMargin() == number
    assert picture.blockFormat().lineHeight() == 100
    assert document.documentLayout().blockBoundingRect(picture).height() < 215
