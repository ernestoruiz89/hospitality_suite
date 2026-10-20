"""Native ledgers honor property/service accounts and historical reversals."""
import uuid

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_suite import api
from hospitality_suite.service import operation


class TestServiceAccounting(IntegrationTestCase):
    def setUp(self):
        super().setUp();self.addCleanup(frappe.db.rollback)
        frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        self.guest=frappe.get_doc('HS Guest',{'property':self.prop.name})
        self.income=self.account('Income');self.expense=self.account('Expense')
        parent=frappe.db.get_value('Cost Center',{'company':self.prop.company,'is_group':1})
        self.center=frappe.get_doc(dict(doctype='Cost Center',company=self.prop.company,parent_cost_center=parent,
            cost_center_name='Servicio sintético '+uuid.uuid4().hex[:6])).insert().name

    def tearDown(self):
        frappe.set_user('Administrator');super().tearDown()

    def account(self,root):
        parent=frappe.db.get_value('Account',{'company':self.prop.company,'root_type':root,'is_group':1})
        return frappe.get_doc(dict(doctype='Account',company=self.prop.company,parent_account=parent,root_type=root,
            account_name='Servicio '+root+' '+uuid.uuid4().hex[:6],account_currency='NIO')).insert().name

    def configure(self,services=None,defaults=None,prop=None,key=None,modified=None):
        prop=prop or self.prop
        config=api.service_accounting_configuration(prop.name)
        data=dict(modified=modified or config['modified'],defaults=defaults or config['defaults'],services=services if services is not None else config['services'])
        # The read projection carries names; only the allowed fields are writes.
        data['services']=[{field:row.get(field) for field in ('item','income_account','expense_account','cost_center')} for row in data['services']]
        return api.execute(prop.name,'service_accounting',key or uuid.uuid4().hex,data)

    def mapping(self):return dict(item='HS-DEMO-WATER',income_account=self.income,expense_account=self.expense,cost_center=self.center)

    def invoice(self,prop=None,item='HS-DEMO-WATER',update_stock=1,rate=30):
        prop=prop or self.prop
        doc=frappe.get_doc(dict(doctype='Sales Invoice',company=prop.company,hs_property=prop.name,
            customer=self.guest.customer,currency=prop.currency,debit_to=prop.receivable_account,cost_center=prop.cost_center,update_stock=update_stock,disable_rounded_total=1))
        doc.append('items',dict(item_code=item,qty=1,rate=rate,warehouse=prop.warehouse,cost_center=prop.cost_center))
        doc.set_missing_values();return doc.insert().submit()

    def ledger(self,doc,account):
        return frappe.get_all('GL Entry',filters={'voucher_type':doc.doctype,'voucher_no':doc.name,'account':account,'is_cancelled':0},fields=['debit','credit','cost_center'])

    def test_service_income_and_cogs_use_their_native_accounts_and_cost_center(self):
        shared=frappe.get_all('Item Default',filters={'parent':'HS-DEMO-WATER'},fields=['*'],order_by='name')
        self.configure([self.mapping()])
        invoice=self.invoice()
        self.assertEqual((invoice.items[0].income_account,invoice.items[0].expense_account,invoice.items[0].cost_center),(self.income,self.expense,self.center))
        revenue=self.ledger(invoice,self.income);cost=self.ledger(invoice,self.expense)
        self.assertEqual(sum(row.credit-row.debit for row in revenue),30)
        self.assertGreater(sum(row.debit-row.credit for row in cost),0)
        self.assertTrue(all(row.cost_center==self.center for row in revenue+cost))
        self.assertEqual(shared,frappe.get_all('Item Default',filters={'parent':'HS-DEMO-WATER'},fields=['*'],order_by='name'))

    def test_two_properties_in_one_company_can_use_different_defaults_for_the_same_item(self):
        self.configure([self.mapping()])
        other=frappe.copy_doc(self.prop)
        other.property_name='Otra sede sintética '+uuid.uuid4().hex[:6]
        other.income_account=self.account('Income');other.expense_account=self.account('Expense');other.cost_center=self.center
        other.set('service_accounts',[])
        with operation():other.insert()
        one=self.invoice();two=self.invoice(other)
        self.assertNotEqual(one.items[0].income_account,two.items[0].income_account)
        self.assertEqual(two.items[0].income_account,other.income_account)
        self.assertEqual(sum(row.credit-row.debit for row in self.ledger(two,other.income_account)),30)
        self.assertFalse(self.ledger(two,self.income))

    def test_return_keeps_original_accounts_after_configuration_changes(self):
        self.configure([self.mapping()]);invoice=self.invoice()
        old=invoice.items[0].as_dict()
        new_income=self.account('Income');new_expense=self.account('Expense')
        self.configure([],dict(income_account=new_income,expense_account=new_expense,cost_center=self.prop.cost_center))
        returned=api.execute(self.prop.name,'credit_note',uuid.uuid4().hex,dict(invoice=invoice.name,reason='Revierte con las cuentas históricas'))
        credit=frappe.get_doc('Sales Invoice',returned['credit_note'])
        self.assertEqual((credit.items[0].income_account,credit.items[0].expense_account,credit.items[0].cost_center),(old.income_account,old.expense_account,old.cost_center))
        self.assertFalse(self.ledger(credit,new_income));self.assertFalse(self.ledger(credit,new_expense))
        for account in (self.income,self.expense):
            self.assertAlmostEqual(sum(row.debit-row.credit for row in self.ledger(invoice,account)+self.ledger(credit,account)),0)

    def test_operational_delivery_and_nonstock_purchase_do_not_override_inventory_accounts(self):
        from hospitality_suite.inventory import stock_movement
        self.configure([self.mapping()],dict(income_account=self.income,expense_account=self.expense,cost_center=self.center))
        delivery=stock_movement(frappe.get_doc('HS Property',self.prop.name),'HS-DEMO-WATER',1)
        self.assertGreater(sum(row.debit-row.credit for row in self.ledger(delivery,self.expense)),0)
        supplier=api.execute(self.prop.name,'register_supplier',uuid.uuid4().hex,dict(supplier_name='Proveedor sintético '+uuid.uuid4().hex[:6]))['supplier']
        doc=frappe.get_doc(dict(doctype='Purchase Invoice',company=self.prop.company,hs_property=self.prop.name,supplier=supplier,
            currency='NIO',update_stock=1,cost_center=self.prop.cost_center,bill_no='QA-'+uuid.uuid4().hex[:8]))
        for item,rate in ((self.prop.lodging_item,100),('HS-DEMO-WATER',10)):
            doc.append('items',dict(item_code=item,qty=1,rate=rate,warehouse=self.prop.warehouse,cost_center=self.prop.cost_center))
        doc.set_missing_values();doc.insert().submit()
        self.assertEqual(sum(row.debit-row.credit for row in self.ledger(doc,self.expense)),100)
        self.assertNotEqual(doc.items[1].expense_account,self.expense)
        self.assertTrue(all(row.cost_center==self.center for row in doc.items))

    def test_invalid_scope_accounts_duplicates_and_stale_settings_leave_configuration_unchanged(self):
        config=api.service_accounting_configuration(self.prop.name)
        company=frappe.get_doc(dict(doctype='Company',company_name='Contabilidad aislada '+uuid.uuid4().hex[:7],
            abbr=uuid.uuid4().hex[:5].upper(),country='Nicaragua',default_currency='NIO',chart_of_accounts='Standard')).insert()
        foreign=frappe.db.get_value('Account',{'company':company.name,'root_type':'Income','is_group':0})
        for services in ([dict(self.mapping(),income_account=foreign)],[dict(self.mapping(),income_account=self.expense)],[self.mapping(),self.mapping()]):
            with self.assertRaises(frappe.ValidationError):self.configure(services)
        self.assertEqual(api.service_accounting_configuration(self.prop.name),config)
        self.configure([self.mapping()])
        with self.assertRaises(frappe.TimestampMismatchError):self.configure([],modified=config['modified'])
        frappe.set_user('housekeeping@hospitality.example.invalid')
        with self.assertRaises(frappe.PermissionError):api.service_accounting_configuration(self.prop.name)
        with self.assertRaises(frappe.PermissionError):api.execute(self.prop.name,'service_accounting',uuid.uuid4().hex,dict(modified=config['modified'],defaults={},services=[]))

    def test_a_disabled_service_account_blocks_the_quote_before_creating_documents(self):
        self.configure([self.mapping()])
        account=frappe.get_doc('Account',self.income);account.disabled=1;account.save()
        method=frappe.db.get_value('HS Payment Method',{'property':self.prop.name,'currency':'NIO','is_cash':1},'name')
        values=dict(customer=self.guest.customer,item='HS-DEMO-WATER',quantity=1,method=method)
        with self.assertRaisesRegex(frappe.ValidationError,'Seleccione cuentas y centros de costo habilitados'):
            api.preview(self.prop.name,values,'direct_sale')
        self.assertEqual(frappe.db.count('Sales Invoice'),0)
        self.assertEqual(frappe.db.count('HS Service Request'),0)
