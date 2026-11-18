"""Excel exporter: one workbook, Vietnamese column labels + technical keys.

Sheets required by the project spec:
  Danh sách tin đăng / Chưa xác định / Bằng chứng dữ liệu / Cảnh báo /
  Báo cáo crawl / Thông tin bổ sung / Tin nghi trùng
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

HEADER_FILL = PatternFill("solid", fgColor="087F8C")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
UNKNOWN_FILL = PatternFill("solid", fgColor="FFF4CE")
WARN_FILL = PatternFill("solid", fgColor="FFE0E0")
DUP_FILL = PatternFill("solid", fgColor="E8E8F5")

# key -> (Vietnamese label, number format)
MAIN_FIELDS = [
    ("title", "Tiêu đề", None),
    ("source_url", "Đường dẫn gốc", None),
    ("source_site", "Website nguồn", None),
    ("address", "Địa chỉ", None),
    ("province", "Tỉnh/thành", None),
    ("district", "Quận/huyện", None),
    ("ward", "Phường/xã", None),
    ("rent_amount", "Giá thuê (rent_amount)", "#,##0"),
    ("rent_amount_text", "Giá thuê hiển thị", None),
    ("price_per_m2_vnd", "Giá theo m² (VND/m²/tháng)", "#,##0"),
    ("rent_period", "Chu kỳ giá", None),
    ("deposit", "Tiền đặt cọc", None),
    ("land_area_m2", "Diện tích đất (land_area_m2)", "#,##0.##"),
    ("factory_area_m2", "Diện tích xưởng (factory_area_m2)", "#,##0.##"),
    ("usable_area_m2", "Diện tích sử dụng (usable_area_m2)", "#,##0.##"),
    ("usable_area_text", "Diện tích hiển thị", None),
    ("frontage_m", "Mặt tiền (frontage_m)", "#,##0.##"),
    ("contact", "Liên hệ", None),
    ("extraction_status", "Trạng thái dữ liệu", None),
    ("confidence", "Độ tin cậy", "0.00"),
    ("warnings", "Cảnh báo", None),
]

SUPPLEMENT_FIELDS = [
    ("listing_code", "Mã tin"),
    ("posted_at", "Ngày đăng"),
    ("expires_at", "Ngày hết hạn"),
    ("post_type", "Loại tin"),
    ("legal", "Pháp lý"),
    ("direction", "Hướng"),
    ("property_type", "Loại hình"),
    ("project", "Dự án"),
    ("price_per_m2_text", "Giá theo m² (nguyên văn)"),
    ("address_alt", "Địa chỉ thay thế"),
    ("contact_masked", "Số liên hệ bị ẩn"),
    ("area_conflict", "Mâu thuẫn diện tích"),
    ("description", "Mô tả"),
    ("snapshot", "Snapshot HTML"),
    ("collected_at", "Thời điểm thu thập"),
]


# Fast-screening column set for the kho/nhà xưởng use case: enough to filter
# by location, price and size in Excel without a supplement sheet. Deliberately
# excludes confidence/quality columns and free text.
CORE_FIELDS = [
    "title",
    "source_url",
    "address",
    "province",
    "district",
    "rent_amount",
    "rent_period",
    "factory_area_m2",
    "usable_area_m2",
    "contact",
    "extraction_status",
]


def _write_sheet(wb, title, headers, rows, widths=None, table_name=None):
    # `wb.active` is None once the default sheet was removed, so an empty
    # workbook needs an explicit first sheet.
    if wb.sheetnames:
        ws = wb.create_sheet(title)
    else:
        ws = wb.active if wb.active is not None else wb.create_sheet(title)
        ws.title = title
    if ws.title != title:
        ws.title = title
    ws.append(headers)
    for row in rows:
        ws.append(row)
    ws.freeze_panes = "A2"
    for cell in ws[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30
    if rows and table_name:
        ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"
        tab = Table(displayName=table_name, ref=ref)
        tab.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2",
                                            showRowStripes=True, showFirstColumn=False)
        ws.add_table(tab)
    for idx, header in enumerate(headers, start=1):
        letter = get_column_letter(idx)
        if widths and header in widths:
            ws.column_dimensions[letter].width = widths[header]
            continue
        values = [len(str(c.value or "")) for c in ws[column_letters(letter)][:200]]
        ws.column_dimensions[letter].width = min(58, max(12, (max(values) if values else 12) + 2))
    ws.auto_filter.ref = ws.dimensions
    return ws


def column_letters(letter):
    return letter


def _dedupe_key(record: dict) -> tuple:
    """Normalised title+address+area — a suspicion signal only, never a merge."""
    def norm(value):
        text = str(value or "").lower()
        text = re.sub(r"[^\w\s]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    return (norm(record.get("title"))[:60],
            norm(record.get("district")),
            str(record.get("usable_area_m2") or record.get("usable_area_text") or ""))


def find_duplicates(records: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for rec in records:
        key = _dedupe_key(rec)
        if key[0]:
            groups[key].append(rec)
    rows = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        urls = {i.get("source_url") for i in items}
        for item in items:
            rows.append({
                "Nhóm nghi trùng": key[0][:50],
                "Tiêu đề": item.get("title"),
                "Địa chỉ": item.get("address"),
                "Diện tích": item.get("usable_area_text") or item.get("usable_area_m2"),
                "Giá": item.get("rent_amount_text"),
                "Website": item.get("source_site"),
                "Đường dẫn": item.get("source_url"),
                "Số URL khác nhau trong nhóm": len(urls),
                "Ghi chú": "Chỉ đánh dấu — chưa tự gộp" if len(urls) > 1 else "Cùng URL, xuất hiện nhiều lần",
            })
    return rows


def unknown_fields(records: list[dict], unknown_rows: list[dict]) -> list[dict]:
    """One row per record × missing main field (the 'Chưa xác định' sheet)."""
    rows = []
    for rec in records:
        for key, label, _ in MAIN_FIELDS:
            if key in ("extraction_status", "confidence", "warnings"):
                continue
            if str(rec.get(key) or "").strip():
                continue
            rows.append({
                "Đường dẫn gốc": rec.get("source_url"),
                "Website": rec.get("source_site"),
                "Trường thiếu": label,
                "Key kỹ thuật": key,
                "Lý do": "Không tìm thấy trong trang" if not unknown_rows else "Không có bằng chứng",
                "Trạng thái": "Chưa xác định",
            })
    # keep crawler-reported unknowns that are not covered above
    seen = {(r["Đường dẫn gốc"], r["Key kỹ thuật"]) for r in rows}
    for u in unknown_rows:
        if (u.get("source_url"), u.get("field")) in seen:
            continue
        rows.append({
            "Đường dẫn gốc": u.get("source_url"),
            "Website": u.get("site"),
            "Trường thiếu": u.get("field"),
            "Key kỹ thuật": u.get("field"),
            "Lý do": u.get("reason"),
            "Trạng thái": "Chưa xác định",
        })
    return rows


def export(records: list[dict], evidence: list[dict], unknown_rows: list[dict],
           warnings: list[dict], sites: list[dict], queue: list[dict],
           output: Path, field_config: Path | None = None,
           extra_sheets: bool = False,
           exclude_fields: list[str] | tuple[str, ...] = ("confidence",),
           core_only: bool = False,
           field_keys: list[str] | tuple[str, ...] | None = None):
    """Write the workbook. Only "Danh sách tin đăng" unless extra_sheets=True.

    Extra sheets exist for audit, but an AI reading the workbook pays tokens for
    every one of them, so they are opt-in via `config/settings.json`.
    `exclude_fields` drops columns such as `confidence` that invite AI re-checking.
    `core_only` narrows the main sheet to CORE_FIELDS (fast screening view).
    `field_keys` narrows the main sheet to exactly the columns the user asked
    for; it wins over `core_only`.
    """
    wb = Workbook()
    # `_write_sheet` always creates a new sheet, so the workbook's default empty
    # "Sheet" would otherwise be saved alongside the real ones.
    wb.remove(wb.active)

    # 1. main list — the only sheet written by default
    main_fields = [f for f in MAIN_FIELDS if f[0] not in set(exclude_fields)]
    if field_keys:
        wanted = list(field_keys)
        main_fields = [f for f in MAIN_FIELDS if f[0] in wanted]
        # any requested key that has no label yet still gets a column
        known = {f[0] for f in MAIN_FIELDS}
        main_fields += [(k, k, None) for k in wanted if k not in known]
    elif core_only:
        main_fields = [f for f in main_fields if f[0] in CORE_FIELDS]
    headers = [label for _, label, _ in main_fields]
    rows = [[rec.get(key, "") for key, _, _ in main_fields] for rec in records]
    ws = _write_sheet(wb, "Danh sách tin đăng", headers, rows, table_name="TableMain")
    for idx, (key, _, fmt) in enumerate(main_fields, start=1):
        if not fmt:
            continue
        letter = get_column_letter(idx)
        for cell in ws[letter][1:]:
            cell.number_format = fmt
    for row_cells in ws.iter_rows(min_row=2):
        if row_cells[-1].value:
            for cell in row_cells:
                if cell.column <= len(main_fields):
                    cell.alignment = Alignment(vertical="top", wrap_text=False)

    summary = {"output": str(output), "records": len(records),
               "sheets": ["Danh sách tin đăng"],
               "excluded_columns": sorted(set(exclude_fields))}
    if not extra_sheets:
        output.parent.mkdir(parents=True, exist_ok=True)
        wb.save(output)
        return summary

    # 2. unknown
    unk = unknown_fields(records, unknown_rows)
    ws_u = _write_sheet(
        wb, "Chưa xác định",
        ["Đường dẫn gốc", "Website", "Trường thiếu", "Key kỹ thuật", "Lý do", "Trạng thái"],
        [[u["Đường dẫn gốc"], u["Website"], u["Trường thiếu"], u["Key kỹ thuật"],
          u["Lý do"], u["Trạng thái"]] for u in unk],
        table_name="TableUnknown")
    for row in ws_u.iter_rows(min_row=2):
        row[5].fill = UNKNOWN_FILL

    # 3. evidence
    _write_sheet(
        wb, "Bằng chứng dữ liệu",
        ["URL nguồn", "Website", "Trường", "Giá trị", "Đoạn dữ liệu nguồn", "Snapshot", "Độ tin cậy"],
        [[e.get("source_url"), e.get("site"), e.get("field"), str(e.get("value"))[:200],
          str(e.get("source_text") or "")[:500], e.get("snapshot"), e.get("confidence")]
         for e in evidence],
        table_name="TableEvidence")

    # 4. warnings
    warn_rows = []
    for rec in records:
        if rec.get("warnings"):
            warn_rows.append([rec.get("source_url"), rec.get("source_site"),
                              "record_warning", rec.get("warnings")])
    for w in warnings:
        warn_rows.append([w.get("url"), w.get("site"), w.get("issue"), w.get("detail")])
    ws_w = _write_sheet(
        wb, "Cảnh báo",
        ["URL nguồn", "Website", "Loại", "Chi tiết"],
        warn_rows, table_name="TableWarnings")
    for row in ws_w.iter_rows(min_row=2):
        row[3].fill = WARN_FILL

    # 5. crawl report
    report_rows = []
    for s in sites:
        report_rows.append([
            s.get("site_id"), s.get("status"),
            s.get("listings_fetched"), s.get("details_fetched"), s.get("records"),
            "Có" if s.get("blocked") else "Không",
            s.get("challenge_solved_at") or "",
            "; ".join(s.get("notes") or []),
        ])
    for q in queue:
        report_rows.append([
            q.get("site"), q.get("status"), q.get("kind"), q.get("url"),
            q.get("category") or "", q.get("attempts") or "",
            "", "; ".join(q.get("notes") or []),
        ])
    _write_sheet(
        wb, "Báo cáo crawl",
        ["Website/Job", "Trạng thái", "Trang listing", "Trang detail", "Số record",
         "Bị chặn", "Thời điểm vượt challenge", "Ghi chú"],
        report_rows, table_name="TableCrawl")

    # 6. supplemental
    sup_headers = ["Đường dẫn gốc"] + [label for _, label in SUPPLEMENT_FIELDS]
    sup_rows = [[rec.get("source_url")] + [str(rec.get(key, "") or "") for key, _ in SUPPLEMENT_FIELDS]
                for rec in records]
    _write_sheet(wb, "Thông tin bổ sung", sup_headers, sup_rows, table_name="TableSupplement")

    # 7. suspected duplicates
    dups = find_duplicates(records)
    ws_d = _write_sheet(
        wb, "Tin nghi trùng",
        ["Nhóm nghi trùng", "Tiêu đề", "Địa chỉ", "Diện tích", "Giá", "Website",
         "Đường dẫn", "Số URL khác nhau trong nhóm", "Ghi chú"],
        [[d["Nhóm nghi trùng"], d["Tiêu đề"], d["Địa chỉ"], d["Diện tích"], d["Giá"],
          d["Website"], d["Đường dẫn"], d["Số URL khác nhau trong nhóm"], d["Ghi chú"]]
         for d in dups],
        table_name="TableDuplicates")
    for row in ws_d.iter_rows(min_row=2):
        row[8].fill = DUP_FILL

    output.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output)
    return {"output": str(output), "records": len(records), "unknown": len(unk),
            "evidence": len(evidence), "warnings": len(warn_rows), "duplicates": len(dups),
            "sheets": wb.sheetnames,
            "excluded_columns": sorted(set(exclude_fields))}


def export_from_job(job_dir: Path, output: Path, field_config: Path | None = None,
                    settings_path: Path = Path("config/settings.json")) -> dict:
    from .settings import load_settings
    settings = load_settings(settings_path)
    export_cfg = settings.get("export") or {}
    result = json.loads((job_dir / "crawl-result.json").read_text(encoding="utf-8"))
    return export(
        result.get("records", []),
        result.get("evidence", []),
        result.get("unknown", []),
        result.get("warnings", []),
        result.get("sites", []),
        result.get("queue", []),
        output,
        field_config,
        extra_sheets=bool(export_cfg.get("extra_sheets", False)),
        exclude_fields=export_cfg.get("main_sheet_exclude_fields", ["confidence"]) or [],
    )


def main():
    import argparse
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Xuất crawl-result.json ra Excel nhiều sheet")
    ap.add_argument("job_dir", type=Path)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--extra-sheets", action="store_true",
                    help="bật các sheet phụ (mặc định chỉ xuất Danh sách tin đăng)")
    ap.add_argument("--max-records", type=int, default=None,
                    help="giới hạn số bản ghi xuất ra; mặc định đọc config/settings.json")
    ap.add_argument("--core-only", action="store_true",
                    help="chỉ xuất field cốt lõi tìm mặt bằng (CORE_FIELDS)")
    ap.add_argument("--fields", nargs="*", default=None,
                    help="chỉ xuất đúng các key này, theo thứ tự đã cho "
                         "(ví dụ: title source_url address district rent_amount)")
    args = ap.parse_args()
    out = args.output or (args.job_dir / f"property-data-{datetime.now():%Y%m%d-%H%M%S}.xlsx")

    from .settings import load_settings, max_records as cap_from_settings
    settings = load_settings()
    cap = args.max_records if args.max_records is not None else cap_from_settings(settings)
    export_cfg = settings.get("export") or {}
    result = json.loads((args.job_dir / "crawl-result.json").read_text(encoding="utf-8"))
    records = result.get("records", [])
    if cap and len(records) > cap:
        records = records[:cap]
    summary = export(
        records,
        result.get("evidence", []),
        result.get("unknown", []),
        result.get("warnings", []),
        result.get("sites", []),
        result.get("queue", []),
        out,
        extra_sheets=args.extra_sheets or bool(export_cfg.get("extra_sheets", False)),
        exclude_fields=export_cfg.get("main_sheet_exclude_fields", ["confidence"]) or [],
        core_only=args.core_only,
        field_keys=args.fields,
    )
    print(json.dumps({"status": "success", **summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()