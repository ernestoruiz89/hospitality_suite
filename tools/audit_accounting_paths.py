"""Record source paths reviewed for S09-17; this is not a runtime proof."""
import ast
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LEDGERS=('GL Entry','Payment Ledger Entry','Stock Ledger Entry')
reviewed={
    'hooks.py':'Permisos de lectura y condiciones de consulta.',
    'install.py':'Concede lectura de GL Entry; no crea movimientos.',
    'native_pos.py':'Lee GL Entry vigente para el efectivo POS neto.',
    'pos_returns.py':'Lee GL Entry para identificar medios del documento original.',
    'reports.py':'Lee Stock Ledger Entry para reportes de inventario.',
    'security.py':'Condiciones de lectura y permisos por documento de origen.',
    'treasury.py':'Lee GL Entry para recuperar la valoración histórica de compensación.',
    'translation_messages.py':'Textos del diccionario de traducción.',
}
files=[];ledger_paths=[];constructors=[];sql=[];direct=[]
for path in sorted((ROOT/'hospitality_suite').rglob('*.py')):
    if 'tests' in path.parts:
        continue
    source=path.read_text(encoding='utf-8')
    tree=ast.parse(source)
    relative=path.relative_to(ROOT).as_posix()
    files.append(dict(path=relative,sha256=hashlib.sha256(source.encode()).hexdigest()))
    for node in ast.walk(tree):
        if isinstance(node,ast.Constant) and isinstance(node.value,str) and any(name in node.value for name in LEDGERS):
            assert path.name in reviewed,(relative,node.lineno)
            ledger_paths.append(dict(path=relative,line=node.lineno,review=reviewed[path.name]))
        if not isinstance(node,ast.Call):
            continue
        function=ast.unparse(node.func)
        if function in ('frappe.new_doc','frappe.get_doc'):
            constructors.append(dict(path=relative,line=node.lineno,call=ast.get_source_segment(source,node)))
        if function=='frappe.db.sql':
            query=ast.unparse(node.args[0])
            sql.append(dict(path=relative,line=node.lineno,query=query))
            assert query.lstrip("f'\"").upper().startswith(('SELECT','SHOW')),query
        if function in ('frappe.db.set_value','frappe.db.delete','frappe.db.insert') or function.endswith(('.db_insert','.db_update')):
            direct.append(dict(path=relative,line=node.lineno,call=ast.get_source_segment(source,node)))
            assert not any(name in ast.unparse(node) for name in LEDGERS)
proof=dict(scope='Product Python including patches; excludes tests and development tools',
    limitation='Static inventory plus manual review, not a proof of every possible runtime path.',
    manual_review=dict(
        native_posting='accounting.post_standard inserts/submits standard documents; callers construct fixed voucher types.',
        dynamic_documents='service.insert callers use HS operational types; setup sections/actions are fixed mappings; portal confirmation is read-only and checks its two allowed types.',
        reconciliation='Payment Reconciliation and native cancellation controllers own ledger allocations/reversals.',
        other_writes='Guest CRM, configuration, privacy files and HS patches do not write ledgers.'),
    files=files,ledger_references=ledger_paths,native_document_constructors=constructors,sql=sql,direct_database_calls=direct)
(ROOT/'docs/evidence/finance-audit-source-review.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(dict(product_files=len(files),ledger_references=len(ledger_paths),constructors=len(constructors),sql_calls=len(sql),direct_database_calls=len(direct))))
