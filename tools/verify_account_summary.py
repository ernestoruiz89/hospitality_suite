"""Read-only comparison of the installed compact print with native metadata."""
import os
import json
import hashlib
from pathlib import Path
import frappe
import hospitality_suite

root=Path(__file__).resolve().parents[1]
bench=Path('/home/frappe/benches/hospitality-bench')
os.chdir(bench/'sites')
metadata=json.loads((root/'hospitality_suite/hospitality_suite/print_format/hs_folio/hs_folio.json').read_text())
expected=metadata['html']
assert 'Cálculo histórico del precio' not in expected and 'hs-print-price' not in expected
proof=dict(app_version=hospitality_suite.__version__,native_format=metadata['name'],html_sha256=hashlib.sha256(expected.encode()).hexdigest(),sites={})
for site,database in [('hospitality.localhost','hospitality_dev'),('hospitality-acceptance.localhost','hospitality_acceptance')]:
    frappe.init(site=site,sites_path=str(bench/'sites'));frappe.connect()
    try:
        assert frappe.conf.db_name==database and frappe.conf.allow_tests
        assert frappe.db.get_value('Print Format',metadata['name'],'html')==expected
        proof['sites'][site]=dict(installed_html_matches_source=True,calculation_blocks_absent=True,mutations=False)
    finally:
        frappe.db.rollback();frappe.destroy()
(root/'docs/evidence/account-summary-installed.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(proof))
