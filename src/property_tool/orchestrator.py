"""Persistent discovery-first orchestration for the main skill."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from .discover import explore,sid
from .phase_explorer import run_phase
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime


def run(urls, root=Path('research/sites'), max_pages=20, headed=False, wait_human=0):
    results=[]
    for url in dict.fromkeys(urls):
        site=sid(url); manifest=root/site/'manifest.json'
        # Existing artifacts are always revalidated by replaying discovery.
        mode='revalidate' if manifest.exists() else 'research'
        phase_names=['surface','search-filter','network','detail-pagination']
        jobs=[(site,url,phase,str(root)) for phase in phase_names]
        with ProcessPoolExecutor(max_workers=min(4,len(jobs))) as pool:
            phase_reports=[future.result() for future in as_completed([pool.submit(run_phase,job) for job in jobs])]
        report=explore(url,root,max_pages,headless=not headed,interactive_timeout=wait_human)
        phase_ok=all(x.get('status')=='passed' for x in phase_reports)
        complete=report['complete'] and phase_ok
        (root/site/'phase-report.json').write_text(json.dumps({'site_id':site,'mode':mode,'phases':phase_reports,'complete':complete},ensure_ascii=False,indent=2),encoding='utf-8')
        results.append({'site_id':site,'mode':mode,'complete':complete,'checks':report['checks'],'phases':phase_reports,'artifact':str(root/site)})
    return results

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('urls',nargs='+'); ap.add_argument('--max-pages',type=int,default=20); ap.add_argument('--headed',action='store_true'); ap.add_argument('--wait-human',type=int,default=300); args=ap.parse_args(); print(json.dumps({'status':'success','phase':'discovery_gate','sites':run(args.urls,max_pages=args.max_pages,headed=args.headed,wait_human=args.wait_human)},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
