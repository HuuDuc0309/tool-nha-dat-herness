"""Phase-isolated explorers: every phase owns its own Playwright browser/context."""
from __future__ import annotations
import argparse,json
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

def stamp(): return datetime.now(timezone.utc).isoformat()
def run_phase(args):
    site,url,phase,out=args; dest=Path(out)/site/'phases'/phase; dest.mkdir(parents=True,exist_ok=True)
    result={'site_id':site,'phase':phase,'url':url,'started_at':stamp(),'status':'failed','observations':[],'requests':[],'errors':[]}
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True); ctx=browser.new_context(viewport={'width':1440,'height':1000}); page=ctx.new_page()
            def req(r):
                if r.resource_type in {'document','xhr','fetch'} and urlparse(r.url).netloc.endswith(urlparse(url).netloc): result['requests'].append({'url':r.url,'method':r.method,'type':r.resource_type})
            page.on('request',req); page.goto(url,wait_until='domcontentloaded',timeout=45000); page.wait_for_timeout(2500)
            if phase=='surface':
                result['observations']={'title':page.title(),'links':page.locator('a[href]').count(),'forms':page.locator('form').count(),'inputs':page.locator('input').count(),'buttons':page.locator('button,[role=button]').count()}
            elif phase=='search-filter':
                for i in range(min(10,page.locator('input').count())):
                    el=page.locator('input').nth(i); typ=el.get_attribute('type') or ''
                    if typ in ('text','search'):
                        try: el.fill('nhà xưởng'); el.press('Enter'); page.wait_for_timeout(1500); result['observations'].append({'action':'search','url':page.url})
                        except Exception as e: result['errors'].append(str(e))
                result['observations'].append({'buttons':page.locator('button,[role=button]').all_inner_texts()[:50]})
            elif phase=='network':
                result['observations']={'content_sample':page.locator('body').inner_text()[:5000]}
            elif phase=='detail-pagination':
                links=page.locator('a[href]').evaluate_all("els=>els.map(e=>e.href)")
                result['observations']={'candidate_links':[x for x in links if any(k in x.lower() for k in ('detail','chi-tiet','property','bat-dong-san','nha-dat'))][:100]}
            page.screenshot(path=str(dest/'screenshot.png')); browser.close()
        result['status']='passed'; result['finished_at']=stamp(); (dest/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8'); return result
    except Exception as e:
        result['errors'].append(str(e)); result['finished_at']=stamp(); (dest/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8'); return result

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('site'); ap.add_argument('url'); ap.add_argument('--out',type=Path,default=Path('research/sites')); ap.add_argument('--workers',type=int,default=4); args=ap.parse_args()
    phases=['surface','search-filter','network','detail-pagination']; jobs=[(args.site,args.url,p,str(args.out)) for p in phases]
    with ProcessPoolExecutor(max_workers=min(args.workers,len(jobs))) as pool: results=[f.result() for f in as_completed([pool.submit(run_phase,j) for j in jobs])]
    print(json.dumps({'site_id':args.site,'phases':results},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
