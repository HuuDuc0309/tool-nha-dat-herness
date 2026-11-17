"""Phase explorers that reuse one browser session per site.

Each phase is a step in the same context, not a separate browser: cookies and
any solved Cloudflare challenge stay valid across phases. run_phase() keeps its
``(site, url, phase, out)`` argument tuple so existing callers keep working.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

PHASES = ["surface", "search-filter", "network", "detail-pagination"]


def stamp():
    return datetime.now(timezone.utc).isoformat()


def _save(result: dict, dest: Path) -> dict:
    result.setdefault("finished_at", stamp())
    (dest / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def run_phase(args, runtime=None, profile_dir=None, wait_human=0):
    from .session import SessionRuntime

    site, url, phase, out = args[:4]
    dest = Path(out) / site / "phases" / phase
    dest.mkdir(parents=True, exist_ok=True)
    result = {"site_id": site, "phase": phase, "url": url, "started_at": stamp(),
              "status": "failed", "observations": [], "requests": [], "errors": []}

    def _run(rt):
        session = rt.site(site, profile_dir=profile_dir)
        page = session.ensure_page()

        def req(r):
            if (r.resource_type in {"document", "xhr", "fetch"}
                    and urlparse(r.url).netloc.endswith(urlparse(url).netloc)):
                result["requests"].append({"url": r.url, "method": r.method,
                                           "type": r.resource_type})

        page.on("request", req)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
            if rt.is_challenge(page):
                if rt.headed:
                    deadline = wait_human if wait_human > 0 else 300
                    print(f">> [{phase}] challenge — giải trong cửa sổ (tối đa {deadline}s).",
                          flush=True)
                    for _ in range(deadline):
                        page.wait_for_timeout(1000)
                        if not rt.is_challenge(page):
                            break
                if rt.is_challenge(page):
                    result["status"] = "blocked"
                    result["errors"].append("cloudflare challenge not cleared")
                    return _save(result, dest)

            if phase == "surface":
                result["observations"] = {
                    "title": page.title(),
                    "links": page.locator("a[href]").count(),
                    "forms": page.locator("form").count(),
                    "inputs": page.locator("input").count(),
                    "buttons": page.locator("button,[role=button]").count(),
                }
            elif phase == "search-filter":
                for i in range(min(10, page.locator("input").count())):
                    el = page.locator("input").nth(i)
                    if (el.get_attribute("type") or "") in ("text", "search"):
                        try:
                            el.fill("nhà xưởng")
                            el.press("Enter")
                            page.wait_for_timeout(1500)
                            result["observations"].append({"action": "search", "url": page.url})
                        except Exception as e:
                            result["errors"].append(str(e))
                result["observations"].append(
                    {"buttons": page.locator("button,[role=button]").all_inner_texts()[:50]})
            elif phase == "network":
                result["observations"] = {
                    "content_sample": page.locator("body").inner_text()[:5000]}
            elif phase == "detail-pagination":
                links = page.locator("a[href]").evaluate_all("els=>els.map(e=>e.href)")
                result["observations"] = {
                    "candidate_links": [x for x in links
                                        if any(k in x.lower() for k in
                                               ("detail", "chi-tiet", "property",
                                                "bat-dong-san", "nha-dat"))][:100]}

            page.screenshot(path=str(dest / "screenshot.png"))
            result["status"] = "passed"
            return _save(result, dest)
        finally:
            page.remove_listener("request", req)

    try:
        if runtime is not None:
            return _run(runtime)
        with SessionRuntime(headed=False) as owned:
            return _run(owned)
    except Exception as e:
        result["errors"].append(str(e))
        return _save(result, dest)


def main():
    from .session import SessionRuntime

    ap = argparse.ArgumentParser()
    ap.add_argument("site")
    ap.add_argument("url")
    ap.add_argument("--out", type=Path, default=Path("research/sites"))
    ap.add_argument("--wait-human", type=int, default=300)
    args = ap.parse_args()
    with SessionRuntime(headed=False) as runtime:
        results = [run_phase((args.site, args.url, phase, str(args.out)),
                             runtime=runtime, wait_human=args.wait_human)
                   for phase in PHASES]
    print(json.dumps({"site_id": args.site, "phases": results},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()