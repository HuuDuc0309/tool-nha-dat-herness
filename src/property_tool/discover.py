"""Interactive website explorer with persistent artifacts and completeness gates."""
from __future__ import annotations
import argparse, json, re, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

TRACK_TYPES={"document","xhr","fetch"}
KEYWORDS={"search","tim-kiem","listing","property","real-estate","bat-dong-san","nha-dat","kho","xuong","filter","loc","page","detail","chi-tiet"}

def now(): return datetime.now(timezone.utc).isoformat()
def sid(url): return re.sub(r"[^a-z0-9]+","-",urlparse(url).netloc.lower()).strip("-") or "site"
def same_site(a,b):
    x,y=urlparse(a),urlparse(b)
    return x.netloc==y.netloc or x.netloc.endswith("."+y.netloc) or y.netloc.endswith("."+x.netloc)
def relevant(url): return any(k in url.lower() for k in KEYWORDS)
def safe_name(url): return re.sub(r"[^a-zA-Z0-9_-]+","_",urlparse(url).path.strip("/") or "home")[:80]

def explore(start: str, root: Path, max_pages=20, max_clicks=30, headless=True, interactive_timeout=0):
    site=sid(start); out=root/site; out.mkdir(parents=True,exist_ok=True)
    (out/"discovery").mkdir(exist_ok=True); (out/"discovery"/"screenshots").mkdir(exist_ok=True)
    requests=[]; responses=[]; pages=[]; interactions=[]; errors=[]; visited=set(); queued=[start]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=headless)
        context=browser.new_context(viewport={"width":1440,"height":1000})
        def req(r):
            if r.resource_type in TRACK_TYPES and same_site(r.url,start):
                requests.append({"url":r.url,"method":r.method,"type":r.resource_type,"post_data":r.post_data})
        def res(r):
            if r.request.resource_type in {"xhr","fetch"} and same_site(r.url,start):
                responses.append({"url":r.url,"status":r.status,"content_type":r.headers.get("content-type","")})
        context.on("request",req); context.on("response",res)
        while queued and len(visited)<max_pages:
            url=queued.pop(0)
            if url in visited or not same_site(url,start): continue
            page=context.new_page(); visited.add(url); before=len(requests)
            try:
                page.goto(url,wait_until="domcontentloaded",timeout=45000); page.wait_for_timeout(2500)
                title=page.title()
                if not headless and ("just a moment" in title.lower() or "security verification" in page.locator("body").inner_text(timeout=8000).lower()):
                    if interactive_timeout <= 0:
                        interactive_timeout = 300
                    print(f"[{site}] Challenge detected. Complete it in the visible browser; waiting {interactive_timeout}s.", flush=True)
                    page.wait_for_timeout(interactive_timeout * 1000)
                final=page.url; title=page.title(); html=page.content(); text=page.locator("body").inner_text(timeout=8000)[:12000]
                links=page.locator("a[href]").evaluate_all("els=>els.map(e=>({href:e.href,text:(e.innerText||'').trim()}))")
                forms=page.locator("form").evaluate_all("els=>els.map(e=>({action:e.action,method:e.method,fields:[...e.elements].map(x=>x.name||x.type).filter(Boolean)}))")
                buttons=page.locator("button,[role=button]").evaluate_all("els=>els.map(e=>(e.innerText||e.getAttribute('aria-label')||'').trim()).filter(Boolean).slice(0,80)")
                pages.append({"input_url":url,"final_url":final,"title":title,"links":links[:200],"forms":forms,"buttons":buttons,"request_start":before,"request_end":len(requests),"text_sample":text})
                (out/"discovery"/f"{len(pages):03d}_{safe_name(final)}.html").write_text(html,encoding="utf-8")
                page.screenshot(path=str(out/"discovery"/"screenshots"/f"{len(pages):03d}.png"),full_page=False)
                for item in links:
                    href=item.get("href","")
                    if same_site(href,start) and (relevant(href) or len(queued)<max_pages*2) and href not in visited and href not in queued:
                        queued.append(href)
                # Explore visible search/filter controls without bypassing challenges.
                for i in range(min(page.locator("input").count(),8)):
                    el=page.locator("input").nth(i)
                    typ=el.get_attribute("type") or "text"; name=el.get_attribute("name") or ""
                    if typ in {"text","search"}:
                        try:
                            el.fill("nhà xưởng"); el.press("Enter"); page.wait_for_timeout(1800)
                            interactions.append({"page":final,"action":"fill_search","field":name,"value":"nhà xưởng","result_url":page.url})
                        except Exception as e: errors.append({"page":final,"action":"fill_search","error":str(e)})
                for i in range(min(page.locator("button").count(),max_clicks)):
                    b=page.locator("button").nth(i); label=(b.inner_text() or "").strip().lower()
                    if any(k in label for k in ("tìm","search","lọc","filter","xem thêm","next","tiếp")):
                        try:
                            b.click(timeout=1500); page.wait_for_timeout(1200); interactions.append({"page":final,"action":"click","label":label,"result_url":page.url})
                        except Exception as e: errors.append({"page":final,"action":"click","label":label,"error":str(e)})
            except Exception as e:
                errors.append({"page":url,"action":"navigate","error":str(e)})
            finally: page.close()
        browser.close()
    api=[r for r in responses if not any(x in r["url"].lower() for x in ("google","doubleclick","analytics","rum","challenge"))]
    routes={"search":[],"listing":[],"detail":[],"filter":[],"pagination":[]}
    for p in pages:
        for l in p["links"]:
            u=l.get("href","").lower(); label=(l.get("text") or "").lower()
            for kind,words in {"search":("search","tìm kiếm","tim-kiem"),"filter":("filter","lọc"),"pagination":("page=","trang","next","tiếp"),"detail":("chi-tiet","detail","/p/","/property/")}.items():
                if any(w in u or w in label for w in words): routes[kind].append(l)
        if p["forms"]: routes["search"].extend(p["forms"])
    checks={"homepage":bool(pages),"internal_routes":len(pages)>1,"search_route":bool(routes["search"]),"listing_collection":bool(routes["listing"] or api),"listing_detail":bool(routes["detail"]),"pagination":bool(routes["pagination"]),"filter_interaction":bool(routes["filter"] or interactions),"network_catalog":bool(api),"replay_ready":bool(pages)}
    # Required gates are conjunctive: a high score cannot hide a missing detail flow.
    required=("homepage","search_route","listing_collection","listing_detail","network_catalog","replay_ready")
    complete=all(checks[k] for k in required) and not errors
    report={"site_id":site,"start_url":start,"discovered_at":now(),"pages_explored":len(pages),"pages":pages,"interactions":interactions,"routes":routes,"requests":requests,"responses":responses,"api_candidates":api,"errors":errors,"checks":checks,"required_checks":list(required),"complete":complete,"notes":["Automation does not bypass CAPTCHA/Cloudflare; human session may be required.","API candidates exclude known analytics/tracking/challenge traffic."]}
    (out/"discovery.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"manifest.json").write_text(json.dumps({"site_id":site,"status":"candidate" if not report["complete"] else "tested","last_discovery":now(),"completeness":checks},ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"template.md").write_text(f"# Site Integration\n\n- Site ID: `{site}`\n- Status: `{'tested' if report['complete'] else 'incomplete'}`\n- Pages explored: `{len(pages)}`\n\n## Completeness\n\n```json\n{json.dumps(checks,ensure_ascii=False,indent=2)}\n```\n\n## API / Feed\nSee `discovery.json` and `requests`/`api_candidates`.\n\n## Special Notes\n- CAPTCHA/Cloudflare is not bypassed.\n- Do not promote to active until all required flows are replay-tested.\n",encoding="utf-8")
    return report

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("urls",nargs="+"); ap.add_argument("--out",type=Path,default=Path("research/sites")); ap.add_argument("--max-pages",type=int,default=20); ap.add_argument("--headed",action="store_true",help="Mở browser để human xử lý challenge/login"); ap.add_argument("--wait-human",type=int,default=0,help="Số giây chờ human sau khi mở browser"); args=ap.parse_args()
    reports=[explore(u,args.out,args.max_pages,headless=not args.headed,interactive_timeout=args.wait_human) for u in args.urls]; print(json.dumps({"status":"success","sites":[{"site_id":r["site_id"],"pages":r["pages_explored"],"complete":r["complete"],"checks":r["checks"]} for r in reports]},ensure_ascii=False))
if __name__=='__main__': main()
