"""Regression tests for the batdongsan adapters.

Runs against HTML snapshots saved under research/jobs/*/snapshots/, so it needs
no network access. A missing snapshot is reported as SKIP, never as a pass.

    .\.venv\Scripts\python.exe -m src.property_tool.regression
    .\.venv\Scripts\python.exe -m src.property_tool.regression --write-report
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from .adapters import batdongsan_vn
from .adapters.batdongsan_group import (
    location_parts,
    normalise_vnd,
    parse_area_m2,
    parse_detail as parse_detail_group,
    parse_listing_cards,
)

RESULTS: list[dict] = []


def check(name: str, condition: bool, detail: str = ""):
    RESULTS.append({"test": name, "status": "pass" if condition else "fail", "detail": detail})
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail and not condition else ""))


def skip(name: str, why: str):
    RESULTS.append({"test": name, "status": "skip", "detail": why})
    print(f"  [SKIP] {name} — {why}")


# ---------------------------------------------------------------- unit tests
def test_normalisers():
    print("\n== normalisers ==")
    from .crawler import detect_period

    periods = {
        "10.5 triệu/tháng": "tháng",
        "5 triệu / th": "tháng",
        "65 nghìn/m²": "",
        "52,6 nghìn/m²": "",
        "Thỏa thuận": "",
        "30 triệu/tháng": "tháng",
        "1.2 tỷ/năm": "năm",
        "500 nghìn/ngày": "ngày",
    }
    for raw, want in periods.items():
        got = detect_period(raw, "")
        check(f"detect_period({raw!r})", got == want, f"want {want!r} got {got!r}")
    cases = {
        "10.5 triệu": "10500000",
        "5 triệu": "5000000",
        "2.5 tỷ": "2500000000",
        "150 nghìn": "150000",
        "52,6 nghìn": "52600",
        "Thoả thuận": "",
        "Thỏa thuận": "",
        "Giá thỏa thuận": "",
        "Liên hệ": "",
    }
    for raw, want in cases.items():
        got = normalise_vnd(raw)
        check(f"normalise_vnd({raw!r})", got == want, f"want {want!r} got {got!r}")

    areas = {
        "11.000 m²": "11000",
        "9000,0 m2": "9000",
        "957,9 m²": "957.9",
        "2.000 m²": "2000",
        "1000m": "1000",
        "70,0 m²": "70",
        "185,0 m2": "185",
        "3.415,4 m²": "3415.4",   # thousands '.' + decimal ','
        "60.000m²": "60000",
        "1.234.567 m²": "1234567",
    }
    for raw, want in areas.items():
        got = parse_area_m2(raw)
        check(f"parse_area_m2({raw!r})", got == want, f"want {want!r} got {got!r}")

    # Both pagination shapes the platform uses must be detected; bds.com.vn
    # only emits '/p2', so a '?page='-only pattern capped it at page 1.
    from .adapters.batdongsan_group import next_page_urls

    pages = next_page_urls(
        '<a href="/cho-thue-van-phong/p2">2</a>'
        '<a href="?page=3">3</a>'
        '<a href="/cho-thue-nha-mat-pho/trang-4/">4</a>', "https://x.test")
    check("pagination /p2 detected",
          "https://x.test/cho-thue-van-phong/p2" in pages, str(pages))
    check("pagination ?page= detected",
          "https://x.test?page=3" in pages or "?page=3" in pages, str(pages))
    check("pagination /trang-4 detected",
          any("trang-4" in p for p in pages), str(pages))
    check("no duplicate page links", len(pages) == len(set(pages)), str(pages))

    loc = location_parts("Xã Hạ Bằng, Huyện Thạch Thất, Thành phố Hà Nội")
    check("location ward", loc["ward"] == "Xã Hạ Bằng", loc)
    check("location district", loc["district"] == "Huyện Thạch Thất", loc)
    check("location province", loc["province"] == "Thành phố Hà Nội", loc)

    loc2 = location_parts("Đường Số 17, Phường Tân Thuận Đông, Quận 7, Hồ Chí Minh")
    check("location street+ward", loc2["ward"] == "Phường Tân Thuận Đông", loc2)
    check("location district q7", loc2["district"] == "Quận 7", loc2)

    # ceiling height: only a number with a metre unit counts, and it must be
    # plausible for a warehouse (2–30 m). Multi-value text keeps every value.
    from .adapters.batdongsan_group import parse_ceiling_height

    ceiling_cases = {
        "Chiều cao kho: 6,5m.": "6.5",
        "trần cao 11m, nền bê tông": "11",
        "trần cao 8, 10m": "8; 10",
        "chiều cao lên đỉnh mái 10,5m, chiều cao vách 8m": "8; 10.5",
        "kho xưởng cao 12m": "12",
        "khung zamil cao 8 - 12m": "8; 12",
        "chất lượng cao, thoáng mát": "",
        "cao tốc Bắc Thang Long": "",
        "tường cao 1 m": "",
        "khung thép zamil cao 812m": "",
        "trần cao, thoáng": "",
        "cao 68m": "",
    }
    for text, want in ceiling_cases.items():
        got, snippet = parse_ceiling_height(text)
        check(f"parse_ceiling_height({text[:42]!r})", got == want, f"want {want!r} got {got!r}")
        check(f"  snippet for {text[:24]!r} present when value", bool(snippet) == bool(want),
              f"snippet={snippet[:50]!r}")


# ---------------------------------------------------------------- snapshot tests
def job_dirs() -> list[Path]:
    root = Path("research/jobs")
    return sorted([p for p in root.glob("*") if (p / "snapshots").exists()]) if root.exists() else []


def test_group_detail(snap: Path):
    print(f"\n== batdongsan365 detail: {snap.name} ==")
    html = snap.read_text(encoding="utf-8")
    d = parse_detail_group(html, "test")
    check("has title", bool(d["title"]), d["title"][:60])
    check("has address", bool(d["address"]), d["address"])
    check("has listing_code", bool(d["listing_code"]), d["listing_code"])
    check("has area_text", bool(d["area_text"]), d["area_text"])
    check("has posted_at", bool(d["posted_at"]), d["posted_at"])
    check("has description", len(d["description"]) > 50, f"{len(d['description'])} chars")
    # each attribute row must be a label/value pair, never a label only
    bad = [k for k, v in d["attributes"].items() if not v]
    check("no empty attribute values", not bad, str(bad))
    # a phone is either found in the description or masked — never invented
    if d["contact"]:
        check("contact looks like a phone or mask",
              bool(__import__("re").match(r"^0[\d.\s]{7,13}$|^\*{4,}\d+$", d["contact"])),
              d["contact"])


def test_vn_detail(snap: Path):
    print(f"\n== batdongsan.com.vn detail: {snap.name} ==")
    html = snap.read_text(encoding="utf-8")
    d = batdongsan_vn.parse_detail(html, "test")
    check("has title", bool(d["title"]), d["title"][:60])
    check("has address", bool(d["address"]), d["address"])
    check("address has no leading bullet",
          not d["address"].strip().startswith("·"), d["address"])
    check("has listing_code", d["listing_code"].isdigit(), d["listing_code"])
    check("has area_text", bool(d["area_text"]), d["area_text"])
    check("has posted_at", bool(d["posted_at"]), d["posted_at"])
    check("address_alt kept separate", d["address_alt"] != d["address"] or not d["address_alt"],
          f"alt={d['address_alt']!r}")
    # price basis must be distinguishable
    per_m2 = "/m²" in d["price_text"] or "/m2" in d["price_text"].lower()
    if per_m2:
        check("per-m² price parses to a number",
              bool(normalise_vnd(d["price_text"])), d["price_text"])
    if d["contact"]:
        check("masked contact is not fabricated",
              "***" in d["contact"] or d["contact_masked"] == "",
              f"{d['contact']!r} masked={d['contact_masked']!r}")


def test_verifier_catches_defects():
    """The verifier must fail a deliberately broken record — otherwise it is noise."""
    print("\n== verifier catches defects ==")
    from .verify import verify

    bad = {
        "title": "", "source_url": "u", "source_site": "s",
        "address": "· Hà Nội", "province": "HN", "district": "", "ward": "",
        "rent_amount": "52600", "rent_amount_text": "", "price_per_m2_vnd": "52600",
        "rent_period": "", "deposit": "", "land_area_m2": "", "factory_area_m2": "",
        "usable_area_m2": "3", "usable_area_text": "3 m2", "frontage_m": "",
        "contact": "abc", "extraction_status": "", "confidence": "x", "warnings": "",
        "listing_code": "", "posted_at": "2026-11-17",
    }
    kinds = {i["kind"] for i in verify(bad, "text không chứa gì")}
    for expected in ("rent_too_low", "price_basis_contradiction", "area_too_small",
                     "bad_confidence", "address_not_trimmed", "contact_not_a_phone",
                     "bad_date_format", "missing_title"):
        check(f"verifier flags {expected}", expected in kinds, str(sorted(kinds)))

    good = dict(bad)
    good.update({
        "title": "Cho thuê kho", "address": "Xã A, Huyện B, Hà Nội", "province": "Hà Nội",
        "rent_amount": "30000000", "price_per_m2_vnd": "150000", "usable_area_m2": "200",
        "usable_area_text": "200 m2", "contact": "0912345678", "confidence": "0.8",
        "posted_at": "01/11/2026",
    })
    good_kinds = {i["kind"] for i in verify(good, "Xã A, Huyện B, Hà Nội 200 m2")}
    check("verifier passes a clean record",
          not (good_kinds & {"rent_too_low", "price_basis_contradiction", "bad_confidence",
                             "address_not_trimmed", "missing_title"}),
          str(good_kinds))


def test_record_mapping():
    """Record-level rules: price basis, area conflict, rent period."""
    print("\n== record mapping rules ==")
    from .crawler import Crawler

    c = Crawler.__new__(Crawler)
    c.evidence = []
    c.unknown = []

    # per-m² price must never become a total monthly rent
    r = c._to_record({"title": "Kho", "address": "", "price_text": "65 nghìn", "area_text": "1000 m2"},
                     {"price_text": "65 nghìn", "price_vnd": "65000",
                      "price_per_m2_text": "65 nghìn/m²", "price_per_m2_vnd": "65000",
                      "price_basis": "per_m2"}, "s", Path("x"))
    check("per-m² price excluded from rent_amount", r["rent_amount"] == "", repr(r["rent_amount"]))
    check("per-m² value preserved separately", r["price_per_m2_vnd"] == "65000", r["price_per_m2_vnd"])
    check("per-m² warning present", "theo m²" in r["warnings"], r["warnings"])

    # a total monthly price is kept
    r2 = c._to_record({"title": "Nhà", "address": "", "price_text": "30 triệu/tháng", "area_text": "500 m2"},
                      {"price_basis": "total"}, "s", Path("x"))
    check("total price kept", r2["rent_amount"] == "30000000", repr(r2["rent_amount"]))
    check("period from evidence", r2["rent_period"] == "tháng", repr(r2["rent_period"]))

    # price text alone must not imply a period
    r3 = c._to_record({"title": "Đất", "price_text": "Thỏa thuận", "area_text": "200 m2"},
                      {"price_basis": "negotiable"}, "s", Path("x"))
    check("negotiable has no period", r3["rent_period"] == "", repr(r3["rent_period"]))
    check("negotiable has no rent", r3["rent_amount"] == "", repr(r3["rent_amount"]))

    # ambiguous tiny total is not exported as a real rent
    r4 = c._to_record({"title": "MB", "price_text": "1 nghìn", "area_text": "100 m2"},
                      {"price_text": "1 nghìn", "price_vnd": "1000",
                       "price_per_m2_text": "10/m²", "price_per_m2_vnd": "10",
                       "price_basis": "ambiguous"}, "s", Path("x"))
    check("ambiguous price excluded", r4["rent_amount"] == "", repr(r4["rent_amount"]))
    check("ambiguous warning present", "không đủ tin cậy" in r4["warnings"], r4["warnings"])

    # several areas in the text must be surfaced, not silently picked
    desc = ("Diện tích khuôn viên: 11.000m² | Diện tích xưởng: 5.000m² | "
            "Tổng diện tích: 3.415,4 m². DT từ 500m², 700m², 1000m².")
    r5 = c._to_record({"title": "Xưởng", "price_text": "65 nghìn", "area_text": "9000 m2",
                       "description": desc},
                      {"price_basis": "per_m2"}, "s", Path("x"))
    check("factory area parsed", r5["factory_area_m2"] == "5000", repr(r5["factory_area_m2"]))
    # both the 'khuôn viên' and the 'tổng diện tích' mention are land areas, so
    # keeping both is correct; silently discarding one would lose information
    check("land area keeps every distinct value",
          "11000" in str(r5["land_area_m2"]) and "3415.4" in str(r5["land_area_m2"]),
          repr(r5["land_area_m2"]))
    check("area conflict flagged", bool(r5["area_conflict"]), r5["area_conflict"][:80])
    check("area conflict lowers confidence", float(r5["confidence"]) <= 0.6, r5["confidence"])
    check("area conflict in warnings", "nhiều diện tích" in r5["warnings"], r5["warnings"][:100])

    # ceiling height is recorded with its source phrase; several values are kept
    r6 = c._to_record({"title": "Kho", "price_text": "30 triệu/tháng", "area_text": "500 m2",
                       "description": "Kho xưởng cao 12m, trần cao 8, 10m."},
                      {"price_basis": "total"}, "s", Path("x"))
    check("ceiling height parsed", r6["ceiling_height_m"] == "8; 10; 12", repr(r6["ceiling_height_m"]))
    check("ceiling note keeps source phrase", "cao" in r6["ceiling_height_note"].lower(),
          r6["ceiling_height_note"][:80])
    check("multi ceiling height warned", "Chiều cao trần có nhiều giá trị" in r6["warnings"],
          r6["warnings"][:120])

    # no height mentioned → empty, never a guessed default
    r7 = c._to_record({"title": "Kho", "price_text": "30 triệu/tháng", "area_text": "500 m2",
                       "description": "Kho sạch đẹp, chất lượng cao."},
                      {"price_basis": "total"}, "s", Path("x"))
    check("ceiling height stays empty when not stated", r7["ceiling_height_m"] == "",
          repr(r7["ceiling_height_m"]))
    check("ceiling note empty when not stated", r7["ceiling_height_note"] == "",
          repr(r7["ceiling_height_note"]))


def _is_challenge_snapshot(html: str) -> bool:
    """A saved challenge page has no listing markup; parsing it proves nothing."""
    from .session import CHALLENGE_MARKERS

    head = html[:4000].lower()
    return any(m in head for m in CHALLENGE_MARKERS)


def test_listing(snap: Path):
    print(f"\n== listing cards: {snap.name} ==")
    html = snap.read_text(encoding="utf-8")
    if _is_challenge_snapshot(html):
        skip(f"listing {snap.name}", "snapshot là trang challenge, không phải trang danh sách")
        return
    cards = parse_listing_cards(html, "https://example.test")
    check("cards found", len(cards) > 0, str(len(cards)))
    if not cards:
        return
    check("every card has a title", all(c["title"] for c in cards),
          str([i for i, c in enumerate(cards) if not c["title"]]))
    check("every card has an absolute url",
          all(c["url"].startswith("http") for c in cards),
          str([c["url"][:40] for c in cards if not c["url"].startswith("http")][:3]))
    # a headline price identical to the per-m² price must be flagged per_m2
    for c in cards:
        if c["price_per_m2_vnd"] and c["price_vnd"] == c["price_per_m2_vnd"]:
            check(f"card '{c['title'][:30]}' flagged per_m2", c["price_basis"] == "per_m2",
                  c["price_basis"])
            break


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-report", action="store_true")
    args = ap.parse_args()

    test_normalisers()
    test_verifier_catches_defects()
    test_record_mapping()

    groups, vns, listings = [], [], []
    for job in job_dirs():
        for site_dir in (job / "snapshots").iterdir():
            if not site_dir.is_dir():
                continue
            for f in sorted(site_dir.glob("*.html")):
                if f.name.startswith("detail_"):
                    (groups if "365" in site_dir.name else vns).append(f)
                elif f.name.startswith("listing_"):
                    listings.append(f)

    if not listings:
        skip("listing cards", "chưa có snapshot listing nào trong research/jobs")
    for f in listings[:3]:
        test_listing(f)

    if not groups:
        skip("batdongsan365 detail", "chưa có snapshot detail 365")
    for f in groups[:2]:
        test_group_detail(f)

    if not vns:
        skip("batdongsan.com.vn detail", "chưa có snapshot detail bds.com.vn")
    for f in vns[:2]:
        test_vn_detail(f)

    passed = sum(1 for r in RESULTS if r["status"] == "pass")
    failed = sum(1 for r in RESULTS if r["status"] == "fail")
    skipped = sum(1 for r in RESULTS if r["status"] == "skip")
    print(f"\n{'='*60}\nPASS {passed} | FAIL {failed} | SKIP {skipped}\n{'='*60}")

    if args.write_report:
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "passed": passed, "failed": failed, "skipped": skipped,
            "results": RESULTS,
        }
        out = Path("research/sites") / "regression-report.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report: {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())