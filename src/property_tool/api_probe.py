"""Bounded listing/pagination/detail network probe in one session per site.

Only public, configured rental routes are visited. No endpoint guessing, phone
reveal, authentication tokens or request bodies are saved. A JSON response is a
candidate, not a verified integration. Existing site artifacts are never changed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .adapters.batdongsan_group import next_page_urls, parse_listing_cards
from .crawler import Crawler, ChallengeRequired, ChallengeTimeout, SiteState, load_registry, now_iso, detail_parser_for
from .session import SessionRuntime


def _public_url(url):
    # Query strings can carry credentials. Endpoint paths suffice for the catalog.
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}{p.path}"


def _shape(value):
    if isinstance(value, dict):
        return {"type": "object", "keys": list(value)[:40]}
    if isinstance(value, list):
        return {"type": "array", "length": len(value),
                "item": _shape(value[0]) if value else None}
    return {"type": type(value).__name__}


def probe(registry_path: Path, out: Path, site_filter=None, wait_human=300):
    import re

    registry = load_registry(registry_path)
    out.mkdir(parents=True, exist_ok=True)
    reports = []
    with SessionRuntime(headed=True) as runtime:
        crawler = Crawler(registry, out, 2, 1, 1.5, True, wait_human, runtime)
        for site in registry["sites"]:
            if site_filter and site["site_id"] not in site_filter:
                continue
            site_id, base = site["site_id"], site["base"]
            state = SiteState(site_id, base, site.get("profile_dir"),
                              site.get("cloudflare", False),
                              re.compile(site["detail_path_re"]),
                              platform=site["platform"],
                              parse_detail=detail_parser_for(site["platform"]))
            report = {"site_id": site_id, "status": "needs_review", "pages": [],
                      "network": [], "json_responses": [], "errors": [],
                      "api_status": "not_verified"}
            reports.append(report)
            dest = out / site_id
            dest.mkdir(exist_ok=True)
            try:
                session = runtime.site(site_id, profile_dir=state.profile_dir)
                page = session.ensure_page()
            except Exception as exc:
                report["status"] = "failed"
                report["errors"].append(type(exc).__name__)
                continue

            # Listen only to document/xhr/fetch, never store cookies, headers,
            # query values, request bodies, account responses or analytics.
            pending = []

            def response(r):
                p = urlparse(r.url)
                host = urlparse(base).netloc
                if not (p.netloc == host or p.netloc.endswith("." + host)):
                    return
                if r.request.resource_type not in {"document", "xhr", "fetch"}:
                    return
                if any(x in p.path.lower() for x in
                       ("account", "users", "survey", "cdn-cgi", "flags", "proxy")):
                    return
                ct = r.headers.get("content-type", "")
                report["network"].append({"endpoint": _public_url(r.url),
                                          "method": r.request.method,
                                          "status": r.status,
                                          "content_type": ct,
                                          "step": len(report["pages"]) + 1})
                if "json" in ct.lower() and 200 <= r.status < 300:
                    pending.append(r)

            def read_json_responses():
                # Read bodies before navigating: Chromium may release response
                # bodies from the previous document after a new navigation.
                for r in pending[:]:
                    try:
                        data = r.json()
                        report["json_responses"].append({
                            "endpoint": _public_url(r.url), "shape": _shape(data)})
                    except Exception:
                        report["errors"].append("json_response_unreadable")
                    pending.remove(r)

            page.on("response", response)
            try:
                # Use an office listing so the sample has a chance of pagination.
                cat = next((c for c in site["categories"] if "van-phong" in c["key"]),
                           site["categories"][0])
                listing = urljoin(base, cat["path"])
                html, final = crawler._fetch(session.context, state, listing, "listing")
                page.wait_for_timeout(1500)
                read_json_responses()
                cards = parse_listing_cards(html, base)
                (dest / "listing.html").write_text(html, encoding="utf-8")
                report["pages"].append({"kind": "listing", "url": final,
                                        "cards": len(cards), "parse_ok": bool(cards)})
                print(f"[{site_id}] listing: {len(cards)} cards; session reused", flush=True)
                next_urls = [urljoin(final, u) for u in next_page_urls(html, base)]
                # '?page=1' is the current page, not a next page.
                nxt = next((u for u in next_urls
                            if u not in (final, final + "?page=1")
                            and not u.endswith(("page=1", "/p1", "/p1/"))
                            and urlparse(u).netloc == urlparse(base).netloc), None)
                if nxt:
                    # Follow the real link in the same tab to exercise pagination.
                    html2, final2 = crawler._fetch(session.context, state, nxt, "listing")
                    page.wait_for_timeout(1500)
                    read_json_responses()
                    cards2 = parse_listing_cards(html2, base)
                    (dest / "pagination.html").write_text(html2, encoding="utf-8")
                    report["pages"].append({"kind": "pagination", "url": final2,
                                            "cards": len(cards2),
                                            "results_changed": {c['url'] for c in cards2} !=
                                                               {c['url'] for c in cards}})
                if cards:
                    card = cards[0]
                    detail, final3 = crawler._fetch(session.context, state, card["url"], "detail")
                    page.wait_for_timeout(1500)
                    read_json_responses()
                    snapshot = dest / "detail.html"
                    snapshot.write_text(detail, encoding="utf-8")
                    parsed = state.parse_detail(detail, final3)
                    rec = crawler._to_record(parsed, card, site_id, snapshot)
                    crawler.records.append(rec)
                    crawler._add_evidence(parsed, card, rec, final3, site_id, snapshot)
                    report["pages"].append({"kind": "detail", "url": final3,
                                            "parse_ok": bool(parsed.get("title")),
                                            "fields_present": [k for k, v in parsed.items() if v]})
                read_json_responses()
                report["status"] = "sampled" if cards else "needs_review"
                print(f"[{site_id}] sampled: {len(report['json_responses'])} JSON responses; "
                      "API integration NOT verified", flush=True)
            except (ChallengeRequired, ChallengeTimeout):
                report["status"] = "blocked"
                report["errors"].append("human_challenge_not_cleared")
                print(f"[{site_id}] blocked — no further requests for this site", flush=True)
            except Exception as exc:
                report["status"] = "failed"
                report["errors"].append(type(exc).__name__)
                print(f"[{site_id}] failed: {type(exc).__name__}", flush=True)
            finally:
                page.remove_listener("response", response)
                (dest / "api-research.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                (out / "crawl-result.json").write_text(json.dumps({
                    "generated_at": now_iso(), "sites": reports,
                    "records": crawler.records, "evidence": crawler.evidence,
                    "unknown": crawler.unknown, "warnings": crawler.warnings,
                    "queue": crawler.queue_items,
                }, ensure_ascii=False, indent=2), encoding="utf-8")
    return reports


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", type=Path, default=Path("config/sites.json"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sites", nargs="*")
    ap.add_argument("--wait-human", type=int, default=300)
    args = ap.parse_args()
    print(json.dumps(probe(args.registry, args.out, args.sites, args.wait_human),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
