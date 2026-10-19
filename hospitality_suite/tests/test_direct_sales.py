import uuid

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_suite import api


class TestDirectSales(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        self.guest=frappe.get_all("HS Guest",filters={"property":self.prop.name},fields=["*"])[0]
        self.shift=self.call("open_shift",dict(opening_amount=0))["shift"]
        self.method=frappe.db.get_value("HS Payment Method",{"property":self.prop.name})
        self.item="HS-DEMO-WATER"

    def call(self,action,data,key=None):
        return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data)

    def test_sale_retry_one_stock_issue_and_full_standard_refund(self):
        frappe.set_user("cashier@hospitality.example.invalid")
        self.shift=self.call("open_shift",dict(opening_amount=0))["shift"]
        values=dict(customer=self.guest.customer,item=self.item,quantity=2,method=self.method,shift=self.shift)
        quote=api.preview(self.prop.name,values,"direct_sale")
        values.update(acceptance=quote["acceptance"],tendered=100)
        key=uuid.uuid4().hex
        one=self.call("direct_sale",values,key)
        self.assertEqual(one,self.call("direct_sale",values,key))
        service=frappe.get_doc("HS Service Request",one["service"])
        invoice=frappe.get_doc("Sales Invoice",one["invoice"])
        self.assertEqual(invoice.update_stock,0)
        self.assertEqual(invoice.outstanding_amount,0)
        self.assertTrue(all(row.warehouse==self.prop.warehouse for row in invoice.items))
        self.assertEqual(frappe.db.get_value("Stock Entry",service.stock_entry,"docstatus"),1)
        frappe.set_user("Administrator")
        result=self.call("return_direct_sale",dict(service=service.name,shift=self.shift,reason="Devolución de venta de prueba"))
        self.assertEqual(frappe.db.get_value("Stock Entry",service.stock_entry,"docstatus"),2)
        self.assertEqual(frappe.db.get_value("Sales Invoice",result["credit_note"],"outstanding_amount"),0)
        from hospitality_suite.cashier import expected
        self.assertEqual(expected(frappe.get_doc("HS Shift",self.shift))["NIO"],"0.00")

    def test_stock_failure_rolls_back_invoice_and_payment(self):
        values=dict(customer=self.guest.customer,item=self.item,quantity=100000,method=self.method,shift=self.shift)
        quote=api.preview(self.prop.name,values,"direct_sale")
        values["acceptance"]=quote["acceptance"]
        before=frappe.db.count("Sales Invoice")
        with self.assertRaises(frappe.ValidationError):
            self.call("direct_sale",values)
        self.assertEqual(frappe.db.count("Sales Invoice"),before)
