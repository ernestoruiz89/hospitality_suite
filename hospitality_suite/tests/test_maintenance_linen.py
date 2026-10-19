from datetime import timedelta
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.service import operation


class TestMaintenanceLinen(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        self.room=frappe.db.get_value("HS Room",{"property":self.prop.name},"name")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def call(self,action,data,key=None):
        return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data)

    def order(self,**extra):
        start=now_datetime()+timedelta(days=30)
        result=self.call("maintenance",dict(room=self.room,title="Revisión preventiva ficticia",kind="Preventive",
                                            starts_at=str(start),ends_at=str(start+timedelta(hours=2)),**extra))
        return frappe.get_doc("HS Maintenance Order",result["order"])

    def stock(self,warehouse):
        return frappe.db.get_value("Bin",{"item_code":"HS-DEMO-WATER","warehouse":warehouse},"actual_qty") or 0

    def test_parts_cost_stock_retry_return_and_authorized_reopening(self):
        order=self.order(assigned_to="maintenance@hospitality.example.invalid")
        initial=self.stock(self.prop.warehouse)
        frappe.set_user("maintenance@hospitality.example.invalid")
        data=dict(order=order.name,modified=str(order.modified),parts=[dict(item="HS-DEMO-WATER",quantity=2)])
        key=uuid.uuid4().hex
        result=self.call("maintenance_parts",data,key)
        self.assertEqual(self.call("maintenance_parts",data,key),result)
        order.reload()
        self.assertEqual(self.stock(self.prop.warehouse),initial-2)
        entry=frappe.get_doc("Stock Entry",result["stock_entry"])
        self.assertEqual(order.cost,entry.total_outgoing_value)
        self.assertEqual(order.cost,20)
        from hospitality_suite.printing import hs_maintenance_context
        frappe.set_user("housekeeping@hospitality.example.invalid")
        self.assertIsNone(hs_maintenance_context(order.name)["cost"])
        self.assertEqual(hs_maintenance_context(order.name)["parts"],[])
        frappe.set_user("maintenance@hospitality.example.invalid")
        with self.assertRaises(frappe.PermissionError):
            self.call("maintenance",dict(order=order.name,modified=str(order.modified),status="Completed"))
        frappe.set_user("manager@hospitality.example.invalid")
        self.call("maintenance_parts",dict(order=order.name,modified=str(order.modified),return_entry=entry.name,reason="Repuestos sin usar"))
        order.reload()
        self.assertEqual(order.cost,0)
        self.assertEqual(self.stock(self.prop.warehouse),initial)
        self.assertEqual(frappe.db.get_value("Stock Entry",entry.name,"docstatus"),2)
        frappe.set_user("supervisor@hospitality.example.invalid")
        self.call("maintenance",dict(order=order.name,modified=str(order.modified),status="Completed"))
        self.assertEqual(frappe.db.get_value("HS Allocation",{"maintenance":order.name},"status"),"Released")

    def test_invalid_assignment_and_stock_failure_leave_no_partial_order_changes(self):
        with self.assertRaises(frappe.ValidationError):
            self.order(assigned_to="housekeeping@hospitality.example.invalid")
        order=self.order()
        count=frappe.db.count("Stock Entry")
        with self.assertRaises(frappe.ValidationError):
            self.call("maintenance_parts",dict(order=order.name,modified=str(order.modified),parts=[dict(item="HS-DEMO-WATER",quantity=1000000)]))
        self.assertEqual(frappe.db.count("Stock Entry"),count)
        order.reload()
        self.assertEqual(order.parts,[])

    def test_private_evidence_and_incident_resolution(self):
        from frappe.utils.file_manager import save_file
        order=self.order()
        file=save_file("evidencia-ficticia.txt",b"Evidencia sintetica",order.doctype,order.name,is_private=1)
        self.call("maintenance",dict(order=order.name,modified=str(order.modified),evidence=file.file_url))
        order.reload()
        self.assertEqual(order.evidence,file.file_url)
        incident=self.call("incident",dict(room=self.room,kind="Lost Property",description="Objeto sintético en custodia"))["incident"]
        record=frappe.get_doc("HS Incident",incident)
        with self.assertRaises(frappe.ValidationError):
            self.call("incident",dict(incident=record.name,modified=str(record.modified),evidence=file.file_url))
        frappe.set_user("housekeeping@hospitality.example.invalid")
        with self.assertRaises(frappe.PermissionError):
            self.call("incident",dict(incident=record.name,modified=str(record.modified),resolve=True,resolution="Entregado"))
        frappe.set_user("supervisor@hospitality.example.invalid")
        self.call("incident",dict(incident=record.name,modified=str(record.modified),resolve=True,resolution="Entrega registrada a su propietario ficticio"))
        record.reload()
        self.assertEqual(record.resolved_by,frappe.session.user)
        self.assertEqual(record.status,"Resolved")

    def test_linen_transfer_receipt_and_loss_use_native_stock(self):
        laundry=frappe.get_doc(dict(doctype="Warehouse",warehouse_name="Lavandería ficticia "+uuid.uuid4().hex[:6],company=self.prop.company,
                                   parent_warehouse=frappe.db.get_value("Warehouse",{"company":self.prop.company,"is_group":1},"name"),hs_property=self.prop.name)).insert()
        with operation():
            self.prop.laundry_warehouse=laundry.name
            self.prop.save()
        initial=self.stock(self.prop.warehouse)
        self.call("linen",dict(room=self.room,item="HS-DEMO-WATER",quantity=3,direction="Send"))
        self.assertEqual(self.stock(laundry.name),3)
        self.call("linen",dict(room=self.room,item="HS-DEMO-WATER",quantity=2,direction="Receive"))
        lost=self.call("linen",dict(room=self.room,item="HS-DEMO-WATER",quantity=1,direction="Loss",reason="Pérdida sintética autorizada"))
        self.assertEqual(self.stock(laundry.name),0)
        self.assertEqual(self.stock(self.prop.warehouse),initial-1)
        self.assertEqual(frappe.db.get_value("Stock Entry",lost["stock_entry"],"stock_entry_type"),"Material Issue")
