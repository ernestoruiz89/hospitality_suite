"""Policies apply to quotes, posting and native ERP; old funds remain reversible."""
from datetime import timedelta
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime,nowdate

from hospitality_suite import api


class TestPaymentPolicies(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        self.room=frappe.get_doc("HS Room",{"property":self.prop.name})
        self.guest=frappe.get_doc("HS Guest",{"property":self.prop.name})
        self.method=frappe.get_doc("HS Payment Method",{"property":self.prop.name,"is_cash":1})
        start=now_datetime().replace(microsecond=0)
        values=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),customer=self.guest.customer,guest=self.guest.name,
                    rooms=[dict(category=self.room.category,room=self.room.name,people=1)])
        self.stay=self.call("walk_in",dict(values,acceptance=api.preview(self.prop.name,values)["acceptance"]))
        frappe.set_user("cashier@hospitality.example.invalid")
        self.shift=self.call("open_shift",dict(opening_amount=0))["shift"]

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def call(self,action,data):
        return api.execute(self.prop.name,action,uuid.uuid4().hex,data)

    def values(self,kind="Advance",amount=100,**extra):
        return dict(stay=self.stay["stay"],folio=self.stay["folio"],shift=self.shift,method=self.method.name,kind=kind,amount=amount,**extra)

    def policy(self,advance,guarantee):
        previous=frappe.session.user
        frappe.set_user("Administrator")
        self.prop.reload()
        api.save_setup(self.prop.name,"property",dict(advance_policy=advance,guarantee_policy=guarantee),uuid.uuid4().hex,str(self.prop.modified))
        self.prop.reload()
        frappe.set_user(previous)

    def native_advance(self,amount=100):
        return frappe.get_doc(dict(doctype="Payment Entry",company=self.prop.company,payment_type="Receive",posting_date=nowdate(),
                         party_type="Customer",party=self.guest.customer,paid_from=self.prop.receivable_account,paid_to=self.method.account,
                         paid_amount=amount,received_amount=amount,source_exchange_rate=1,target_exchange_rate=1,
                         mode_of_payment=self.method.mode_of_payment,reference_no="POLICY-TEST",reference_date=nowdate(),
                         hs_property=self.prop.name,hs_stay=self.stay["stay"],hs_folio=self.stay["folio"],hs_shift=self.shift))

    def test_disabled_new_receipts_do_not_trap_existing_advances_or_guarantees(self):
        advance=self.call("payment",self.values())
        guarantee=self.call("payment",self.values("Guarantee",150))
        self.policy("Disabled","Disabled")
        for kind in ("Advance","Guarantee"):
            with self.assertRaises(frappe.ValidationError):
                api.preview(self.prop.name,self.values(kind),"payment")
            with self.assertRaises(frappe.ValidationError):
                self.call("payment",self.values(kind))
        frappe.set_user("Administrator")
        self.call("payment",self.values("Refund",30,source_payment=advance["payment"],reason="Devolución ficticia"))
        self.call("payment",self.values("Guarantee Refund",50,source_payment=guarantee["payment"],reason="Liberación parcial ficticia"))
        self.call("apply_guarantee",dict(source_payment=guarantee["payment"],folio=self.stay["folio"],shift=self.shift,amount=100,reason="Aplicación ficticia autorizada"))
        invoice=self.call("invoice",dict(folio=self.stay["folio"]))["invoice"]
        self.assertEqual(frappe.db.get_value("Sales Invoice",invoice,"total_advance"),170)
        self.assertEqual(frappe.db.count("HS Payment",{"source_payment":guarantee["payment"],"status":"Posted"}),2)

    def test_approval_is_server_enforced_and_recorded_with_the_quote(self):
        old=api.preview(self.prop.name,self.values(),"payment")
        self.policy("Approval","Approval")
        frappe.set_user("supervisor@hospitality.example.invalid")
        self.prop.reload()
        with self.assertRaises(frappe.PermissionError):
            api.save_setup(self.prop.name,"property",dict(advance_policy="Manual"),uuid.uuid4().hex,str(self.prop.modified))
        direct=frappe.get_doc("HS Property",self.prop.name)
        direct.advance_policy="Manual"
        with self.assertRaises(frappe.PermissionError):
            direct.save()
        frappe.set_user("cashier@hospitality.example.invalid")
        for kind in ("Advance","Guarantee"):
            with self.assertRaises(frappe.PermissionError):
                api.preview(self.prop.name,self.values(kind),"payment")
            with self.assertRaises(frappe.PermissionError):
                self.call("payment",self.values(kind,fx_acceptance=old["acceptance"]))
        self.assertFalse(frappe.db.exists("HS Payment",{"stay":self.stay["stay"]}))
        frappe.set_user("manager@hospitality.example.invalid")
        quote=api.preview(self.prop.name,self.values(),"payment")
        self.assertNotEqual(quote["acceptance"],old["acceptance"])
        self.assertEqual(quote["payment_policy"],dict(kind="Advance",policy="Approval",approved_by=frappe.session.user))
        result=self.call("payment",self.values(fx_acceptance=quote["acceptance"]))
        event=frappe.get_doc("HS Audit Event",{"source_name":result["payment"],"action":"Advance"})
        self.assertEqual(frappe.parse_json(event.details)["payment_policy"],quote["payment_policy"])
        self.policy("Disabled","Disabled")
        self.assertEqual(frappe.parse_json(event.reload().details)["payment_policy"]["policy"],"Approval")

    def test_native_receipts_cannot_bypass_disabled_policies_or_financial_enablement(self):
        frappe.set_user("Administrator")
        self.policy("Disabled","Disabled")
        payment=self.native_advance().insert()
        before=frappe.db.count("GL Entry")
        with self.assertRaisesRegex(frappe.ValidationError,"no admite nuevos anticipos"):
            payment.submit()
        self.assertEqual(frappe.db.count("GL Entry"),before)
        self.assertEqual(payment.reload().docstatus,0)
        journal=frappe.get_doc(dict(doctype="Journal Entry",company=self.prop.company,posting_date=nowdate(),voucher_type="Journal Entry",
                    hs_property=self.prop.name,hs_stay=self.stay["stay"],hs_shift=self.shift,
                    accounts=[dict(account=self.method.account,debit_in_account_currency=100,cost_center=self.prop.cost_center),
                              dict(account=self.prop.guarantee_account,credit_in_account_currency=100,cost_center=self.prop.cost_center)])).insert()
        with self.assertRaisesRegex(frappe.ValidationError,"no admite nuevas garantías"):
            journal.submit()
        self.assertEqual(frappe.db.count("GL Entry"),before)
        self.prop.reload()
        api.save_setup(self.prop.name,"property",dict(financial_enabled=0),uuid.uuid4().hex,str(self.prop.modified))
        with self.assertRaisesRegex(frappe.ValidationError,"Habilite y valide"):
            payment.submit()
        self.assertEqual(frappe.db.count("GL Entry"),before)
        charge=frappe.get_doc("HS Charge",{"stay":self.stay["stay"],"kind":"Lodging"})
        invoice=frappe.get_doc(dict(doctype="Sales Invoice",company=self.prop.company,customer=self.guest.customer,currency=self.prop.currency,
                    debit_to=self.prop.receivable_account,cost_center=self.prop.cost_center,hs_property=self.prop.name,
                    hs_stay=self.stay["stay"],hs_folio=self.stay["folio"],update_stock=0,
                    items=[dict(item_code=charge.item,qty=charge.quantity,rate=charge.rate,price_list_rate=charge.rate,cost_center=self.prop.cost_center,hs_charge=charge.name)])).insert()
        with self.assertRaisesRegex(frappe.ValidationError,"Habilite y valide"):
            invoice.submit()
        self.assertEqual(frappe.db.count("GL Entry"),before)

    def test_native_approved_advance_and_migration_preserve_custom_policy(self):
        frappe.set_user("Administrator")
        self.policy("Approval","Disabled")
        payment=self.native_advance().insert().submit()
        record=frappe.get_doc("HS Payment",{"payment_entry":payment.name})
        self.assertEqual(record.kind,"Advance")
        events=frappe.get_all("HS Audit Event",filters={"property":self.prop.name},fields=["details"])
        detail=next(frappe.parse_json(e.details) for e in events if frappe.parse_json(e.details).get("name")==payment.name)
        self.assertEqual(detail["payment_policy"],dict(kind="Advance",policy="Approval",approved_by="Administrator"))
        self.prop.reload()
        modified=self.prop.modified
        frappe.db.set_value("HS Property",self.prop.name,"advance_policy",None,update_modified=False)
        from hospitality_suite.patches.v0_3.default_payment_policies import execute
        execute()
        self.prop.reload()
        self.assertEqual(self.prop.advance_policy,"Manual")
        self.assertEqual(self.prop.guarantee_policy,"Disabled")
        self.assertEqual(self.prop.modified,modified)

    def test_native_mixed_invoice_and_unallocated_advance_requires_separate_receipts(self):
        frappe.set_user("Administrator")
        invoice=self.call("invoice",dict(folio=self.stay["folio"]))["invoice"]
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
        payment=get_payment_entry("Sales Invoice",invoice,bank_account=self.method.account)
        payment.update(dict(hs_property=self.prop.name,hs_stay=self.stay["stay"],hs_folio=self.stay["folio"],hs_shift=self.shift,
                            mode_of_payment=self.method.mode_of_payment,paid_amount=1700,received_amount=1700,
                            reference_no="POLICY-MIXED",reference_date=nowdate()))
        payment.insert()
        self.assertEqual(payment.unallocated_amount,200)
        before=frappe.db.count("GL Entry")
        with self.assertRaisesRegex(frappe.ValidationError,"Separe el cobro"):
            payment.submit()
        self.assertEqual(frappe.db.count("GL Entry"),before)

    def test_credit_and_discount_require_approval_and_a_current_sufficient_limit(self):
        from hospitality_suite.service import operation
        from frappe.utils import getdate
        charge=frappe.get_doc("HS Charge",{"stay":self.stay["stay"],"kind":"Lodging"})
        values=dict(charge=charge.name,adjustment_type="Discount",amount=100,reason="Descuento sintético autorizado")
        frappe.set_user("supervisor@hospitality.example.invalid")
        with self.assertRaises(frappe.PermissionError):
            self.call("adjustment",values)
        frappe.set_user("Administrator")
        with self.assertRaisesRegex(frappe.ValidationError,"supera el cargo"):
            self.call("adjustment",dict(values,amount=1501))
        self.call("adjustment",values)
        invoice=self.call("invoice",dict(folio=self.stay["folio"]))["invoice"]
        self.assertEqual(frappe.db.get_value("Sales Invoice",invoice,"grand_total"),1400)
        def leave():
            stay=frappe.get_doc("HS Stay",self.stay["stay"])
            return self.call("check_out",dict(stay=stay.name,modified=str(stay.modified),credit_reason="Crédito sintético revisado"))
        with self.assertRaisesRegex(frappe.ValidationError,"Liquiden el saldo"):
            leave()
        self.prop.reload()
        api.save_setup(self.prop.name,"property",dict(allow_credit=1),uuid.uuid4().hex,str(self.prop.modified))
        with self.assertRaisesRegex(frappe.ValidationError,"autorización de crédito vigente"):
            leave()
        grant=api.save_setup(self.prop.name,"billing_party",dict(customer=self.guest.customer,kind="Company",credit_authorized=1,
                             credit_limit=1399,valid_until=str(getdate(nowdate())+timedelta(days=1)),reason="Límite sintético"),uuid.uuid4().hex)
        with self.assertRaisesRegex(frappe.ValidationError,"supera su límite"):
            leave()
        rule=frappe.get_doc("HS Billing Party",grant["name"])
        with operation():
            rule.credit_limit=1400
            rule.valid_until=getdate(nowdate())-timedelta(days=1)
            rule.save()
        with self.assertRaisesRegex(frappe.ValidationError,"autorización de crédito vigente"):
            leave()
        with operation():
            rule.valid_until=getdate(nowdate())+timedelta(days=1)
            rule.save()
        frappe.set_user("supervisor@hospitality.example.invalid")
        with self.assertRaises(frappe.PermissionError):
            leave()
        frappe.set_user("manager@hospitality.example.invalid")
        leave()
        stay=frappe.get_doc("HS Stay",self.stay["stay"])
        self.assertEqual(stay.status,"Checked Out")
        self.assertEqual(stay.reason,"Crédito sintético revisado")
        self.assertEqual(frappe.db.get_value("Sales Invoice",invoice,"outstanding_amount"),1400)
