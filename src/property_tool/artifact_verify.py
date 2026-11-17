"""Read-only artifact completeness verification."""
from __future__ import annotations
import argparse,json
from pathlib import Path

def verify(site_dir: Path):
    discovery=site_dir/'discovery.json'; manifest=site_dir/'manifest.json'; phase=site_dir/'phase-report.json'
    issues=[]; report={"artifact":str(site_dir),"files":{},"checks":{}}
    for p in (discovery,manifest,phase): report['files'][p.name]=p.exists()
    if not discovery.exists(): issues.append('missing discovery.json')
    else:
        data=json.loads(discovery.read_text(encoding='utf-8')); checks=data.get('checks',{}); required=data.get('required_checks',[])
        report['checks']=checks; report['required_checks']=required
        report['required_passed']=all(checks.get(k,False) for k in required)
        if not report['required_passed']: issues.extend([k for k in required if not checks.get(k,False)])
        if data.get('errors'): issues.append('discovery_errors_present')
    report['status']='complete' if not issues else 'incomplete'; report['issues']=issues
    (site_dir/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('site_dir',type=Path); args=ap.parse_args(); print(json.dumps(verify(args.site_dir),ensure_ascii=False,indent=2))
if __name__=='__main__': main()
