"""리팩터링 전후 성능 비교용 측정 스크립트.

- 모듈 임포트 시간
- 앱 기동(창 생성) 시간과 메모리
- 본문 렌더링(파싱 → HTML → QTextBrowser 표시) 구간별 시간
- 인용 링크 변환·행정규칙 줄바꿈 보정 처리량

네트워크 없이 로컬 캐시 자료만 사용한다.
"""

from __future__ import annotations

import gc
import json
import os
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_DIR = Path(__file__).resolve().parent
RESULTS_PATH = APP_DIR / "perf_baseline_result.json"


def timed(function, *args, **kwargs) -> tuple[float, object]:
    start = time.perf_counter()
    value = function(*args, **kwargs)
    return (time.perf_counter() - start) * 1000, value


def repeat(function, rounds: int = 5) -> dict[str, float]:
    """여러 번 재서 중앙값을 쓴다(첫 회는 캐시 효과가 커서 따로 남김)."""
    samples = [timed(function)[0] for _ in range(rounds)]
    return {
        "first_ms": round(samples[0], 2),
        "median_ms": round(statistics.median(samples), 2),
        "min_ms": round(min(samples), 2),
        "max_ms": round(max(samples), 2),
    }


def process_memory_mb() -> float:
    try:
        import psutil  # type: ignore

        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


def main() -> None:
    report: dict[str, object] = {
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "python": sys.version.split()[0],
        "source_lines": sum(
            sum(1 for _ in path.open(encoding="utf-8"))
            for directory in (
                "ui",
                "utils",
                "workers",
                "storage",
                "models",
                "llm",
            )
            for path in (APP_DIR / directory).rglob("*.py")
        ),
    }

    import_ms, module = timed(__import__, "molit_cgm_expc_qt")
    report["import_ms"] = round(import_ms, 2)

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    tracemalloc.start()
    memory_before = process_memory_mb()
    window_ms, window = timed(module.LawSearchWindow)
    window.resize(1400, 900)
    window.show()
    app.processEvents()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    report["window_create_ms"] = round(window_ms, 2)
    report["window_rss_delta_mb"] = round(process_memory_mb() - memory_before, 2)
    report["window_python_peak_mb"] = round(peak / (1024 * 1024), 2)

    # --- 저장된 법령 본문으로 렌더링 측정 -----------------------------
    # 저장소에 둔 개발용 표본으로 잰다. 프로그램이 실행 중에 쓰는 자리
    # (storage.paths.LAW_CACHE_DIR)는 사용자 폴더라 기계마다 내용이 달라
    # 측정값을 비교할 수 없다.
    cache_dir = APP_DIR / "# law 캐시" / "저장내역"
    records = sorted(cache_dir.glob("*.json"), key=lambda p: p.stat().st_size)
    if records:
        biggest = records[-1]
        load_ms, payload = timed(
            lambda: json.loads(biggest.read_text(encoding="utf-8"))
        )
        html = str(payload.get("rendered_html") or "")
        report["sample_record"] = {
            "file": biggest.name,
            "file_kb": round(biggest.stat().st_size / 1024, 1),
            "html_kb": round(len(html.encode("utf-8")) / 1024, 1),
            "json_load_ms": round(load_ms, 2),
        }
        report["json_load"] = repeat(
            lambda: json.loads(biggest.read_text(encoding="utf-8")), rounds=3
        )
        if html:
            tab = window.resource_tab
            browser = tab.detail_view

            def render() -> None:
                browser.setHtml(html)
                browser.document().adjustSize()
                app.processEvents()

            report["detail_setHtml"] = repeat(render, rounds=3)

        # 사용자가 실제로 겪는 "저장 본문 열기" 전체 구간
        row = payload.get("row")
        if isinstance(row, dict):
            tab = window.resource_tab

            def open_saved() -> None:
                tab.open_cached_law(dict(payload), clear_highlights=False)
                app.processEvents()

            report["open_cached_law"] = repeat(open_saved, rounds=3)

    # --- 조문 캐시로 인용 링크 변환 측정 -------------------------------
    article_dir = APP_DIR / "# law 캐시" / "조문"
    articles = sorted(article_dir.glob("*.json"), key=lambda p: p.stat().st_size)
    if articles:
        text_source = json.loads(articles[-1].read_text(encoding="utf-8"))
        sample_text = str(text_source.get("html") or "")[:20000]
        if sample_text:
            report["law_reference_html_text"] = repeat(
                lambda: module.law_reference_html_text(
                    sample_text,
                    (),
                    current_law_name="국토의 계획 및 이용에 관한 법률 시행규칙",
                    current_law_id="009469",
                    use_api_links=True,
                ),
                rounds=5,
            )

    # --- 행정규칙 줄바꿈 보정 측정 -------------------------------------
    guideline = APP_DIR / "perf_sample_guideline.txt"
    if guideline.is_file():
        body = guideline.read_text(encoding="utf-8")
        report["guideline_chars"] = len(body)
        report["insert_admin_clause_breaks"] = repeat(
            lambda: module.insert_admin_clause_breaks(body), rounds=5
        )
        report["normalize_and_body_to_html_admin"] = repeat(
            lambda: module.body_to_html(
                module.normalize_admin_rule_text(body),
                (),
                use_api_links=True,
                administrative_rule=True,
                administrative_rule_normalized=True,
            ),
            rounds=3,
        )

    gc.collect()
    report["gc_objects"] = len(gc.get_objects())

    RESULTS_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
