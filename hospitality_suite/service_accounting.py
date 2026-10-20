"""Property/service account defaults without changing shared Item defaults."""
import frappe

from hospitality_suite.security import require
from hospitality_suite.service import assert_version,audit

FIELDS=('income_account','expense_account','cost_center')


def validate_configuration(prop):
    currency=frappe.db.get_value('Company',prop.company,'default_currency')
    seen=set()
    for row in [prop]+list(prop.get('service_accounts') or []):
        if row!=prop:
            if not row.item or row.item in seen or not any(row.get(field) for field in FIELDS):
                frappe.throw(frappe._('Seleccione servicios distintos e indique al menos una cuenta o centro de costo'))
            seen.add(row.item)
            if not frappe.db.exists('Item',{'name':row.item,'is_fixed_asset':0}):
                frappe.throw(frappe._('Seleccione un artículo o servicio operativo'))
        for field in FIELDS:
            name=row.get(field)
            if not name:continue
            doc=frappe.get_doc('Cost Center' if field=='cost_center' else 'Account',name)
            if doc.company!=prop.company or doc.is_group or doc.get('disabled'):
                frappe.throw(frappe._('Seleccione cuentas y centros de costo habilitados, sin agrupar y de la misma compañía'))
            if field!='cost_center' and (doc.root_type!=('Income' if field=='income_account' else 'Expense') or doc.account_currency!=currency):
                frappe.throw(frappe._('Seleccione una cuenta de ingresos o gastos en la moneda base de la compañía, según su uso'))


def configuration(property_name):
    prop=require(property_name,'setup')
    return dict(modified=str(prop.modified),company=prop.company,
        defaults={field:prop.get(field) for field in FIELDS},
        services=[dict(item=row.item,item_name=frappe.db.get_value('Item',row.item,'item_name'),**{field:row.get(field) for field in FIELDS}) for row in prop.get('service_accounts') or []])


def save(prop,data):
    assert_version(prop,data.get('modified'))
    if not isinstance(data.get('defaults'),dict) or set(data)-{'modified','defaults','services'} or set(data['defaults'])-set(FIELDS):
        frappe.throw(frappe._('Configuración contable no admitida'))
    rows=data.get('services')
    if not isinstance(rows,list) or len(rows)>500 or any(not isinstance(row,dict) or set(row)-{'item',*FIELDS} for row in rows):
        frappe.throw(frappe._('Revise la contabilidad de los servicios'))
    prop.update(data.get('defaults') or {})
    prop.set('service_accounts',[{field:row.get(field) for field in ('item',*FIELDS)} for row in rows])
    prop.save()
    audit(prop,'Service accounting configuration',prop,details=dict(defaults=data.get('defaults'),services=rows))
    return dict(property=prop.name,modified=str(prop.modified))


def apply_defaults(doc,prop,original=None):
    # Returns and posted documents retain their original accounting dimensions.
    if doc.get('is_return') or doc.docstatus==2 or (original and original.docstatus==1):return
    if doc.doctype not in ('Sales Invoice','Purchase Order','Purchase Receipt','Purchase Invoice','Stock Entry'):return
    validate_configuration(prop)
    services={row.item:row for row in prop.get('service_accounts') or []}
    for row in doc.get('items') or []:
        if not row.get('item_code'):continue
        service=services.get(row.item_code)
        value=lambda field: (service.get(field) if service else None) or prop.get(field)
        if value('cost_center'):row.cost_center=value('cost_center')
        if doc.doctype=='Sales Invoice' and value('income_account'):row.income_account=value('income_account')
        stock=frappe.db.get_value('Item',row.item_code,'is_stock_item')
        expense=(doc.doctype=='Sales Invoice' or (doc.doctype=='Purchase Invoice' and not stock)
                 or (doc.doctype=='Stock Entry' and doc.get('hs_stock_purpose')=='Sale' and doc.get('purpose')=='Material Issue'))
        if expense and value('expense_account'):row.expense_account=value('expense_account')
