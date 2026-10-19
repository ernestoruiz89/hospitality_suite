"""Catalogue search stays complete and operationally scoped beyond 500 Items."""
from datetime import timedelta
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.catalog import FIELDS


class TestCatalog(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_search_beyond_500_then_charge_and_keep_referenced_name(self):
        prefix="catalog-"+uuid.uuid4().hex[:8]
        template=frappe.get_doc("Item","HS-DEMO-WATER")
        fields=["name","item_code","item_name","item_group","stock_uom","is_stock_item","is_sales_item","is_purchase_item","disabled","is_fixed_asset","owner","creation","modified"]
        stamp=now_datetime()
        # Read fixture only: the selected item and its price use real controllers.
        frappe.db.bulk_insert("Item",fields=fields,values=[(prefix+f"-{i:04}",prefix+f"-{i:04}",f"Catálogo {prefix} {i:04}",template.item_group,template.stock_uom,0,1,1,0,0,"Administrator",stamp,stamp) for i in range(605)])
        target=frappe.get_doc(dict(doctype="Item",item_code=prefix+"-0605",item_name="Servicio % y _ de catálogo 0605",item_group=template.item_group,
                                    stock_uom=template.stock_uom,is_stock_item=0,is_sales_item=1,is_purchase_item=1)).insert()
        price_list=self.prop.price_list or frappe.db.get_single_value("Selling Settings","selling_price_list")
        frappe.get_doc(dict(doctype="Item Price",item_code=target.name,price_list=price_list,price_list_rate=41.25,currency=self.prop.currency,selling=1)).insert()
        frappe.set_user("receptionist@hospitality.example.invalid")
        first=api.catalog_search(self.prop.name,prefix,"sale")
        self.assertEqual(len(first["items"]),50)
        self.assertTrue(first["has_more"])
        self.assertNotIn(target.name,{r.name for r in first["items"]})
        found=api.catalog_search(self.prop.name,target.name,"sale")
        self.assertEqual([r.name for r in found["items"]],[target.name])
        self.assertFalse(found["has_more"])
        self.assertEqual([r.name for r in api.catalog_search(self.prop.name,"% y _","sale")["items"]],[target.name])
        self.assertFalse(api.catalog_search(self.prop.name,target.name,"stock")["items"])
        self.assertEqual(set(found["items"][0]),set(FIELDS))
        before=api.bootstrap(self.prop.name)
        self.assertLessEqual(len(before["items"]),50)
        self.assertNotIn(target.name,{r.name for r in before["items"]})
        room=before["rooms"][0]
        guest=before["guests"][0]
        start=now_datetime().replace(microsecond=0)
        data=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),guest=guest.name,customer=guest.customer,
                  rooms=[dict(category=room.category,room=room.name,people=1)])
        data["acceptance"]=api.preview(self.prop.name,data)["acceptance"]
        entered=api.execute(self.prop.name,"walk_in",uuid.uuid4().hex,data)
        requested=api.execute(self.prop.name,"request_service",uuid.uuid4().hex,dict(stay=entered["stay"],folio=entered["folio"],item=target.name,quantity=1))
        service=frappe.get_doc("HS Service Request",requested["service"])
        self.assertEqual(service.amount,41.25)
        api.execute(self.prop.name,"update_service",uuid.uuid4().hex,dict(service=service.name,status="Delivered",modified=str(service.modified)))
        self.assertEqual(frappe.db.get_value("HS Charge",frappe.db.get_value("HS Service Request",service.name,"charge"),"item"),target.name)
        self.assertFalse(frappe.db.exists("Stock Ledger Entry",{"item_code":target.name}),"A non-stock service must not create an inventory ledger")
        frappe.set_user("Administrator")
        target.disabled=1
        target.save()
        frappe.set_user("receptionist@hospitality.example.invalid")
        self.assertFalse(api.catalog_search(self.prop.name,target.name,"sale")["items"])
        referenced=next(r for r in api.bootstrap(self.prop.name)["items"] if r.name==target.name)
        self.assertEqual(referenced.item_name,target.item_name)
        self.assertTrue(referenced.disabled)

    def test_minimal_role_projection_and_scope_cannot_be_bypassed(self):
        foreign=frappe.db.get_value("HS Property",{"property_name":"Motel Luna Demo"},"name")
        # Give the existing demo role only one property in this rolled-back fixture.
        frappe.db.delete("HS Access",{"user":"housekeeping@hospitality.example.invalid","property":foreign})
        frappe.set_user("housekeeping@hospitality.example.invalid")
        rows=api.catalog_search(self.prop.name,"HS-DEMO-WATER","stock")["items"]
        self.assertEqual([r.name for r in rows],["HS-DEMO-WATER"])
        self.assertEqual(set(rows[0]),set(FIELDS))
        with self.assertRaises(frappe.PermissionError):
            api.catalog_search(foreign,"HS-DEMO-WATER")
        for txt,purpose in (("x"*141,"any"),("",{}),(None,"any"),("","cost")):
            with self.assertRaises(frappe.ValidationError):
                api.catalog_search(self.prop.name,txt,purpose)
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            api.catalog_search(self.prop.name,"HS-DEMO-WATER")
