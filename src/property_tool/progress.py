"""Màn hình tiến độ cho một job crawl đang chạy.

Đọc trực tiếp những gì crawler đã ghi ra đĩa, nên không can thiệp vào job:
  - ``snapshots/<site>/listing_*.html`` / ``detail_*.html`` → số lần fetch thật
  - ``crawl-partial.json`` (checkpoint mỗi 10 record) → số record + số card
    trên từng trang listing (tổng detail dự kiến cho site đó)

Cách dùng:
  python -m src.property_tool.progress                       # tự chọn job mới nhất
  python -m src.property_tool.progress --job research/jobs/<job>
  python -m src.property_tool.progress --watch               # tự làm mới 2 giây/lần
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

BAR_WIDTH = 24


def _bar(done: int, total: int) -> str:
    if total <= 0:
        return "[" + "?" * BAR_WIDTH + "]"
    filled = min(BAR_WIDTH, round(BAR_WIDTH * done / total))
    return "[" + "=" * filled + "-" * (BAR_WIDTH - filled) + "]"


def latest_job(root: Path) -> Path | None:
    if not root.exists():
        return None
    candidates = [p for p in root.iterdir() if p.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _load_checkpoint(job: Path) -> dict:
    """Final result if the job finished, otherwise the last checkpoint.

    Records are only checkpointed every 10 pages, so in a running job this view
    can lag the true count by up to 9 records; crawl-result.json is exact.
    """
    for name in ("crawl-result.json", "crawl-partial.json"):
        path = job / name
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return {}


def planned_details(checkpoint: dict, site: str) -> int:
    """Số link tin đã thấy trên các trang listing = số fetch detail dự kiến.

    Queue được lưu cùng checkpoint mỗi 10 record nên có thể trễ tối đa một
    chu kỳ checkpoint; đủ chính xác cho thanh tiến độ.
    """
    total = 0
    for item in checkpoint.get("queue", []):
        if item.get("site") != site or item.get("kind") != "listing":
            continue
        for note in item.get("notes") or []:
            match = re.match(r"(\d+) cards", str(note))
            if match:
                total += int(match.group(1))
    return total


def snapshots(job: Path, site: str) -> tuple[int, int]:
    folder = job / "snapshots" / site
    if not folder.exists():
        return 0, 0
    return (len(list(folder.glob("listing_*.html"))),
            len(list(folder.glob("detail_*.html"))))


def site_rows(job: Path, checkpoint: dict) -> list[dict]:
    records = checkpoint.get("records", [])
    sites = sorted({r.get("source_site") for r in records if r.get("source_site")})
    snap_root = job / "snapshots"
    if snap_root.exists():
        sites = sorted(set(sites) | {p.name for p in snap_root.iterdir() if p.is_dir()})
    # A finished job may have skipped detail pages by design (max_records cap),
    # so its "remaining" count is 0, not the card count of the listing pages.
    finished = (job / "crawl-result.json").exists()
    rows = []
    for site in sites:
        listings, details = snapshots(job, site)
        planned = max(planned_details(checkpoint, site), details)
        rows.append({
            "site": site,
            "listings": listings,
            "details": details,
            "planned": planned,
            "remaining": 0 if finished else max(0, planned - details),
            "records": sum(1 for r in records if r.get("source_site") == site),
        })
    return rows


def render(job: Path) -> str:
    checkpoint = _load_checkpoint(job)
    records = checkpoint.get("records", [])
    rows = site_rows(job, checkpoint)
    lines = [f"=== {job.name} — {time.strftime('%H:%M:%S')} ==="]
    for r in rows:
        lines.append(
            f"{r['site'][:26]:<26} listing {_bar(r['listings'], r['listings'])} {r['listings']:>3}  "
            f"detail {_bar(r['details'], r['planned'])} {r['details']}/{r['planned'] or '?'} "
            f"(còn ~{r['remaining']})  record {r['records']}")
    lines.append(f"{'TỔNG RECORD':<26} {len(records)}")
    return "\n".join(lines)


def done_message(job: Path, reason: str) -> str:
    checkpoint = _load_checkpoint(job)
    total = len(checkpoint.get("records", []))
    finished = " (đã xong toàn bộ fetch, còn lại là xuất Excel)" if reason == "result" else ""
    return (
        "Tiến độ đã xong, vui lòng đợi AI xử lý kết quả\n"
        f"Số tin đã lấy: {total}{finished}"
    )


def _snapshot_activity(job: Path) -> tuple[int, float]:
    """Độ "sống" của crawl: số file snapshot + thời gian ghi gần nhất."""
    snap_root = job / "snapshots"
    count, newest = 0, 0.0
    if snap_root.exists():
        for f in snap_root.glob("*/*.html"):
            count += 1
            newest = max(newest, f.stat().st_mtime)
    return count, newest


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = _parse_args()
    try:
        _watch(args)
    finally:
        # Cửa sổ do `start` mở sẽ đóng ngay khi tiến trình thoát; giữ lại để
        # user đọc được dòng "Tiến độ đã xong".
        if args.pause_on_exit:
            _pause_before_close()


def _parse_args():
    ap = argparse.ArgumentParser(description="Xem tiến độ crawl trực tiếp")
    ap.add_argument("--job", type=Path,
                    help="thư mục job (mặc định: job mới nhất trong research/jobs)")
    ap.add_argument("--root", type=Path, default=Path("research/jobs"))
    ap.add_argument("--watch", action="store_true", help="tự làm mới tới khi crawl xong")
    ap.add_argument("--every", type=float, default=2.0, help="chu kỳ làm mới (giây)")
    ap.add_argument("--idle-exit", type=float, default=90.0,
                    help="im lặng bao nhiêu giây thì coi như crawl đã dừng (0 = không tự dừng)")
    ap.add_argument("--pause-on-exit", action="store_true",
                    help="chờ Enter trước khi đóng (dùng cho cửa sổ tiến độ riêng)")
    return ap.parse_args()


def _watch(args) -> None:
    job = args.job or latest_job(args.root)
    if not job or not job.exists():
        print("Chưa có job crawl nào trong", args.root)
        return

    last_activity = (0, 0.0)
    quiet_since = time.time()
    while True:
        checkpoint = _load_checkpoint(job)
        activity = _snapshot_activity(job)
        remaining = sum(r["remaining"] for r in site_rows(job, checkpoint))
        finished = (job / "crawl-result.json").exists()
        text = render(job)
        if args.watch and sys.stdout.isatty():
            print("\x1b[2J\x1b[H" + text, flush=True)
        else:
            print(text, flush=True)

        if not args.watch:
            return

        # Crawl ghi crawl-result.json ở bước cuối: đó là dấu hiệu chắc chắn nhất.
        if finished:
            print("\n" + done_message(job, "result"), flush=True)
            return

        if activity != last_activity:
            last_activity, quiet_since = activity, time.time()
        elif args.idle_exit > 0 and remaining == 0 \
                and time.time() - quiet_since >= args.idle_exit:
            # Không fetch mới, không còn link nào trong hàng đợi -> crawl đã dừng
            # (hoặc chưa kịp bắt đầu). Không để cửa sổ treo vô hạn.
            print("\n" + done_message(job, "idle"), flush=True)
            return
        time.sleep(max(0.5, args.every))


def _pause_before_close() -> None:
    """Cửa sổ `start` đóng ngay khi tiến trình thoát — giữ lại để user đọc kết quả."""
    try:
        input("\nNhấn Enter để đóng cửa sổ tiến độ...")
    except (EOFError, OSError):
        pass


if __name__ == "__main__":
    main()