"""검색·본문 조회를 배경 스레드에서 수행한다. 화면이 멈추지 않게."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QWidget
from models.law import (
    AI_RELATED_AGENCY,
    AI_SEARCH_AGENCY,
    RESOURCE_ALL_TARGET,
    RESOURCE_CATEGORIES,
)
from molit_cgm_expc_api import (
    AgencyConfig,
    get_detail,
    get_historical_law,
    get_law_article,
    get_resource_detail,
    get_three_stage_comparison,
    search_agency_scopes,
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


def administrative_rule_detail_id(
    oc: str,
    name: str,
    *,
    rule_id: str = "",
    issue_date: str = "",
    issue_number: str = "",
) -> str:
    """연관검색의 행정규칙 ID를 본문용 일련번호로 바꾼다.

    aiRltLs/aiSearch 응답의 ``행정규칙ID``는 admrul 본문 API가 받는
    ``행정규칙일련번호``와 서로 다르다. 행정규칙 목록에서 같은 규칙을
    다시 찾되, 개정 이력이나 동명 규칙이 섞이면 원래 결과의 IDㆍ발령일ㆍ
    발령번호로 후보를 좁힌다.
    """
    name = str(name or "").strip()
    if not name:
        raise ValueError("행정규칙명이 없습니다.")
    payload = search_resource(oc, "admrul", name, display=100)
    root = payload.get("AdmRulSearch", {})
    candidates = (
        [item for item in json_list(root.get("admrul")) if isinstance(item, dict)]
        if isinstance(root, dict)
        else []
    )
    expected_name = re.sub(r"\s+", "", name)
    candidates = [
        item
        for item in candidates
        if re.sub(r"\s+", "", json_text(item.get("행정규칙명")))
        == expected_name
    ]
    if not candidates:
        raise ValueError("같은 이름의 행정규칙을 찾지 못했습니다.")

    def narrow(field: str, expected: str, normalize) -> None:
        nonlocal candidates
        wanted = normalize(expected)
        if not wanted:
            return
        matched = [
            item
            for item in candidates
            if normalize(json_text(item.get(field))) == wanted
        ]
        if matched:
            candidates = matched

    def compact(value: str) -> str:
        return re.sub(r"\s+", "", str(value or ""))

    def digits(value: str) -> str:
        return re.sub(r"\D", "", str(value or ""))

    def issue_key(value: str) -> str:
        return re.sub(r"[\s제호]", "", str(value or "")).casefold()

    narrow("행정규칙ID", rule_id, compact)
    narrow("발령일자", issue_date, digits)
    narrow("발령번호", issue_number, issue_key)

    item_id = json_text(candidates[0].get("행정규칙일련번호"))
    if not item_id:
        raise ValueError("행정규칙 본문 조회 ID가 없습니다.")
    return item_id


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
                item_id = administrative_rule_detail_id(
                    self.oc,
                    name,
                    rule_id=str(self.row.get("source_id") or ""),
                    issue_date=str(self.row.get("publication_date") or ""),
                    issue_number=str(self.row.get("publication_number") or ""),
                )
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
        resolve_admrul_id: bool = False,
        issue_date: str = "",
        issue_number: str = "",
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
        self.resolve_admrul_id = resolve_admrul_id
        self.issue_date = issue_date
        self.issue_number = issue_number
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
                    # 통합검색은 목록 검색뿐 아니라 연관검색ㆍ직접검색까지
                    # 한 번에 묶어 보여 준다. 한쪽이 실패해도 나머지 결과는
                    # 그대로 내보낸다.
                    keyword_roots: list[object] = []
                    try:
                        roots, agency_errors = search_agency_scopes(
                            self.oc,
                            (
                                (AI_RELATED_AGENCY, 0),
                                (AI_RELATED_AGENCY, 1),
                                (AI_SEARCH_AGENCY, 1),
                            ),
                            query=self.query,
                            display=100,
                        )
                        keyword_roots = roots
                        errors.extend(
                            f"{agency.name}: {message}"
                            for agency, message in agency_errors
                        )
                    except Exception as exc:
                        errors.append(f"연관검색ㆍ직접검색: {exc}")
                    result = {
                        "integrated_results": results,
                        "keyword_roots": keyword_roots,
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
                item_id = self.item_id
                if self.resolve_admrul_id:
                    item_id = administrative_rule_detail_id(
                        self.oc,
                        self.law_name,
                        rule_id=self.item_id,
                        issue_date=self.issue_date,
                        issue_number=self.issue_number,
                    )
                result = get_resource_detail(
                    self.oc,
                    self.detail_target,
                    item_id,
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
