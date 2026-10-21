"""Read-only inspection of documented commands in the installed native CLI."""
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime,timezone

bench=Path('/home/frappe/benches/hospitality-bench')
root=Path(__file__).resolve().parents[1]
logs=root/'.local/delivery-review';logs.mkdir(parents=True,exist_ok=True)
cli='/home/frappe/.local/bin/bench';site='hospitality.localhost'
help_commands=[
    ('get-app',['get-app','--help'],['--branch']),
    ('install-app',['--site',site,'install-app','--help'],['--help']),
    ('migrate',['--site',site,'migrate','--help'],['--help']),
    ('build',['build','--help'],['--app']),
    ('backup',['--site',site,'backup','--help'],['--with-files']),
    ('restore',['--site',site,'restore','--help'],['--with-public-files','--with-private-files']),
    ('run-tests',['--site','hospitality-acceptance.localhost','run-tests','--help'],['--app','--junit-xml-output']),
    ('set-maintenance-mode',['--site',site,'set-maintenance-mode','--help'],['--help']),
    ('disable-scheduler',['--site',site,'disable-scheduler','--help'],['--help']),
    ('enable-scheduler',['--site',site,'enable-scheduler','--help'],['--help']),
]
proof=dict(review_date='2026-10-21',requirements=['S18-06','S18-09'],
    checked_at_utc=datetime.now(timezone.utc).isoformat(),verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    scope='Native --help and read-only diagnostics; no install, migrate, backup, restore, maintenance or scheduler setting executed.',
    database_or_operational_mutations=False,commands=[])
for label,args,expected in help_commands:
    result=subprocess.run([cli,*args],cwd=bench,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (logs/f'{label}-help.txt').write_bytes(result.stdout);result.check_returncode()
    text=result.stdout.decode();assert all(option in text for option in expected),(label,expected,text)
    proof['commands'].append(dict(command=['bench',*args],exit_code=result.returncode,
        expected_options_present=expected,output_sha256=hashlib.sha256(result.stdout).hexdigest(),
        usage=next(line for line in text.splitlines() if line.startswith('Usage:'))))
for name in ('list-apps','doctor','show-pending-jobs'):
    args=['--site',site,name]
    result=subprocess.run([cli,*args],cwd=bench,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (logs/f'{name}.txt').write_bytes(result.stdout)
    result.check_returncode()
    entry=dict(command=['bench',*args],exit_code=result.returncode,output_sha256=hashlib.sha256(result.stdout).hexdigest(),output_bytes=len(result.stdout))
    if name in ('doctor','list-apps'):entry['output']=result.stdout.decode().strip()
    proof['commands'].append(entry)
(root/'docs/evidence/delivery-review-cli.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(commands=len(proof['commands']),all_exit_zero=True,diagnostics=[row for row in proof['commands'] if 'output' in row]),ensure_ascii=False))
