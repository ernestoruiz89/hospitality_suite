const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

test('partial receipt edits only existing order lines and preserves their provenance',async()=>{
  class Desk{}
  const context={window:{hospitality_suite:{Desk}},__:(text,args)=>String(text).replace(/\{(\d+)\}/g,(_,i)=>args?.[i]??_),
    frappe:{boot:{sysdefaults:{currency_precision:2}},utils:{get_random:()=> 'receipt-request',escape_html:String}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_finance_stock.js'),'utf8'),context);
  const desk=new Desk(),order={name:'order-original',items:[
    {name:'line-original-1',item:'water',quantity:6,received_quantity:2},
    {name:'line-original-2',item:'soap',quantity:3,received_quantity:0},
    {name:'line-already-received',item:'towel',quantity:2,received_quantity:2}]};
  const original=JSON.stringify(order);
  desk.data={purchase_orders:[order],items:[{name:'water',item_name:'Agua'},{name:'soap',item_name:'Jabón'}]};
  let form,mutation;
  desk.dialog=async(title,fields,submit,label)=>{form={title,fields,submit,label};return form;};
  desk.mutate=async(action,values,key)=>{mutation={action,values:JSON.parse(JSON.stringify(values)),key};};
  await desk.action_receive_purchase(order.name);
  const table=form.fields.find(field=>field.fieldname==='lines');
  assert.equal(table.cannot_add_rows,1,'receipt cannot invent order lines');
  assert.equal(table.cannot_delete_rows,1,'zero quantity is the explicit omission action');
  assert.deepEqual(Array.from(table.data,row=>[row.order_item,row.pending,row.quantity]),[
    ['line-original-1',4,4],['line-original-2',3,3]]);
  assert.equal(table.fields.find(field=>field.fieldname==='order_item').hidden,1);
  assert.equal(table.fields.find(field=>field.fieldname==='item_label').read_only,1);
  assert.equal(table.fields.find(field=>field.fieldname==='quantity').read_only,undefined);
  let hidden=false;
  await form.submit({lines:[{...table.data[0],quantity:1.5},{...table.data[1],quantity:0}],reason:'Entrega parcial'},
    {hide(){hidden=true;}});
  assert.deepEqual(mutation,{action:'receive_purchase',values:{order:'order-original',
    items:[{order_item:'line-original-1',quantity:1.5}],reason:'Entrega parcial'},key:'receipt-request'});
  assert.equal(JSON.stringify(order),original);
  assert.equal(hidden,true);
});

test('billing an empty receipt queue explains the state without opening an unusable form',async()=>{
  const alerts=[];
  class Desk{}
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_finance_stock.js'),'utf8'),
    {window:{hospitality_suite:{Desk}},__:text=>text,frappe:{boot:{sysdefaults:{currency_precision:2}},
      utils:{get_random:()=> 'invoice-request',escape_html:String},msgprint:text=>alerts.push(text)}});
  const desk=new Desk();let dialogs=0,mutations=0;
  desk.data={purchase_receipts:[]};
  desk.dialog=async()=>{dialogs++;};
  desk.mutate=async()=>{mutations++;};
  await desk.action_purchase_invoice();
  assert.equal(dialogs,0);
  assert.equal(mutations,0);
  assert.deepEqual(alerts,['No hay recepciones de compra pendientes de facturar.']);
});

test('fully received orders have no receive action while their invoices are still pending',async()=>{
  const alerts=[];
  class Desk{
    render_services(){}
    button(action,label,id){return action==='receive_purchase'?`RECEIVE:${id}`:'';}
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_finance_stock.js'),'utf8'),
    {window:{hospitality_suite:{Desk}},__:text=>text,frappe:{boot:{sysdefaults:{currency_precision:2}},
      utils:{get_random:()=> 'receipt-request',escape_html:String},msgprint:text=>alerts.push(text)}});
  const desk=new Desk();
  desk.allowed=()=>true;
  desk.amount=String;
  desk.table=(_,rows)=>JSON.stringify(rows);
  desk.data={purchase_orders:[
    {name:'received-awaiting-invoice',supplier:'Proveedor',grand_total:60,items:[{quantity:6,received_quantity:6}]},
    {name:'partially-received',supplier:'Proveedor',grand_total:60,items:[{quantity:6,received_quantity:2}]}]};
  let section='',dialogs=0,mutations=0;
  desk.dialog=async()=>{dialogs++;};
  desk.mutate=async()=>{mutations++;};
  desk.render_services({find:()=>({append(){}}),append(value){section+=value;}});
  assert.match(section,/RECEIVE:partially-received/);
  assert.doesNotMatch(section,/received-awaiting-invoice/);
  await desk.action_receive_purchase('received-awaiting-invoice');
  await desk.action_receive_purchase('not-in-current-bootstrap');
  assert.equal(dialogs,0);
  assert.equal(mutations,0);
  assert.equal(alerts.length,2);
  assert.match(alerts[0],/recibida por completo/);
  assert.match(alerts[1],/Actualice/);
});
