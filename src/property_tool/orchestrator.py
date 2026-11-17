"""Discovery-first orchestration for the main skill.

All phases and exploration share one SessionRuntime. Each site gets a separate
context, but it is reused for its entire run — no browser per phase or URL.

Flow is crawl-first when an artifact already exists:
  1. smoke crawl a couple of listing pages + details through Crawler
     (fetch transport) — this is the normal path and skips discovery;
  2. only when the smoke crawl cannot read the site does the full discovery
     revalidation run, and then the crawl is retried.
A Cloudflare challenge is NOT a parser failure: the run stops with
``needs_human`` so a person can solve it, instead of re-exploring the site.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .crawler import Crawler
from .discover import explore, sid
from .phase_explorer import PHASES, run_phase
from .session import SessionRuntime

SMOKE_LISTING_PAGES = 1
SMOKE_DETAILS = 3


def _profile_for(site: str, config=Path("config/sites.json")) -> str | None:
    if not config.exists():
        return None
    data = json.loads(config.read_text(encoding="utf-8"))
    for item in data.get("sites", []):
        if item.get("site_id") == site:
            return item.get("profile_dir")
    return None


def _site_config(site: str, config=Path("config/sites.json")) -> dict | None:
    if not config.exists():
        return None
    data = json.loads(config.read_text(encoding="utf-8"))
    for item in data.get("sites", []):
        if item.get("site_id") == site:
            return item
    return None


def smoke_crawl(site_id: str, out_dir: Path, runtime, headed: bool,
                wait_human: int, config_path=Path("config/sites.json")) -> dict:
    """Small crawl that answers one question: can we read this site right now?

    Returns {"ok": bool, "blocked": bool, "records": int, "reason": str}.
    A blocked result means a human must solve a challenge — it is deliberately
    distinguished from a parse failure so the caller does not re-explore.
    """
    site = _site_config(site_id, config_path)
    if not site:
        return {"ok": False, "blocked": False, "records": 0,
                "reason": "site chưa có trong config/sites.json"}

    crawler = Crawler({"sites": [site]}, out_dir, SMOKE_LISTING_PAGES, SMOKE_DETAILS,
                      delay=1.5, headed=headed, wait_human=wait_human, runtime=runtime)
    summary = crawler.crawl_site(site)
    records = len(crawler.records)
    details = summary.get("details_fetched", 0)
    cards = summary.get("listings_fetched", 0)
    blocked = bool(summary.get("blocked"))

    if blocked:
        return {"ok": False, "blocked": True, "records": records,
                "reason": "Cloudflare challenge chưa được giải",
                "summary": summary}
    # A card-only record means the listing markup still parses but the detail
    # page does not: that is exactly the case discovery is meant to catch, so
    # records alone are not enough to call the artifact healthy.
    parsed_details = sum(
        1 for r in crawler.records
        if "detail" in str(r.get("extraction_status", "")).lower())
    if records and parsed_details:
        return {"ok": True, "blocked": False, "records": records,
                "details_parsed": parsed_details,
                "reason": f"{parsed_details} detail parse được / {cards} trang listing",
                "summary": summary}
    if not cards:
        return {"ok": False, "blocked": False, "records": records,
                "reason": "không đọc được trang listing — cần discovery",
                "summary": summary}
    return {"ok": False, "blocked": False, "records": records,
            "details_parsed": parsed_details,
            "reason": "listing đọc được nhưng detail không parse — cần discovery",
            "summary": summary}


def run(urls, root=Path("research/sites"), max_pages=20, headed=False,
        wait_human=0, runtime=None, skip_smoke=False,
        config_path=Path("config/sites.json")):
    results = []

    def _discovery(rt, site, url, profile_dir, mode):
        phase_reports = [
            run_phase((site, url, phase, str(root)), runtime=rt,
                      profile_dir=profile_dir, wait_human=wait_human)
            for phase in PHASES
        ]
        report = explore(url, root, max_pages, headless=not headed,
                         interactive_timeout=wait_human, runtime=rt,
                         profile_dir=profile_dir)
        complete = report["complete"] and all(
            x.get("status") == "passed" for x in phase_reports)
        (root / site / "phase-report.json").write_text(
            json.dumps({"site_id": site, "mode": mode, "phases": phase_reports,
                        "complete": complete}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return report, phase_reports, complete

    def _run(rt):
        for url in dict.fromkeys(urls):
            site = sid(url)
            manifest = root / site / "manifest.json"
            has_artifact = manifest.exists()
            profile_dir = _profile_for(site, config_path)

            if has_artifact and not skip_smoke:
                smoke = smoke_crawl(site, Path("research/jobs/_smoke") / site,
                                    rt, headed, wait_human, config_path)
                if smoke["blocked"]:
                    results.append({
                        "site_id": site, "mode": "smoke", "complete": False,
                        "status": "blocked", "needs_human": True,
                        "smoke": {k: v for k, v in smoke.items() if k != "summary"},
                        "action": "Giải Cloudflare trong cửa sổ browser rồi chạy lại.",
                        "artifact": str(root / site),
                    })
                    continue
                if smoke["ok"]:
                    results.append({
                        "site_id": site, "mode": "smoke", "complete": True,
                        "status": "ready", "smoke": smoke,
                        "note": "Artifact còn tốt — bỏ qua discovery, chuyển sang crawl.",
                        "artifact": str(root / site),
                    })
                    continue
                # Fall through to discovery only for a real read/parse failure.
                report, phase_reports, complete = _discovery(rt, site, url, profile_dir,
                                                             "repair")
                results.append({
                    "site_id": site, "mode": "repair", "complete": complete,
                    "status": "ready" if complete else "needs_review",
                    "smoke": {k: v for k, v in smoke.items() if k != "summary"},
                    "checks": report["checks"], "phases": phase_reports,
                    "artifact": str(root / site),
                })
                continue

            mode = "revalidate" if has_artifact else "research"
            report, phase_reports, complete = _discovery(rt, site, url, profile_dir, mode)
            results.append({"site_id": site, "mode": mode, "complete": complete,
                            "checks": report["checks"], "phases": phase_reports,
                            "artifact": str(root / site)})

    if runtime is not None:
        _run(runtime)
    else:
        with SessionRuntime(headed=headed) as owned:
            _run(owned)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--wait-human", type=int, default=300)
    ap.add_argument("--skip-smoke", action="store_true",
                    help="bỏ smoke crawl, luôn chạy discovery")
    args = ap.parse_args()
    print(json.dumps({"status": "success", "phase": "discovery_gate",
                      "sites": run(args.urls, max_pages=args.max_pages,
                                   headed=args.headed, wait_human=args.wait_human,
                                   skip_smoke=args.skip_smoke)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
