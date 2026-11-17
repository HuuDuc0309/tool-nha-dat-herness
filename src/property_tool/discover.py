"""Interactive website explorer with persistent artifacts and completeness gates.

One browser session per site for the whole exploration: the same context (and
its cookies/Cloudflare clearance) is reused for every page instead of launching
a browser per URL. The work page is never closed — see session.py for why.

Transport rule: the entry page is loaded with goto() because it is the page
that gets interacted with (search box, filters, clicks) and screenshotted.
Every additional URL is read with fetch() in that same page, so the number of
document navigations — the main trigger for Cloudflare's managed challenge —
stays at one per exploration instead of one per page.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .crawler import fetch_in_page

TRACK_TYPES = {"document", "xhr", "fetch"}
KEYWORDS = {"search", "tim-kiem", "listing", "property", "real-estate",
            "bat-dong-san", "nha-dat", "kho", "xuong", "filter", "loc", "page",
            "detail", "chi-tiet"}

_LINK_RE = re.compile(r'<a\b[^>]*\bhref="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
_SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def links_from_html(html: str, base: str, limit: int = 200) -> list[dict]:
    """Anchor list from raw HTML: absolute href plus visible text."""
    out = []
    for href, inner in _LINK_RE.findall(html):
        text = re.sub(r"\s+", " ", unescape(_TAG_RE.sub(" ", inner))).strip()
        out.append({"href": urljoin(base, href), "text": text})
        if len(out) >= limit:
            break
    return out


def text_from_html(html: str, limit: int = 12000) -> str:
    cleaned = _SCRIPT_RE.sub(" ", html)
    return re.sub(r"\s+", " ", unescape(_TAG_RE.sub(" ", cleaned))).strip()[:limit]


def now():
    return datetime.now(timezone.utc).isoformat()


def sid(url):
    return re.sub(r"[^a-z0-9]+", "-", urlparse(url).netloc.lower()).strip("-") or "site"


def same_site(a, b):
    x, y = urlparse(a), urlparse(b)
    return x.netloc == y.netloc or x.netloc.endswith("." + y.netloc) or y.netloc.endswith("." + x.netloc)


def relevant(url):
    return any(k in url.lower() for k in KEYWORDS)


def safe_name(url):
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", urlparse(url).path.strip("/") or "home")[:80]


def _clear_challenge(runtime, page, headed: bool, wait_seconds: int) -> bool:
    """True when the page is readable. Never bypasses a challenge."""
    if not runtime.is_challenge(page):
        return True
    if not headed:
        return False
    deadline = wait_seconds if wait_seconds > 0 else 300
    print(f">> Challenge detected. Giải trong cửa sổ browser (tối đa {deadline}s).",
          flush=True)
    for _ in range(deadline):
        page.wait_for_timeout(1000)
        if not runtime.is_challenge(page):
            return True
    return not runtime.is_challenge(page)


def explore(start: str, root: Path, max_pages=20, max_clicks=30, headless=True,
            interactive_timeout=0, runtime=None, profile_dir=None):
    from .session import SessionRuntime

    site = sid(start)
    out = root / site
    out.mkdir(parents=True, exist_ok=True)
    (out / "discovery").mkdir(exist_ok=True)
    (out / "discovery" / "screenshots").mkdir(exist_ok=True)

    requests, responses, pages, interactions, errors = [], [], [], [], []
    visited, queued = set(), [start]

    def _run(runtime):
        session = runtime.site(site, profile_dir=profile_dir)
        page = session.ensure_page()

        def req(r):
            if r.resource_type in TRACK_TYPES and same_site(r.url, start):
                requests.append({"url": r.url, "method": r.method,
                                 "type": r.resource_type, "post_data": r.post_data})

        def res(r):
            if r.request.resource_type in {"xhr", "fetch"} and same_site(r.url, start):
                responses.append({"url": r.url, "status": r.status,
                                  "content_type": r.headers.get("content-type", "")})

        page.on("request", req)
        page.on("response", res)
        try:
            first = True
            while queued and len(visited) < max_pages:
                url = queued.pop(0)
                if url in visited or not same_site(url, start):
                    continue
                visited.add(url)
                before = len(requests)

                if first:
                    # Only the entry page is navigated: it is what gets the
                    # search box, filters, clicks and screenshots.
                    first = False
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(2500)
                    if not _clear_challenge(runtime, page, not headless,
                                            interactive_timeout):
                        errors.append({"page": url, "action": "challenge",
                                       "error": "challenge not cleared"})
                        continue
                    final, title = page.url, page.title()
                    html = page.content()
                    text = page.locator("body").inner_text(timeout=8000)[:12000]
                    links = page.locator("a[href]").evaluate_all(
                        "els=>els.map(e=>({href:e.href,text:(e.innerText||'').trim()}))")
                    forms = page.locator("form").evaluate_all(
                        "els=>els.map(e=>({action:e.action,method:e.method,"
                        "fields:[...e.elements].map(x=>x.name||x.type).filter(Boolean)}))")
                    buttons = page.locator("button,[role=button]").evaluate_all(
                        "els=>els.map(e=>(e.innerText||e.getAttribute('aria-label')||'')"
                        ".trim()).filter(Boolean).slice(0,80)")
                else:
                    # Every later URL is read without leaving the cleared page.
                    probe = fetch_in_page(page, url)
                    if probe.get("challenge") or not probe.get("html"):
                        errors.append({
                            "page": url,
                            "action": "fetch",
                            "error": probe.get("error") or "challenge/empty response",
                            "status": probe.get("status"),
                        })
                        continue
                    final, title = probe.get("url") or url, ""
                    html = probe["html"]
                    text = text_from_html(html)
                    links = links_from_html(html, final)
                    forms, buttons = [], []

                pages.append({"input_url": url, "final_url": final, "title": title,
                              "links": links[:200], "forms": forms, "buttons": buttons,
                              "request_start": before, "request_end": len(requests),
                              "text_sample": text})
                (out / "discovery" / f"{len(pages):03d}_{safe_name(final)}.html").write_text(
                    html, encoding="utf-8")
                if url == start:
                    page.screenshot(
                        path=str(out / "discovery" / "screenshots" / f"{len(pages):03d}.png"),
                        full_page=False)

                for item in links:
                    href = item.get("href", "")
                    if (same_site(href, start)
                            and (relevant(href) or len(queued) < max_pages * 2)
                            and href not in visited and href not in queued):
                        queued.append(href)

                # Interactive exploration only makes sense on a real document;
                # fetched pages have no live DOM to click.
                if url != start:
                    continue

                # Explore visible search controls; navigation is re-read from
                # the same page, so the next queued URL starts from the home
                # state instead of a filtered one.
                for i in range(min(page.locator("input").count(), 8)):
                    el = page.locator("input").nth(i)
                    typ = el.get_attribute("type") or "text"
                    name = el.get_attribute("name") or ""
                    if typ in {"text", "search"}:
                        try:
                            el.fill("nhà xưởng")
                            el.press("Enter")
                            page.wait_for_timeout(1800)
                            interactions.append({"page": final, "action": "fill_search",
                                                 "field": name, "value": "nhà xưởng",
                                                 "result_url": page.url})
                        except Exception as e:
                            errors.append({"page": final, "action": "fill_search",
                                           "error": str(e)})
                for i in range(min(page.locator("button").count(), max_clicks)):
                    button = page.locator("button").nth(i)
                    label = (button.inner_text() or "").strip().lower()
                    if any(k in label for k in
                           ("tìm", "search", "lọc", "filter", "xem thêm", "next", "tiếp")):
                        try:
                            button.click(timeout=1500)
                            page.wait_for_timeout(1200)
                            interactions.append({"page": final, "action": "click",
                                                 "label": label, "result_url": page.url})
                        except Exception as e:
                            errors.append({"page": final, "action": "click",
                                           "label": label, "error": str(e)})
        except Exception as e:
            errors.append({"page": start, "action": "explore", "error": str(e)})
        finally:
            page.remove_listener("request", req)
            page.remove_listener("response", res)

    if runtime is not None:
        _run(runtime)
    else:
        with SessionRuntime(headed=not headless) as owned:
            _run(owned)

    api = [r for r in responses
           if not any(x in r["url"].lower()
                      for x in ("google", "doubleclick", "analytics", "rum", "challenge"))]
    routes = {"search": [], "listing": [], "detail": [], "filter": [], "pagination": []}
    for p in pages:
        for l in p["links"]:
            u, label = l.get("href", "").lower(), (l.get("text") or "").lower()
            for kind, words in {
                "search": ("search", "tìm kiếm", "tim-kiem"),
                "filter": ("filter", "lọc"),
                "pagination": ("page=", "trang", "next", "tiếp"),
                "detail": ("chi-tiet", "detail", "/p/", "/property/"),
            }.items():
                if any(w in u or w in label for w in words):
                    routes[kind].append(l)
        if p["forms"]:
            routes["search"].extend(p["forms"])
    checks = {
        "homepage": bool(pages),
        "internal_routes": len(pages) > 1,
        "search_route": bool(routes["search"]),
        "listing_collection": bool(routes["listing"] or api),
        "listing_detail": bool(routes["detail"]),
        "pagination": bool(routes["pagination"]),
        "filter_interaction": bool(routes["filter"] or interactions),
        "network_catalog": bool(api),
        "replay_ready": bool(pages),
    }
    required = ("homepage", "search_route", "listing_collection",
                "listing_detail", "network_catalog", "replay_ready")
    complete = all(checks[k] for k in required) and not errors
    report = {"site_id": site, "start_url": start, "discovered_at": now(),
              "pages_explored": len(pages), "pages": pages,
              "interactions": interactions, "routes": routes, "requests": requests,
              "responses": responses, "api_candidates": api, "errors": errors,
              "checks": checks, "required_checks": list(required), "complete": complete,
              "notes": ["Automation does not bypass CAPTCHA/Cloudflare; human session may be required.",
                        "API candidates exclude known analytics/tracking/challenge traffic."]}
    (out / "discovery.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "manifest.json").write_text(
        json.dumps({"site_id": site,
                    "status": "candidate" if not complete else "tested",
                    "last_discovery": now(), "completeness": checks},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    from .session import SessionRuntime

    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--out", type=Path, default=Path("research/sites"))
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--wait-human", type=int, default=0)
    args = ap.parse_args()

    with SessionRuntime(headed=args.headed) as runtime:
        reports = [explore(u, args.out, args.max_pages, headless=not args.headed,
                           interactive_timeout=args.wait_human, runtime=runtime)
                   for u in args.urls]
    print(json.dumps({"status": "success",
                      "sites": [{"site_id": r["site_id"], "pages": r["pages_explored"],
                                 "complete": r["complete"], "checks": r["checks"]}
                                for r in reports]}, ensure_ascii=False))


if __name__ == "__main__":
    main()