"""Room and facility-only Day Pass flows share pricing without sharing room stock."""
from datetime import timedelta
import uuid

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_suite import api
from hospitality_suite.service import operation
from hospitality_suite.time import now_local


class TestDayPass(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    @staticmethod
    def span(prop):
        start=(now_local(prop)+timedelta(days=90)).replace(hour=9,minute=0,second=0,microsecond=0)
        return start,start+timedelta(hours=8)

    def test_room_day_pass_uses_its_own_rate_and_shared_room_capacity(self):
        prop=frappe.get_doc("HS Property",{"property_name":"Luna Demo · Por tiempo"})
        self.assertEqual(prop.mode,"Por tiempo")
        base=frappe.get_doc("HS Rate",{"property":prop.name,"mode":"Por tiempo","active":1})
        self.assertEqual(base.mode,"Por tiempo")
        rate=frappe.copy_doc(base)
        rate.title="Day Pass de prueba"
        rate.day_pass=1
        rate.block_hours=8
        rate.amount=800
        rate.priority=base.priority+1
        with operation():
            rate.insert()
        guest=frappe.get_doc("HS Guest",{"property":prop.name})
        room=frappe.get_doc("HS Room",{"property":prop.name,"category":base.category,"active":1})
        start,end=self.span(prop)
        values=dict(starts_at=start.isoformat(),ends_at=end.isoformat(),customer=guest.customer,guest=guest.name,
                    mode="Day Pass",rooms=[dict(category=base.category,room=room.name,people=1)])
        accepted=api.preview(prop.name,values)
        previous_client=api.preview(prop.name,{**values,"mode":"Motel"})
        self.assertEqual(previous_client["lines"][0]["rules"]["mode"],"Por tiempo")
        self.assertEqual(accepted["lines"][0]["stay_type"],"Day Pass")
        self.assertEqual(accepted["lines"][0]["rules"]["name"],rate.name)
        self.assertEqual(accepted["lines"][0]["amount"],"800.00")
        booking=api.execute(prop.name,"reserve",uuid.uuid4().hex,{**values,"acceptance":accepted["acceptance"]})
        self.assertTrue(booking["booking"])
        with self.assertRaises(frappe.ValidationError):
            api.preview(prop.name,{**values,"mode":"Por tiempo"})
        with self.assertRaises(frappe.ValidationError):
            api.preview(prop.name,{**values,"starts_at":start.isoformat(),"ends_at":(end+timedelta(hours=8)).isoformat()})

    def test_no_room_pass_issues_and_refunds_without_a_room_allocation(self):
        prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        guest=frappe.get_doc("HS Guest",{"property":prop.name})
        template=frappe.get_doc("Item",prop.lodging_item)
        item=frappe.copy_doc(template)
        item.item_code="HS-TEST-PASS-"+uuid.uuid4().hex[:10]
        item.item_name="Acceso Day Pass de prueba"
        item.is_stock_item=0
        item.is_sales_item=1
        item.disabled=0
        item.insert(ignore_permissions=True)
        price_list=prop.price_list or frappe.db.get_single_value("Selling Settings","selling_price_list")
        frappe.get_doc(dict(doctype="Item Price",item_code=item.name,price_list=price_list,
                            price_list_rate=250,currency=prop.currency,selling=1)).insert(ignore_permissions=True)
        with operation():
            prop.day_pass_item=item.name
            prop.save()
        shift=api.execute(prop.name,"open_shift",uuid.uuid4().hex,dict(opening_amount=0))["shift"]
        method=frappe.db.get_value("HS Payment Method",{"property":prop.name})
        start,end=self.span(prop)
        values=dict(customer=guest.customer,guest=guest.name,people=2,starts_at=start.isoformat(),ends_at=end.isoformat(),
                    shift=shift,method=method)
        quote=api.preview(prop.name,values,"day_pass_no_room")
        self.assertEqual(quote["quantity"],"2")
        with self.assertRaises(frappe.ValidationError):
            api.preview(prop.name,{**values,"ends_at":(end+timedelta(days=1)).isoformat()},"day_pass_no_room")
        with self.assertRaises(frappe.ValidationError):
            api.execute(prop.name,"day_pass_no_room",uuid.uuid4().hex,{**values,"acceptance":"obsolete"})
        before=frappe.db.count("HS Allocation",{"property":prop.name})
        key=uuid.uuid4().hex
        sale=api.execute(prop.name,"day_pass_no_room",key,{**values,"acceptance":quote["acceptance"]})
        self.assertEqual(sale,api.execute(prop.name,"day_pass_no_room",key,{**values,"acceptance":quote["acceptance"]}))
        record=frappe.get_doc("HS Day Pass",sale["day_pass"])
        self.assertEqual((record.people,record.status,record.service,record.sales_invoice),
                         (2,"Issued",sale["service"],sale["invoice"]))
        self.assertEqual(frappe.db.count("HS Allocation",{"property":prop.name}),before)
        self.assertEqual(frappe.db.get_value("HS Service Request",sale["service"],"stay"),None)
        self.assertEqual(frappe.db.get_value("Sales Invoice",sale["invoice"],"docstatus"),1)
        api.execute(prop.name,"return_direct_sale",uuid.uuid4().hex,
                    dict(service=sale["service"],shift=shift,reason="Devolución Day Pass de prueba"))
        self.assertEqual(frappe.db.get_value("HS Day Pass",record.name,"status"),"Cancelled")
