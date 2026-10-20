"""Attest the native midnight Company cache refresh without changing any rows."""
import datetime
import decimal
import gzip
import hashlib
import json
import os
from pathlib import Path
import re

import frappe

BENCH=Path('/home/frappe/benches/hospitality-bench')
ROOT=Path(__file__).resolve().parents[1]


def tokens(text):
    result=[];part='';quoted=False;escaped=False
    for char in text:
        if escaped:part+=char;escaped=False;continue
        if quoted and char=='\\':part+=char;escaped=True;continue
        if char=="'":quoted=not quoted;part+=char;continue
        if char==',' and not quoted:result.append(part);part=''
        else:part+=char
    result.append(part)
    return result


def value(token,example):
    if token=='NULL':return None
    if token.startswith("'"):
        raw=token[1:-1];out='';index=0
        escapes={'0':'\0','n':'\n','r':'\r','t':'\t','Z':'\x1a'}
        while index<len(raw):
            if raw[index]=='\\':index+=1;out+=escapes.get(raw[index],raw[index])
            else:out+=raw[index]
            index+=1
        if isinstance(example,datetime.datetime):return datetime.datetime.fromisoformat(out)
        if isinstance(example,datetime.date):return datetime.date.fromisoformat(out)
        return out
    if isinstance(example,decimal.Decimal):return decimal.Decimal(token)
    if isinstance(example,float):return float(token)
    return int(token) if re.fullmatch(r'-?\d+',token) else float(token)


def digest(rows):
    return hashlib.sha256(json.dumps(rows,default=str,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


os.chdir(BENCH/'sites')
frappe.init(site='hospitality.localhost',sites_path=str(BENCH/'sites'));frappe.connect()
try:
    assert frappe.conf.db_name=='hospitality_dev'
    frappe.set_user('Administrator')
    original=json.loads((BENCH/'.hospitality-financial-upgrade.json').read_text())['tables']['Company']
    phase=json.loads((BENCH/'.hospitality-accounting-upgrade.json').read_text())['tables']['Company']
    current=frappe.db.sql('SELECT * FROM `tabCompany` ORDER BY name',as_dict=True)
    assert len(current)==original['rows']==phase['rows']==1
    assert digest(current)==phase['sha256'],'Company changed during this phase'
    matched=None
    for path in sorted((BENCH/'sites/hospitality.localhost/private/backups').glob('*database.sql.gz')):
        with gzip.open(path,'rt',encoding='utf-8') as stream:source=stream.read()
        schema=re.search(r'CREATE TABLE `tabCompany` \((.*?)\) ENGINE=',source,re.S)
        insert=re.search(r'^INSERT INTO `tabCompany`(?: \([^\n]*?\))? VALUES\s*\((.*?)\)\s*;\s*$',source,re.M|re.S)
        if not schema or not insert:continue
        columns=re.findall(r'^\s*`([^`]+)`',schema[1],re.M)
        data=tokens(insert[1])
        if len(columns)!=len(data):continue
        row={field:value(raw,current[0].get(field)) for field,raw in zip(columns,data)}
        if digest([row])==original['sha256']:
            matched=row;break
    assert matched is not None,'No backup row proves the original Company snapshot'
    changed=sorted(field for field in set(matched)|set(current[0]) if matched.get(field)!=current[0].get(field))
    assert changed==['modified','sales_monthly_history','transactions_annual_history'],changed
    method='erpnext.setup.doctype.company.company.cache_companies_monthly_sales_history'
    job=frappe.db.get_value('Scheduled Job Type',{'method':method},'name')
    logs=frappe.get_all('Scheduled Job Log',filters={'scheduled_job_type':job,'status':'Complete'},fields=['creation','modified'],order_by='creation desc',limit_page_length=10)
    run=next((row for row in logs if row.creation<=current[0].modified<=row.modified),None)
    assert run,'No completed native job brackets the Company modification'
    from frappe.utils.goal import get_monthly_results
    from erpnext.setup.doctype.company.company import get_all_transactions_annual_history
    sales=get_monthly_results('Sales Invoice','base_grand_total','posting_date',{'company':current[0].name,'status':['!=','Draft'],'docstatus':1},'sum')
    annual=get_all_transactions_annual_history(current[0].name)
    assert json.loads(current[0].sales_monthly_history)==json.loads(json.dumps(sales))
    assert json.loads(current[0].transactions_annual_history)==json.loads(json.dumps(annual))
    proof=dict(site=frappe.local.site,mutations=False,source_company_sha256=original['sha256'],current_company_sha256=digest(current),
        source_backup_row_matches_original=True,changed_fields=changed,all_other_company_fields_preserved=True,
        company_matches_pre_phase_backup=True,native_method=method,native_schedule='daily_maintenance',job_status='Complete',
        job_started=str(run.creation),job_finished=str(run.modified),company_modified=str(current[0].modified),cached_histories_match_native_read_functions=True)
    private=BENCH/'.hospitality-accounting-company-cache.json'
    private.write_text(json.dumps(proof,indent=2)+'\n');private.chmod(0o600)
    (ROOT/'docs/evidence/accounting-company-cache.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(proof))
finally:frappe.db.rollback();frappe.destroy()
