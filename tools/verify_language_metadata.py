"""Labels may change; DocType fields, options, defaults and permissions may not."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--base',required=True);args=parser.parse_args()
def without_labels(value):
    if isinstance(value,dict):return {key:without_labels(item) for key,item in value.items() if key!='label'}
    if isinstance(value,list):return [without_labels(item) for item in value]
    return value
checked=[];changed=0
for path in sorted((ROOT/'hospitality_suite/hospitality_suite/doctype').glob('*/*.json')):
    relative=path.relative_to(ROOT).as_posix()
    old=json.loads(subprocess.check_output(['git','show',args.base+':'+relative],cwd=ROOT))
    new=json.loads(path.read_text(encoding='utf-8'))
    assert without_labels(old)==without_labels(new),relative
    checked.append(relative);changed+=sum(a.get('label')!=b.get('label') for a,b in zip(old['fields'],new['fields']))
with (ROOT/'hospitality_suite/translations/es.csv').open(encoding='utf-8',newline='') as stream:rows=list(csv.reader(stream))
keys=[(row[0],row[2] if len(row)>2 else '') for row in rows];assert len(keys)==len(set(keys))
proof=dict(base=args.base,doctypes=len(checked),changed_field_labels=changed,fieldnames_options_defaults_permissions_unchanged=True,
           contextual_options=sum(len(row)==3 for row in rows),source_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in checked})
(ROOT/'docs/evidence/language-review-metadata.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({key:value for key,value in proof.items() if key!='source_sha256'}))
