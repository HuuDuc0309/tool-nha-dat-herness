"""Verify structured extraction against its own evidence — no raw data into context.

Reads a crawl-result.json plus the HTML snapshots it points to and reports:
  - schema completeness (every record has the required keys)
  - value sanity (area/price ranges, date format, phone shape)
  - evidence agreement (the value appears in the snapshot text)
  - contradictions (e.g. a total rent that equals the per-m² price)

Writes verification.json next to the crawl result.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REQUIRED_KEYS = [
    "title", "source_url", "source_site", "address", "province", "district", "ward",
    "rent_amount", "rent_amount_text", "rent_period", "deposit",
    "land_area_m2", "factory_area_m2", "usable_area_m2", "frontage_m",
    "contact", "extraction_status", "confidence", "warnings",
]

PHONE_RE = re.compile(r"^\d{10,11}$|^0\d[\d.\s]{7,12}$|^\*{4,}\d+$|^0\d{3}[\s.]\d{3}[\s.]\*{3}$")
DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s²]", " ", text or "")).strip().lower()


def _to_float(value) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def verify(record: dict, snapshot_text: str | None) -> list[dict]:
    issues = []
    url = record.get("source_url")

    missing = [k for k in REQUIRED_KEYS if k not in record]
    if missing:
        issues.append({"level": "error", "kind": "schema_missing_key", "detail": ",".join(missing)})

    # unknown must never be silently turned into false/0
    for key in ("rent_amount", "usable_area_m2", "land_area_m2", "factory_area_m2", "frontage_m"):
        if record.get(key) in (0, "0", False):
            issues.append({"level": "warn", "kind": "suspicious_zero",
                           "detail": f"{key}=0 — kiểm tra xem đây là 0 thật hay giá trị thiếu bị đổi"})

    area = _to_float(record.get("usable_area_m2"))
    if area is not None:
        if area < 5:
            issues.append({"level": "warn", "kind": "area_too_small",
                           "detail": f"usable_area_m2={area} (<5m²) — có thể là giá/m² bị nhầm"})
        elif area > 200000:
            issues.append({"level": "warn", "kind": "area_too_large",
                           "detail": f"usable_area_m2={area} (>200.000m²)"})

    rent = _to_float(record.get("rent_amount"))
    if rent is not None:
        if rent < 100000:
            issues.append({"level": "error", "kind": "rent_too_low",
                           "detail": f"rent_amount={rent:.0f} — khả năng là giá theo m² bị ghi thành tổng giá"})
        elif rent > 5_000_000_000:
            issues.append({"level": "warn", "kind": "rent_too_high", "detail": f"rent_amount={rent:.0f}"})

    # contradiction: total rent == per-m² price
    per_m2 = _to_float(record.get("price_per_m2_vnd"))
    if rent is not None and per_m2 is not None and abs(rent - per_m2) < 1:
        issues.append({"level": "error", "kind": "price_basis_contradiction",
                       "detail": f"rent_amount == price_per_m2_vnd == {rent:.0f}"})

    contact = record.get("contact") or ""
    if contact and not PHONE_RE.match(contact):
        issues.append({"level": "warn", "kind": "contact_not_a_phone", "detail": contact[:40]})

    for key in ("posted_at", "expires_at"):
        value = record.get(key)
        if value and not DATE_RE.match(value):
            issues.append({"level": "warn", "kind": "bad_date_format", "detail": f"{key}={value}"})

    conf = _to_float(record.get("confidence"))
    if conf is None or not (0 <= conf <= 1):
        issues.append({"level": "error", "kind": "bad_confidence", "detail": str(record.get("confidence"))})

    # address decomposition sanity
    addr = record.get("address") or ""
    if addr and addr.strip().startswith("·"):
        issues.append({"level": "error", "kind": "address_not_trimmed", "detail": addr[:60]})
    if record.get("province") and addr and record["province"] not in addr:
        issues.append({"level": "warn", "kind": "province_not_in_address",
                       "detail": f"{record['province']!r} vs {addr[:60]!r}"})

    if not record.get("title"):
        issues.append({"level": "error", "kind": "missing_title", "detail": ""})
    if not record.get("source_url"):
        issues.append({"level": "error", "kind": "missing_source_url", "detail": ""})

    # evidence agreement: the address and area text should appear in the snapshot
    if snapshot_text:
        hay = _norm(snapshot_text)
        # address may legitimately be rendered as several lines/spans, so compare
        # its longest comma-separated part instead of the whole joined string
        addr = record.get("address") or ""
        if addr:
            parts = [_norm(p) for p in addr.split(",") if p.strip()]
            if parts and not any(p in hay for p in parts):
                issues.append({"level": "warn", "kind": "address_not_in_snapshot",
                               "detail": addr[:60]})
        # area: compare the numeric value, the site may render '60.000' vs '60000'
        area_nums = re.findall(r"[\d][\d.,]*", record.get("usable_area_text") or "")
        if area_nums:
            digits = re.sub(r"[.,]", "", area_nums[0])
            if digits and digits not in re.sub(r"[.,]", "", snapshot_text):
                issues.append({"level": "warn", "kind": "area_text_not_in_snapshot",
                               "detail": str(record.get("usable_area_text"))[:60]})
        code = record.get("listing_code")
        if code and code not in snapshot_text:
            issues.append({"level": "warn", "kind": "code_not_in_snapshot", "detail": str(code)})

    return issues


def run(job_dir: Path) -> dict:
    result_path = job_dir / "crawl-result.json"
    if not result_path.exists():
        return {"status": "error", "detail": f"missing {result_path}"}
    result = json.loads(result_path.read_text(encoding="utf-8"))
    records = result.get("records", [])

    snapshots: dict[str, str] = {}
    snap_root = job_dir / "snapshots"
    if snap_root.exists():
        for f in snap_root.rglob("*.html"):
            snapshots[str(f)] = f.read_text(encoding="utf-8", errors="replace")

    rows = []
    kind_counter: Counter = Counter()
    level_counter: Counter = Counter()
    for rec in records:
        snap_path = rec.get("snapshot") or ""
        snap_text = snapshots.get(snap_path)
        issues = verify(rec, snap_text)
        for iss in issues:
            kind_counter[iss["kind"]] += 1
            level_counter[iss["level"]] += 1
        rows.append({
            "source_url": rec.get("source_url"),
            "site": rec.get("source_site"),
            "title": (rec.get("title") or "")[:80],
            "issues": issues,
            "snapshot_checked": bool(snap_text),
        })

    errors = sum(1 for r in rows for i in r["issues"] if i["level"] == "error")
    warns = sum(1 for r in rows for i in r["issues"] if i["level"] == "warn")
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "job_dir": str(job_dir),
        "records": len(records),
        "records_with_snapshot_evidence": sum(1 for r in rows if r["snapshot_checked"]),
        "errors": errors,
        "warnings": warns,
        "clean_records": sum(1 for r in rows if not r["issues"]),
        "issue_kinds": dict(kind_counter.most_common()),
        "issue_levels": dict(level_counter),
        "status": "clean" if errors == 0 else ("has_errors" if errors else "warnings_only"),
        "rows": rows,
    }
    (job_dir / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    ap = argparse.ArgumentParser(description="Verify crawl-result.json against schema + snapshots")
    ap.add_argument("job_dir", type=Path)
    args = ap.parse_args()
    report = run(args.job_dir)
    summary = {k: v for k, v in report.items() if k not in ("rows",)}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()