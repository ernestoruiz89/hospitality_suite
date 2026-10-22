"""Read-only HTTP/asset gate for the one independent deployment rehearsal."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
BENCH=Path('/home/frappe/.hospitality-release-install/benches/hospitality-release-bench')
parser=argparse.ArgumentParser()
parser.add_argument('--label',required=True)
parser.add_argument('--expected',choices=['healthy','asset-fault'],required=True)
args=parser.parse_args()
assert __import__('re').fullmatch('[a-z0-9]+(?:-[a-z0-9]+)*',args.label)
output=ROOT/f'docs/evidence/f26-{args.label}.json';assert not output.exists()
assets=json.loads((BENCH/'sites/assets/assets.json').read_text())
bundle=assets['hospitality.bundle.js']
results={}
for path in ['/api/method/ping','/login',bundle]:
    try:
        with urllib.request.urlopen('http://hospitality-release.localhost:8091'+path,timeout=15) as response:
            raw=response.read();results[path]=dict(status=response.status,sha256=hashlib.sha256(raw).hexdigest())
    except urllib.error.HTTPError as error:results[path]=dict(status=error.code)
assert results['/api/method/ping']['status']==results['/login']['status']==200
assert results[bundle]['status']==(404 if args.expected=='asset-fault' else 200)
if args.expected=='healthy':
    assert results[bundle]['sha256']==hashlib.sha256((BENCH/'sites'/bundle.lstrip('/')).resolve().read_bytes()).hexdigest()
proof=dict(at_utc=datetime.now(timezone.utc).isoformat(),label=args.label,expected=args.expected,
    site='hospitality-release.localhost',bundle=bundle,results=results,read_only=True)
output.write_text(json.dumps(proof,indent=2)+'\n',newline='\n');print(json.dumps(proof))
