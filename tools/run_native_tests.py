"""Run native app regressions only on protected, empty acceptance; preserve raw reports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
BENCH=Path('/home/frappe/benches/hospitality-bench')
SITE='hospitality-acceptance.localhost'
parser=argparse.ArgumentParser()
parser.add_argument('--phase',required=True)
parser.add_argument('--label',default='native-full-1')
args=parser.parse_args()
assert all(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',value) for value in [args.phase,args.label])
config=json.loads((BENCH/'sites'/SITE/'site_config.json').read_text())
assert config['db_name']=='hospitality_acceptance' and config.get('allow_tests') and config.get('hospitality_integration_test_site') and config.get('pause_scheduler')
assert (BENCH/f'.hospitality-{args.phase}-upgrade.json').is_file() and (BENCH/f'.hospitality-{args.phase}-ux-baseline.json').is_file()
output=ROOT/'.local'/args.phase;output.mkdir(exist_ok=True,parents=True)
log=output/(args.label+'.log');raw_xml=output/(args.label+'.raw.xml')
assert not log.exists() and not raw_xml.exists(),'Preserve the preceding run; choose another explicit label'
command=['/home/frappe/.local/bin/bench','--site',SITE,'run-tests','--app','hospitality_suite','--junit-xml-output',str(raw_xml)]
environment=dict(os.environ)
environment['PATH']=str(BENCH/'.runtime/wkhtmltox/usr/local/bin')+os.pathsep+environment.get('PATH','')
print('Native regression running on protected acceptance; raw logs retained under .local/'+args.phase,flush=True)
with log.open('w') as stream:
    result=subprocess.run(command,cwd=BENCH,env=environment,stdout=stream,stderr=subprocess.STDOUT)
if result.returncode:
    print('Native command failed; review preserved log: '+str(log))
    raise SystemExit(result.returncode)
raw=raw_xml.read_bytes()
documents=[chunk for chunk in re.split(br'<\?xml[^>]*\?>',raw) if chunk.strip()]
assert len(documents)==2,'Expected both integration and unit report documents from Frappe 16.52'
combined=ET.Element('testsuites')
document_counts=[]
for document in documents:
    source=ET.fromstring(document);assert source.tag=='testsuites'
    document_counts.append(len(source.findall('.//testcase')))
    combined.extend(source)
cases=combined.findall('.//testcase')
assert len({(row.get('classname'),row.get('name')) for row in cases})==len(cases)
counts={key:len(combined.findall('.//'+tag)) for key,tag in [('failures','failure'),('errors','error'),('skipped','skipped')]}
assert not any(counts.values()),counts
text=log.read_text(encoding='utf-8')
reported=[int(value) for value in re.findall(r'Ran (\d+) tests? in ',text)]
assert reported==document_counts and text.count('\nOK\n')==2 and 'FAILED' not in text
combined.attrib.update(tests=str(len(cases)),**{key:str(value) for key,value in counts.items()})
ET.indent(combined,space='  ')
ET.ElementTree(combined).write(ROOT/f'docs/evidence/{args.phase}-native-tests.xml',encoding='utf-8',xml_declaration=True)
(ROOT/f'docs/evidence/{args.phase}-native-tests.log').write_text('\n'.join(line.rstrip() for line in text.splitlines())+'\n',encoding='utf-8',newline='\n')
receipt=dict(site=SITE,command=command,exit_code=0,tests=len(cases),integration=document_counts[0],unit=document_counts[1],
             raw_log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),raw_concatenated_xml_sha256=hashlib.sha256(raw).hexdigest(),
             source_xml_documents=2,all_cases_preserved=True,failures=0,errors=0,skipped=0,external_providers_activated=False)
(ROOT/f'docs/evidence/{args.phase}-native-run.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(receipt))
