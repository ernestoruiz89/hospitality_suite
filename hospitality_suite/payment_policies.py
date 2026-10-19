"""Per-property receipt policies; existing liabilities remain refundable/applicable."""
import frappe

from hospitality_suite.security import require


FIELDS={"Advance":"advance_policy","Guarantee":"guarantee_policy"}


def policies(prop):
    return {kind:prop.get(field) or "Manual" for kind,field in FIELDS.items()}


def authorize(prop,kind):
    if not isinstance(kind,str) or kind not in ("Payment","Advance","Guarantee","Refund","Guarantee Refund"):
        frappe.throw(frappe._("Tipo de movimiento inválido"))
    if kind not in FIELDS:
        return {}
    rule=policies(prop)[kind]
    if rule not in ("Manual","Approval","Disabled"):
        frappe.throw(frappe._("Revise la política de anticipos y garantías"))
    if rule=="Disabled":
        frappe.throw(frappe._("Este establecimiento no admite nuevos anticipos") if kind=="Advance" else frappe._("Este establecimiento no admite nuevas garantías"))
    if rule=="Approval":
        require(prop.name,"approve")
    return dict(kind=kind,policy=rule,approved_by=frappe.session.user if rule=="Approval" else None)


def validate_native(doc,prop,original):
    if doc.doctype not in ("Sales Invoice","Payment Entry","Journal Entry") or doc.docstatus!=1 or (original and original.docstatus==1) or getattr(frappe.local,"hs_posting",False):
        return
    from hospitality_suite.service import lock_property
    from hospitality_suite.accounting import ready
    prop=lock_property(prop.name)
    ready(prop)
    from hospitality_suite.pricing import decimal,money
    decision={}
    if doc.doctype=="Payment Entry" and doc.party_type=="Customer" and doc.payment_type=="Receive":
        unallocated=money(doc.unallocated_amount,currency=doc.paid_from_account_currency or prop.currency)
        if doc.references and unallocated>0:
            frappe.throw(frappe._("Separe el cobro de facturas y el anticipo en movimientos distintos"))
        if not doc.references:
            decision=authorize(prop,"Advance")
    elif doc.doctype=="Journal Entry" and prop.guarantee_account:
        liability=sum(decimal(row.credit_in_account_currency)-decimal(row.debit_in_account_currency) for row in doc.accounts if row.account==prop.guarantee_account)
        if liability>0:
            decision=authorize(prop,"Guarantee")
    if decision:
        doc.flags.hs_payment_policy=decision
