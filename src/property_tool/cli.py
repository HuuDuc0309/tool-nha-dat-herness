"""Property data MVP: fetch URLs, extract JSON-LD/HTML metadata, verify, export Excel."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_fields(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["fields"]


def ssl_context():
    """Use certifi's CA bundle; the Windows store is not always visible to Python."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()

def fetch_html(url: str, timeout: int = 25) -> tuple[str, str]:
    req = Request(url, headers={"User-Agent": "PropertyResearchBot/0.1 (+local research)", "Accept-Language": "vi,en;q=0.9"})
    with urlopen(req, timeout=timeout, context=ssl_context()) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace"), response.geturl()


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _number(value):
    if value is None:
        return ""
    raw = _text(value).lower().replace(",", "").replace(".", "")
    match = re.search(r"\d+(?:[.,]\d+)?", raw)
    if not match:
        return ""
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return ""


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def json_ld_blocks(html: str) -> list[dict]:
    blocks = []
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S):
        try:
            data = json.loads(unescape(raw.strip()))
            values = data if isinstance(data, list) else data.get("@graph", []) if isinstance(data, dict) else []
            if isinstance(data, dict) and not values:
                values = [data]
            blocks.extend(x for x in values if isinstance(x, dict))
        except json.JSONDecodeError:
            continue
    return blocks


def meta_content(html: str, name: str) -> str:
    pattern = rf'<meta[^>]+(?:name|property)=["\']{re.escape(name)}["\'][^>]+content=["\'](.*?)["\']'
    match = re.search(pattern, html, re.I | re.S)
    return _strip_html(match.group(1)) if match else ""


def map_record(url: str, html: str, final_url: str, source: str, fields: list[dict]) -> tuple[dict, list[dict], list[dict]]:
    p = urlparse(final_url or url)
    blocks = json_ld_blocks(html)
    listing = next((b for b in blocks if b.get("@type") in {"Product", "Place", "House", "Residence", "RealEstateListing"}), blocks[0] if blocks else {})
    title = _text(listing.get("name")) or meta_content(html, "og:title")
    description = _text(listing.get("description")) or meta_content(html, "description")
    address = listing.get("address", {})
    address_text = _text(address.get("streetAddress") if isinstance(address, dict) else address)
    price = listing.get("offers", {})
    price = price.get("price") if isinstance(price, dict) else price
    area = listing.get("floorSize", {})
    area = area.get("value") if isinstance(area, dict) else area
    record = {f["key"]: "" for f in fields}
    record.update({
        "title": title,
        "source_url": url,
        "source_site": p.netloc,
        "address": address_text,
        "rent_amount": _number(price),
        "rent_period": _text(listing.get("priceCurrency")),
        "usable_area_m2": _number(area),
        "extraction_status": "Đã lấy HTML/JSON-LD" if (title or description or blocks) else "Đã lấy trang nhưng thiếu dữ liệu chuẩn",
        "confidence": 0.85 if blocks else 0.35,
        "warnings": "" if blocks else "Không tìm thấy JSON-LD; cần kiểm tra thủ công hoặc bổ sung adapter.",
        "collected_at": now_iso(),
    })
    if not record.get("title"):
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        record["title"] = _strip_html(title_match.group(1)) if title_match else ""
    evidence = []
    for key in ("title", "address", "rent_amount", "usable_area_m2"):
        value = record.get(key, "")
        if value != "":
            evidence.append({"source_url": url, "field": key, "value": value, "source_text": description[:500] or title, "confidence": record.get("confidence", 0)})
    unknown = [{"source_url": url, "field": f["key"], "reason": "Không tìm thấy trong dữ liệu trang"} for f in fields if f["key"] not in {"title", "source_url", "source_site", "address", "rent_amount", "rent_period", "usable_area_m2", "extraction_status", "confidence", "warnings"}]
    return record, evidence, unknown


def fallback_playwright(url: str, fields: list[dict]):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        html = page.content()
        final_url = page.url
        browser.close()
    return map_record(url, html, final_url, "playwright", fields)


def collect(url: str, fields: list[dict], use_browser: bool):
    try:
        html, final_url = fetch_html(url)
        result = map_record(url, html, final_url, "http", fields)
        if use_browser and result[0].get("confidence", 0) < 0.5:
            browser_result = fallback_playwright(url, fields)
            if browser_result:
                return browser_result
        return result
    except Exception as exc:
        if use_browser:
            try:
                browser_result = fallback_playwright(url, fields)
                if browser_result:
                    return browser_result
            except Exception:
                pass
        p = urlparse(url)
        return ({"title": "", "source_url": url, "source_site": p.netloc, "extraction_status": "Lỗi thu thập", "confidence": 0.0, "warnings": str(exc), "collected_at": now_iso()}, [], [{"source_url": url, "field": "_page", "reason": str(exc)}])


def export_xlsx(records, evidence, unknown, crawl_rows, fields, output: Path):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo
    wb = Workbook()
    ws = wb.active
    ws.title = "Danh sách tin đăng"
    keys = [f["key"] for f in fields]
    ws.append([f["label"] for f in fields])
    for record in records:
        ws.append([record.get(k, "") for k in keys])
    for name, headers, rows in [
        ("Chưa xác định", ["URL nguồn", "Trường cần kiểm tra", "Lý do"], [[x.get("source_url"), x.get("field"), x.get("reason")] for x in unknown]),
        ("Bằng chứng dữ liệu", ["URL nguồn", "Tên trường", "Giá trị", "Đoạn dữ liệu nguồn", "Độ tin cậy"], [[x.get("source_url"), x.get("field"), x.get("value"), x.get("source_text"), x.get("confidence")] for x in evidence]),
        ("Báo cáo crawl", ["URL nguồn", "Website", "Trạng thái", "Thời điểm"], crawl_rows),
    ]:
        sh = wb.create_sheet(name)
        sh.append(headers)
        for row in rows:
            sh.append(row)
        sh.freeze_panes = "A2"
        if rows:
            ref = f"A1:{get_column_letter(len(headers))}{len(rows)+1}"
            tab = Table(displayName="T" + str(abs(hash(name)))[:8], ref=ref)
            tab.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
            sh.add_table(tab)
    for sh in wb.worksheets:
        sh.freeze_panes = sh.freeze_panes or "A2"
        for cell in sh[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="087F8C")
        for column in sh.columns:
            letter = get_column_letter(column[0].column)
            values = [len(str(c.value or "")) for c in column[:100]]
            sh.column_dimensions[letter].width = min(55, max(14, max(values or [14]) + 2))
    output.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output)


def main():
    ap = argparse.ArgumentParser(description="Thu thập và xuất dữ liệu nhà đất")
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--urls-file", type=Path)
    ap.add_argument("--fields", type=Path, default=Path("config/property-fields.json"))
    ap.add_argument("--output", type=Path)
    ap.add_argument("--browser", action="store_true", help="Dùng Playwright khi HTTP thiếu dữ liệu")
    ap.add_argument("--discover", action="store_true", help="Chạy discovery và lưu artifact trước khi extract")
    args = ap.parse_args()
    urls = list(args.urls)
    if args.urls_file:
        urls += [x.strip() for x in args.urls_file.read_text(encoding="utf-8").splitlines() if x.strip() and not x.lstrip().startswith("#")]
    urls = list(dict.fromkeys(urls))
    if not urls:
        ap.error("Cần cung cấp URL hoặc --urls-file")
    fields = load_fields(args.fields)
    if args.discover:
        from .discover import discover
        discovery = [discover(u, Path("research/sites")) for u in urls]
        print(json.dumps({"discovery": discovery}, ensure_ascii=False))
    records, evidence, unknown, crawl = [], [], [], []
    for url in urls:
        record, ev, un = collect(url, fields, args.browser)
        records.append(record); evidence.extend(ev); unknown.extend(un)
        crawl.append([url, record.get("source_site", ""), record.get("extraction_status", ""), record.get("collected_at", "")])
    output = args.output or Path("research/jobs") / f"property-data-{datetime.now():%Y%m%d-%H%M%S}.xlsx"
    export_xlsx(records, evidence, unknown, crawl, fields, output)
    print(json.dumps({"status": "success", "records": len(records), "evidence": len(evidence), "unknown_fields": len(unknown), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
