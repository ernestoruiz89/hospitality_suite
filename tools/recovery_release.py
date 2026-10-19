"""Exercise a code-only rollback on the named restored test site.

An isolated archived checkout is selected through PYTHONPATH for this process.
The source checkout, bench app links, web server and source DB are never changed.
This does not claim that arbitrary schema migrations can be rolled back by code.
"""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile

parser=argparse.ArgumentParser()
parser.add_argument('stage',choices=['previous','current'])
args=parser.parse_args()
bench=Path('/home/frappe/benches/hospitality-bench')
repo=Path('/mnt/c/Users/Ernesto/Documents/ChatGPT/Hotel')
target=bench/'sites/hospitality-restore.localhost'
config=json.loads((target/'site_config.json').read_text())
assert target.resolve()==Path('/home/frappe/benches/hospitality-bench/sites/hospitality-restore.localhost')
assert config.get('allow_tests') and config['db_name']=='hospitality_restore' and config.get('pause_scheduler')
revision=subprocess.check_output(['git','-C',str(repo),'rev-parse','8152ac5' if args.stage=='previous' else 'HEAD'],text=True).strip()
code=repo
if args.stage=='previous':
    code=bench/'.hospitality-reversal'/('code-'+revision[:12])
    if not code.exists():
        code.mkdir(parents=True,mode=0o700)
        archive=subprocess.check_output(['git','-C',str(repo),'archive','--format=tar',revision])
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(code,filter='data')
        (code/'.revision').write_text(revision)
    assert code.resolve().is_relative_to((bench/'.hospitality-reversal').resolve())
    assert (code/'.revision').read_text()==revision
environment={**os.environ,'PYTHONPATH':str(code)}
python=str(bench/'env/bin/python')
# The editable install has an import redirector that precedes PathFinder, so
# PYTHONPATH alone does not select the archived package. Load that package's
# normal __init__ explicitly, then let Frappe import its submodules normally.
bootstrap='''
import importlib.util, pathlib, runpy, sys
root=pathlib.Path(sys.argv.pop(1))/'hospitality_suite'
spec=importlib.util.spec_from_file_location('hospitality_suite',root/'__init__.py',submodule_search_locations=[str(root)])
module=importlib.util.module_from_spec(spec)
sys.modules['hospitality_suite']=module
spec.loader.exec_module(module)
if sys.argv[1:]==['--probe']:
    print(module.__file__)
else:
    sys.argv[0]='bench_helper'
    runpy.run_module('frappe.utils.bench_helper',run_name='__main__')
'''
probe=subprocess.check_output([python,'-c',bootstrap,str(code),'--probe'],env=environment,text=True).strip()
assert Path(probe).resolve()==(code/'hospitality_suite/__init__.py').resolve()
log=bench/('.hospitality-reversal-'+args.stage+'.log')
with log.open('w') as stream:
    log.chmod(0o600)
    result=subprocess.run([python,'-c',bootstrap,str(code),'frappe','--site','hospitality-restore.localhost','migrate'],cwd=bench/'sites',env=environment,stdout=stream,stderr=subprocess.STDOUT)
assert result.returncode==0,'Migration failed; inspect private log '+str(log)
proof=dict(stage=args.stage,site='hospitality-restore.localhost',code_revision=revision,
           isolated_archive=args.stage=='previous',migration_passed=True,source_checkout_unchanged=True)
(repo/'docs/evidence'/('recovery-code-'+args.stage+'.json')).write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof))
