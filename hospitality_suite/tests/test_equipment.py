from datetime import timedelta
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime,nowdate

from hospitality_suite import api


class TestEquipment(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        self.other=frappe.get_doc("HS Property",{"property_name":"Motel Luna Demo"})
        self.room=frappe.get_doc("HS Room",{"property":self.prop.name})
        self.start=now_datetime()+timedelta(days=60)
        self.end=self.start+timedelta(hours=2)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def call(self,action,data,prop=None,key=None):
        return api.execute((prop or self.prop).name,action,key or uuid.uuid4().hex,data)

    def equipment(self,**extra):
        result=api.save_setup(self.prop.name,"equipment",dict(equipment_code="EQ-"+uuid.uuid4().hex[:8],label="Equipo sintético",active=1,**extra),uuid.uuid4().hex)
        return frappe.get_doc("HS Equipment",result["name"])

    def values(self,equipment,**extra):
        return dict(equipment=equipment.name,title="Revisión preventiva sintética",kind="Preventive",starts_at=str(self.start),ends_at=str(self.end),**extra)

    def test_equipment_without_room_overlap_limits_and_authorized_completion(self):
        equipment=self.equipment(instructions="Sala técnica")
        values=self.values(equipment,assigned_to="maintenance@hospitality.example.invalid")
        frappe.set_user("maintenance@hospitality.example.invalid")
        key=uuid.uuid4().hex
        result=self.call("maintenance",values,key=key)
        self.assertEqual(result,self.call("maintenance",values,key=key))
        order=frappe.get_doc("HS Maintenance Order",result["order"])
        self.assertFalse(order.room)
        self.assertEqual(order.blocks_room,0)
        self.assertFalse(frappe.db.exists("HS Allocation",{"maintenance":order.name}))
        with self.assertRaises(frappe.ValidationError):
            self.call("maintenance",values)
        self.call("maintenance",dict(values,starts_at=str(self.end),ends_at=str(self.end+timedelta(hours=1))))
        with self.assertRaises(frappe.PermissionError):
            self.call("maintenance",dict(order=order.name,modified=str(order.modified),status="Completed"))
        frappe.set_user("supervisor@hospitality.example.invalid")
        self.call("maintenance",dict(order=order.name,modified=str(order.modified),status="Completed",notes="Trabajo verificado"))
        self.assertEqual(frappe.db.get_value("HS Maintenance Order",order.name,"status"),"Completed")

    def test_equipment_room_conflict_does_not_cancel_booking_and_nonblocking_is_explicit(self):
        equipment=self.equipment(room=self.room.name)
        guest=frappe.get_doc("HS Guest",{"property":self.prop.name})
        booking=dict(starts_at=str(self.start),ends_at=str(self.start+timedelta(days=1)),customer=guest.customer,guest=guest.name,
                     rooms=[dict(room=self.room.name,category=self.room.category,people=1)])
        booking["acceptance"]=api.preview(self.prop.name,booking)["acceptance"]
        result=self.call("reserve",booking)
        with self.assertRaises(frappe.ValidationError):
            self.call("maintenance",self.values(equipment))
        self.assertEqual(frappe.db.get_value("HS Booking",result["booking"],"status"),"Confirmed")
        order=self.call("maintenance",self.values(equipment,blocks_room=False))["order"]
        self.assertFalse(frappe.db.exists("HS Allocation",{"maintenance":order}))
        equipment.active=0
        with self.assertRaises(frappe.ValidationError):
            equipment.save()
        with self.assertRaises(frappe.ValidationError):
            self.call("maintenance",self.values(equipment),prop=self.other)

    def test_native_asset_link_scope_duplicates_and_private_financial_projection(self):
        fixed=frappe.db.get_value("Account",{"company":self.prop.company,"account_type":"Fixed Asset","is_group":0},"name")
        if not fixed:
            parent=frappe.db.get_value("Account",{"company":self.prop.company,"root_type":"Asset","is_group":1},"name")
            fixed=frappe.get_doc(dict(doctype="Account",company=self.prop.company,parent_account=parent,account_name="Activo fijo sintético "+uuid.uuid4().hex[:6],account_currency=self.prop.currency,account_type="Fixed Asset")).insert().name
        category=frappe.get_doc(dict(doctype="Asset Category",asset_category_name="Categoría de equipo "+uuid.uuid4().hex[:6],enable_cwip_accounting=0,non_depreciable_category=1,
                                    accounts=[dict(company_name=self.prop.company,fixed_asset_account=fixed)])).insert()
        item=frappe.get_doc(dict(doctype="Item",item_code="EQ-ITEM-"+uuid.uuid4().hex[:6],item_name="Equipo fijo sintético",item_group=frappe.db.get_value("Item","HS-DEMO-WATER","item_group"),stock_uom="Nos",is_stock_item=0,is_fixed_asset=1,asset_category=category.name)).insert()
        location=frappe.get_doc(dict(doctype="Location",location_name="Sala técnica "+uuid.uuid4().hex[:6])).insert()
        asset=frappe.get_doc(dict(doctype="Asset",asset_name="Equipo fijo sintético",asset_category=category.name,item_code=item.name,company=self.prop.company,
                                  hs_property=self.prop.name,asset_type="Existing Asset",purchase_date=nowdate(),available_for_use_date=nowdate(),
                                  net_purchase_amount=1000,purchase_amount=1000,asset_quantity=1,location=location.name,cost_center=self.prop.cost_center,calculate_depreciation=0)).insert()
        equipment=self.equipment(asset=asset.name)
        with self.assertRaises(frappe.ValidationError):
            self.equipment(asset=asset.name)
        with self.assertRaises(frappe.ValidationError):
            api.save_setup(self.other.name,"equipment",dict(equipment_code="CROSS",label="No permitido",asset=asset.name),uuid.uuid4().hex)
        asset.hs_property=self.other.name
        with self.assertRaises(frappe.ValidationError):
            asset.save()
        frappe.set_user("maintenance@hospitality.example.invalid")
        from hospitality_suite.equipment import asset_permission,asset_query
        self.assertFalse(asset_permission(asset))
        self.assertEqual(asset_query(),"1=0")
        projection=api.bootstrap(self.prop.name)
        self.assertNotIn("assets",projection)
        row=next(r for r in projection["equipment"] if r.name==equipment.name)
        self.assertNotIn("asset",row)
        self.assertNotIn("net_purchase_amount",row)
