"""Persistent discovery-first orchestration for the main skill.

All phases and exploration share one SessionRuntime. Each site gets a separate
context, but it is reused for its entire run — no browser per phase or URL.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .discover import explore, sid
from .phase_explorer import PHASES, run_phase
from .session import SessionRuntime


def _profile_for(site: str, config=Path("config/sites.json")) -> str | None:
    if not config.exists():
        return None
    data = json.loads(config.read_text(encoding="utf-8"))
    for item in data.get("sites", []):
        if item.get("site_id") == site:
            return item.get("profile_dir")
    return None


def run(urls, root=Path("research/sites"), max_pages=20, headed=False,
        wait_human=0, runtime=None):
    results = []

    def _run(rt):
        for url in dict.fromkeys(urls):
            site = sid(url)
            manifest = root / site / "manifest.json"
            mode = "revalidate" if manifest.exists() else "research"
            profile_dir = _profile_for(site)
            # Sequential steps: Playwright's sync API is not thread/process-safe,
            # and separate processes cannot share a browser context/session.
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
    args = ap.parse_args()
    print(json.dumps({"status": "success", "phase": "discovery_gate",
                      "sites": run(args.urls, max_pages=args.max_pages,
                                   headed=args.headed, wait_human=args.wait_human)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
