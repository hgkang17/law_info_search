"""판례 생사 확인. 후속 판결의 변경·폐기 문구를 스캔한다."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import molit_cgm_expc_api as api
from llm.case_sources import CASE_SOURCES
from utils.case_numbers import extract_case_numbers, field_has_exact_case
from utils.precedent_scan import extract_holding, scan_treatment

_PREC = CASE_SOURCES["prec"]
_NOT_FOUND = "[NOT_FOUND]"


def _to_ymd(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _is_en_banc(title: str, judgment_type: str = "") -> bool:
    return "전원합의체" in f"{title} {judgment_type}"


def _prec_item(node) -> dict:
    return {
        "id": api._find_text(node, _PREC["id"]),
        "title": api._find_text(node, _PREC["title"]),
        "number": api._find_text(node, _PREC["number"]),
        "date": api._find_text(node, _PREC["date"]),
        "court": api._find_text(node, "법원명"),
        "judgment_type": api._find_text(node, "판결유형"),
    }


def _prec_detail(oc_key: str, item_id: str) -> dict:
    root = api.get_detail(oc_key, item_id, target="prec")
    return {
        "판시사항": api._find_text(root, "판시사항"),
        "판결요지": api._find_text(root, "판결요지"),
        "참조판례": api._find_text(root, "참조판례"),
        "판례내용": api._find_text(root, "판례내용"),
        "사건번호": api._find_text(root, "사건번호"),
    }


def run_cite_check(
    oc_key: str,
    case_number: str,
    display: int = 20,
    deep_scan: bool = True,
) -> str:
    candidates = extract_case_numbers(case_number)
    if not candidates:
        return (
            f"{_NOT_FOUND} '{case_number}'에서 사건번호를 추출하지 못했습니다. "
            "예: 2013다61381, 96누4671, 2018두42559. 추측하지 마세요."
        )
    case_no = candidates[0]
    target_root = api.search_list(
        oc_key, target="prec", nb=case_no, display=10
    )
    items = [_prec_item(node) for node in api.iter_xml_items(target_root, "prec")]
    exact = [
        item
        for item in items
        if case_no in (item["number"] or "").replace(" ", "")
    ]
    pool = exact or items
    target = next((item for item in pool if "대법원" in item["court"]), None)
    if target is None and pool:
        target = pool[0]
    if not target or not target.get("id"):
        return (
            f"{_NOT_FOUND} 사건번호 '{case_no}' 판례를 법제처에서 찾지 "
            "못했습니다. 수록분은 대법원 중심이라 하급심은 부존재로 "
            "단정하지 마세요. search_cases(source=prec)로 키워드 검색하세요."
        )

    citing_root = None
    target_detail: dict = {}

    def load_target() -> dict:
        return _prec_detail(oc_key, target["id"])

    def load_citing():
        return api.search_list(
            oc_key,
            query=case_no,
            search=2,
            display=50,
            target="prec",
        )

    with ThreadPoolExecutor(max_workers=2) as pool_exec:
        future_detail = pool_exec.submit(load_target)
        future_citing = pool_exec.submit(load_citing)
        try:
            target_detail = future_detail.result()
        except Exception:
            target_detail = {}
        citing_root = future_citing.result()

    citing = []
    for node in api.iter_xml_items(citing_root, "prec"):
        item = _prec_item(node)
        if not item["id"] or item["id"] == target["id"]:
            continue
        if (item["number"] or "").replace(" ", "") == case_no:
            continue
        item["en_banc"] = _is_en_banc(item["title"], item["judgment_type"])
        citing.append(item)
    citing.sort(key=lambda item: _to_ymd(item["date"]), reverse=True)

    scan_results: list[dict] = []
    if deep_scan and citing:
        prioritized = sorted(
            citing,
            key=lambda item: (
                0 if item["en_banc"] else 1,
                0 if "대법원" in item["court"] else 1,
                0 - int(_to_ymd(item["date"]) or 0),
            ),
        )[:3]
        details: dict[str, dict] = {}

        def load_one(item: dict) -> tuple[str, dict]:
            return item["id"], _prec_detail(oc_key, item["id"])

        with ThreadPoolExecutor(max_workers=min(3, len(prioritized))) as pool_exec:
            futures = [pool_exec.submit(load_one, item) for item in prioritized]
            for future in as_completed(futures):
                try:
                    item_id, detail = future.result()
                    details[item_id] = detail
                except Exception:
                    continue
        for item in prioritized:
            body = (details.get(item["id"]) or {}).get("판례내용") or ""
            if not body:
                continue
            signals, context = scan_treatment(body, case_no)
            scan_results.append(
                {"item": item, "signals": signals, "context": context}
            )

    changed = [row for row in scan_results if row["signals"]]
    en_banc_citing = [item for item in citing if item["en_banc"]]
    scanned_ids = {row["item"]["id"] for row in scan_results}
    en_banc_unscanned = [
        item for item in en_banc_citing if item["id"] not in scanned_ids
    ]
    if changed:
        parts = [
            f"{row['item']['number']}({', '.join(row['signals'])})"
            for row in changed
        ]
        verdict = (
            f"변경·폐기 신호 감지 — {'; '.join(parts)}. "
            "이 판례를 현재 법리로 인용하기 전에 해당 후속 판결 전문을 "
            "get_case로 확인하세요."
        )
    elif en_banc_unscanned:
        numbers = ", ".join(item["number"] for item in en_banc_unscanned[:3])
        verdict = (
            f"미스캔 전원합의체 후속 판결 {len(en_banc_unscanned)}건 존재 — "
            f"법리 변경 여부 본문 확인 권장 ({numbers})"
        )
    elif citing:
        extra = (
            f" (전원합의체 {len(en_banc_citing)}건 포함 정밀 스캔 완료)"
            if en_banc_citing
            else ""
        )
        verdict = (
            f"후속 인용 {len(citing)}건, 변경·폐기 신호 미감지 — "
            f"계속 인용되는 것으로 추정{extra}"
        )
    else:
        verdict = (
            "법제처 수록 범위 내 후속 인용 없음 — "
            "미수록 판례의 인용 가능성은 배제하지 못 함"
        )

    ref_cases = [
        number
        for number in extract_case_numbers(target_detail.get("참조판례") or "")
        if number != case_no
    ]
    en_banc_mark = (
        " 전원합의체"
        if _is_en_banc(target["title"], target["judgment_type"])
        else ""
    )
    lines = [
        f"[판례 생사] {case_no}",
        (
            f"대상: {target['court']} {target['date']} 선고 "
            f"{target['number'] or case_no}{en_banc_mark} 판결"
        ),
    ]
    if not field_has_exact_case(target["number"], case_no):
        lines.append(
            f"입력 사건번호와 다른 판례가 특정됨: {case_no} → "
            f"{target['number'] or '(사건번호 없음)'} — "
            "아래 판정은 특정된 판례 기준입니다."
        )
    if target["title"]:
        lines.append(f"사건명: {target['title']}")
    holding = extract_holding(target_detail)
    if holding:
        lines.append(f"{holding[0]}: {holding[1]}")
    lines.append("")
    lines.append(f"판정: {verdict}")

    if citing:
        lines.append("")
        lines.append(f"이 판례를 인용한 후속 판례 ({len(citing)}건, 최신순)")
        limit = max(1, min(int(display or 20), 50))
        for index, item in enumerate(citing[:limit], start=1):
            mark = " [전원합의체]" if item["en_banc"] else ""
            title = (item["title"] or "")[:60]
            lines.append(
                f"  {index}. {item['court']} {item['date']} "
                f"{item['number']}{mark} — {title}"
            )
        if len(citing) > limit:
            lines.append(f"  … 외 {len(citing) - limit}건")

    if scan_results:
        lines.append("")
        lines.append(f"본문 정밀 스캔 ({len(scan_results)}건)")
        for row in scan_results:
            if row["signals"]:
                mark = ", ".join(row["signals"])
            else:
                mark = "인용 확인 (변경 문구 없음)"
            lines.append(f"  - {row['item']['number']}: {mark}")
            if row["context"]:
                lines.append(f"    맥락: …{row['context']}…")

    if ref_cases:
        lines.append("")
        lines.append(f"이 판례가 인용한 판례 (참조판례 {len(ref_cases)}건)")
        lines.append(f"  {', '.join(ref_cases)}")
        lines.append('  각 판례의 생사 확인: cite_check(case_number="...")')

    lines.append("")
    lines.append(
        "한계: 법제처 수록 판례(대법원 중심) 범위 내 검색입니다. "
        "하급심·미수록 판례의 인용은 포함되지 않으며, 변경 신호 감지는 "
        "휴리스틱입니다. 최종 확인은 후속 판결 전문(get_case)을 읽으세요."
    )
    return "\n".join(lines)
