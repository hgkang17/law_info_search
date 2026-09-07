from pathlib import Path
import re
import xlsxwriter

source_dir = Path(r"D:\(00-000) 참고\03. 프로그래밍\02. 법령프로그램 AI포함\건축할수 있는 건축물\markdown")
output = source_dir.parent / "건축할수 있는 건축물.xlsx"
files = sorted(source_dir.glob("*.md"), key=lambda p: p.name)

with xlsxwriter.Workbook(output) as book:
    title_fmt = book.add_format({"bold": True, "font_size": 14, "font_color": "#173B63"})
    header_fmt = book.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#1F4E78", "align": "center", "valign": "vcenter"})
    body_fmt = book.add_format({"font_name": "Aptos", "font_size": 10, "valign": "top", "text_wrap": True})
    note_fmt = book.add_format({"font_name": "Aptos", "font_size": 9, "font_color": "#59616C", "text_wrap": True, "valign": "top"})
    link_fmt = book.add_format({"font_name": "Aptos", "font_size": 10, "font_color": "#0563C1", "underline": 1, "valign": "top", "text_wrap": True})
    index = book.add_worksheet("목록")
    index.hide_gridlines(2)
    index.write("A1", "건축할 수 있는 건축물 별표 모음", title_fmt)
    index.write("A2", "원자료: 법제처 국가법령정보센터에서 변환한 Markdown 파일", note_fmt)
    index.write_row("A4", ["별표", "제목", "원자료 파일", "시트"], header_fmt)
    index.set_column("A:A", 14); index.set_column("B:B", 58); index.set_column("C:C", 70); index.set_column("D:D", 14)
    index.freeze_panes(4, 0)
    row = 4
    for path in files:
        text = path.read_text(encoding="utf-8")
        marker = re.search(r"\[별표\s*([^\]]+)\]", path.name)
        number = marker.group(1) if marker else str(row - 3)
        headings = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("[")]
        title = next((line.lstrip("-#■ ").strip() for line in headings if "건축할 수" in line or "건축물의 종류" in line), path.stem)
        sheet_name = (f"별표 {number}")[:31]
        sheet = book.add_worksheet(sheet_name)
        sheet.hide_gridlines(2)
        sheet.write("A1", f"별표 {number}", title_fmt); sheet.write("A2", title, title_fmt); sheet.write("A3", f"출처 파일: {path.name}", note_fmt)
        sheet.write("A5", "원문", header_fmt); sheet.set_column("A:A", 120); sheet.freeze_panes(5, 0)
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        for offset, line in enumerate(lines, start=5):
            sheet.write(offset, 0, line, body_fmt); sheet.set_row(offset, 32 if len(line) > 90 else 18)
        sheet.autofilter(4, 0, max(4, 4 + len(lines)), 0)
        index.write(row, 0, f"별표 {number}", body_fmt); index.write(row, 1, title, body_fmt); index.write(row, 2, path.name, body_fmt)
        index.write_url(row, 3, f"internal:'{sheet_name}'!A1", link_fmt, sheet_name); row += 1
    index.autofilter(3, 0, max(3, row - 1), 3); index.set_row(0, 24)
print(output)
