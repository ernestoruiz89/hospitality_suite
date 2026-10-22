import uuid
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.permissions import has_permission

from hospitality_suite import api
from hospitality_suite.service import operation


class TestProcurement(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        self.vendor=self.call("register_supplier",dict(supplier_name="Proveedor ficticio "+uuid.uuid4().hex[:7]))["supplier"]
        self.method=frappe.db.get_value("HS Payment Method",{"property":self.prop.name,"is_cash":1})
        self.shift=self.call("open_shift",dict(opening_amount=500))["shift"]

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def call(self,action,data,key=None,prop=None):
        return api.execute((prop or self.prop).name,action,key or uuid.uuid4().hex,data)

    def order(self,quantity=5):
        values=dict(supplier=self.vendor,reason="Compra ficticia aprobada",items=[dict(item="HS-DEMO-WATER",quantity=quantity,rate=10)])
        values["acceptance"]=api.preview(self.prop.name,values,"purchase_order")["acceptance"]
        name=self.call("purchase_order",values)["order"]
        return frappe.get_doc("Purchase Order",name)

    def receive(self,order,quantity,key=None):
        return self.call("receive_purchase",dict(order=order.name,items=[dict(order_item=order.items[0].name,quantity=quantity)]),key)

    def invoice(self,receipt):
        return self.call("purchase_invoice",dict(receipt=receipt,bill_no="FACT-FICTICIA-"+uuid.uuid4().hex[:7],bill_date=frappe.utils.nowdate()))["invoice"]

    def pay(self,invoice,amount):
        values=dict(invoice=invoice,shift=self.shift,method=self.method,amount=amount,reason="Pago ficticio documentado")
        values["acceptance"]=api.preview(self.prop.name,values,"supplier_payment")["acceptance"]
        return self.call("supplier_payment",values)

    def stock(self,warehouse=None):
        return frappe.db.get_value("Bin",{"item_code":"HS-DEMO-WATER","warehouse":warehouse or self.prop.warehouse},"actual_qty") or 0

    def category(self):
        account=frappe.db.get_value("Account",{"company":self.prop.company,"root_type":"Expense","is_group":0},"name")
        with operation():
            return frappe.get_doc(dict(doctype="HS Expense Category",property=self.prop.name,company=self.prop.company,label="Consumo/pérdida ficticia",account=account,active=1)).insert().name

    def test_partial_purchase_receipt_native_invoice_and_supplier_payments_once(self):
        initial=self.stock()
        frappe.set_user("accountant@hospitality.example.invalid")
        # Own drawer is required even for an accountant.
        self.shift=self.call("open_shift",dict(opening_amount=500))["shift"]
        order=self.order()
        values=dict(order=order.name,items=[dict(order_item=order.items[0].name,quantity=3)])
        key=uuid.uuid4().hex
        received=self.call("receive_purchase",values,key)
        self.assertEqual(received,self.call("receive_purchase",values,key))
        self.assertEqual(self.stock(),initial+3)
        invoice=self.invoice(received["receipt"])
        self.assertEqual(self.stock(),initial+3)
        self.assertEqual(frappe.db.get_value("Purchase Invoice",invoice,"update_stock"),0)
        self.pay(invoice,20)
        self.assertEqual(frappe.db.get_value("Purchase Invoice",invoice,"outstanding_amount"),10)
        self.pay(invoice,10)
        self.assertEqual(frappe.db.get_value("Purchase Invoice",invoice,"outstanding_amount"),0)
        from hospitality_suite.cashier import expected
        self.assertEqual(expected(frappe.get_doc("HS Shift",self.shift))["NIO"],"470.00")
        with self.assertRaises(frappe.ValidationError):
            self.receive(order,3)
        self.receive(order,2)
        order.reload()
        self.assertEqual(order.items[0].received_qty,5)
        self.assertEqual(self.stock(),initial+5)
        from hospitality_suite.reconciliation import differences
        self.assertEqual(differences(self.prop),[])

    def test_supplier_and_warehouse_cannot_cross_properties(self):
        other=frappe.get_doc("HS Property",{"property_name":"Motel Luna Demo"})
        with self.assertRaises(frappe.ValidationError):
            self.call("purchase_order",dict(supplier=self.vendor,reason="Prueba cruzada",items=[dict(item="HS-DEMO-WATER",quantity=1,rate=10)]),prop=other)
        order=self.order()
        with self.assertRaises(frappe.PermissionError):
            self.call("receive_purchase",dict(order=order.name,items=[dict(order_item=order.items[0].name,quantity=1)]),prop=other)
        unrelated=frappe.get_doc(dict(doctype="Warehouse",warehouse_name="No asignado "+uuid.uuid4().hex[:6],company=self.prop.company)).insert()
        with self.assertRaises(frappe.PermissionError):
            self.call("purchase_order",dict(supplier=self.vendor,warehouse=unrelated.name,reason="No debe acceder",items=[dict(item="HS-DEMO-WATER",quantity=1,rate=10)]))

    def test_manager_count_delegates_only_native_balance_calculation_and_preserves_actor(self):
        from erpnext.stock.doctype.stock_reconciliation import stock_reconciliation as native
        category=self.category()
        initial=self.stock()
        frappe.set_user('manager@hospitality.example.invalid')
        self.assertFalse(has_permission('Stock Reconciliation','write',print_logs=False))
        request=(frappe.session.user,frappe.session.sid,frappe.session.data,frappe.local.form_dict)
        values=dict(item='HS-DEMO-WATER',counted_quantity=initial-1,category=category,reason='Conteo ficticio por gerencia')
        values['acceptance']=api.preview(self.prop.name,values,'adjust_stock')['acceptance']
        balance_actors=[]
        validation_actors=[]
        balance=native.get_stock_balance_for
        validate=native.StockReconciliation.validate_data
        def read_balance(*args,**kwargs):
            balance_actors.append(frappe.session.user)
            return balance(*args,**kwargs)
        def validate_data(doc):
            validation_actors.append(frappe.session.user)
            return validate(doc)
        key=uuid.uuid4().hex
        with patch.object(native,'get_stock_balance_for',read_balance),patch.object(native.StockReconciliation,'validate_data',validate_data):
            result=self.call('adjust_stock',values,key)
            self.assertEqual(self.call('adjust_stock',values,key),result)
        self.assertTrue(balance_actors)
        self.assertEqual(set(balance_actors),{'Administrator'})
        self.assertEqual(set(validation_actors),{request[0]})
        self.assertEqual((frappe.session.user,frappe.session.sid),request[:2])
        self.assertIs(frappe.session.data,request[2])
        self.assertIs(frappe.local.form_dict,request[3])
        self.assertFalse(has_permission('Stock Reconciliation','write',print_logs=False))
        doc=frappe.get_doc('Stock Reconciliation',result['stock_reconciliation'])
        self.assertEqual((doc.owner,doc.modified_by,doc.docstatus),(request[0],request[0],1))
        self.assertEqual(self.stock(),initial-1)
        for doctype in ['GL Entry','Stock Ledger Entry']:
            rows=frappe.get_all(doctype,filters={'voucher_type':doc.doctype,'voucher_no':doc.name},fields=['owner'])
            self.assertTrue(rows)
            self.assertEqual({row.owner for row in rows},{request[0]})
        with self.assertRaises(frappe.PermissionError):
            native.get_stock_balance_for('HS-DEMO-WATER',self.prop.warehouse,doc.posting_date,doc.posting_time)

    def test_failed_delegated_count_restores_request_and_accountant_cannot_approve(self):
        from erpnext.stock.doctype.stock_reconciliation import stock_reconciliation as native
        category=self.category()
        initial=self.stock()
        frappe.set_user('manager@hospitality.example.invalid')
        values=dict(item='HS-DEMO-WATER',counted_quantity=initial-1,category=category,reason='Error sintético de consulta')
        values['acceptance']=api.preview(self.prop.name,values,'adjust_stock')['acceptance']
        request=(frappe.session.user,frappe.session.sid,frappe.session.data,frappe.local.form_dict)
        counts={dt:frappe.db.count(dt) for dt in ['Stock Reconciliation','GL Entry','Stock Ledger Entry','HS Request']}
        with patch.object(native,'get_stock_balance_for',side_effect=frappe.ValidationError('Fallo sintético de saldo')) as balance:
            with self.assertRaises(frappe.ValidationError):
                self.call('adjust_stock',values)
            self.assertEqual(balance.call_count,1)
            self.assertEqual((frappe.session.user,frappe.session.sid),request[:2])
            self.assertIs(frappe.session.data,request[2])
            self.assertIs(frappe.local.form_dict,request[3])
            frappe.set_user('accountant@hospitality.example.invalid')
            with self.assertRaises(frappe.PermissionError):
                self.call('adjust_stock',values)
            self.assertEqual(balance.call_count,1)
        self.assertEqual(self.stock(),initial)
        self.assertEqual({dt:frappe.db.count(dt) for dt in counts},counts)

    def test_stock_transfer_cleaning_loss_replacement_and_count_adjustment(self):
        category=self.category()
        dest=frappe.get_doc(dict(doctype="Warehouse",warehouse_name="Piso y ropa ficticios "+uuid.uuid4().hex[:6],company=self.prop.company,hs_property=self.prop.name)).insert()
        initial=self.stock()
        self.call("move_stock",dict(item="HS-DEMO-WATER",quantity=2,purpose="Linen Replacement",target_warehouse=dest.name,reason="Reposición ficticia de ubicación"))
        self.assertEqual(self.stock(dest.name),2)
        for purpose in ("Cleaning","Waste"):
            self.call("move_stock",dict(item="HS-DEMO-WATER",quantity=1,purpose=purpose,category=category,reason="Uso ficticio segregado"))
        self.assertEqual(self.stock(),initial-4)
        values=dict(item="HS-DEMO-WATER",counted_quantity=initial-5,category=category,reason="Conteo físico ficticio autorizado")
        q=api.preview(self.prop.name,values,"adjust_stock")
        result=self.call("adjust_stock",dict(**values,acceptance=q["acceptance"]))
        self.assertEqual(frappe.db.get_value("Stock Reconciliation",result["stock_reconciliation"],"docstatus"),1)
        self.assertEqual(self.stock(),initial-5)
        from hospitality_suite.reports import rows
        movements=rows(self.prop,"Movimientos de inventario",dict(purpose="Waste"))
        loss=[r for r in movements if r["item"]=="HS-DEMO-WATER"]
        self.assertEqual(len(loss),1)
        self.assertEqual(loss[0]["quantity"],-1)
        self.assertLess(loss[0]["cost"],0)
        self.assertEqual(loss[0]["cost_center"],self.prop.cost_center)
        self.assertEqual(loss[0]["source_doctype"],"Stock Entry")
        other=frappe.get_doc("HS Property",{"property_name":"Motel Luna Demo"})
        self.assertFalse(any(r["source_name"]==loss[0]["source_name"] for r in rows(other,"Movimientos de inventario")))
        q=api.preview(self.prop.name,dict(values,counted_quantity=initial-6),"adjust_stock")
        self.call("move_stock",dict(item="HS-DEMO-WATER",quantity=1,purpose="Transfer",source_warehouse=dest.name,target_warehouse=self.prop.warehouse,reason="Retorno ficticio"))
        with self.assertRaises(frappe.ValidationError):
            self.call("adjust_stock",dict(values,counted_quantity=initial-6,acceptance=q["acceptance"]))

    def test_supplier_payment_from_native_erp_syncs_and_cancels(self):
        order=self.order(2)
        invoice=self.invoice(self.receive(order,2)["receipt"])
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
        method=frappe.get_doc("HS Payment Method",self.method)
        payment=get_payment_entry("Purchase Invoice",invoice,bank_account=method.account)
        payment.update(dict(hs_property=self.prop.name,hs_shift=self.shift,mode_of_payment=method.mode_of_payment,reference_no="PAGO-FICTICIO",reference_date=frappe.utils.nowdate()))
        payment.insert().submit()
        record=frappe.get_doc("HS Payment",{"payment_entry":payment.name})
        self.assertEqual(record.kind,"Supplier Payment")
        self.assertEqual(record.supplier,self.vendor)
        self.assertEqual(record.amount,20)
        payment.hs_correction_reason="Anulación ficticia autorizada"
        payment.cancel()
        self.assertEqual(frappe.db.get_value("HS Payment",record.name,"status"),"Cancelled")
        self.assertEqual(frappe.db.get_value("Purchase Invoice",invoice,"outstanding_amount"),20)

    def test_native_reorder_minimums_and_classification_are_property_scoped(self):
        result=self.call("stock_policy",dict(item="HS-DEMO-WATER",purpose="Linen",minimum=120,reorder_quantity=30))
        self.assertTrue(result["policy"])
        status=api.inventory_status(self.prop.name)
        row=next(r for r in status["items"] if r.item_code=="HS-DEMO-WATER")
        self.assertEqual(row["purpose"],"Linen")
        self.assertEqual(row["minimum"],120)
        self.assertEqual(row["reorder_quantity"],30)
        self.assertTrue(row["needs_restock"])
        native=frappe.get_doc("Item","HS-DEMO-WATER")
        setting=next(r for r in native.reorder_levels if r.warehouse==self.prop.warehouse)
        self.assertEqual(setting.warehouse_reorder_level,120)
        outsider=frappe.get_doc(dict(doctype="Warehouse",warehouse_name="Almacén ajeno "+uuid.uuid4().hex[:6],company=self.prop.company)).insert()
        with self.assertRaises(frappe.PermissionError):
            self.call("stock_policy",dict(item="HS-DEMO-WATER",warehouse=outsider.name,purpose="Merchandise",minimum=1,reorder_quantity=1))
