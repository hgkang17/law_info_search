"""검색·본문 조회를 배경 스레드에서 수행한다. 화면이 멈추지 않게."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QWidget
from models.law import RESOURCE_ALL_TARGET, RESOURCE_CATEGORIES
from molit_cgm_expc_api import (
    AgencyConfig,
    get_detail,
    get_historical_law,
    get_law_article,
    get_resource_detail,
    get_three_stage_comparison,
    search_agencies,
    search_resource,
)
from utils.parsing import (
    choose_law_reference_row,
    json_list,
    json_text,
    law_payload_has_body,
    resolve_law_reference_row,
    slice_law_detail_to_article,
)
import re
import xml.etree.ElementTree as ET


def named_law_reference_row(oc: str, law_name: str) -> dict[str, object]:
    """인용 법령명을 현행에서 찾고, 없으면 연혁(eflaw)에서 같은 이름을 찾는다."""
    try:
        return resolve_law_reference_row(
            search_resource(oc, "law", law_name, display=100),
            law_name,
        )
    except ValueError:
        row = resolve_law_reference_row(
            search_resource(oc, "eflaw", law_name, display=100),
            law_name,
        )
        return {**row, "from_history": True}


def load_law_reference_payload(
    oc: str,
    row: dict[str, object],
    *,
    jo: str = "",
    hang: str = "",
    ho: str = "",
    mok: str = "",
) -> dict:
    """조문 팝업용 본문. 현행에 없으면 연혁에서 찾은 행은 그 시행일로 읽는다."""
    resolved_id = str(row["id"])
    payload: object = {}
    try:
        if jo:
            payload = get_law_article(
                oc, resolved_id, jo, hang=hang, ho=ho, mok=mok
            )
        else:
            payload = get_resource_detail(oc, "eflaw", resolved_id)
    except Exception:
        if not row.get("from_history"):
            raise
        payload = {}
    if law_payload_has_body(payload) or not row.get("from_history"):
        return payload if isinstance(payload, dict) else {}
    date = str(row.get("effective") or "").strip()
    if not date:
        return payload if isinstance(payload, dict) else {}
    historical = get_historical_law(
        oc,
        resolved_id,
        date=date,
        jo=jo,
        mst=str(row.get("mst") or ""),
    )
    if not law_payload_has_body(historical):
        return payload if isinstance(payload, dict) else historical
    if jo:
        sliced = slice_law_detail_to_article(historical, jo, hang, ho, mok)
        return sliced if isinstance(sliced, dict) else historical
    return historical


class ApiWorker(QThread):
    """네트워크 요청으로 UI가 멈추지 않도록 하는 작업 스레드."""

    succeeded = Signal(str, object)
    failed = Signal(str, str)

    def __init__(
        self,
        operation: str,
        *,
        oc: str,
        query: str = "",
        search_scope: int = 1,
        item_id: str = "",
        agencies: tuple[AgencyConfig, ...] = (),
        agency: AgencyConfig | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.operation = operation
        self.oc = oc
        self.query = query
        self.search_scope = search_scope
        self.item_id = item_id
        self.agencies = agencies
        self.agency = agency

    def run(self) -> None:
        try:
            if self.operation == "search":
                roots, errors = search_agencies(
                    self.oc,
                    self.agencies,
                    query=self.query,
                    search=self.search_scope,
                    display=100,
                )
                result = {"roots": roots, "errors": errors}
            else:
                if self.agency is None:
                    raise ValueError("본문을 조회할 기관 정보가 없습니다.")
                root = get_detail(
                    self.oc,
                    self.item_id,
                    target=self.agency.target,
                )
                result = {"root": root, "agency": self.agency}
            self.succeeded.emit(self.operation, result)
        except Exception as exc:  # GUI에서 네트워크·파싱 오류를 안내
            self.failed.emit(self.operation, str(exc))


class RelatedArticleWorker(QThread):
    """연관법령 결과의 실제 법령·행정규칙 조문을 추가 조회."""

    succeeded = Signal(str, object)
    failed = Signal(str, str)

    def __init__(
        self,
        *,
        oc: str,
        row_index: int,
        row: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.operation = "related_article"
        self.oc = oc
        self.row_index = row_index
        self.row = dict(row)

    def run(self) -> None:
        try:
            is_admin = str(self.row.get("kind") or "").startswith("행정규칙")
            if is_admin:
                name = str(self.row.get("name") or "")
                search_payload = search_resource(
                    self.oc, "admrul", name, display=100
                )
                root = search_payload.get("AdmRulSearch", {})
                candidates = (
                    json_list(root.get("admrul"))
                    if isinstance(root, dict)
                    else []
                )
                expected = re.sub(r"\s+", "", name)
                matched = next(
                    (
                        candidate
                        for candidate in candidates
                        if isinstance(candidate, dict)
                        and re.sub(
                            r"\s+",
                            "",
                            json_text(candidate.get("행정규칙명")),
                        )
                        == expected
                    ),
                    None,
                )
                if not isinstance(matched, dict):
                    raise ValueError("같은 이름의 행정규칙을 찾지 못했습니다.")
                item_id = json_text(matched.get("행정규칙일련번호"))
                if not item_id:
                    raise ValueError("행정규칙 본문 조회 ID가 없습니다.")
                payload = get_resource_detail(
                    self.oc, "admrul", item_id, id_param="ID"
                )
                target = "admrul"
            else:
                item_id = str(self.row.get("source_id") or "")
                jo = str(self.row.get("jo_code") or "")
                if not item_id or not jo:
                    raise ValueError("법령 ID 또는 조문 번호가 없습니다.")
                payload = get_law_article(self.oc, item_id, jo)
                target = "law"
            self.succeeded.emit(
                self.operation,
                {
                    "row_index": self.row_index,
                    "target": target,
                    "payload": payload,
                },
            )
        except Exception as exc:
            self.failed.emit(self.operation, str(exc))


class ResourceApiWorker(QThread):
    """법령·행정규칙·자치법규의 JSON 목록/본문 요청 스레드."""

    succeeded = Signal(str, object)
    failed = Signal(str, str)

    def __init__(
        self,
        operation: str,
        *,
        oc: str,
        target: str,
        query: str = "",
        search_scope: int = 1,
        item_id: str = "",
        detail_target: str = "",
        id_param: str = "ID",
        law_name: str = "",
        jo: str = "",
        hang: str = "",
        ho: str = "",
        mok: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.operation = operation
        self.oc = oc
        self.target = target
        self.query = query
        self.search_scope = search_scope
        self.item_id = item_id
        self.detail_target = detail_target
        self.id_param = id_param
        self.law_name = law_name
        self.jo = jo
        self.hang = hang
        self.ho = ho
        self.mok = mok

    def run(self) -> None:
        try:
            if self.operation == "resource_search":
                if self.target == RESOURCE_ALL_TARGET:
                    results: dict[str, object] = {}
                    errors: list[str] = []
                    for target, config in RESOURCE_CATEGORIES.items():
                        try:
                            results[target] = search_resource(
                                self.oc,
                                target,
                                self.query,
                                search_scope=1,
                                display=100,
                            )
                        except Exception as exc:
                            errors.append(f"{config['label']}: {exc}")
                    result = {
                        "integrated_results": results,
                        "errors": errors,
                    }
                else:
                    result = search_resource(
                        self.oc,
                        self.target,
                        self.query,
                        search_scope=self.search_scope,
                        display=100,
                    )
            elif self.operation in (
                "resource_detail",
                "document_reference_detail",
            ):
                result = get_resource_detail(
                    self.oc,
                    self.detail_target,
                    self.item_id,
                    id_param=self.id_param,
                )
            elif self.operation == "law_reference_detail":
                named_row = None
                if self.law_name:
                    try:
                        named_row = named_law_reference_row(
                            self.oc, self.law_name
                        )
                    except ValueError:
                        if not self.item_id:
                            raise
                        named_row = None
                row = choose_law_reference_row(
                    item_id=self.item_id,
                    law_name=self.law_name,
                    named_row=named_row,
                )
                payload = load_law_reference_payload(
                    self.oc,
                    row,
                    jo=self.jo,
                    hang=self.hang,
                    ho=self.ho,
                    mok=self.mok,
                )
                mode = "article" if self.jo else "full"
                result = {
                    "payload": payload,
                    "row": row,
                    "mode": mode,
                    "jo": self.jo,
                    "hang": self.hang,
                    "ho": self.ho,
                    "mok": self.mok,
                }
            elif self.operation == "inquiry_reference_detail":
                root = get_detail(self.oc, self.item_id, target=self.target)
                result = {
                    "xml": ET.tostring(root, encoding="unicode"),
                    "target": self.target,
                    "item_id": self.item_id,
                    "name": self.law_name,
                }
            elif self.operation in ("three_stage_comparison", "three_stage_links"):
                result = {
                    "payload": get_three_stage_comparison(
                        self.oc,
                        self.item_id,
                        comparison_kind=2,
                    ),
                    "item_id": self.item_id,
                    "law_name": self.law_name,
                    "jo": self.jo,
                }
            else:
                raise ValueError(f"지원하지 않는 작업입니다: {self.operation}")
            self.succeeded.emit(self.operation, result)
        except Exception as exc:
            self.failed.emit(self.operation, str(exc))


class AnnexReferenceWorker(QThread):
    """채팅의 별표·서식 링크를 찾아 원문 URL을 돌려준다."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        *,
        oc: str,
        category: str,
        query: str,
        search_scope: int,
        item_id: str = "",
        hint: str = "",
        title: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.oc = oc
        self.category = category
        self.query = query
        self.search_scope = search_scope
        self.item_id = item_id
        self.hint = hint
        self.title = title

    def run(self) -> None:
        try:
            payload = search_resource(
                self.oc,
                self.category,
                self.query,
                search_scope=self.search_scope,
                display=100,
            )
            self.succeeded.emit(
                {
                    "payload": payload,
                    "category": self.category,
                    "item_id": self.item_id,
                    "hint": self.hint,
                    "title": self.title,
                    "query": self.query,
                }
            )
        except Exception as exc:
            self.failed.emit(str(exc))
