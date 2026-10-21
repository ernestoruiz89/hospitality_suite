"""Source inventory for the security review; not a penetration-test substitute."""
import ast
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--output',default='docs/evidence/permissions-audit-source.json');args=parser.parse_args()
sources={};endpoints=[];delegations=[]
for path in sorted((ROOT/'hospitality_suite').rglob('*.py')):
    if 'tests' in path.relative_to(ROOT/'hospitality_suite').parts:continue
    raw=path.read_bytes();relative=path.relative_to(ROOT).as_posix();tree=ast.parse(raw,filename=relative)
    sources[relative]=hashlib.sha256(raw).hexdigest()
    for node in ast.walk(tree):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            whitelisted=None;rate=None
            for decorator in node.decorator_list:
                if not isinstance(decorator,ast.Call):continue
                name=ast.unparse(decorator.func)
                if name=='frappe.whitelist':whitelisted={kw.arg:ast.literal_eval(kw.value) for kw in decorator.keywords}
                if name=='rate_limit':rate={kw.arg:ast.literal_eval(kw.value) for kw in decorator.keywords}
            if whitelisted is not None:
                endpoints.append(dict(path=relative,function=node.name,line=node.lineno,allow_guest=whitelisted.get('allow_guest',False),methods=whitelisted.get('methods'),rate_limit=rate))
        if isinstance(node,ast.Call):
            for kw in node.keywords:
                if kw.arg=='ignore_permissions':delegations.append(dict(path=relative,line=node.lineno,expression=ast.unparse(kw.value)))
        if isinstance(node,ast.Assign) and any(isinstance(target,ast.Attribute) and target.attr=='ignore_permissions' for target in node.targets):
            delegations.append(dict(path=relative,line=node.lineno,expression=ast.unparse(node.value)))
public=[row for row in endpoints if row['allow_guest']]
assert {(row['path'],row['function']) for row in public}=={
    ('hospitality_suite/portal.py','catalog'),('hospitality_suite/portal.py','quote'),
    ('hospitality_suite/portal.py','request'),('hospitality_suite/integrations.py','webhook')}
assert all(row['rate_limit'] and row['rate_limit']['seconds']==60 for row in public)
assert all(row['methods']==['POST'] for row in public if row['function'] in ('request','webhook'))
proof=dict(source_review_only=True,not_proof_of_all_runtime_paths=True,sources=sources,endpoints=endpoints,
    explicit_permission_delegations=delegations,public_endpoint_count=len(public),external_provider_activation=False)
(ROOT/args.output).write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(production_python_files=len(sources),whitelisted_endpoints=len(endpoints),public_endpoints=len(public),explicit_delegations=len(delegations))))
