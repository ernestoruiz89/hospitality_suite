"""Migrate only the two protected local sites; keep verbose native logs private."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
BENCH=Path('/home/frappe/benches/hospitality-bench')
parser=argparse.ArgumentParser()
parser.add_argument('--site',choices=['hospitality.localhost','hospitality-acceptance.localhost'],required=True)
parser.add_argument('--phase',required=True)
parser.add_argument('--label',required=True)
args=parser.parse_args()
assert all(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',value) for value in [args.phase,args.label])
config=json.loads((BENCH/'sites'/args.site/'site_config.json').read_text())
assert config['db_name']==('hospitality_dev' if args.site=='hospitality.localhost' else 'hospitality_acceptance') and config.get('allow_tests')
if args.site=='hospitality-acceptance.localhost':assert config.get('hospitality_integration_test_site') and config.get('pause_scheduler')
assert (BENCH/f'.hospitality-{args.phase}-upgrade.json').is_file()
folder=ROOT/'.local'/args.phase;folder.mkdir(exist_ok=True,parents=True)
log=folder/(args.label+'.log');assert not log.exists(),'Preserve the preceding migration log'
command=['/home/frappe/.local/bin/bench','--site',args.site,'migrate']
print('Migrating protected local site: '+args.site,flush=True)
with log.open('w') as output:result=subprocess.run(command,cwd=BENCH,stdout=output,stderr=subprocess.STDOUT)
receipt=dict(site=args.site,command=command,exit_code=result.returncode,raw_log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),log_relative_to_workspace=log.relative_to(ROOT).as_posix())
(ROOT/f'docs/evidence/{args.phase}-{args.label}.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(receipt))
raise SystemExit(result.returncode)
